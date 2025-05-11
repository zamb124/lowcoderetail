# core_sdk/data_access/base_manager.py

import logging
from typing import Type, List, Optional, Any, Mapping, Dict, TypeVar, Generic, Union, Literal
from uuid import UUID
from pydantic import BaseModel, ValidationError, create_model
from sqlmodel import SQLModel, select as sqlmodel_select, col
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select # Добавляем select из sqlalchemy
from fastapi import HTTPException
import httpx

# --- SDK Импорты ---
from core_sdk.db.session import get_current_session
from core_sdk.exceptions import ServiceCommunicationError, ConfigurationError, DetailException
# --- Импорты для фильтров ---
from fastapi_filter.contrib.sqlalchemy import Filter as BaseFilter # Переименовано для ясности
from core_sdk.registry import ModelRegistry
from core_sdk.filters.base import DefaultFilter
from core_sdk.data_access.broker_proxy import BrokerTaskProxy

# ---------------------------
# --- Логгер ---
logger = logging.getLogger("core_sdk.data_access")
# -------------
# --- Asyncpg ошибки ---
try:
    from asyncpg.exceptions import UniqueViolationError, NotNullViolationError, ForeignKeyViolationError
except ImportError:
    logger.warning("asyncpg not installed, IntegrityError details might be limited.")
    class UniqueViolationError(Exception): pass
    class NotNullViolationError(Exception): pass
    class ForeignKeyViolationError(Exception): pass
# --------------------

# Типы для моделей и схем
ModelType = TypeVar("ModelType", bound=SQLModel)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)

sqlmodel_select = sqlmodel_select

# Константа для "максимального" LSN, если начальный desc-запрос не вернул данных
# Это значение должно быть больше любого возможного LSN в вашей системе.
# PostgreSQL BIGINT Identity (always=True) обычно начинается с 1 и увеличивается.
# Максимальное значение для BIGINT (signed) ~9 * 10^18.
# Используем значение, которое явно велико, но не вызывает переполнения при передаче как int.
MAX_LSN_FOR_EMPTY_DESC_INITIAL = 2**62 # Примерно 4.6 * 10^18

