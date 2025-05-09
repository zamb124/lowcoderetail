# core_sdk/registry.py
import logging
from typing import Type, Dict, Union, Optional, Literal, TypeVar, Any # List не используется напрямую в этом файле

from pydantic import BaseModel, HttpUrl, Field, ConfigDict
from sqlmodel import SQLModel

from core_sdk.exceptions import ConfigurationError
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter # Переименовываем для ясности

# Используем TYPE_CHECKING для избежания циклического импорта с BaseDataAccessManager
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core_sdk.data_access.base_manager import BaseDataAccessManager
else:
    # В runtime BaseDataAccessManager может быть еще не импортирован или вызывать цикл.
    # Используем TypeVar как заглушку, если импорт не удался.
    # Фабрика DAM проверит фактический тип при создании менеджера.
    try:
        from core_sdk.data_access.base_manager import BaseDataAccessManager
    except ImportError:
        BaseDataAccessManager = TypeVar("BaseDataAccessManager") # type: ignore

logger = logging.getLogger(__name__) # Имя будет core_sdk.registry

# Типы для моделей и схем
ModelClassType = TypeVar("ModelClassType", bound=SQLModel) # Уточненное имя
SchemaClassType = TypeVar("SchemaClassType", bound=SQLModel) # Уточненное имя

class RemoteConfig(BaseModel):
    """
    Конфигурация для удаленного доступа к модели через другой сервис.
    """
    service_url: HttpUrl = Field(..., description="Базовый URL удаленного сервиса (например, 'http://users-service:8000').")
    model_endpoint: str = Field(..., description="Путь к API эндпоинту модели на удаленном сервисе (например, '/api/v1/users').")
    # client_class и другие специфичные для клиента параметры больше не нужны здесь,
    # так как используется стандартизированный RemoteDataAccessManager.

    # model_config для Pydantic v2, если нужно (например, arbitrary_types_allowed)
    # model_config = ConfigDict(arbitrary_types_allowed=True)

class ModelInfo(BaseModel):
    """
    Хранит информацию о зарегистрированной модели, включая ее классы,
    конфигурацию доступа и класс фильтра.
    """
    model_cls: Type[SQLModel] = Field(description="Класс модели SQLModel.")
    create_schema_cls: Optional[Type[SchemaClassType]] = Field(default=None, description="Pydantic схема для создания экземпляров модели.")
    update_schema_cls: Optional[Type[SchemaClassType]] = Field(default=None, description="Pydantic схема для обновления экземпляров модели.")
    read_schema_cls: Optional[Type[SQLModel]] = Field(default=None, description="SQLModel/Pydantic схема для чтения/сериализации экземпляров модели (если отличается от model_cls).")
    manager_cls: Type[Any] = Field(description="Класс менеджера данных (DataAccessManager) для этой модели.") # Тип Any, т.к. может быть BaseDataAccessManager или его наследник
    access_config: Union[RemoteConfig, Literal["local"]] = Field(description="Конфигурация доступа: 'local' или объект RemoteConfig.")
    filter_cls: Optional[Type[BaseSQLAlchemyFilter]] = Field(default=None, description="Класс фильтра FastAPI-Filter для этой модели.")

    model_config = ConfigDict(arbitrary_types_allowed=True) # Разрешаем произвольные типы (например, Type[SQLModel])

