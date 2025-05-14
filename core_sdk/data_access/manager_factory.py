# core_sdk/data_access/manager_factory.py
import logging
from typing import Type, Optional, Any, Dict, TYPE_CHECKING

from fastapi import Depends
import httpx
from sqlmodel import SQLModel
from starlette.requests import Request as StarletteRequest
# FastAPIRequest не используется напрямую, но оставлю для TYPE_CHECKING, если понадобится
from fastapi import Request as FastAPIRequest

# --- ИЗМЕНЕНИЕ ИМПОРТОВ ---
from core_sdk.data_access.base_manager import BaseDataAccessManager # Теперь это интерфейс
from core_sdk.data_access.local_manager import LocalDataAccessManager
from core_sdk.data_access.remote_manager import RemoteDataAccessManager
# --------------------------
from core_sdk.data_access.common import get_optional_token, get_global_http_client
from core_sdk.exceptions import ConfigurationError
from pydantic import BaseModel # Для type hinting схем

if TYPE_CHECKING:
    from core_sdk.registry import ModelRegistry, RemoteConfig, ModelInfo

logger = logging.getLogger("core_sdk.data_access.manager_factory")

class DataAccessManagerFactory:
    def __init__(
        self,
        http_client: Optional[httpx.AsyncClient] = None,
        auth_token: Optional[str] = None,
        registry: Optional[Any] = None, # Используем Any для аргумента, чтобы не импортировать ModelRegistry здесь
    ):
        from core_sdk.registry import ModelRegistry as ActualModelRegistry # Импорт внутри __init__
        self.registry: Type[ActualModelRegistry] = registry or ActualModelRegistry # Указываем тип здесь

        if not self.registry.is_configured():
            raise ConfigurationError("ModelRegistry has not been configured.")
        self.http_client = http_client
        self.auth_token = auth_token
        self._manager_cache: Dict[str, BaseDataAccessManager] = {}
        logger.debug(f"DataAccessManagerFactory initialized. HTTP client: {http_client is not None}, Factory auth_token: {auth_token is not None}")

    def get_manager(
        self, model_name: str, request: Optional[StarletteRequest] = None
    ) -> BaseDataAccessManager[Any, Any, Any]:
        normalized_model_name = model_name.lower()

        # Логика кэширования и обновления токена для RemoteManager
        if normalized_model_name in self._manager_cache:
            cached_manager = self._manager_cache[normalized_model_name]
            if isinstance(cached_manager, RemoteDataAccessManager) and request:
                # Попытка получить токен из запроса
                token_from_request_header = request.headers.get("Authorization")
                token_from_request_cookie = request.cookies.get("Authorization")
                token_from_request = token_from_request_header or token_from_request_cookie

                new_auth_token = token_from_request if token_from_request else self.auth_token

                # Обновляем токен, только если он действительно изменился
                if cached_manager.auth_token != new_auth_token:
                    logger.debug(f"Updating auth token for cached RemoteManager '{model_name}' from '{cached_manager.auth_token}' to '{new_auth_token}'")
                    cached_manager.auth_token = new_auth_token
                    if hasattr(cached_manager, "client") and cached_manager.client:
                        cached_manager.client.auth_token = new_auth_token
            return cached_manager

        model_info = self.registry.get_model_info(model_name) # Используем self.registry
        manager_instance: BaseDataAccessManager[Any, Any, Any]

        effective_read_schema_cls = model_info.read_schema_cls or model_info.model_cls

        if model_info.access_config == "local":
            ManagerClass = model_info.manager_cls
            if ManagerClass is None or ManagerClass is Any: # type: ignore
                ManagerClass = LocalDataAccessManager

            # --- РАСКОММЕНТИРОВАТЬ И, ВОЗМОЖНО, УТОЧНИТЬ ПРОВЕРКУ ---
            # Проверяем, что ManagerClass является подклассом BaseDataAccessManager
            # или LocalDataAccessManager (если ManagerClass это LocalDataAccessManager по умолчанию)
            if model_info.access_config == "local":
                ManagerClass = model_info.manager_cls
                if ManagerClass is None or ManagerClass is Any: # type: ignore
                    ManagerClass = LocalDataAccessManager # По умолчанию LocalDataAccessManager

                # --- УСИЛЕННАЯ ПРОВЕРКА ---
                if not issubclass(ManagerClass, LocalDataAccessManager):
                    # Если это не так, но это BaseDataAccessManager, это тоже странно для локального
                    if issubclass(ManagerClass, BaseDataAccessManager):
                        logger.warning(f"Registered local manager_cls for '{model_name}' ('{ManagerClass.__name__}') is BaseDataAccessManager, expected LocalDataAccessManager or subclass. This might lead to issues.")
                        # Можно здесь тоже выбросить ошибку, если это недопустимо
                        # raise TypeError(f"Registered local manager_cls for '{model_name}' ('{ManagerClass.__name__}') should be a subclass of LocalDataAccessManager, not BaseDataAccessManager directly.")
                    else:
                        raise TypeError(f"Registered local manager_cls for '{model_name}' ('{ManagerClass.__name__}') is not a subclass of LocalDataAccessManager.")
                # -------------------------

                logger.info(f"Instantiating LOCAL manager: {ManagerClass.__name__} for model '{model_name}'.")
                if not issubclass(model_info.model_cls, SQLModel):
                    raise ConfigurationError(f"Local manager for '{model_name}' requires model_cls to be SQLModel, got {model_info.model_cls}")

                manager_instance = ManagerClass(
                    model_name=model_name,
                    model_cls=model_info.model_cls,
                    read_schema_cls=effective_read_schema_cls,
                    create_schema_cls=model_info.create_schema_cls,
                    update_schema_cls=model_info.update_schema_cls,
                )
        elif isinstance(model_info.access_config, BaseModel): # Проверяем, что это Pydantic модель (RemoteConfig)
            if self.http_client is None:
                raise ConfigurationError(f"HTTP client required for remote manager '{model_name}'.")

            token_for_remote = self.auth_token
            if request:
                token_from_request_header = request.headers.get("Authorization")
                token_from_request_cookie = request.cookies.get("Authorization")
                token_from_request = token_from_request_header or token_from_request_cookie
                if token_from_request: token_for_remote = token_from_request

            logger.info(f"Instantiating REMOTE manager for model '{model_name}'. Token used: {'Provided' if token_for_remote else 'None'}")
            manager_instance = RemoteDataAccessManager(
                model_name=model_name,
                model_cls=effective_read_schema_cls,
                remote_config=model_info.access_config, # model_info.access_config уже будет RemoteConfig
                http_client=self.http_client,
                auth_token=token_for_remote,
                create_schema_cls=model_info.create_schema_cls,
                update_schema_cls=model_info.update_schema_cls,
            )
        else:
            raise ConfigurationError(f"Invalid access config type for '{model_name}': {type(model_info.access_config)}")

        self._manager_cache[normalized_model_name] = manager_instance
        return manager_instance

def get_dam_factory(
    http_client: Optional[httpx.AsyncClient] = Depends(get_global_http_client),
    auth_token: Optional[str] = Depends(get_optional_token),
) -> DataAccessManagerFactory:
    from core_sdk.registry import ModelRegistry as GlobalModelRegistry # Импорт здесь
    return DataAccessManagerFactory(http_client=http_client, auth_token=auth_token, registry=GlobalModelRegistry)