# core_sdk/data_access/__init__.py
from .base_manager import BaseDataAccessManager # Теперь это интерфейс
from .local_manager import LocalDataAccessManager
from .remote_manager import RemoteDataAccessManager
from .manager_factory import DataAccessManagerFactory, get_dam_factory
from .common import get_optional_token, get_global_http_client, app_http_client_lifespan
from .broker_proxy import BrokerTaskProxy

__all__ = [
    "BaseDataAccessManager", # Экспортируем интерфейс
    "LocalDataAccessManager",
    "RemoteDataAccessManager",
    "DataAccessManagerFactory",
    "get_dam_factory",
    "get_optional_token",
    "get_global_http_client",
    "app_http_client_lifespan",
    "BrokerTaskProxy",
]