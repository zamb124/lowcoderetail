# core_sdk/data_access/local_manager.py
import logging
from typing import (
    Type,
    List,
    Optional,
    Any,
    Mapping,
    Dict,
    Union,
    Literal,
    ClassVar
)
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlmodel import SQLModel, col, select as sqlmodel_select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from fastapi import HTTPException

# SDK Импорты
from core_sdk.db.session import get_current_session
from core_sdk.exceptions import ConfigurationError
from core_sdk.filters.base import DefaultFilter
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter
from .base_manager import BaseDataAccessManager, ModelType_co, CreateSchemaType_contra, UpdateSchemaType_contra

# Asyncpg ошибки
try:
    from asyncpg.exceptions import (
        UniqueViolationError,
        NotNullViolationError,
        ForeignKeyViolationError,
    )
except ImportError:
    logger_local_exc = logging.getLogger("core_sdk.data_access.local_manager.exceptions")
    logger_local_exc.warning("asyncpg not installed, IntegrityError details might be limited.")
    class UniqueViolationError(Exception): pass # type: ignore
    class NotNullViolationError(Exception): pass # type: ignore
    class ForeignKeyViolationError(Exception): pass # type: ignore

logger = logging.getLogger("core_sdk.data_access.local_manager")

MAX_LSN_FOR_EMPTY_DESC_INITIAL = 2**62 # Примерное максимальное значение для LSN

