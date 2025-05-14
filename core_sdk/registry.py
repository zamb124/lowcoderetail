# core_sdk/registry.py
import logging
from typing import (
    Type,
    Dict,
    Union,
    Optional,
    Literal,
    TypeVar,
    Any,
)

from pydantic import BaseModel, HttpUrl, Field, ConfigDict
from sqlmodel import SQLModel
from pydantic import BaseModel as PydanticBaseModel # Оставляем для ясности, что model_cls может быть Pydantic

from core_sdk.exceptions import ConfigurationError
from fastapi_filter.contrib.sqlalchemy import (
    Filter as BaseSQLAlchemyFilter,
)

from typing import TYPE_CHECKING
# --- ИЗМЕНЕНИЕ ИМПОРТА ---
# LocalDataAccessManager импортируется только для аннотации типа и значения по умолчанию.
# Сам класс LocalDataAccessManager не должен создавать циклической зависимости от ModelRegistry на уровне модуля.
if TYPE_CHECKING:
    from core_sdk.data_access.local_manager import LocalDataAccessManager
    from core_sdk.data_access.base_manager import BaseDataAccessManager
# --------------------------

logger = logging.getLogger("core_sdk.registry")

ModelClassType = TypeVar("ModelClassType", bound=PydanticBaseModel) # model_cls может быть и SQLModel, и PydanticBaseModel
SchemaClassType = TypeVar("SchemaClassType", bound=PydanticBaseModel)


class RemoteConfig(BaseModel):
    service_url: HttpUrl = Field(...)
    model_endpoint: str = Field(...)
    model_config = ConfigDict(arbitrary_types_allowed=True)


class ModelInfo(PydanticBaseModel):
    model_cls: Type[ModelClassType]
    create_schema_cls: Optional[Type[SchemaClassType]] = None
    update_schema_cls: Optional[Type[SchemaClassType]] = None
    read_schema_cls: Optional[Type[PydanticBaseModel]] = None # Может быть любая Pydantic модель
    manager_cls: Type[Any] # Может быть BaseDataAccessManager или другой совместимый
    access_config: Union[RemoteConfig, Literal["local"]]
    filter_cls: Optional[Type[BaseSQLAlchemyFilter]] = None
    model_config = ConfigDict(arbitrary_types_allowed=True)


