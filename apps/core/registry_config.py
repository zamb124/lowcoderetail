# apps/core/registry_config.py
import logging

# Импорты фильтров из моделей вашего сервиса
from .models.company import CompanyFilter
from .models.group import GroupFilter
from .models.user import UserFilter

# Импорты из SDK
from core_sdk.registry import ModelRegistry
#from core_sdk.data_access.local_manager import LocalDataAccessManager # Используем LocalDataAccessManager

# Относительные импорты моделей и схем из текущего приложения
from . import models # models.user.User, models.company.Company, models.group.Group
from . import schemas # schemas.user.UserRead и т.д.

# Относительные импорты кастомных менеджеров
from .data_access.user_manager import UserDataAccessManager
from .data_access.company_manager import CompanyDataAccessManager
from core_sdk.exceptions import ConfigurationError # Добавил импорт

logger = logging.getLogger("app.registry_config")
logger.debug("--- Executing apps.core.registry_config.py ---")


def configure_core_registry():
    """
    Настраивает ModelRegistry для локальных моделей сервиса Core.
    Регистрирует модели, их схемы, менеджеры доступа и классы фильтров.
    """
    try:
        if ModelRegistry.is_configured() and ModelRegistry.get_model_info("User", raise_error=False):
            logger.warning("Core models appear to be already registered in ModelRegistry. Skipping configuration.")
            return
    except ConfigurationError:
        pass

    logger.info("Configuring ModelRegistry for Core service...")
    try:
        ModelRegistry.register_local(
            model_cls=models.user.User,
            manager_cls=UserDataAccessManager,
            filter_cls=UserFilter,
            create_schema_cls=schemas.user.UserCreate,
            update_schema_cls=schemas.user.UserUpdate,
            read_schema_cls=schemas.user.UserRead,
            model_name="User",
        )
        logger.debug(f"Registered User model with manager {UserDataAccessManager.__name__}")

        ModelRegistry.register_local(
            model_cls=models.company.Company,
            manager_cls=CompanyDataAccessManager,
            filter_cls=CompanyFilter,
            create_schema_cls=schemas.company.CompanyCreate,
            update_schema_cls=schemas.company.CompanyUpdate,
            read_schema_cls=schemas.company.CompanyRead,
            model_name="Company",
        )
        logger.debug(f"Registered Company model with manager {CompanyDataAccessManager.__name__}")

        ModelRegistry.register_local(
            model_cls=models.group.Group,
            #manager_cls=LocalDataAccessManager,
            filter_cls=GroupFilter,
            create_schema_cls=schemas.group.GroupCreate,
            update_schema_cls=schemas.group.GroupUpdate,
            read_schema_cls=schemas.group.GroupRead,
            model_name="Group",
        )
        #logger.debug(f"Registered Group model with manager {LocalDataAccessManager.__name__}")

        logger.info("ModelRegistry configuration complete for Core service.")
    except Exception as e:
        logger.critical("Failed to configure ModelRegistry for Core service.", exc_info=True)
        raise RuntimeError("Core service ModelRegistry configuration failed.") from e

# --- ВЫЗЫВАЕМ КОНФИГУРАЦИЮ СРАЗУ ПРИ ИМПОРТЕ ЭТОГО МОДУЛЯ ---
# Проверяем, не были ли уже модели этого сервиса зарегистрированы
# (полезно для тестов или сценариев с горячей перезагрузкой)
user_info = ModelRegistry.get_model_info("User", raise_error=False)
company_info = ModelRegistry.get_model_info("Company", raise_error=False)

if not (user_info and company_info): # Если хотя бы одна из ключевых моделей не зарегистрирована
    configure_core_registry()
else:
    logger.info("Skipping configure_core_registry() call as core models seem already configured.")
# ----------------------------------------------------------

logger.debug("--- Finished executing apps.core.registry_config.py ---")