class LocalDataAccessManager(BaseDataAccessManager[ModelType_co, CreateSchemaType_contra, UpdateSchemaType_contra]):
    db_model_cls: Type[SQLModel] # Класс SQLModel для работы с БД

    def __init__(
            self,
            model_name: str,
            model_cls: Type[SQLModel], # Это SQLModel класс таблицы
            read_schema_cls: Type[ModelType_co], # Это Pydantic/SQLModel схема для возврата (UserRead)
            create_schema_cls: Optional[Type[CreateSchemaType_contra]] = None,
            update_schema_cls: Optional[Type[UpdateSchemaType_contra]] = None,
            **kwargs: Any # kwargs для BaseDataAccessManager (например, http_client, который здесь не нужен)
    ):
        # В BaseDataAccessManager model_cls - это то, что возвращается (read_schema_cls)
        super().__init__(
            model_name=model_name,
            model_cls=read_schema_cls,
            create_schema_cls=create_schema_cls,
            update_schema_cls=update_schema_cls
        )
        # db_model_cls - это конкретная SQLModel таблица
        self.db_model_cls: Type[SQLModel] = model_cls
        logger.debug(f"LocalDataAccessManager '{self.__class__.__name__}' initialized for DB model '{model_cls.__name__}', returns '{read_schema_cls.__name__}'.")


    @property
    def session(self) -> AsyncSession:
        return get_current_session()

    def _get_filter_class(self) -> Type[BaseSQLAlchemyFilter]:
        from core_sdk.registry import ModelRegistry # Импорт внутри метода
        try:
            model_info = ModelRegistry.get_model_info(self.model_name)
            filter_cls = model_info.filter_cls
            if filter_cls:
                if issubclass(filter_cls, BaseSQLAlchemyFilter):
                    # Динамическое добавление Constants.model, если его нет
                    if not hasattr(filter_cls, "Constants") or not hasattr(filter_cls.Constants, "model"):
                        logger.debug(f"Filter {filter_cls.__name__} for {self.model_name} is missing Constants.model. Adding dynamically.")
                        # Определяем поля для поиска, если они не заданы в Constants фильтра
                        search_fields_from_filter_constants = []
                        if hasattr(filter_cls, "Constants") and hasattr(filter_cls.Constants, "search_model_fields"):
                            search_fields_from_filter_constants = filter_cls.Constants.search_model_fields

                        constants_class = type(
                            "Constants",
                            (object,),
                            {
                                "model": self.db_model_cls, # Используем db_model_cls (SQLModel)
                                "search_model_fields": search_fields_from_filter_constants
                            }
                        )
                        # Создаем новый класс фильтра с добавленным Constants
                        wrapper_name = f"{filter_cls.__name__}WithDynamicConstants"
                        attrs_for_new_filter = {
                            "Constants": constants_class,
                            "__module__": filter_cls.__module__,
                            "__qualname__": f"{filter_cls.__qualname__}.{wrapper_name}"
                        }
                        if hasattr(filter_cls, 'model_config'): # Для Pydantic v2
                            attrs_for_new_filter['model_config'] = filter_cls.model_config.copy()

                        filter_cls_with_constants = type(wrapper_name, (filter_cls,), attrs_for_new_filter)

                        try:
                            if hasattr(filter_cls_with_constants, 'model_rebuild'):
                                filter_cls_with_constants.model_rebuild(force=True) # type: ignore
                        except Exception as e_rebuild:
                            logger.warning(f"Could not rebuild filter_cls_with_constants {filter_cls_with_constants.__name__}: {e_rebuild}")
                        return filter_cls_with_constants
                    return filter_cls
                else:
                    logger.warning(f"Registered filter_cls {filter_cls.__name__} for {self.model_name} is not a subclass of BaseSQLAlchemyFilter. Falling back.")
            else:
                logger.debug(f"No specific filter registered for {self.model_name}. Using DefaultFilter derivative.")
        except ConfigurationError:
            logger.warning(f"Model '{self.model_name}' not found in registry for filter. Using DefaultFilter derivative.")
        except Exception as e:
            logger.exception(f"Error getting filter class for {self.model_name}. Using DefaultFilter derivative. Error: {e}")

        final_filter_model_name = f"{self.db_model_cls.__name__}DefaultRuntimeFilter"
        search_fields = [
            name for name, field_info_obj in self.db_model_cls.model_fields.items()
            if hasattr(field_info_obj, 'annotation') and (field_info_obj.annotation is str or field_info_obj.annotation is Optional[str])
        ]

        runtime_constants_class_name = f"{self.db_model_cls.__name__}RuntimeFilterConstants"
        RuntimeConstantsClass = type(
            runtime_constants_class_name,
            (DefaultFilter.Constants,),
            {
                "model": self.db_model_cls,
                "search_model_fields": search_fields,
                "__module__": DefaultFilter.Constants.__module__,
                "__qualname__": f"{DefaultFilter.Constants.__qualname__}.{runtime_constants_class_name}"
            }
        )
        filter_attrs = {
            "Constants": RuntimeConstantsClass,
            "__module__": DefaultFilter.__module__,
            "__qualname__": f"{DefaultFilter.__qualname__}.{final_filter_model_name}",
            "model_config": getattr(DefaultFilter, 'model_config', {}).copy()
        }
        filter_attrs["__annotations__"] = {"Constants": ClassVar[Type[RuntimeConstantsClass]]} # type: ignore

        default_runtime_filter_cls = type(final_filter_model_name, (DefaultFilter,), filter_attrs)
        try:
            if hasattr(default_runtime_filter_cls, 'model_rebuild'): default_runtime_filter_cls.model_rebuild(force=True)
        except Exception as e_rebuild_def:
            logger.warning(f"Could not rebuild default_runtime_filter_cls {default_runtime_filter_cls.__name__}: {e_rebuild_def}")
        return default_runtime_filter_cls # type: ignore


    async def list(
            self,
            *,
            cursor: Optional[int] = None,
            limit: int = 50,
            filters: Optional[Union[BaseSQLAlchemyFilter, Mapping[str, Any]]] = None,
            direction: Literal["asc", "desc"] = "asc",
    ) -> Dict[str, Any]:
        logger.debug(f"Local DAM LIST: {self.model_name}, Direction: {direction}, Input Cursor: {cursor}, Limit: {limit}, Filters: {type(filters)}")
        if not hasattr(self.db_model_cls, "lsn"):
            raise ValueError(f"Cursor pagination requires 'lsn' attribute on model {self.db_model_cls.__name__}")

        lsn_attr = col(self.db_model_cls.lsn) # type: ignore
        base_statement = sqlmodel_select(self.db_model_cls)
        session = self.session
        order_by_clauses: List[Any] = []
        filter_obj: Optional[BaseSQLAlchemyFilter] = None

        if isinstance(filters, Mapping) or isinstance(filters, BaseSQLAlchemyFilter):
            actual_filter_cls = self._get_filter_class()
            logger.debug(f"Using filter class: {actual_filter_cls.__name__} for list operation.")
            if isinstance(filters, Mapping):
                try:
                    filter_obj = actual_filter_cls(**filters) # Pydantic v1 style
                    # Для Pydantic v2: filter_obj = actual_filter_cls.model_validate(filters)
                except ValidationError as ve:
                    logger.error(f"Filter validation error: {ve.errors()}", exc_info=True)
                    raise HTTPException(status_code=422, detail=f"Invalid filter parameters: {ve.errors()}")
                except Exception as e:
                    logger.error(f"Error creating filter object: {e}", exc_info=True)
                    raise HTTPException(status_code=500, detail=f"Internal error processing filters: {e}")
            elif isinstance(filters, BaseSQLAlchemyFilter):
                if not isinstance(filters, actual_filter_cls):
                    logger.warning(f"Received filter object of type {type(filters).__name__}, but expected {actual_filter_cls.__name__}. Proceeding cautiously.")
                filter_obj = filters
        elif filters is not None:
            raise TypeError(f"Unsupported filter type: {type(filters)}. Expected Filter object or dict.")

        statement = base_statement
        if filter_obj:
            statement = filter_obj.filter(statement)
            constants = getattr(filter_obj, "Constants", None)
            if constants and hasattr(constants, "model"):
                try:
                    sort_result_select = filter_obj.sort(sqlmodel_select(constants.model)) # type: ignore
                    if hasattr(sort_result_select, '_order_by_clauses'):
                        order_by_clauses = sort_result_select._order_by_clauses # type: ignore
                        logger.debug(f"Applied custom sort from {type(filter_obj).__name__}: {order_by_clauses}")
                    else:
                        logger.warning(f"Filter {type(filter_obj).__name__}.sort() did not return expected structure for order_by_clauses.")
                except Exception as e_sort:
                    logger.warning(f"Could not apply sort from custom filter {type(filter_obj).__name__}: {e_sort}")
            else:
                logger.debug(f"Filter {type(filter_obj).__name__} has no Constants.model, skipping custom sort application.")


        effective_query_cursor: Optional[int] = cursor
        if effective_query_cursor is not None:
            if not isinstance(effective_query_cursor, int):
                raise ValueError("Cursor must be an integer LSN value.")
            if direction == "asc":
                statement = statement.where(lsn_attr > effective_query_cursor)
            else: # desc
                statement = statement.where(lsn_attr < effective_query_cursor)
        else: # No cursor provided
            if direction == "desc": # For initial DESC query, no LSN condition needed yet
                pass

        if order_by_clauses:
            statement = statement.order_by(None)
            for ob_clause in order_by_clauses:
                statement = statement.order_by(ob_clause)
        if direction == "asc":
            statement = statement.order_by(lsn_attr.asc())
        else: # desc
            statement = statement.order_by(lsn_attr.desc())

        statement = statement.limit(limit)
        logger.debug(f"Executing query: {str(statement.compile(compile_kwargs={'literal_binds': True})) if hasattr(statement, 'compile') else 'SQLModel select object'}")

        try:
            result = await session.execute(statement)
            items_from_db_raw = list(result.scalars().all()) # type: List[SQLModel]
            count = len(items_from_db_raw)
            items_to_return = [self.model_cls.model_validate(item_db) for item_db in items_from_db_raw]
            logger.debug(f"Fetched {count} items from DB, converted to {self.model_cls.__name__}.")
        except Exception as e:
            logger.exception(f"Error executing list query for {self.model_name}")
            raise HTTPException(status_code=500, detail="Database error during list operation.")

        output_next_cursor: Optional[int] = None
        if count > 0:
            last_item_lsn = items_from_db_raw[-1].lsn # type: ignore
            if last_item_lsn is not None:
                 output_next_cursor = int(last_item_lsn)
            else:
                logger.error(f"LSN is None for the last item in pagination query for {self.model_name}. This should not happen.")
                if direction == "asc": output_next_cursor = effective_query_cursor
                else: output_next_cursor = MAX_LSN_FOR_EMPTY_DESC_INITIAL
        elif cursor is not None:
            output_next_cursor = cursor
        else:
            if direction == "asc": output_next_cursor = 0
            else: output_next_cursor = MAX_LSN_FOR_EMPTY_DESC_INITIAL

        pagination_data = {
            "items": items_to_return,
            "next_cursor": output_next_cursor,
            "limit": limit,
            "count": count,
        }
        logger.debug(f"List result for {self.model_name}: Count={count}, NextCursor={output_next_cursor}")
        return pagination_data

    async def get(self, item_id: UUID) -> Optional[ModelType_co]:
        logger.debug(f"Local DAM GET: {self.model_name} ID: {item_id}")
        db_item = await self.session.get(self.db_model_cls, item_id)
        if db_item:
            return self.model_cls.model_validate(db_item) # model_cls это ReadSchema
        return None

    async def create(self, data: Union[CreateSchemaType_contra, Dict[str, Any]]) -> ModelType_co:
        logger.debug(f"Local DAM CREATE: {self.model_name}")
        validated_data: CreateSchemaType_contra
        if isinstance(data, dict):
            if self.create_schema_cls is None:
                raise ConfigurationError(f"CreateSchema not defined for {self.db_model_cls.__name__}, cannot validate dict.")
            try:
                validated_data = self.create_schema_cls.model_validate(data)
            except ValidationError as ve:
                raise HTTPException(status_code=422, detail=ve.errors())
        elif self.create_schema_cls and isinstance(data, self.create_schema_cls):
            validated_data = data
        elif isinstance(data, BaseModel) and self.create_schema_cls is None: # Если create_schema не задан, но data - Pydantic
            validated_data = data # type: ignore
        else:
            expected_type = self.create_schema_cls.__name__ if self.create_schema_cls else "registered Create Schema"
            raise TypeError(f"Unsupported data type for creating {self.db_model_cls.__name__}: {type(data)}. Expected {expected_type} or dict.")

        db_item_instance = await self._prepare_for_create(validated_data)
        session = self.session
        session.add(db_item_instance)
        try:
            await session.commit()
            await session.refresh(db_item_instance)
            logger.info(f"Successfully created {self.model_name} with ID {getattr(db_item_instance, 'id', 'N/A')}")
            return self.model_cls.model_validate(db_item_instance) # model_cls это ReadSchema
        except IntegrityError as e:
            await session.rollback() # Откатываем сессию перед обработкой ошибки
            self._handle_integrity_error(e, context="create", input_data=validated_data)
            raise # _handle_integrity_error уже выбросит HTTPException
        except Exception as e:
            await session.rollback()
            logger.exception(f"Failed to create {self.db_model_cls.__name__} due to internal error: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create {self.db_model_cls.__name__} due to internal error: {e}")

    async def update(
            self, item_id: UUID, data: Union[UpdateSchemaType_contra, Dict[str, Any]]
    ) -> ModelType_co:
        logger.debug(f"Local DAM UPDATE: {self.model_name} ID: {item_id}")
        db_item_from_db = await self.session.get(self.db_model_cls, item_id)
        if not db_item_from_db:
            raise HTTPException(status_code=404, detail=f"{self.model_name} with id {item_id} not found")

        update_payload: Dict[str, Any]
        if isinstance(data, dict):
            if self.update_schema_cls:
                try:
                    validated_update_schema = self.update_schema_cls.model_validate(data)
                    update_payload = validated_update_schema.model_dump(exclude_unset=True)
                except ValidationError as ve:
                    raise HTTPException(status_code=422, detail=ve.errors())
            else: # Если update_schema не задан, используем dict как есть
                update_payload = data
        elif self.update_schema_cls and isinstance(data, self.update_schema_cls):
            update_payload = data.model_dump(exclude_unset=True)
        elif isinstance(data, BaseModel) and self.update_schema_cls is None: # Если update_schema не задан, но data - Pydantic
            update_payload = data.model_dump(exclude_unset=True) # type: ignore
        else:
            expected_type = self.update_schema_cls.__name__ if self.update_schema_cls else "registered Update Schema"
            raise TypeError(f"Unsupported data type for updating {self.db_model_cls.__name__}: {type(data)}. Expected {expected_type} or dict.")

        if not update_payload: # Если после exclude_unset ничего не осталось
            logger.info(f"No fields to update for {self.model_name} {item_id}. Returning current state.")
            return self.model_cls.model_validate(db_item_from_db) # model_cls это ReadSchema

        db_item_prepared, updated = await self._prepare_for_update(db_item_from_db, update_payload)

        if not updated:
            logger.info(f"No actual changes detected for {self.model_name} {item_id} after _prepare_for_update. Returning current state.")
            return self.model_cls.model_validate(db_item_prepared) # model_cls это ReadSchema

        session = self.session
        session.add(db_item_prepared)
        try:
            await session.commit()
            await session.refresh(db_item_prepared)
            logger.info(f"Successfully updated {self.model_name} {item_id}")
            return self.model_cls.model_validate(db_item_prepared) # model_cls это ReadSchema
        except IntegrityError as e:
            await session.rollback()
            self._handle_integrity_error(e, context="update", input_data=update_payload)
            raise
        except Exception as e:
            await session.rollback()
            logger.exception(f"Failed to update {self.db_model_cls.__name__} due to internal error: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to update {self.db_model_cls.__name__} due to internal error: {e}")

    async def delete(self, item_id: UUID) -> bool:
        logger.debug(f"Local DAM DELETE: {self.model_name} ID: {item_id}")
        session = self.session
        db_item = await self.session.get(self.db_model_cls, item_id)
        if db_item:
            await self._prepare_for_delete(db_item)
            try:
                await session.delete(db_item)
                await session.commit()
                logger.info(f"Successfully deleted {self.model_name} {item_id}")
                return True
            except IntegrityError as e:
                await session.rollback()
                self._handle_integrity_error(e, context="delete")
                return False # Или можно перевыбросить HTTPException, если это предпочтительнее
            except Exception as e:
                await session.rollback()
                logger.exception(f"Failed to delete {self.db_model_cls.__name__} due to internal error.")
                raise HTTPException(status_code=500, detail=f"Failed to delete {self.db_model_cls.__name__} due to internal error.")
        else:
            raise HTTPException(status_code=404, detail=f"{self.model_name} with id {item_id} not found")

    async def _prepare_for_create(self, validated_data: CreateSchemaType_contra) -> SQLModel:
        """
        Подготавливает объект модели БД для создания.
        По умолчанию просто преобразует схему создания в модель БД.
        Может быть переопределен для кастомной логики (например, хеширование пароля).
        """
        logger.debug(f"_prepare_for_create for {self.model_name}")
        try:
            # validated_data уже является экземпляром create_schema_cls
            # Преобразуем его в словарь, чтобы создать экземпляр db_model_cls
            # Это предполагает, что поля create_schema_cls совместимы с полями db_model_cls
            data_dict = validated_data.model_dump()
            return self.db_model_cls(**data_dict)
        except Exception as e:
            logger.exception(f"Error preparing model instance from create schema: {e}")
            raise HTTPException(status_code=400, detail=f"Error preparing model instance: {e}")

    async def _prepare_for_update(
            self, db_item: SQLModel, update_payload: Dict[str, Any]
    ) -> tuple[SQLModel, bool]:
        """
        Применяет данные из update_payload к существующему объекту модели БД.
        Возвращает обновленный объект и флаг, указывающий, были ли внесены изменения.
        Может быть переопределен для кастомной логики (например, обновление `updated_at`).
        """
        updated = False
        item_id_str = getattr(db_item, "id", "N/A")
        logger.debug(f"_prepare_for_update for {self.model_name} ID {item_id_str}")
        for key, value in update_payload.items():
            if hasattr(db_item, key):
                current_value = getattr(db_item, key)
                if current_value != value:
                    setattr(db_item, key, value)
                    updated = True
            else:
                logger.warning(f"Attribute '{key}' not found on model {self.db_model_cls.__name__} during update preparation.")

        if updated and hasattr(db_item, "updated_at"):
            from datetime import datetime, timezone # Импорт внутри, чтобы избежать глобального
            setattr(db_item, "updated_at", datetime.now(timezone.utc))
        return db_item, updated

    async def _prepare_for_delete(self, db_item: SQLModel) -> None:
        """
        Хук, вызываемый перед удалением объекта из БД.
        Может быть переопределен для выполнения кастомных действий (например, проверки зависимостей).
        """
        logger.debug(f"_prepare_for_delete for {self.model_name} ID {getattr(db_item, 'id', 'N/A')}")
        pass # По умолчанию ничего не делает

    def _handle_integrity_error(
            self, error: IntegrityError, context: str = "operation", input_data: Optional[Any] = None
    ):
        """
        Обрабатывает ошибки IntegrityError (например, UniqueViolationError)
        и преобразует их в соответствующие HTTPException.
        """
        orig_exc = getattr(error, "orig", None) # asyncpg хранит оригинальное исключение в .orig
        detail = f"Database integrity error during {context}."
        status_code = 409 # По умолчанию конфликт

        logger.warning(f"Handling IntegrityError (orig: {type(orig_exc).__name__ if orig_exc else 'Unknown'}) during {context} for {self.model_name}")

        if isinstance(orig_exc, UniqueViolationError) or (isinstance(orig_exc, Exception) and UniqueViolationError.__name__ in str(type(orig_exc))):
            status_code = 409
            # Попытка извлечь имя поля из сообщения об ошибке (зависит от СУБД)
            constraint_name = getattr(orig_exc, "constraint_name", "unknown")
            error_detail_pg = getattr(orig_exc, "detail", None) # type: ignore
            field_name = "unknown field"
            if error_detail_pg and isinstance(error_detail_pg, str) and "Key (" in error_detail_pg and ")=" in error_detail_pg:
                try: field_name = error_detail_pg.split("(")[1].split(")")[0]
                except Exception: pass
            detail = f"Conflict: Value for '{field_name}' already exists."
            if constraint_name != "unknown": detail += f" (Constraint: {constraint_name})"
        elif isinstance(orig_exc, NotNullViolationError) or (isinstance(orig_exc, Exception) and NotNullViolationError.__name__ in str(type(orig_exc))):
            status_code = 400 # Bad Request
            column_name = getattr(orig_exc, "column_name", "unknown_column") # type: ignore
            detail = f"Bad Request: Field '{column_name}' cannot be null."
        elif isinstance(orig_exc, ForeignKeyViolationError) or (isinstance(orig_exc, Exception) and ForeignKeyViolationError.__name__ in str(type(orig_exc))):
            status_code = 400 # Bad Request, т.к. ссылка на несуществующую запись
            constraint_name = getattr(orig_exc, "constraint_name", "unknown_fk_constraint") # type: ignore
            detail = f"Bad Request: Related entity not found or constraint '{constraint_name}' failed."
        else: # Общий случай IntegrityError или неизвестная ошибка asyncpg
            status_code = 500 # Внутренняя ошибка сервера, если не можем точно определить
            error_args = getattr(error, "args", [])
            if error_args and isinstance(error_args[0], str):
                detail += f" Details: {error_args[0]}"
            logger.error(f"Unhandled IntegrityError for {self.model_name} during {context}: {detail}", exc_info=True)

        raise HTTPException(status_code=status_code, detail=detail) from error