class BaseDataAccessManager(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    model: Type[ModelType]
    create_schema: Optional[Type[CreateSchemaType]] = None
    update_schema: Optional[Type[UpdateSchemaType]] = None
    model_name: str
    _broker_instance: Optional["BrokerTaskProxy"] = None

    def __init__(
            self,
            model_name: str,
            http_client: Optional[httpx.AsyncClient] = None
    ):
        self._http_client = http_client
        self.model_name = model_name

    @property
    def session(self) -> AsyncSession:
        return get_current_session()

    @property
    def broker(self) -> "BrokerTaskProxy":
        if self._broker_instance is None:
            from .broker_proxy import BrokerTaskProxy
            logger.debug(f"Lazily initializing BrokerTaskProxy for {self.model_name}")
            self._broker_instance = BrokerTaskProxy(dam_instance=self, model_name=self.model_name)
        return self._broker_instance

    def _get_filter_class(self) -> Type[BaseFilter]:
        try:
            model_info = ModelRegistry.get_model_info(self.model_name)
            filter_cls = model_info.filter_cls
            if filter_cls:
                if issubclass(filter_cls, BaseFilter):
                    if not hasattr(filter_cls, 'Constants') or not hasattr(filter_cls.Constants, 'model'):
                        constants_class = type('Constants', (object,), {'model': self.model, 'search_model_fields': []})
                        wrapper_name = f"{filter_cls.__name__}WithConstants"
                        filter_cls = type(wrapper_name, (filter_cls,), {"Constants": constants_class})
                        try: filter_cls.model_rebuild(force=True) # type: ignore
                        except Exception: pass
                    return filter_cls
                else:
                    logger.warning(f"Registered filter_cls {filter_cls.__name__} for {self.model_name} is not a subclass of BaseFilter. Falling back.")
            else:
                logger.debug(f"No specific filter registered for {self.model_name}. Using DefaultFilter.")
        except ConfigurationError:
            logger.warning(f"Model '{self.model_name}' not found in registry for filter. Using DefaultFilter.")
        except Exception as e:
            logger.exception(f"Error getting filter class for {self.model_name}. Using DefaultFilter. Error: {e}")

        final_filter_model_name = f"{self.model_name}DefaultRuntimeFilter"
        search_fields = [
            name for name, field in self.model.model_fields.items()
            if field.annotation is str or field.annotation is Optional[str]
        ]
        constants_class = type('Constants', (object,), {'model': self.model, 'search_model_fields': search_fields, 'ordering_field_name': 'order_by'})
        default_runtime_filter = create_model(
            final_filter_model_name,
            __base__=DefaultFilter,
            Constants=(constants_class, ...)
        )
        try: default_runtime_filter.model_rebuild(force=True)
        except Exception: pass
        return default_runtime_filter # type: ignore

    async def list(
            self,
            *,
            cursor: Optional[int] = None,
            limit: int = 50,
            filters: Optional[Union[BaseFilter, Mapping[str, Any]]] = None,
            direction: Literal["asc", "desc"] = "asc"
    ) -> Dict[str, Any]:
        logger.debug(f"Base DAM LIST: {self.model_name}, Direction: {direction}, Input Cursor: {cursor}, Limit: {limit}")
        if not hasattr(self, 'model') or not self.model:
            raise ConfigurationError(f"Model class not set for manager {self.__class__.__name__}")
        if not hasattr(self.model, 'lsn'):
            raise ValueError(f"Cursor pagination requires 'lsn' attribute on model {self.model.__name__}")

        lsn_attr = col(self.model.lsn)
        base_statement = sqlmodel_select(self.model)
        session = self.session
        order_by_clauses: List[Any] = [] # Явно типизируем
        filter_obj: Optional[BaseFilter] = None

        # --- Обработка и валидация фильтров ---
        if isinstance(filters, Mapping) or isinstance(filters, BaseFilter):
            actual_filter_cls = self._get_filter_class()
            if isinstance(filters, Mapping):
                logger.debug(f"Received dict filters. Validating against {actual_filter_cls.__name__}.")
                try:
                    filter_obj = actual_filter_cls.model_validate(filters)
                except ValidationError as ve:
                    raise HTTPException(status_code=422, detail=f"Invalid filter parameters: {ve.errors()}")
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Internal error processing filters: {e}")
            elif isinstance(filters, BaseFilter):
                if not isinstance(filters, actual_filter_cls):
                    logger.warning(f"Received filter object of type {type(filters).__name__}, but expected {actual_filter_cls.__name__}. Proceeding.")
                filter_obj = filters
        elif filters is not None:
            raise TypeError(f"Unsupported filter type: {type(filters)}. Expected Filter object or dict.")

        statement = base_statement
        if filter_obj:
            statement = filter_obj.filter(statement)
            is_default_filter = isinstance(filter_obj, DefaultFilter) or filter_obj.__class__.__name__.endswith("DefaultRuntimeFilter")
            if not is_default_filter: # Применяем сортировку только из кастомных фильтров
                constants = getattr(filter_obj, 'Constants', None)
                if constants and hasattr(constants, 'model'):
                    try:
                        # FastAPI-Filter sort() возвращает новый select, из которого можно извлечь order_by
                        sort_result_select = filter_obj.sort(sqlmodel_select(constants.model)) # type: ignore
                        if hasattr(sort_result_select, '_order_by_clauses'):
                            order_by_clauses = sort_result_select._order_by_clauses
                        else: # Фоллбэк, если _order_by_clauses нет (маловероятно для SQLAlchemy)
                            logger.warning(f"Could not extract _order_by_clauses from sort result of {type(filter_obj).__name__}")
                    except Exception as e:
                        logger.warning(f"Could not apply sort from custom filter {type(filter_obj).__name__}: {e}")
                else:
                    logger.warning(f"Custom filter {type(filter_obj).__name__} is missing 'Constants.model'. Cannot apply sorting.")
                logger.debug(f"Applied custom sort from {type(filter_obj).__name__}: {order_by_clauses}")

        # --- Логика курсора для запроса к БД ---
        # `effective_query_cursor` используется для построения WHERE-условия
        effective_query_cursor: Optional[int] = cursor

        if effective_query_cursor is not None:
            if not isinstance(effective_query_cursor, int):
                raise ValueError("Cursor must be an integer LSN value.")
            if direction == "asc":
                statement = statement.where(lsn_attr > effective_query_cursor)
            else: # direction == "desc"
                statement = statement.where(lsn_attr < effective_query_cursor)
        # Если effective_query_cursor is None:
        #   - для 'asc': получаем записи с самого начала (обычно с LSN > 0)
        #   - для 'desc': получаем записи с самого "конца" (самые новые LSN)
        # В обоих случаях нет дополнительного WHERE по LSN.

        # --- Применяем сортировку ---
        if order_by_clauses:
            statement = statement.order_by(None) # Сбрасываем предыдущие order_by
            for ob_clause in order_by_clauses:
                statement = statement.order_by(ob_clause)

        if direction == "asc":
            statement = statement.order_by(lsn_attr.asc())
        else: # direction == "desc"
            statement = statement.order_by(lsn_attr.desc())

        statement = statement.limit(limit)

        logger.debug(f"Executing query: {statement.compile(compile_kwargs={'literal_binds': True}) if hasattr(statement, 'compile') else 'SQLModel select object'}")
        try:
            result = await session.execute(statement)
            items_from_db = list(result.scalars().all())
            count = len(items_from_db)
            logger.debug(f"Fetched {count} items from DB.")
        except Exception as e:
            logger.exception(f"Error executing list query for {self.model_name}")
            raise HTTPException(status_code=500, detail="Database error during list operation.")

        # --- Определение `next_cursor` для ответа API ---
        output_next_cursor: int

        if count > 0:
            output_next_cursor = items_from_db[-1].lsn
        else: # count == 0 (ничего не найдено)
            if cursor is not None:
                # Если на входе был курсор и ничего не нашли, значит, достигли конца в этом направлении.
                # Возвращаем тот же курсор.
                output_next_cursor = cursor
            else: # Начальный запрос (входной cursor is None) и ничего не найдено
                if direction == "asc":
                    output_next_cursor = 0 # Начальная точка для ASC
                else: # direction == "desc"
                    # Начальный запрос DESC и ничего нет (например, пустая таблица).
                    # Возвращаем "максимально возможный" LSN.
                    output_next_cursor = MAX_LSN_FOR_EMPTY_DESC_INITIAL


        pagination_data = {
            "items": items_from_db,
            "next_cursor": output_next_cursor,
            "limit": limit,
            "count": count
        }
        logger.debug(f"List result for {self.model_name}: Count={count}, NextCursor={output_next_cursor}")
        return pagination_data

    async def get(self, item_id: UUID) -> Optional[ModelType]:
        logger.debug(f"Base DAM GET: {self.model_name} ID: {item_id}")
        if not hasattr(self, 'model') or not self.model:
            raise ConfigurationError(f"Model class not set for manager {self.__class__.__name__}")
        try:
            obj = await self.session.get(self.model, item_id)
            return obj
        except Exception as e:
            logger.exception(f"Error getting {self.model_name} {item_id}")
            raise

    async def create(self, data: Union[CreateSchemaType, Dict[str, Any]]) -> ModelType:
        logger.debug(f"Base DAM CREATE: {self.model_name}")
        if not hasattr(self, 'model') or not self.model:
            raise ConfigurationError(f"Model class not set for manager {self.__class__.__name__}")

        create_schema_cls = self.create_schema
        validated_data: CreateSchemaType
        if isinstance(data, dict):
            if create_schema_cls is None:
                raise ConfigurationError(f"CreateSchema not defined for {self.model.__name__}, cannot validate dict.")
            try: validated_data = create_schema_cls.model_validate(data)
            except ValidationError as ve: raise HTTPException(status_code=422, detail=ve.errors())
        elif create_schema_cls and isinstance(data, create_schema_cls):
            validated_data = data
        elif isinstance(data, BaseModel) and create_schema_cls is None:
            logger.warning(f"CreateSchema not defined for {self.model.__name__}, using provided BaseModel.")
            validated_data = data # type: ignore
        else:
            expected_type = create_schema_cls.__name__ if create_schema_cls else 'registered Create Schema'
            raise TypeError(f"Unsupported data type for creating {self.model.__name__}: {type(data)}. Expected {expected_type} or dict.")

        db_item = await self._prepare_for_create(validated_data)
        session = self.session
        session.add(db_item)
        try:
            await session.commit()
            await session.refresh(db_item)
            logger.info(f"Successfully created {self.model_name} with ID {getattr(db_item, 'id', 'N/A')}")
            return db_item
        except IntegrityError as e:
            logger.warning(f"DAM Create IntegrityError for {self.model_name}: {e}")
            self._handle_integrity_error(e, context="create", input_data=validated_data) # Выбросит HTTPException
            raise # До этой строки не дойдет, но для линтера/полноты
        except Exception as e:
            logger.exception(f"DAM Create Error for {self.model_name}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create {self.model.__name__} due to internal error: {e}")

    async def update(self, item_id: UUID, data: Union[UpdateSchemaType, Dict[str, Any]]) -> ModelType:
        logger.debug(f"Base DAM UPDATE: {self.model_name} ID: {item_id}")
        if not hasattr(self, 'model') or not self.model:
            raise ConfigurationError(f"Model class not set for manager {self.__class__.__name__}")

        db_item_from_db = await self.get(item_id) # Используем self.get() чтобы получить объект в текущей сессии
        if not db_item_from_db:
            raise HTTPException(status_code=404, detail=f"{self.model_name} with id {item_id} not found")

        update_schema_cls = self.update_schema
        update_payload: Dict[str, Any]

        if isinstance(data, dict):
            if update_schema_cls:
                try:
                    validated_update_schema = update_schema_cls.model_validate(data)
                    update_payload = validated_update_schema.model_dump(exclude_unset=True)
                except ValidationError as ve: raise HTTPException(status_code=422, detail=ve.errors())
            else: update_payload = data # Если схемы нет, используем dict как есть
        elif update_schema_cls and isinstance(data, update_schema_cls):
            update_payload = data.model_dump(exclude_unset=True)
        elif isinstance(data, BaseModel) and update_schema_cls is None:
            logger.warning(f"UpdateSchema not defined for {self.model.__name__}, using provided BaseModel for update.")
            update_payload = data.model_dump(exclude_unset=True) # type: ignore
        else:
            expected_type = update_schema_cls.__name__ if update_schema_cls else 'registered Update Schema'
            raise TypeError(f"Unsupported data type for updating {self.model.__name__}: {type(data)}. Expected {expected_type} or dict.")

        if not update_payload:
            logger.debug("Update payload is empty, returning original item.")
            return db_item_from_db

        db_item_prepared, updated = await self._prepare_for_update(db_item_from_db, update_payload)

        if not updated:
            logger.debug("No actual changes detected during update, returning original item.")
            return db_item_prepared # Возвращаем подготовленный объект, даже если нет изменений по флагу

        session = self.session
        session.add(db_item_prepared)
        try:
            await session.commit()
            await session.refresh(db_item_prepared)
            logger.info(f"Successfully updated {self.model_name} {item_id}")
            return db_item_prepared
        except IntegrityError as e:
            logger.warning(f"DAM Update IntegrityError for {self.model_name} {item_id}: {e}")
            self._handle_integrity_error(e, context="update", input_data=update_payload)
            raise
        except Exception as e:
            logger.exception(f"DAM Update Error for {self.model_name} {item_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to update {self.model.__name__} due to internal error: {e}")

    async def delete(self, item_id: UUID) -> bool:
        logger.debug(f"Base DAM DELETE: {self.model_name} ID: {item_id}")
        if not hasattr(self, 'model') or not self.model:
            raise ConfigurationError(f"Model class not set for manager {self.__class__.__name__}")

        session = self.session
        db_item = await self.get(item_id)
        if db_item:
            await self._prepare_for_delete(db_item)
            try:
                await session.delete(db_item)
                await session.commit()
                logger.info(f"Successfully deleted {self.model_name} {item_id}")
                return True
            except IntegrityError as e:
                logger.warning(f"DAM Delete IntegrityError for {self.model_name} {item_id}: {e}")
                self._handle_integrity_error(e, context="delete")
                return False # Не дойдет
            except Exception as e:
                logger.exception(f"DAM Delete Error for {self.model_name} {item_id}: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to delete {self.model.__name__} due to internal error.")
        else:
            raise HTTPException(status_code=404, detail=f"{self.model_name} with id {item_id} not found")

    async def _prepare_for_create(self, validated_data: CreateSchemaType) -> ModelType:
        logger.debug(f"_prepare_for_create for {self.model_name}")
        if not hasattr(self, 'model') or not self.model:
            raise ConfigurationError(f"Model class not set for manager {self.__class__.__name__}")
        try:
            # model_validate используется для Pydantic/SQLModel
            return self.model.model_validate(validated_data)
        except Exception as e:
            logger.exception(f"Error preparing model instance for {self.model_name}")
            raise HTTPException(status_code=400, detail=f"Error preparing model instance: {e}")

    async def _prepare_for_update(self, db_item: ModelType, update_payload: Dict[str, Any]) -> tuple[ModelType, bool]:
        updated = False
        item_id_str = getattr(db_item, 'id', 'N/A')
        logger.debug(f"_prepare_for_update for {self.model_name} ID {item_id_str}")
        for key, value in update_payload.items():
            if hasattr(db_item, key):
                current_value = getattr(db_item, key)
                if current_value != value:
                    logger.debug(f"  Updating field '{key}' from {repr(current_value)} to {repr(value)}")
                    try:
                        setattr(db_item, key, value)
                        updated = True
                    except Exception as e:
                        logger.exception(f"  Error setting field '{key}'")
                        raise HTTPException(status_code=400, detail=f"Error setting field '{key}': {e}")
            else:
                logger.warning(f"  Attribute '{key}' not found on model {self.model.__name__} during update preparation.")

        if updated and hasattr(db_item, 'updated_at'):
            from datetime import datetime, timezone
            logger.debug("  Setting 'updated_at' field.")
            setattr(db_item, 'updated_at', datetime.now(timezone.utc))

        logger.debug(f"_prepare_for_update finished for ID {item_id_str}. Updated: {updated}")
        return db_item, updated

    async def _prepare_for_delete(self, db_item: ModelType) -> None:
        logger.debug(f"_prepare_for_delete for {self.model_name} ID {getattr(db_item, 'id', 'N/A')}")
        pass

    def _handle_integrity_error(self, error: IntegrityError, context: str = "operation", input_data: Optional[Any] = None):
        orig_exc = getattr(error, 'orig', None)
        detail = f"Database integrity error during {context}."
        status_code = 409

        logger.warning(f"Handling IntegrityError (orig: {type(orig_exc).__name__}) during {context}")

        if isinstance(orig_exc, UniqueViolationError) or UniqueViolationError.__name__ in str(orig_exc):
            status_code = 409
            constraint_name = getattr(orig_exc, 'constraint_name', 'unknown')
            error_detail_pg = getattr(orig_exc, 'detail', None) # type: ignore
            field_name = "unknown field"
            if error_detail_pg and 'Key (' in error_detail_pg and ')=' in error_detail_pg:
                try: field_name = error_detail_pg.split('(')[1].split(')')[0]
                except Exception: pass
            detail = f"Conflict: Value for '{field_name}' already exists."
            if constraint_name != 'unknown': detail += f" (Constraint: {constraint_name})"
        elif isinstance(orig_exc, NotNullViolationError) or NotNullViolationError.__name__ in str(orig_exc):
            status_code = 400
            column_name = getattr(orig_exc, 'column_name', 'unknown') # type: ignore
            detail = f"Bad Request: Field '{column_name}' cannot be null."
        elif isinstance(orig_exc, ForeignKeyViolationError) or ForeignKeyViolationError.__name__ in str(orig_exc):
            status_code = 400
            constraint_name = getattr(orig_exc, 'constraint_name', 'unknown') # type: ignore
            error_detail_pg = getattr(orig_exc, 'detail', str(error)) # type: ignore
            detail = f"Bad Request: Related entity not found or constraint '{constraint_name}' failed."
        else:
            status_code = 500
            error_args = getattr(error, 'args', [])
            if error_args: detail += f" Details: {error_args[0]}"
            logger.error(f"Unhandled IntegrityError: {detail}")

        raise HTTPException(status_code=status_code, detail=detail) from error