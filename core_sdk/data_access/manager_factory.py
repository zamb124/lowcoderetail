# core_sdk/data_access/manager_factory.py
import logging
from typing import Type, Optional, Any, Dict

from fastapi import Depends # Depends используется для get_dam_factory
import httpx # httpx.AsyncClient используется для type hinting
from starlette.requests import Request
from fastapi import Request as FastAPIRequest
from core_sdk.registry import ModelRegistry, RemoteConfig, ModelInfo
from core_sdk.data_access.base_manager import BaseDataAccessManager
from core_sdk.data_access.remote_manager import RemoteDataAccessManager
from core_sdk.data_access.common import get_optional_token, get_global_http_client
from core_sdk.exceptions import ConfigurationError

logger = logging.getLogger(__name__) # Имя будет core_sdk.data_access.manager_factory

class DataAccessManagerFactory:
    def __init__(
            self,
            http_client: Optional[httpx.AsyncClient] = None, # httpx импортируется в тестах
            auth_token: Optional[str] = None,
            registry: Type[ModelRegistry] = ModelRegistry
    ):
        if not registry.is_configured():
            raise ConfigurationError("ModelRegistry has not been configured.")
        self.http_client = http_client
        self.auth_token = auth_token # Токен по умолчанию для фабрики
        self.registry = registry
        self._manager_cache: Dict[str, Any] = {} # Ключ будет model_name.lower()
        logger.debug(f"DataAccessManagerFactory initialized. HTTP client: {http_client is not None}, Factory auth_token: {auth_token is not None}")

    def get_manager(self, model_name: str, request: Optional[FastAPIRequest] = None) -> Any:
        # Используем имя в нижнем регистре для ключа кэша и для запроса в ModelRegistry
        normalized_model_name = model_name.lower()

        if normalized_model_name in self._manager_cache:
            # ВАЖНО: Если кэшируем RemoteManager, нужно учитывать, что токен мог измениться.
            # Текущий простой кэш этого не делает. Для RemoteManager с request-specific токеном
            # кэширование может быть нежелательно или ключ кэша должен включать токен.
            # Пока оставляем простой кэш.
            cached_manager = self._manager_cache[normalized_model_name]
            logger.debug(f"Returning cached DAM instance for model '{normalized_model_name}'. Type: {type(cached_manager)}")
            # Если это RemoteManager и передан request, возможно, нужно обновить его токен
            if isinstance(cached_manager, RemoteDataAccessManager) and request:
                token_from_request = request.headers.get("Authorization") or request.cookies.get("Authorization")
                if token_from_request: # Если в request есть токен
                    cached_manager.auth_token = token_from_request
                    if hasattr(cached_manager, 'client') and cached_manager.client: # Обновляем токен и в клиенте
                        cached_manager.client.auth_token = token_from_request
                elif self.auth_token: # Если в request нет, но есть в фабрике
                    cached_manager.auth_token = self.auth_token
                    if hasattr(cached_manager, 'client') and cached_manager.client:
                        cached_manager.client.auth_token = self.auth_token
                else: # Токена нет нигде
                    cached_manager.auth_token = None
                    if hasattr(cached_manager, 'client') and cached_manager.client:
                        cached_manager.client.auth_token = None

            return cached_manager

        logger.debug(f"Attempting to create new DAM instance for normalized_model_name '{normalized_model_name}' (original: '{model_name}').")
        try:
            # ModelRegistry.get_model_info уже использует model_name.lower()
            model_info = self.registry.get_model_info(model_name) # Передаем оригинальное имя, т.к. get_model_info его нормализует
        except ConfigurationError:
            logger.error(f"Failed to get ModelInfo for '{model_name}' (normalized: '{normalized_model_name}') from registry.")
            raise # Перебрасываем ошибку конфигурации (сообщение будет с оригинальным model_name)

        manager_instance: Any = None
        access_config = model_info.access_config

        # model_name, передаваемый в конструктор менеджера, должен быть тем, под которым он зарегистрирован (normalized)
        # или тем, по которому его запросили (original), для консистентности.
        # BaseDataAccessManager сохраняет его как self.model_name.
        # Давайте передавать оригинальное имя model_name, чтобы manager.model_name был предсказуем.
        manager_init_model_name = model_name

        if access_config == "local":
            manager_cls = model_info.manager_cls
            if manager_cls is None or manager_cls is Any: # Any может прийти от register_remote
                manager_cls = BaseDataAccessManager
            if not issubclass(manager_cls, BaseDataAccessManager):
                raise TypeError(f"Registered manager_cls for '{manager_init_model_name}' is not a subclass of BaseDataAccessManager, got {manager_cls}")

            logger.info(f"Instantiating LOCAL manager: {manager_cls.__name__} for model '{manager_init_model_name}'.")
            manager_instance = manager_cls(model_name=manager_init_model_name, http_client=self.http_client)

            if not getattr(manager_instance, 'model', None): manager_instance.model = model_info.model_cls
            if not getattr(manager_instance, 'create_schema', None): manager_instance.create_schema = model_info.create_schema_cls
            if not getattr(manager_instance, 'update_schema', None): manager_instance.update_schema = model_info.update_schema_cls

        elif isinstance(access_config, RemoteConfig):
            if self.http_client is None:
                # Используем manager_init_model_name (оригинальное имя) в сообщении об ошибке для пользователя
                raise ConfigurationError(f"HTTP client required for remote manager '{manager_init_model_name}'.")

            token_for_remote = None
            if request:
                token_from_request = request.headers.get("Authorization") or request.cookies.get("Authorization")
                if token_from_request:
                    token_for_remote = token_from_request

            if token_for_remote is None: # Если из request не получили, берем из фабрики
                token_for_remote = self.auth_token

            logger.info(f"Instantiating REMOTE manager for model '{manager_init_model_name}'. Token used: {'Provided' if token_for_remote else 'None'}")
            manager_instance = RemoteDataAccessManager(
                remote_config=access_config, http_client=self.http_client, auth_token=token_for_remote,
                model_cls=model_info.model_cls, create_schema_cls=model_info.create_schema_cls,
                update_schema_cls=model_info.update_schema_cls, read_schema_cls=model_info.read_schema_cls,
            )
        else:
            raise ConfigurationError(f"Invalid access config type for '{manager_init_model_name}': {type(access_config)}")

        self._manager_cache[normalized_model_name] = manager_instance
        logger.debug(f"Successfully created and cached DAM instance for model '{normalized_model_name}' (original: '{model_name}').")
        return manager_instance

def get_dam_factory(
        http_client: Optional[httpx.AsyncClient] = Depends(get_global_http_client),
        auth_token: Optional[str] = Depends(get_optional_token)
) -> DataAccessManagerFactory:
    """
    FastAPI dependency that provides an instance of DataAccessManagerFactory.
    The factory is configured with the global HTTP client and an optional auth token
    extracted from the request.
    """
    logger.debug("FastAPI dependency 'get_dam_factory' called.")
    return DataAccessManagerFactory(
        http_client=http_client,
        auth_token=auth_token,
        registry=ModelRegistry # Используем глобальный ModelRegistry
    )