# core_sdk/data_access/base_manager.py
import logging
from abc import ABC, abstractmethod
from typing import (
    Type,
    List,
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
from pydantic import BaseModel
from sqlmodel import SQLModel
import httpx # Для http_client в конструкторе

# Импорты для фильтров и брокера
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter
# BrokerTaskProxy будет импортирован внутри свойства, чтобы избежать цикла

logger = logging.getLogger("core_sdk.data_access.base_manager")

# Ковариантные и контравариантные типы для Generic
# ModelType_co используется там, где менеджер *возвращает* экземпляры модели (get, list, create, update)
ModelType_co = TypeVar("ModelType_co", bound=BaseModel, covariant=True)
# CreateSchemaType_contra и UpdateSchemaType_contra используются там, где менеджер *принимает* схемы (create, update)
CreateSchemaType_contra = TypeVar("CreateSchemaType_contra", bound=BaseModel, contravariant=True)
UpdateSchemaType_contra = TypeVar("UpdateSchemaType_contra", bound=BaseModel, contravariant=True)


class BaseDataAccessManager(Generic[ModelType_co, CreateSchemaType_contra, UpdateSchemaType_contra], ABC):
    """
    Абстрактный базовый класс (интерфейс) для менеджеров доступа к данным.
    Определяет общий контракт для CRUD операций и листинга.
    """
    model_cls: Type[ModelType_co] # Класс модели, которую возвращает менеджер (обычно ReadSchema или SQLModel)
    create_schema_cls: Optional[Type[CreateSchemaType_contra]]
    update_schema_cls: Optional[Type[UpdateSchemaType_contra]]
    # read_schema_cls не нужен здесь, т.к. ModelType_co уже представляет схему чтения/возврата
    model_name: str # Имя модели, как зарегистрировано в ModelRegistry
    _broker_instance: Optional[Any] = None # Тип BrokerTaskProxy будет позже
    _http_client: Optional[httpx.AsyncClient] = None # Общий атрибут

    def __init__(
        self,
        model_name: str,
        model_cls: Type[ModelType_co], # Это тип, который менеджер будет возвращать (например, UserRead)
        create_schema_cls: Optional[Type[CreateSchemaType_contra]] = None,
        update_schema_cls: Optional[Type[UpdateSchemaType_contra]] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.model_name = model_name
        self.model_cls = model_cls
        self.create_schema_cls = create_schema_cls
        self.update_schema_cls = update_schema_cls
        self._http_client = http_client
        logger.debug(f"BaseDataAccessManager '{self.__class__.__name__}' initialized for model '{model_name}'.")

    @property
    def broker(self) -> Any: # Тип BrokerTaskProxy
        if self._broker_instance is None:
            from core_sdk.data_access.broker_proxy import BrokerTaskProxy
            logger.debug(f"Lazily initializing BrokerTaskProxy for {self.model_name} in {self.__class__.__name__}")
            self._broker_instance = BrokerTaskProxy(
                dam_instance=self, # type: ignore
                model_name=self.model_name
            )
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
        Извлекает список элементов с пагинацией и фильтрацией.
        Возвращает словарь, совместимый со схемой PaginatedResponse,
        где 'items' содержит List[ModelType_co].
        """
        pass

    @abstractmethod
    async def get(self, item_id: UUID) -> Optional[ModelType_co]:
        """Извлекает один элемент по ID."""
        pass

    @abstractmethod
    async def create(self, data: Union[CreateSchemaType_contra, Dict[str, Any]]) -> ModelType_co:
        """Создает новый элемент."""
        pass

    @abstractmethod
    async def update(
        self, item_id: UUID, data: Union[UpdateSchemaType_contra, Dict[str, Any]]
    ) -> ModelType_co:
        """Обновляет существующий элемент."""
        pass

    @abstractmethod
    async def delete(self, item_id: UUID) -> bool:
        """Удаляет элемент по ID."""
        pass