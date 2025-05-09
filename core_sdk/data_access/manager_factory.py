# core_sdk/data_access/manager_factory.py
import logging
from typing import Type, Optional, Any, Dict

from fastapi import Depends # Depends используется для get_dam_factory
import httpx # httpx.AsyncClient используется для type hinting
from starlette.requests import Request

from core_sdk.registry import ModelRegistry, RemoteConfig, ModelInfo
from core_sdk.data_access.base_manager import BaseDataAccessManager
from core_sdk.data_access.remote_manager import RemoteDataAccessManager
from core_sdk.data_access.common import get_optional_token, get_global_http_client
from core_sdk.exceptions import ConfigurationError

logger = logging.getLogger(__name__) # Имя будет core_sdk.data_access.manager_factory

class DataAccessManagerFactory:
    """
    Фабрика для создания и предоставления экземпляров DataAccessManager (DAM).
    Кэширует созданные менеджеры для повторного использования в рамках одного запроса (или жизни фабрики).
    """
    def __init__(
            self,
            http_client: Optional[httpx.AsyncClient] = None,
            auth_token: Optional[str] = None,
            registry: Type[ModelRegistry] = ModelRegistry
    ):
        if not registry.is_configured():
            logger.error("ModelRegistry has not been configured. DAM Factory cannot operate.")
            raise ConfigurationError("ModelRegistry has not been configured.")

        self.http_client = http_client
        self.auth_token = auth_token
        self.registry = registry
        self._manager_cache: Dict[str, BaseDataAccessManager | RemoteDataAccessManager] = {}
        logger.debug(f"DataAccessManagerFactory initialized. HTTP client provided: {http_client is not None}, Auth token provided: {auth_token is not None}")

    def get_manager(self, model_name: str, request: Request=None) -> Any: # Возвращаемый тип Any, т.к. это может быть Base или Remote DAM
        """
        Возвращает экземпляр DataAccessManager для указанной модели.
        Если менеджер для этой модели уже был создан этой фабрикой, возвращается
        кэшированный экземпляр.

        :param model_name: Имя модели, для которой нужен менеджер.
        :raises ConfigurationError: Если модель не найдена в реестре или есть проблемы с конфигурацией.
        :raises TypeError: Если зарегистрированный класс менеджера некорректен.
        :return: Экземпляр BaseDataAccessManager или RemoteDataAccessManager.
        """
        if model_name in self._manager_cache:
            logger.debug(f"Returning cached DAM instance for model '{model_name}'.")
            return self._manager_cache[model_name]

        logger.debug(f"Attempting to create new DAM instance for model '{model_name}'.")
        try:
            model_info = self.registry.get_model_info(model_name)
        except ConfigurationError as e:
            logger.error(f"Failed to get ModelInfo for '{model_name}' from registry.", exc_info=True)
            raise  # Перебрасываем ошибку конфигурации

        manager_instance: Any = None # Используем Any для гибкости
        access_config = model_info.access_config

        if access_config == "local":
            manager_cls = model_info.manager_cls
            if manager_cls is None:
                logger.debug(f"No specific manager_cls registered for local model '{model_name}', defaulting to BaseDataAccessManager.")
                manager_cls = BaseDataAccessManager

            if not issubclass(manager_cls, BaseDataAccessManager):
                logger.error(f"Registered manager_cls '{manager_cls.__name__}' for local model '{model_name}' is not a subclass of BaseDataAccessManager.")
                raise TypeError(f"Registered manager_cls for '{model_name}' is not a subclass of BaseDataAccessManager, got {manager_cls}")

            logger.info(f"Instantiating LOCAL manager: {manager_cls.__name__} for model '{model_name}'.")
            try:
                manager_instance = manager_cls(
                    model_name=model_name,
                    http_client=self.http_client # Передаем, может быть полезно для кастомных локальных DAM
                )
            except Exception as e:
                logger.exception(f"Failed to instantiate local manager {manager_cls.__name__} for '{model_name}'.")
                raise ConfigurationError(f"Error instantiating local manager for '{model_name}'") from e

            # Устанавливаем атрибуты модели и схем, если они не были установлены в конструкторе менеджера
            # Это позволяет кастомным менеджерам определять их самостоятельно или полагаться на фабрику.
            if not getattr(manager_instance, 'model', None): manager_instance.model = model_info.model_cls
            if not getattr(manager_instance, 'create_schema', None): manager_instance.create_schema = model_info.create_schema_cls
            if not getattr(manager_instance, 'update_schema', None): manager_instance.update_schema = model_info.update_schema_cls
            # model_name уже передан в конструктор

        elif isinstance(access_config, RemoteConfig):
            if self.http_client is None:
                logger.error(f"HTTP client is required for remote manager '{model_name}', but none was provided to the factory.")
                raise ConfigurationError(f"HTTP client required for remote manager '{model_name}'.")

            logger.info(f"Instantiating REMOTE manager for model '{model_name}'.")
            token = request.headers.get("Authorization") or request.cookies.get("Authorization") if request else self.auth_token
            try:
                manager_instance = RemoteDataAccessManager(
                    remote_config=access_config,
                    http_client=self.http_client,
                    auth_token=token,
                    model_cls=model_info.model_cls,
                    create_schema_cls=model_info.create_schema_cls,
                    update_schema_cls=model_info.update_schema_cls,
                    read_schema_cls=model_info.read_schema_cls,
                )
            except Exception as e:
                logger.exception(f"Failed to instantiate remote manager for '{model_name}'.")
                raise ConfigurationError(f"Error instantiating remote manager for '{model_name}'") from e
        else:
            logger.error(f"Invalid access_config type for '{model_name}': {type(access_config)}. Expected 'local' or RemoteConfig instance.")
            raise ConfigurationError(f"Invalid access config type for '{model_name}': {type(access_config)}")

        self._manager_cache[model_name] = manager_instance
        logger.debug(f"Successfully created and cached DAM instance for model '{model_name}'.")
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