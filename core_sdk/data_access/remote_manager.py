# core_sdk/data_access/remote_manager.py
import logging
from typing import (
    Type,
    List,
    Optional,
    Any,
    Mapping,
    Dict,
    Union,
    cast,
    Literal,
)
from uuid import UUID

from pydantic import BaseModel, ValidationError, HttpUrl # HttpUrl нужен для RemoteConfig
from sqlmodel import SQLModel
import httpx
from fastapi import HTTPException

# SDK Импорты
from core_sdk.exceptions import ServiceCommunicationError, ConfigurationError
# --- УБИРАЕМ ИМПОРТ RemoteConfig ОТСЮДА ---
# from core_sdk.registry import RemoteConfig
# -------------------------------------------
from core_sdk.clients.base import RemoteServiceClient
from filters.base import DefaultFilter
from .base_manager import BaseDataAccessManager, ModelType_co, CreateSchemaType_contra, UpdateSchemaType_contra

logger = logging.getLogger("core_sdk.data_access.remote_manager")

class RemoteDataAccessManager(BaseDataAccessManager[ModelType_co, CreateSchemaType_contra, UpdateSchemaType_contra]):
    client: RemoteServiceClient[ModelType_co, CreateSchemaType_contra, UpdateSchemaType_contra]
    # --- ДОБАВЛЯЕМ remote_config как атрибут экземпляра ---
    remote_config: Any # Будет типа RemoteConfig, но импортируем позже
    # ----------------------------------------------------


    def __init__(
        self,
        model_name: str,
        model_cls: Type[ModelType_co],
        remote_config: Any, # Принимаем Any, чтобы избежать импорта RemoteConfig здесь
        http_client: httpx.AsyncClient,
        auth_token: Optional[str] = None,
        create_schema_cls: Optional[Type[CreateSchemaType_contra]] = None,
        update_schema_cls: Optional[Type[UpdateSchemaType_contra]] = None,
    ):
        super().__init__(
            model_name=model_name,
            model_cls=model_cls,
            create_schema_cls=create_schema_cls,
            update_schema_cls=update_schema_cls,
            http_client=http_client
        )
        # --- ПЕРЕНОСИМ ИМПОРТ RemoteConfig ВНУТРЬ КОНСТРУКТОРА ---
        from core_sdk.registry import RemoteConfig as ActualRemoteConfig
        if not isinstance(remote_config, ActualRemoteConfig):
            raise TypeError(f"Expected RemoteConfig, got {type(remote_config)}")
        # ---------------------------------------------------------
        self.remote_config = remote_config # Сохраняем типизированный remote_config
        self.auth_token = auth_token

        try:
            self.client = RemoteServiceClient(
                base_url=self.remote_config.service_url, # Используем сохраненный self.remote_config
                model_endpoint=self.remote_config.model_endpoint,
                model_cls=self.model_cls,
                auth_token=self.auth_token,
                http_client=self._http_client,
            )
        except Exception as e:
            logger.exception(f"Failed to initialize RemoteServiceClient for remote DAM (endpoint: {self.remote_config.model_endpoint}).")
            raise ConfigurationError(f"Error initializing HTTP client for remote DAM: {e}") from e

        logger.info(f"Remote DAM Initialized for model '{model_name}', endpoint: '{self.remote_config.model_endpoint}', parsing responses to '{self.model_cls.__name__}'.")

    # ... (остальные методы get, list, create, update, delete без изменений) ...
    async def get(self, item_id: UUID) -> Optional[ModelType_co]:
        logger.debug(f"Remote DAM GET: Requesting '{self.model_name}' with ID: {item_id}")
        try:
            result = await self.client.get(item_id)
            if result is None:
                logger.info(f"Remote DAM GET: Item {item_id} not found (404).")
            return result
        except ServiceCommunicationError as e:
            if e.status_code == 404: return None
            raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal error during remote get: {e}") from e

    async def list(
        self,
        *,
        cursor: Optional[int] = None,
        limit: int = 50,
        filters: Optional[Union[DefaultFilter, Mapping[str, Any]]] = None, # BaseSQLAlchemyFilter здесь для совместимости интерфейса
        direction: Literal["asc", "desc"] = "asc",
    ) -> Dict[str, Any]:
        logger.debug(f"Remote DAM LIST: Requesting list of '{self.model_name}'. Filters: {filters}, Limit: {limit}, Cursor: {cursor}, Direction: {direction}")
        query_filters: Dict[str, Any] = {}
        if isinstance(filters, BaseModel): # Проверяем, если это Pydantic модель (включая BaseSQLAlchemyFilter)
            query_filters = filters.model_dump(exclude_none=True, by_alias=False)
        elif isinstance(filters, Mapping):
            query_filters = {k: v for k, v in filters.items() if v is not None}

        try:
            paginated_dict_result = await self.client.list(
                cursor=cursor,
                limit=limit,
                filters=query_filters,
                direction=direction,
            )
            if not isinstance(paginated_dict_result, dict) or "items" not in paginated_dict_result:
                logger.error(f"RemoteServiceClient.list for {self.model_name} returned unexpected format: {type(paginated_dict_result)}")
                raise ServiceCommunicationError("Invalid paginated response format from remote service.")
            return paginated_dict_result
        except ServiceCommunicationError as e:
            raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal error during remote list: {e}") from e

    async def create(self, data: Union[CreateSchemaType_contra, Dict[str, Any]]) -> ModelType_co:
        logger.debug(f"Remote DAM CREATE: Creating new '{self.model_name}'.")
        validated_data: CreateSchemaType_contra
        if isinstance(data, dict):
            if self.create_schema_cls is None:
                raise ConfigurationError(f"CreateSchema not defined for remote model {self.model_name}, cannot validate dict.")
            try:
                validated_data = self.create_schema_cls.model_validate(data)
            except ValidationError as ve:
                raise HTTPException(status_code=422, detail=ve.errors()) from ve
        elif self.create_schema_cls and isinstance(data, self.create_schema_cls):
            validated_data = data
        else:
            expected_type_name = self.create_schema_cls.__name__ if self.create_schema_cls else "registered Create Schema"
            raise TypeError(f"Unsupported data type for remote create {self.model_name}: {type(data)}. Expected {expected_type_name} or dict.")
        try:
            result = await self.client.create(validated_data)
            return result
        except ServiceCommunicationError as e:
            raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal error during remote create: {e}") from e

    async def update(
        self, item_id: UUID, data: Union[UpdateSchemaType_contra, Dict[str, Any]]
    ) -> ModelType_co:
        logger.debug(f"Remote DAM UPDATE: Updating '{self.model_name}' with ID: {item_id}.")
        validated_data: UpdateSchemaType_contra
        if isinstance(data, dict):
            if self.update_schema_cls is None:
                raise ConfigurationError(f"UpdateSchema not defined for remote model {self.model_name}, cannot validate dict.")
            try:
                validated_data = self.update_schema_cls.model_validate(data)
            except ValidationError as ve:
                raise HTTPException(status_code=422, detail=ve.errors()) from ve
        elif self.update_schema_cls and isinstance(data, self.update_schema_cls):
            validated_data = data
        else:
            expected_type_name = self.update_schema_cls.__name__ if self.update_schema_cls else "registered Update Schema"
            raise TypeError(f"Unsupported data type for remote update {self.model_name}: {type(data)}. Expected {expected_type_name} or dict.")
        try:
            result = await self.client.update(item_id, validated_data)
            return result
        except ServiceCommunicationError as e:
            if e.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Remote {self.model_name} with id {item_id} not found") from e
            raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal error during remote update: {e}") from e

    async def delete(self, item_id: UUID) -> bool:
        logger.debug(f"Remote DAM DELETE: Deleting '{self.model_name}' with ID: {item_id}.")
        try:
            success = await self.client.delete(item_id)
            return success
        except ServiceCommunicationError as e:
            raise HTTPException(status_code=e.status_code or 500, detail=f"Failed to delete remote item: {e}") from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal error during remote delete: {e}") from e