class ModelRegistry:
    _registry: Dict[str, ModelInfo] = {}
    _is_configured: bool = False

    @classmethod
    def register(
        cls,
        model_name: str,
        model_cls: Type[ModelClassType],
        access_config: Union[RemoteConfig, Literal["local"]],
        manager_cls: Type[Any], # manager_cls может быть BaseDataAccessManager или LocalDataAccessManager
        filter_cls: Optional[Type[BaseSQLAlchemyFilter]] = None,
        create_schema_cls: Optional[Type[SchemaClassType]] = None,
        update_schema_cls: Optional[Type[SchemaClassType]] = None,
        read_schema_cls: Optional[Type[PydanticBaseModel]] = None,
    ) -> None:
        model_name_lower = model_name.lower()
        if model_name_lower in cls._registry:
            logger.warning(
                f"Model name '{model_name}' (key: '{model_name_lower}') is already registered. Overwriting previous configuration."
            )

        if filter_cls and not issubclass(filter_cls, BaseSQLAlchemyFilter):
            raise TypeError(
                f"filter_cls for '{model_name}' must be a subclass of fastapi_filter.contrib.sqlalchemy.Filter, got {type(filter_cls)}"
            )

        # Убедимся, что read_schema_cls это PydanticBaseModel, если предоставлен
        if read_schema_cls and not issubclass(read_schema_cls, PydanticBaseModel):
            raise TypeError(f"read_schema_cls for '{model_name}' must be a Pydantic model, got {type(read_schema_cls)}")

        effective_read_schema_cls = read_schema_cls or model_cls

        # Проверка, что manager_cls наследуется от BaseDataAccessManager, если он предоставлен
        if manager_cls is not Any and not hasattr(manager_cls, 'list'): # Простая проверка наличия метода
             # Более строгая проверка: from core_sdk.data_access.base_manager import BaseDataAccessManager
             # if not issubclass(manager_cls, BaseDataAccessManager):
             pass # TODO: рассмотреть issubclass(manager_cls, BaseDataAccessManager), но это может создать цикл импорта, если BaseDataAccessManager импортируется здесь.

        info = ModelInfo(
            model_cls=model_cls,
            create_schema_cls=create_schema_cls,
            update_schema_cls=update_schema_cls,
            read_schema_cls=effective_read_schema_cls,
            manager_cls=manager_cls,
            access_config=access_config,
            filter_cls=filter_cls,
        )
        cls._registry[model_name_lower] = info
        cls._is_configured = True

        access_type_str = (
            f"remote ({access_config.service_url})"
            if isinstance(access_config, RemoteConfig)
            else access_config
        )
        manager_name = getattr(manager_cls, "__name__", str(manager_cls))
        filter_name = filter_cls.__name__ if filter_cls else "Default"

        logger.info(
            f"Registry: Registered '{model_name}' (Model: {model_cls.__name__}, "
            f"Manager: {manager_name}, Access: {access_type_str}, Filter: {filter_name})"
        )

    @classmethod
    def register_local(
        cls,
        model_cls: Type[ModelClassType], # Должен быть SQLModel
        manager_cls: Optional[Type[Any]] = None, # Тип LocalDataAccessManager или его наследник
        filter_cls: Optional[Type[BaseSQLAlchemyFilter]] = None,
        create_schema_cls: Optional[Type[SchemaClassType]] = None,
        update_schema_cls: Optional[Type[SchemaClassType]] = None,
        read_schema_cls: Optional[Type[PydanticBaseModel]] = None,
        model_name: Optional[str] = None,
    ) -> None:
        name_to_register = model_name or model_cls.__name__

        # Импортируем LocalDataAccessManager здесь, чтобы он был доступен для значения по умолчанию
        from core_sdk.data_access.local_manager import LocalDataAccessManager as ActualLocalDAM

        effective_manager_cls = manager_cls or ActualLocalDAM

        if effective_manager_cls is ActualLocalDAM:
             logger.debug(
                f"Registry: No specific manager provided for local model '{name_to_register}'. Defaulting to LocalDataAccessManager."
            )
        # Проверка, что model_cls является SQLModel для локальной регистрации
        if not issubclass(model_cls, SQLModel):
            raise TypeError(f"Local registration for '{name_to_register}' requires model_cls to be a SQLModel, got {type(model_cls)}")

        cls.register(
            model_name=name_to_register,
            model_cls=model_cls,
            access_config="local",
            manager_cls=effective_manager_cls,
            filter_cls=filter_cls,
            create_schema_cls=create_schema_cls,
            update_schema_cls=update_schema_cls,
            read_schema_cls=read_schema_cls,
        )

    @classmethod
    def register_remote(
        cls,
        model_cls: Type[PydanticBaseModel], # Для удаленных моделей, model_cls это обычно схема ответа (ReadSchema)
        config: RemoteConfig,
        create_schema_cls: Optional[Type[SchemaClassType]] = None,
        update_schema_cls: Optional[Type[SchemaClassType]] = None,
        read_schema_cls: Optional[Type[PydanticBaseModel]] = None, # Может быть тем же, что и model_cls
        filter_cls: Optional[Type[BaseSQLAlchemyFilter]] = None, # Фильтры для удаленных DAM могут быть специфичны
        model_name: Optional[str] = None,
    ) -> None:
        name_to_register = model_name or model_cls.__name__
        # Для удаленных менеджеров, manager_cls фактически определяется RemoteDataAccessManager,
        # поэтому здесь можно указать Any или специфичный RemoteDataAccessManager, если он есть.
        # Пока оставим Any, т.к. DataAccessManagerFactory создаст RemoteDataAccessManager.
        from core_sdk.data_access.remote_manager import RemoteDataAccessManager as ActualRemoteDAM
        cls.register(
            model_name=name_to_register,
            model_cls=model_cls, # Это ReadSchema для удаленной модели
            access_config=config,
            manager_cls=ActualRemoteDAM, # Явно указываем, какой менеджер будет использоваться
            filter_cls=filter_cls,
            create_schema_cls=create_schema_cls,
            update_schema_cls=update_schema_cls,
            read_schema_cls=read_schema_cls or model_cls, # Если read_schema не указана, используем model_cls
        )

    @classmethod
    def get_model_info(cls, model_name: str, raise_error: bool = True) -> Optional[ModelInfo]:
        if not cls._is_configured:
            if raise_error:
                raise ConfigurationError(
                    "ModelRegistry has not been configured. Ensure registration methods are called."
                )
            return None

        info = cls._registry.get(model_name.lower())
        if info is None and raise_error:
            raise ConfigurationError(
                f"Model name '{model_name}' not found in registry. Available models: {list(cls._registry.keys())}"
            )
        return info

    @classmethod
    def rebuild_models(cls, force: bool = True) -> None:
        if not cls._is_configured:
            logger.warning("Cannot rebuild models: ModelRegistry is not configured.")
            return
        logger.info("Rebuilding registered Pydantic models and schemas...")
        rebuilt_classes = set()
        for model_name_lower, model_info in cls._registry.items():
            logger.debug(f"Processing model '{model_name_lower}' for rebuild.")
            # Собираем все Pydantic-классы, связанные с этой регистрацией
            classes_to_rebuild = [
                model_info.model_cls,
                model_info.create_schema_cls,
                model_info.update_schema_cls,
                model_info.read_schema_cls,
                model_info.filter_cls,
            ]
            for pydantic_class in classes_to_rebuild:
                if (pydantic_class and isinstance(pydantic_class, type) and
                        issubclass(pydantic_class, BaseModel) and # Проверяем BaseModel из Pydantic
                        pydantic_class not in rebuilt_classes):
                    # Проверяем наличие метода model_rebuild
                    if hasattr(pydantic_class, 'model_rebuild') and callable(getattr(pydantic_class, 'model_rebuild')):
                        try:
                            logger.debug(f"  Rebuilding: {pydantic_class.__module__}.{pydantic_class.__name__}")
                            pydantic_class.model_rebuild(force=force) # type: ignore
                            rebuilt_classes.add(pydantic_class)
                        except Exception as e:
                            logger.error(f"  ERROR rebuilding {pydantic_class.__name__}: {e}", exc_info=True)
                    else:
                        logger.debug(f"  Skipping rebuild for {pydantic_class.__name__} (no model_rebuild method or not a Pydantic model).")
        logger.info(f"Model rebuild finished. Processed {len(rebuilt_classes)} unique Pydantic classes with model_rebuild.")

    @classmethod
    def clear(cls) -> None:
        logger.info("Clearing ModelRegistry.")
        cls._registry = {}
        cls._is_configured = False

    @classmethod
    def is_configured(cls) -> bool:
        return cls._is_configured