# core_sdk/data_access/remote_manager.py
import logging
from typing import (
    Type,
    Optional,
    Any,
    Mapping,
    Dict,
    Union,
    Literal
)
from uuid import UUID

from pydantic import BaseModel as PydanticBaseModel, ValidationError
import httpx
from fastapi import HTTPException

from core_sdk.exceptions import ServiceCommunicationError, ConfigurationError
from core_sdk.clients.base import RemoteServiceClient
from core_sdk.filters.base import DefaultFilter
from .base_manager import BaseDataAccessManager, DM_CreateSchemaType, DM_UpdateSchemaType, DM_ReadSchemaType

logger = logging.getLogger("core_sdk.data_access.remote_manager")

# RemoteDataAccessManager работает с DM_ReadSchemaType как с основным типом (WorkingModelType)
# и также использует DM_ReadSchemaType как схему для чтения (четвертый параметр дженерика)
class RemoteDataAccessManager(BaseDataAccessManager[DM_ReadSchemaType, DM_CreateSchemaType, DM_UpdateSchemaType, DM_ReadSchemaType]):
    client: RemoteServiceClient[DM_ReadSchemaType, DM_CreateSchemaType, DM_UpdateSchemaType]
    remote_config: Any

    def __init__(
            self,
            model_name: str,
            model_cls: Type[DM_ReadSchemaType],
            remote_config: Any,
            http_client: httpx.AsyncClient,
            auth_token: Optional[str] = None,
            create_schema_cls: Optional[Type[DM_CreateSchemaType]] = None,
            update_schema_cls: Optional[Type[DM_UpdateSchemaType]] = None,
            # read_schema_cls для super() будет таким же, как model_cls
    ):
        super().__init__(
            model_name=model_name,
            model_cls=model_cls,
            create_schema_cls=create_schema_cls,
            update_schema_cls=update_schema_cls,
            read_schema_cls=model_cls,
            http_client=http_client
        )
        from core_sdk.registry import RemoteConfig as ActualRemoteConfig
        if not isinstance(remote_config, ActualRemoteConfig):
            raise TypeError(f"Expected RemoteConfig, got {type(remote_config)}")
        self.remote_config = remote_config
        self.auth_token = auth_token

        try:
            self.client = RemoteServiceClient(
                base_url=self.remote_config.service_url,
                model_endpoint=self.remote_config.model_endpoint,
                model_cls=self.model_cls,
                auth_token=self.auth_token,
                http_client=self._http_client,
            )
        except Exception as e:
            logger.exception(f"Failed to initialize RemoteServiceClient for remote DAM (endpoint: {self.remote_config.model_endpoint}).")
            raise ConfigurationError(f"Error initializing HTTP client for remote DAM: {e}") from e

        logger.info(f"Remote DAM Initialized for model '{model_name}', endpoint: '{self.remote_config.model_endpoint}', parsing responses to '{self.model_cls.__name__}'.")

    async def get(self, item_id: UUID) -> Optional[DM_ReadSchemaType]:
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
            filters: Optional[Union[DefaultFilter, Mapping[str, Any]]] = None,
            direction: Literal["asc", "desc"] = "asc",
    ) -> Dict[str, Any]:
        logger.debug(f"Remote DAM LIST: Requesting list of '{self.model_name}'. Filters: {filters}, Limit: {limit}, Cursor: {cursor}, Direction: {direction}")
        query_filters: Dict[str, Any] = {}
        if isinstance(filters, PydanticBaseModel):
            query_filters = filters.model_dump(exclude_none=True, by_alias=False)
        elif isinstance(filters, Mapping):
            query_filters = {k: v for k, v in filters.items() if v != '' }

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

            if paginated_dict_result.get("items") and not all(isinstance(item, self.model_cls) for item in paginated_dict_result["items"]):
                logger.warning(f"Items from RemoteServiceClient.list are not all of type {self.model_cls.__name__}. This might indicate an issue in RemoteServiceClient parsing.")

            return paginated_dict_result
        except ServiceCommunicationError as e:
            raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal error during remote list: {e}") from e

    async def create(self, data: Union[DM_CreateSchemaType, Dict[str, Any]]) -> DM_ReadSchemaType:
        logger.debug(f"Remote DAM CREATE: Creating new '{self.model_name}'.")
        validated_data: DM_CreateSchemaType
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
            self, item_id: UUID, data: Union[DM_UpdateSchemaType, Dict[str, Any]]
    ) -> DM_ReadSchemaType:
        logger.debug(f"Remote DAM UPDATE: Updating '{self.model_name}' with ID: {item_id}.")
        validated_data: DM_UpdateSchemaType
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