class ModelRegistry:
    """
    Центральный реестр для регистрации моделей данных и связанной с ними информации.
    Позволяет унифицировать доступ к данным, независимо от того, локальные они или удаленные.
    """
    _registry: Dict[str, ModelInfo] = {}
    _is_configured: bool = False

    @classmethod
    def register(
            cls,
            model_name: str,
            model_cls: Type[ModelClassType],
            access_config: Union[RemoteConfig, Literal["local"]],
            manager_cls: Type[Any], # Принимаем Any, проверка на BaseDataAccessManager будет в фабрике
            filter_cls: Optional[Type[BaseSQLAlchemyFilter]] = None,
            create_schema_cls: Optional[Type[SchemaClassType]] = None,
            update_schema_cls: Optional[Type[SchemaClassType]] = None,
            read_schema_cls: Optional[Type[ModelClassType]] = None,
    ) -> None:
        """
        Регистрирует модель и связанную с ней информацию в реестре.

        :param model_name: Уникальное имя для регистрации модели (например, "User", "Product").
        :param model_cls: Класс SQLModel, представляющий таблицу/модель данных.
        :param access_config: Конфигурация доступа ('local' или экземпляр RemoteConfig).
        :param manager_cls: Класс DataAccessManager, который будет использоваться для этой модели. Если access_config='local' и manager_cls=None, будет использован BaseDataAccessManager.
        :param filter_cls: Опциональный класс фильтра FastAPI-Filter для этой модели.
        :param create_schema_cls: Опциональная Pydantic схема для операций создания.
        :param update_schema_cls: Опциональная Pydantic схема для операций обновления.
        :param read_schema_cls: Опциональная SQLModel/Pydantic схема для операций чтения (если отличается от model_cls).
        :raises TypeError: Если предоставленный `filter_cls` не является подклассом `fastapi_filter.contrib.sqlalchemy.Filter`.
        """
        if model_name in cls._registry:
            logger.warning(f"Model name '{model_name}' is already registered. Overwriting previous configuration.")

        if filter_cls and not issubclass(filter_cls, BaseSQLAlchemyFilter):
            logger.error(f"filter_cls for '{model_name}' must be a subclass of BaseSQLAlchemyFilter, but got {type(filter_cls)}.")
            raise TypeError(f"filter_cls for '{model_name}' must be a subclass of fastapi_filter.contrib.sqlalchemy.Filter, got {type(filter_cls)}")

        # Если read_schema_cls не предоставлен, по умолчанию используется model_cls.
        effective_read_schema_cls = read_schema_cls or model_cls

        info = ModelInfo(
            model_cls=model_cls,
            create_schema_cls=create_schema_cls,
            update_schema_cls=update_schema_cls,
            read_schema_cls=effective_read_schema_cls,
            manager_cls=manager_cls,
            access_config=access_config,
            filter_cls=filter_cls
        )
        cls._registry[model_name] = info
        cls._is_configured = True # Помечаем, что реестр был сконфигурирован хотя бы раз

        access_type_str = f"remote ({access_config.service_url})" if isinstance(access_config, RemoteConfig) else access_config
        manager_name = getattr(manager_cls, '__name__', str(manager_cls)) # Безопасное получение имени
        filter_name = filter_cls.__name__ if filter_cls else "Default"

        logger.info(
            f"Registry: Registered '{model_name}' (Model: {model_cls.__name__}, "
            f"Manager: {manager_name}, Access: {access_type_str}, Filter: {filter_name})"
        )

    @classmethod
    def register_local(
            cls,
            model_cls: Type[ModelClassType],
            manager_cls: Optional[Type[Any]] = None, # Может быть None, тогда фабрика использует BaseDataAccessManager
            filter_cls: Optional[Type[BaseSQLAlchemyFilter]] = None,
            create_schema_cls: Optional[Type[SchemaClassType]] = None,
            update_schema_cls: Optional[Type[SchemaClassType]] = None,
            read_schema_cls: Optional[Type[ModelClassType]] = None,
            model_name: Optional[str] = None
    ) -> None:
        """
        Упрощенный метод для регистрации локальной модели.

        :param model_cls: Класс SQLModel.
        :param manager_cls: Опциональный кастомный DataAccessManager. Если None, будет использован BaseDataAccessManager.
        :param filter_cls: Опциональный класс фильтра.
        :param create_schema_cls: Схема для создания.
        :param update_schema_cls: Схема для обновления.
        :param read_schema_cls: Схема для чтения.
        :param model_name: Имя для регистрации (по умолчанию имя класса модели).
        """
        name_to_register = model_name or model_cls.__name__

        # Если manager_cls не предоставлен, он останется None.
        # DataAccessManagerFactory подставит BaseDataAccessManager по умолчанию.
        effective_manager_cls = manager_cls
        if effective_manager_cls is None:
            logger.debug(f"Registry: No specific manager provided for local model '{name_to_register}'. Factory will use BaseDataAccessManager.")
            # Явно передаем BaseDataAccessManager, чтобы ModelInfo его содержал,
            # даже если фабрика могла бы сделать это сама. Это делает ModelInfo более полным.
            # Импорт BaseDataAccessManager здесь безопасен, т.к. он уже должен быть доступен.
            try:
                from core_sdk.data_access.base_manager import BaseDataAccessManager as DefaultManager
                effective_manager_cls = DefaultManager
            except ImportError:
                logger.error("Failed to import BaseDataAccessManager for default local registration. This is a critical SDK setup issue.")
                # Это критическая ошибка, если SDK не может найти свой базовый менеджер.
                raise ConfigurationError("BaseDataAccessManager could not be imported for default local model registration.")


        cls.register(
            model_name=name_to_register,
            model_cls=model_cls,
            access_config="local",
            manager_cls=effective_manager_cls, # Передаем None или указанный класс
            filter_cls=filter_cls,
            create_schema_cls=create_schema_cls,
            update_schema_cls=update_schema_cls,
            read_schema_cls=read_schema_cls
        )

    @classmethod
    def register_remote(
            cls,
            model_cls: Type[ModelClassType], # Класс-представление удаленной модели (например, UserRead)
            config: RemoteConfig,
            create_schema_cls: Optional[Type[SchemaClassType]] = None,
            update_schema_cls: Optional[Type[SchemaClassType]] = None,
            read_schema_cls: Optional[Type[ModelClassType]] = None, # Схема для парсинга ответа
            filter_cls: Optional[Type[ModelClassType]] = None,
            model_name: Optional[str] = None
    ) -> None:
        """
        Упрощенный метод для регистрации удаленной модели.

        :param model_cls: Класс SQLModel/Pydantic, представляющий структуру удаленной модели.
        :param config: Экземпляр RemoteConfig с деталями подключения.
        :param create_schema_cls: Схема для создания удаленного объекта.
        :param update_schema_cls: Схема для обновления удаленного объекта.
        :param read_schema_cls: Схема для парсинга ответа от удаленного сервиса (если отличается от model_cls).
        :param model_name: Имя для регистрации (по умолчанию имя класса model_cls).
        """
        name_to_register = model_name or model_cls.__name__
        # Для удаленных моделей manager_cls всегда будет RemoteDataAccessManager,
        # который создается фабрикой. Здесь мы можем передать заглушку Any
        # или импортировать RemoteDataAccessManager, если хотим быть точнее в ModelInfo.
        # Передача Any проще и избегает потенциальных импортов.
        cls.register(
            model_name=name_to_register,
            model_cls=model_cls,
            access_config=config,
            manager_cls=Any, # Фабрика создаст RemoteDataAccessManager на основе access_config
            filter_cls=filter_cls, # Фильтры обычно не применяются к удаленным менеджерам напрямую через FastAPI-Filter
            create_schema_cls=create_schema_cls,
            update_schema_cls=update_schema_cls,
            read_schema_cls=read_schema_cls or model_cls # Если не указана, парсим в model_cls
        )

    @classmethod
    def get_model_info(cls, model_name: str) -> ModelInfo:
        """
        Возвращает информацию о зарегистрированной модели по ее имени.

        :param model_name: Имя модели.
        :raises ConfigurationError: Если реестр не сконфигурирован или модель не найдена.
        :return: Экземпляр ModelInfo.
        """
        if not cls._is_configured:
            logger.error(f"Attempted to get model info for '{model_name}', but ModelRegistry is not configured.")
            raise ConfigurationError("ModelRegistry has not been configured. Ensure registration methods are called.")

        info = cls._registry.get(model_name.lower())
        if info is None:
            logger.error(f"Model name '{model_name}' not found in ModelRegistry.")
            raise ConfigurationError(f"Model name '{model_name}' not found in registry. Available models: {list(cls._registry.keys())}")
        return info

    @classmethod
    def rebuild_models(cls, force: bool = True) -> None:
        """
        Вызывает `model_rebuild()` для всех зарегистрированных классов моделей и схем,
        которые являются наследниками Pydantic `BaseModel`.
        Это может быть необходимо при использовании ForwardRefs или для обновления
        динамически созданных моделей.

        :param force: Параметр `force` для `model_rebuild()`.
        """
        if not cls._is_configured:
            logger.warning("Cannot rebuild models: ModelRegistry is not configured.")
            return

        logger.info("Rebuilding registered Pydantic models and schemas...")
        rebuilt_classes = set()
        for model_name, model_info in cls._registry.items():
            logger.debug(f"Processing model '{model_name}' for rebuild.")
            classes_to_rebuild = [
                model_info.model_cls,
                model_info.create_schema_cls,
                model_info.update_schema_cls,
                model_info.read_schema_cls,
                # Также стоит пересобирать filter_cls, если он является Pydantic моделью
                model_info.filter_cls
            ]
            for pydantic_class in classes_to_rebuild:
                if (pydantic_class and # Проверка на None
                        isinstance(pydantic_class, type) and
                        issubclass(pydantic_class, BaseModel) and # Убедимся, что это Pydantic модель
                        pydantic_class not in rebuilt_classes):
                    try:
                        logger.debug(f"  Rebuilding: {pydantic_class.__module__}.{pydantic_class.__name__}")
                        pydantic_class.model_rebuild(force=force)
                        rebuilt_classes.add(pydantic_class)
                    except Exception as e:
                        logger.error(f"  ERROR rebuilding {pydantic_class.__name__}: {e}", exc_info=True)
        logger.info(f"Model rebuild finished. Processed {len(rebuilt_classes)} unique Pydantic classes.")

    @classmethod
    def clear(cls) -> None:
        """
        Очищает реестр. Полезно для тестов или перезагрузки конфигурации.
        """
        logger.info("Clearing ModelRegistry.")
        cls._registry = {}
        cls._is_configured = False

    @classmethod
    def is_configured(cls) -> bool:
        """
        Проверяет, была ли выполнена хотя бы одна регистрация модели.
        :return: True, если реестр сконфигурирован, иначе False.
        """
        return cls._is_configured