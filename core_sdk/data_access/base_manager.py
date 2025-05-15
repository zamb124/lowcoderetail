# core_sdk/data_access/base_manager.py
import logging
from abc import ABC, abstractmethod
from typing import (
    Type,
    Optional,
    Any,
    Mapping,
    Dict,
    TypeVar,
    Generic,
    Union,
    Literal,
)
from uuid import UUID
from pydantic import BaseModel as PydanticBaseModel
from sqlmodel import SQLModel

import httpx

from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter

logger = logging.getLogger("core_sdk.data_access.base_manager")

# Новые имена для дженериков
DM_SQLModelType = TypeVar("DM_SQLModelType", bound=SQLModel) # Для SQLModel объектов
DM_ReadSchemaType = TypeVar("DM_ReadSchemaType", bound=PydanticBaseModel) # Для Pydantic схем чтения
DM_CreateSchemaType = TypeVar("DM_CreateSchemaType", bound=PydanticBaseModel)
DM_UpdateSchemaType = TypeVar("DM_UpdateSchemaType", bound=PydanticBaseModel)

# BaseDataAccessManager теперь будет типизирован более явно
# Первый параметр - это основной тип данных, с которым работает менеджер:
# - SQLModel для LocalDataAccessManager
# - Pydantic ReadSchema для RemoteDataAccessManager
WorkingModelType = TypeVar("WorkingModelType", bound=Any)

class BaseDataAccessManager(Generic[WorkingModelType, DM_CreateSchemaType, DM_UpdateSchemaType, DM_ReadSchemaType], ABC):
    model_cls: Type[WorkingModelType] # Основной тип модели (SQLModel для Local, Pydantic ReadSchema для Remote)
    create_schema_cls: Optional[Type[DM_CreateSchemaType]]
    update_schema_cls: Optional[Type[DM_UpdateSchemaType]]
    read_schema_cls: Optional[Type[DM_ReadSchemaType]] # Pydantic схема для чтения, используется CRUDRouterFactory

    model_name: str
    _broker_instance: Optional[Any] = None
    _http_client: Optional[httpx.AsyncClient] = None

    def __init__(
        self,
        model_name: str,
        model_cls: Type[WorkingModelType],
        create_schema_cls: Optional[Type[DM_CreateSchemaType]] = None,
        update_schema_cls: Optional[Type[DM_UpdateSchemaType]] = None,
        read_schema_cls: Optional[Type[DM_ReadSchemaType]] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.model_name = model_name
        self.model_cls = model_cls
        self.create_schema_cls = create_schema_cls
        self.update_schema_cls = update_schema_cls
        self.read_schema_cls = read_schema_cls
        self._http_client = http_client
        read_schema_name = read_schema_cls.__name__ if read_schema_cls else getattr(model_cls, '__name__', 'N/A')
        logger.debug(f"BaseDataAccessManager '{self.__class__.__name__}' initialized for model '{model_name}'. Working model type: {model_cls.__name__}, Read schema for API: {read_schema_name}")

    @property
    def broker(self) -> Any:
        if self._broker_instance is None:
            from core_sdk.data_access.broker_proxy import BrokerTaskProxy
            logger.debug(f"Lazily initializing BrokerTaskProxy for {self.model_name} in {self.__class__.__name__}")
            self._broker_instance = BrokerTaskProxy(dam_instance=self, model_name=self.model_name) # type: ignore
        return self._broker_instance

    @abstractmethod
    async def list(
        self,
        *,
        cursor: Optional[int] = None,
        limit: int = 50,
        filters: Optional[Union[BaseSQLAlchemyFilter, Mapping[str, Any]]] = None,
        direction: Literal["asc", "desc"] = "asc",
    ) -> Dict[str, Any]:
        """
        Извлекает список элементов.
        Возвращает словарь с 'items': List[WorkingModelType] и пагинацией.
        """
        pass

    @abstractmethod
    async def get(self, item_id: UUID) -> Optional[WorkingModelType]:
        """Извлекает один элемент по ID, возвращая WorkingModelType."""
        pass

    @abstractmethod
    async def create(self, data: Union[DM_CreateSchemaType, Dict[str, Any]]) -> WorkingModelType:
        """Создает новый элемент, возвращая WorkingModelType."""
        pass

    @abstractmethod
    async def update(
        self, item_id: UUID, data: Union[DM_UpdateSchemaType, Dict[str, Any]]
    ) -> WorkingModelType:
        """Обновляет существующий элемент, возвращая WorkingModelType."""
        pass

    @abstractmethod
    async def delete(self, item_id: UUID) -> bool:
        """Удаляет элемент по ID."""
        pass