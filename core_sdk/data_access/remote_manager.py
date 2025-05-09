# core_sdk/data_access/remote_manager.py
import logging
from typing import Type, List, Optional, Any, Mapping, Dict, TypeVar, Generic, Union, cast
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlmodel import SQLModel # SQLModel используется для ModelType и read_schema
import httpx
from fastapi import HTTPException # HTTPException используется для преобразования ошибок

from core_sdk.exceptions import ServiceCommunicationError, ConfigurationError
from core_sdk.registry import RemoteConfig
from core_sdk.clients.base import RemoteServiceClient # Базовый HTTP клиент

logger = logging.getLogger(__name__) # Имя будет core_sdk.data_access.remote_manager

ModelType = TypeVar("ModelType", bound=SQLModel)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)

class RemoteDataAccessManager(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """
    Менеджер данных для взаимодействия с удаленным сервисом через HTTP.
    Имитирует интерфейс BaseDataAccessManager, делегируя операции
    экземпляру RemoteServiceClient.
    """
    model: Type[ModelType]
    create_schema: Optional[Type[CreateSchemaType]]
    update_schema: Optional[Type[UpdateSchemaType]]
    read_schema: Type[SQLModel] # Схема для парсинга ответов (может быть ModelType)
    client: RemoteServiceClient # Экземпляр HTTP клиента

    def __init__(
            self,
            remote_config: RemoteConfig,
            http_client: httpx.AsyncClient,
            model_cls: Type[ModelType],
            auth_token: Optional[str] = None,
            create_schema_cls: Optional[Type[CreateSchemaType]] = None,
            update_schema_cls: Optional[Type[UpdateSchemaType]] = None,
            read_schema_cls: Optional[Type[SQLModel]] = None,
    ):
        self.remote_config = remote_config
        # _http_client не нужен, т.к. он передается в RemoteServiceClient
        self.auth_token = auth_token

        self.model = model_cls
        self.create_schema = create_schema_cls
        self.update_schema = update_schema_cls
        self.read_schema = read_schema_cls or model_cls # По умолчанию читаем в основную модель

        try:
            self.client = RemoteServiceClient(
                base_url=remote_config.service_url,
                model_endpoint = model_cls.__tablename__.lower(),
                model_cls=self.read_schema, # Клиент будет парсить ответы в эту схему
                auth_token=self.auth_token,
                http_client=http_client # Используем переданный клиент
            )
        except Exception as e:
            logger.exception(f"Failed to initialize RemoteServiceClient for remote DAM (endpoint: {remote_config.model_endpoint}).")
            raise ConfigurationError(f"Error initializing HTTP client for remote DAM: {e}") from e

        logger.info(f"Remote DAM Initialized for model endpoint: '{remote_config.model_endpoint}', parsing responses to '{self.read_schema.__name__}'.")

    async def get(self, item_id: UUID) -> Optional[ModelType]:
        logger.debug(f"Remote DAM GET: Requesting '{self.read_schema.__name__}' with ID: {item_id} from endpoint '{self.remote_config.model_endpoint}'.")
        try:
            # RemoteServiceClient.get ожидает model_endpoint
            result = await self.client.get(item_id)
            if result is None:
                logger.info(f"Remote DAM GET: Item {item_id} not found (404).")
                return None
            # Результат уже типа self.read_schema (или ModelType, если они совпадают)
            # Кастуем к ModelType для соответствия сигнатуре, если read_schema отличается, но совместим.
            return cast(ModelType, result)
        except ServiceCommunicationError as e:
            logger.warning(f"Remote DAM GET: ServiceCommunicationError for ID {item_id}. Status: {e.status_code}. Error: {e}", exc_info=True if e.status_code != 404 else False)
            if e.status_code == 404: return None # Ожидаемая ошибка "не найдено"
            raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e
        except Exception as e:
            logger.exception(f"Remote DAM GET: Unexpected error for ID {item_id}.")
            raise HTTPException(status_code=500, detail=f"Internal error during remote get: {e}") from e

    async def list(
            self,
            *,
            cursor: Optional[int] = None,
            limit: int = 50,
            filters: Optional[Mapping[str, Any]] = {},
            direction: Optional[str] = 'asc', # Не используется в RemoteServiceClient
            # order_by не используется стандартным RemoteServiceClient, но может быть в кастомном
            order_by: Optional[List[Any]] = None # pylint: disable=unused-argument
    ) -> List[ModelType]: # Возвращает список, а не словарь с пагинацией как BaseDAM
        logger.debug(f"Remote DAM LIST: Requesting list of '{self.read_schema.__name__}' from endpoint '{self.remote_config.model_endpoint}'. Filters: {filters}, Limit: {limit}, Cursor: {cursor}")
        filters_cleaned: dict = {}
        for k, v in filters.items():
            if v != '':
                filters_cleaned[k] = v
        try:
            results = await self.client.list(
                #model_endpoint=self.remote_config.model_endpoint,
                cursor=cursor, limit=limit, filters=filters_cleaned, direction=direction,
            )
            # Результат уже список объектов типа self.read_schema
            return cast(List[ModelType], results)
        except ServiceCommunicationError as e:
            logger.warning(f"Remote DAM LIST: ServiceCommunicationError. Status: {e.status_code}. Error: {e}", exc_info=True)
            raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e
        except Exception as e:
            logger.exception("Remote DAM LIST: Unexpected error.")
            raise HTTPException(status_code=500, detail=f"Internal error during remote list: {e}") from e

    async def create(self, data: Union[CreateSchemaType, Dict[str, Any]]) -> ModelType:
        logger.debug(f"Remote DAM CREATE: Creating new '{self.model.__name__}' at endpoint '{self.remote_config.model_endpoint}'.")
        create_schema_cls = self.create_schema
        validated_data: CreateSchemaType # Тип для данных после валидации

        if isinstance(data, dict):
            if create_schema_cls is None:
                logger.error(f"CreateSchema not defined for remote model {self.model.__name__}, cannot validate dict for create.")
                raise ConfigurationError(f"CreateSchema not defined for remote model {self.model.__name__}, cannot validate dict.")
            try:
                validated_data = create_schema_cls.model_validate(data)
            except ValidationError as ve:
                logger.warning(f"Remote DAM CREATE: Validation error for input data. Errors: {ve.errors()}", exc_info=False)
                raise HTTPException(status_code=422, detail=ve.errors()) from ve
        elif create_schema_cls and isinstance(data, create_schema_cls):
            validated_data = data
        else:
            expected_type_name = create_schema_cls.__name__ if create_schema_cls else "registered Create Schema"
            logger.error(f"Unsupported data type for remote create {self.model.__name__}: {type(data)}. Expected {expected_type_name} or dict.")
            raise TypeError(f"Unsupported data type for remote create {self.model.__name__}: {type(data)}. Expected {expected_type_name} or dict.")

        try:
            result = await self.client.create(validated_data)
            return cast(ModelType, result)
        except ServiceCommunicationError as e:
            logger.warning(f"Remote DAM CREATE: ServiceCommunicationError. Status: {e.status_code}. Error: {e}", exc_info=True)
            raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e
        except Exception as e:
            logger.exception("Remote DAM CREATE: Unexpected error.")
            raise HTTPException(status_code=500, detail=f"Internal error during remote create: {e}") from e

    async def update(self, item_id: UUID, data: Union[UpdateSchemaType, Dict[str, Any]]) -> ModelType:
        logger.debug(f"Remote DAM UPDATE: Updating '{self.model.__name__}' with ID: {item_id} at endpoint '{self.remote_config.model_endpoint}'.")
        update_schema_cls = self.update_schema
        validated_data: UpdateSchemaType

        if isinstance(data, dict):
            if update_schema_cls is None:
                logger.error(f"UpdateSchema not defined for remote model {self.model.__name__}, cannot validate dict for update.")
                raise ConfigurationError(f"UpdateSchema not defined for remote model {self.model.__name__}, cannot validate dict.")
            try:
                validated_data = update_schema_cls.model_validate(data)
            except ValidationError as ve:
                logger.warning(f"Remote DAM UPDATE: Validation error for input data. Errors: {ve.errors()}", exc_info=False)
                raise HTTPException(status_code=422, detail=ve.errors()) from ve
        elif update_schema_cls and isinstance(data, update_schema_cls):
            validated_data = data
        else:
            expected_type_name = update_schema_cls.__name__ if update_schema_cls else "registered Update Schema"
            logger.error(f"Unsupported data type for remote update {self.model.__name__}: {type(data)}. Expected {expected_type_name} or dict.")
            raise TypeError(f"Unsupported data type for remote update {self.model.__name__}: {type(data)}. Expected {expected_type_name} or dict.")

        try:
            result = await self.client.update(item_id, validated_data)
            return cast(ModelType, result)
        except ServiceCommunicationError as e:
            logger.warning(f"Remote DAM UPDATE: ServiceCommunicationError for ID {item_id}. Status: {e.status_code}. Error: {e}", exc_info=True if e.status_code != 404 else False)
            if e.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Remote {self.model.__name__} with id {item_id} not found") from e
            raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e
        except Exception as e:
            logger.exception(f"Remote DAM UPDATE: Unexpected error for ID {item_id}.")
            raise HTTPException(status_code=500, detail=f"Internal error during remote update: {e}") from e

    async def delete(self, item_id: UUID) -> bool:
        logger.debug(f"Remote DAM DELETE: Deleting '{self.model.__name__}' with ID: {item_id} from endpoint '{self.remote_config.model_endpoint}'.")
        try:
            # RemoteServiceClient.delete возвращает bool
            success = await self.client.delete(item_id)
            if success:
                logger.info(f"Remote DAM DELETE: Item {item_id} deleted successfully (or was already not found).")
            else:
                # Этого не должно произойти, если клиент выбрасывает исключение при ошибке,
                # кроме 404, который он обрабатывает как успех.
                logger.warning(f"Remote DAM DELETE: Delete operation for {item_id} returned False unexpectedly.")
            return success
        except ServiceCommunicationError as e:
            # Клиент должен был обработать 404 как успех. Другие ошибки логируем.
            logger.error(f"Remote DAM DELETE: ServiceCommunicationError for ID {item_id}. Status: {e.status_code}. Error: {e}", exc_info=True)
            # В соответствии с интерфейсом BaseDataAccessManager, delete при ошибке выбрасывает HTTPException
            # или возвращает False, если ошибка не критична.
            # Здесь мы преобразуем ошибку связи в HTTPException.
            raise HTTPException(status_code=e.status_code or 500, detail=f"Failed to delete remote item: {e}") from e
        except Exception as e:
            logger.exception(f"Remote DAM DELETE: Unexpected error for ID {item_id}.")
            raise HTTPException(status_code=500, detail=f"Internal error during remote delete: {e}") from e