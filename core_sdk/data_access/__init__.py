# core_sdk/data_access/__init__.py
# Этот файл может экспортировать основные компоненты

from .base_manager import BaseDataAccessManager
from .remote_manager import RemoteDataAccessManager
from .manager_factory import (
    DataAccessManagerFactory,
    get_dam_factory,
)  # Переименовали зависимость
from .common import get_optional_token, get_global_http_client, app_http_client_lifespan

__all__ = [
    "BaseDataAccessManager",
    "RemoteDataAccessManager",
    "DataAccessManagerFactory",
    "get_dam_factory",
    "get_optional_token",
    "get_global_http_client",
    "app_http_client_lifespan",
]
