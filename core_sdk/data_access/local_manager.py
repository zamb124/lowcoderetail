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
import re

from pydantic import BaseModel as PydanticBaseModel, ValidationError
from sqlmodel import col, select as sqlmodel_select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

# SDK Импорты
from core_sdk.db.session import get_current_session
from core_sdk.exceptions import ConfigurationError
from core_sdk.filters.base import DefaultFilter
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter
from .base_manager import BaseDataAccessManager, DM_CreateSchemaType, DM_UpdateSchemaType, DM_ReadSchemaType, DM_SQLModelType

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

MAX_LSN_FOR_EMPTY_DESC_INITIAL = 2**62

class LocalDataAccessManager(BaseDataAccessManager[DM_SQLModelType, DM_CreateSchemaType, DM_UpdateSchemaType, DM_ReadSchemaType]):

    def __init__(
            self,
            model_name: str,
            model_cls: Type[DM_SQLModelType],
            read_schema_cls: Type[DM_ReadSchemaType],
            create_schema_cls: Optional[Type[DM_CreateSchemaType]] = None,
            update_schema_cls: Optional[Type[DM_UpdateSchemaType]] = None,
            **kwargs: Any
    ):
        super().__init__(
            model_name=model_name,
            model_cls=model_cls,
            create_schema_cls=create_schema_cls,
            update_schema_cls=update_schema_cls,
            read_schema_cls=read_schema_cls
        )
        logger.debug(f"LocalDataAccessManager '{self.__class__.__name__}' initialized for DB model '{model_cls.__name__}'. API Read schema: {read_schema_cls.__name__}")

    @property
    def session(self) -> AsyncSession:
        return get_current_session()

    def _get_filter_class(self) -> Type[BaseSQLAlchemyFilter]:
        from core_sdk.registry import ModelRegistry
        try:
            model_info = ModelRegistry.get_model_info(self.model_name)
            filter_cls = model_info.filter_cls
            if filter_cls:
                if issubclass(filter_cls, BaseSQLAlchemyFilter):
                    if not hasattr(filter_cls, "Constants") or not hasattr(filter_cls.Constants, "model"):
                        logger.debug(f"Filter {filter_cls.__name__} for {self.model_name} is missing Constants.model. Adding dynamically.")
                        search_fields_from_filter_constants = []
                        if hasattr(filter_cls, "Constants") and hasattr(filter_cls.Constants, "search_model_fields"):
                            search_fields_from_filter_constants = filter_cls.Constants.search_model_fields
                        constants_class = type("Constants", (object,), {"model": self.model_cls, "search_model_fields": search_fields_from_filter_constants})
                        wrapper_name = f"{filter_cls.__name__}WithDynamicConstants"
                        attrs_for_new_filter = {"Constants": constants_class, "__module__": filter_cls.__module__, "__qualname__": f"{filter_cls.__qualname__}.{wrapper_name}"}
                        if hasattr(filter_cls, 'model_config'): attrs_for_new_filter['model_config'] = filter_cls.model_config.copy()
                        filter_cls_with_constants = type(wrapper_name, (filter_cls,), attrs_for_new_filter)
                        try:
                            if hasattr(filter_cls_with_constants, 'model_rebuild'): filter_cls_with_constants.model_rebuild(force=True) # type: ignore
                        except Exception as e_rebuild: logger.warning(f"Could not rebuild filter_cls_with_constants {filter_cls_with_constants.__name__}: {e_rebuild}")
                        return filter_cls_with_constants
                    return filter_cls
                else: logger.warning(f"Registered filter_cls {filter_cls.__name__} for {self.model_name} is not a subclass of BaseSQLAlchemyFilter. Falling back.")
            else: logger.debug(f"No specific filter registered for {self.model_name}. Using DefaultFilter derivative.")
        except ConfigurationError: logger.warning(f"Model '{self.model_name}' not found in registry for filter. Using DefaultFilter derivative.")
        except Exception as e: logger.exception(f"Error getting filter class for {self.model_name}. Using DefaultFilter derivative. Error: {e}")

        final_filter_model_name = f"{self.model_cls.__name__}DefaultRuntimeFilter"
        search_fields = [name for name, field_info_obj in self.model_cls.model_fields.items() if hasattr(field_info_obj, 'annotation') and (field_info_obj.annotation is str or field_info_obj.annotation is Optional[str])]
        runtime_constants_class_name = f"{self.model_cls.__name__}RuntimeFilterConstants"
        RuntimeConstantsClass = type(runtime_constants_class_name, (DefaultFilter.Constants,), {"model": self.model_cls, "search_model_fields": search_fields, "__module__": DefaultFilter.Constants.__module__, "__qualname__": f"{DefaultFilter.Constants.__qualname__}.{runtime_constants_class_name}"})
        filter_attrs = {"Constants": RuntimeConstantsClass, "__module__": DefaultFilter.__module__, "__qualname__": f"{DefaultFilter.__qualname__}.{final_filter_model_name}", "model_config": getattr(DefaultFilter, 'model_config', {}).copy()}
        filter_attrs["__annotations__"] = {"Constants": ClassVar[Type[RuntimeConstantsClass]]}
        default_runtime_filter_cls = type(final_filter_model_name, (DefaultFilter,), filter_attrs)
        try:
            if hasattr(default_runtime_filter_cls, 'model_rebuild'): default_runtime_filter_cls.model_rebuild(force=True)
        except Exception as e_rebuild_def: logger.warning(f"Could not rebuild default_runtime_filter_cls {default_runtime_filter_cls.__name__}: {e_rebuild_def}")
        return default_runtime_filter_cls

    async def list(
            self,
            *,
            cursor: Optional[int] = None,
            limit: int = 50,
            filters: Optional[Union[BaseSQLAlchemyFilter, Mapping[str, Any]]] = None,
            direction: Literal["asc", "desc"] = "asc",
    ) -> Dict[str, Any]:
        logger.debug(f"Local DAM LIST: {self.model_name}, Direction: {direction}, Input Cursor: {cursor}, Limit: {limit}, Filters: {type(filters)}")
        if not hasattr(self.model_cls, "lsn"):
            raise ValueError(f"Cursor pagination requires 'lsn' attribute on model {self.model_cls.__name__}")
        lsn_attr = col(self.model_cls.lsn) # type: ignore
        base_statement = sqlmodel_select(self.model_cls)
        session = self.session
        order_by_clauses: List[Any] = []
        filter_obj: Optional[BaseSQLAlchemyFilter] = None
        if isinstance(filters, Mapping) or isinstance(filters, BaseSQLAlchemyFilter):
            actual_filter_cls = self._get_filter_class()
            if isinstance(filters, Mapping):
                try: filter_obj = actual_filter_cls(**filters)
                except ValidationError as ve: raise HTTPException(status_code=422, detail=f"Invalid filter parameters: {ve.errors()}")
                except Exception as e: raise HTTPException(status_code=500, detail=f"Internal error processing filters: {e}")
            elif isinstance(filters, BaseSQLAlchemyFilter):
                if not isinstance(filters, actual_filter_cls): logger.warning(f"Received filter object of type {type(filters).__name__}, but expected {actual_filter_cls.__name__}.")
                filter_obj = filters
        elif filters is not None: raise TypeError(f"Unsupported filter type: {type(filters)}.")
        statement = base_statement
        if filter_obj:
            statement = filter_obj.filter(statement)
            constants = getattr(filter_obj, "Constants", None)
            if constants and hasattr(constants, "model"):
                try:
                    sort_result_select = filter_obj.sort(sqlmodel_select(constants.model)) # type: ignore
                    if hasattr(sort_result_select, '_order_by_clauses'): order_by_clauses = sort_result_select._order_by_clauses # type: ignore
                except Exception as e_sort: logger.warning(f"Could not apply sort from custom filter {type(filter_obj).__name__}: {e_sort}")
        effective_query_cursor: Optional[int] = cursor
        if effective_query_cursor is not None:
            if direction == "asc": statement = statement.where(lsn_attr > effective_query_cursor)
            else: statement = statement.where(lsn_attr < effective_query_cursor)
        if order_by_clauses:
            statement = statement.order_by(None)
            for ob_clause in order_by_clauses: statement = statement.order_by(ob_clause)
        if direction == "asc": statement = statement.order_by(lsn_attr.asc())
        else: statement = statement.order_by(lsn_attr.desc())
        statement = statement.limit(limit)
        try:
            result = await session.execute(statement)
            items_from_db_raw = list(result.scalars().all())
            count = len(items_from_db_raw)
        except Exception:
            logger.exception(f"Error executing list query for {self.model_name}")
            raise HTTPException(status_code=500, detail="Database error during list operation.")
        output_next_cursor: Optional[int] = None
        if count > 0:
            last_item_lsn = items_from_db_raw[-1].lsn # type: ignore
            if last_item_lsn is not None: output_next_cursor = int(last_item_lsn)
            else:
                if direction == "asc": output_next_cursor = effective_query_cursor
                else: output_next_cursor = MAX_LSN_FOR_EMPTY_DESC_INITIAL
        elif cursor is not None: output_next_cursor = cursor
        else:
            if direction == "asc": output_next_cursor = 0
            else: output_next_cursor = MAX_LSN_FOR_EMPTY_DESC_INITIAL
        pagination_data = {"items": items_from_db_raw, "next_cursor": output_next_cursor, "limit": limit, "count": count}
        return pagination_data

    async def get(self, item_id: UUID) -> Optional[DM_SQLModelType]:
        logger.debug(f"Local DAM GET: {self.model_name} ID: {item_id}")
        db_item = await self.session.get(self.model_cls, item_id)
        return db_item

    async def create(self, data: Union[DM_CreateSchemaType, Dict[str, Any]]) -> DM_SQLModelType:
        logger.debug(f"Local DAM CREATE: {self.model_name}")
        validated_data: DM_CreateSchemaType
        if isinstance(data, dict):
            if self.create_schema_cls is None: raise ConfigurationError(f"CreateSchema not defined for {self.model_cls.__name__}, cannot validate dict.")
            try: validated_data = self.create_schema_cls.model_validate(data)
            except ValidationError as ve: raise HTTPException(status_code=422, detail=ve.errors())
        elif self.create_schema_cls and isinstance(data, self.create_schema_cls): validated_data = data
        elif isinstance(data, PydanticBaseModel) and self.create_schema_cls is None: validated_data = data # type: ignore
        else:
            expected_type = self.create_schema_cls.__name__ if self.create_schema_cls else "registered Create Schema"
            raise TypeError(f"Unsupported data type for creating {self.model_cls.__name__}: {type(data)}. Expected {expected_type} or dict.")
        db_item_instance = await self._prepare_for_create(validated_data)
        session = self.session
        session.add(db_item_instance)
        try:
            await session.commit()
            await session.refresh(db_item_instance)
            logger.info(f"Successfully created {self.model_name} with ID {getattr(db_item_instance, 'id', 'N/A')}")
            return db_item_instance
        except IntegrityError as e:
            await session.rollback()
            self._handle_integrity_error(e, context="create", input_data=validated_data)
        except Exception as e:
            await session.rollback()
            logger.exception(f"Failed to create {self.model_cls.__name__} due to internal error: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create {self.model_cls.__name__} due to internal error: {e}")

    async def update(
            self, item_id: UUID, data: Union[DM_UpdateSchemaType, Dict[str, Any]]
    ) -> DM_SQLModelType:
        logger.debug(f"Local DAM UPDATE: {self.model_name} ID: {item_id}")
        db_item_from_db = await self.session.get(self.model_cls, item_id)
        if not db_item_from_db:
            raise HTTPException(status_code=404, detail=f"{self.model_name} with id {item_id} not found")
        update_payload: Dict[str, Any]
        if isinstance(data, dict):
            if self.update_schema_cls:
                try:
                    validated_update_schema = self.update_schema_cls.model_validate(data)
                    update_payload = validated_update_schema.model_dump(exclude_unset=True)
                except ValidationError as ve: raise HTTPException(status_code=422, detail=ve.errors())
            else: update_payload = data
        elif self.update_schema_cls and isinstance(data, self.update_schema_cls): update_payload = data.model_dump(exclude_unset=True)
        elif isinstance(data, PydanticBaseModel) and self.update_schema_cls is None: update_payload = data.model_dump(exclude_unset=True) # type: ignore
        else:
            expected_type = self.update_schema_cls.__name__ if self.update_schema_cls else "registered Update Schema"
            raise TypeError(f"Unsupported data type for updating {self.model_cls.__name__}: {type(data)}. Expected {expected_type} or dict.")
        if not update_payload:
            logger.info(f"No fields to update for {self.model_name} {item_id}. Returning current state.")
            return db_item_from_db
        db_item_prepared, updated = await self._prepare_for_update(db_item_from_db, update_payload)
        if not updated:
            logger.info(f"No actual changes detected for {self.model_name} {item_id} after _prepare_for_update. Returning current state.")
            return db_item_prepared
        session = self.session
        session.add(db_item_prepared)
        try:
            await session.commit()
            await session.refresh(db_item_prepared)
            logger.info(f"Successfully updated {self.model_name} {item_id}")
            return db_item_prepared
        except IntegrityError as e:
            await session.rollback()
            self._handle_integrity_error(e, context="update", input_data=update_payload)
            raise
        except Exception as e:
            await session.rollback()
            logger.exception(f"Failed to update {self.model_cls.__name__} due to internal error: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to update {self.model_cls.__name__} due to internal error: {e}")

    async def delete(self, item_id: UUID) -> bool:
        logger.debug(f"Local DAM DELETE: {self.model_name} ID: {item_id}")
        session = self.session
        db_item = await self.session.get(self.model_cls, item_id)
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
                return False
            except Exception:
                await session.rollback()
                logger.exception(f"Failed to delete {self.model_cls.__name__} due to internal error.")
                raise HTTPException(status_code=500, detail=f"Failed to delete {self.model_cls.__name__} due to internal error.")
        else:
            raise HTTPException(status_code=404, detail=f"{self.model_name} with id {item_id} not found")

    async def _prepare_for_create(self, validated_data: DM_CreateSchemaType) -> DM_SQLModelType:
        logger.debug(f"_prepare_for_create for {self.model_name}")
        try:
            data_dict = validated_data.model_dump()
            return self.model_cls(**data_dict)
        except Exception as e:
            logger.exception(f"Error preparing model instance from create schema: {e}")
            raise HTTPException(status_code=400, detail=f"Error preparing model instance: {e}")

    async def _prepare_for_update(
            self, db_item: DM_SQLModelType, update_payload: Dict[str, Any]
    ) -> tuple[DM_SQLModelType, bool]:
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
                logger.warning(f"Attribute '{key}' not found on model {self.model_cls.__name__} during update preparation.")
        if updated and hasattr(db_item, "updated_at"):
            from datetime import datetime, timezone
            setattr(db_item, "updated_at", datetime.now(timezone.utc))
        return db_item, updated

    async def _prepare_for_delete(self, db_item: DM_SQLModelType) -> None:
        logger.debug(f"_prepare_for_delete for {self.model_name} ID {getattr(db_item, 'id', 'N/A')}")
        pass

    def _handle_integrity_error(
            self, error: IntegrityError, context: str = "operation", input_data: Optional[Any] = None
    ):
        orig_exc = getattr(error, "orig", None)
        detail = f"Database integrity error during {context}."
        status_code = 500
        logger.warning(f"Handling IntegrityError (orig: {type(orig_exc).__name__ if orig_exc else 'Unknown'}) during {context} for {self.model_name}. Original error: {error}")
        is_unique_violation = False
        if orig_exc:
            if isinstance(orig_exc, UniqueViolationError) or "UniqueViolationError" in str(orig_exc): is_unique_violation = True
        elif "unique constraint" in str(error).lower() or "duplicate key" in str(error).lower(): is_unique_violation = True
        is_not_null_violation = False
        if orig_exc:
            if isinstance(orig_exc, NotNullViolationError) or "NotNullViolationError" in str(orig_exc): is_not_null_violation = True
        elif "not-null constraint" in str(error).lower() or "violates not-null constraint" in str(error).lower(): is_not_null_violation = True
        is_foreign_key_violation = False
        if orig_exc:
            if isinstance(orig_exc, ForeignKeyViolationError) or "ForeignKeyViolationError" in str(orig_exc): is_foreign_key_violation = True
        elif "foreign key constraint" in str(error).lower(): is_foreign_key_violation = True
        if is_unique_violation:
            status_code = 409
            constraint_name = getattr(orig_exc, "constraint_name", "unknown")
            error_detail_pg = getattr(orig_exc, "detail", None)
            field_name = "unknown field"
            if error_detail_pg and isinstance(error_detail_pg, str) and "Key (" in error_detail_pg and ")=" in error_detail_pg:
                try: field_name = error_detail_pg.split("(")[1].split(")")[0]
                except Exception: pass
            elif "ix_companies_name" in str(error): field_name = "name"
            detail = f"Conflict: Value for '{field_name}' already exists."
            if constraint_name != "unknown": detail += f" (Constraint: {constraint_name})"
            logger.warning(f"Unique constraint violation: {detail}. Status code set to {status_code}.")
        elif is_not_null_violation:
            status_code = 400
            column_name = getattr(orig_exc, "column_name", "unknown_column")
            if column_name == "unknown_column" and "violates not-null constraint" in str(error):
                match = re.search(r'column "([^"]+)" of relation', str(error))
                if match: column_name = match.group(1)
            detail = f"Bad Request: Field '{column_name}' cannot be null."
            logger.warning(f"Not-null constraint violation: {detail}. Status code set to {status_code}.")
        elif is_foreign_key_violation:
            status_code = 400
            constraint_name = getattr(orig_exc, "constraint_name", "unknown_fk_constraint")
            detail = f"Bad Request: Related entity not found or constraint '{constraint_name}' failed."
            logger.warning(f"Foreign key constraint violation: {detail}. Status code set to {status_code}.")
        else:
            error_args = getattr(error, "args", [])
            if error_args and isinstance(error_args[0], str): detail += f" Details: {error_args[0]}"
            logger.error(f"Unhandled IntegrityError for {self.model_name} during {context}: {detail}. Status code set to {status_code}.", exc_info=True)
        raise HTTPException(status_code=status_code, detail=detail) from error