# core/app/registry_config.py
import logging

# Импорты фильтров из моделей
from .models.company import CompanyFilter
from .models.group import GroupFilter
from .models.user import UserFilter

# Импорты из SDK
from core_sdk.registry import ModelRegistry # RemoteConfig не используется здесь
from core_sdk.data_access import BaseDataAccessManager

# Относительные импорты моделей и схем из текущего приложения
from . import models
from . import schemas

# Относительные импорты кастомных менеджеров
from .data_access.user_manager import UserDataAccessManager
from .data_access.company_manager import CompanyDataAccessManager

logger = logging.getLogger("app.registry_config") # Логгер для этого модуля

# Лог для отладки порядка импорта и выполнения
logger.debug("--- Executing registry_config.py ---")

def configure_core_registry():
    """
    Настраивает ModelRegistry для локальных моделей сервиса Core.
    Регистрирует модели, их схемы, менеджеры доступа и классы фильтров.
    """
    if ModelRegistry.is_configured():
         logger.warning("ModelRegistry already configured. Skipping configuration.")
         return

    logger.info("Configuring ModelRegistry for Core service...")
    try:
        # Регистрация User
        ModelRegistry.register_local(
            model_cls=models.user.User,
            manager_cls=UserDataAccessManager, # Кастомный менеджер
            filter_cls=UserFilter,
            create_schema_cls=schemas.user.UserCreate,
            update_schema_cls=schemas.user.UserUpdate,
            read_schema_cls=schemas.user.UserRead, # Явно указываем схему чтения
            model_name="User" # Явное имя для регистрации
        )
        # Регистрация Company
        ModelRegistry.register_local(
            model_cls=models.company.Company,
            manager_cls=CompanyDataAccessManager, # Кастомный менеджер
            filter_cls=CompanyFilter,
            create_schema_cls=schemas.company.CompanyCreate,
            update_schema_cls=schemas.company.CompanyUpdate,
            read_schema_cls=schemas.company.CompanyRead,
            model_name="Company"
        )
        # Регистрация Group (использует базовый менеджер)
        ModelRegistry.register_local(
            model_cls=models.group.Group,
            manager_cls=BaseDataAccessManager, # Используем базовый менеджер из SDK
            filter_cls=GroupFilter,
            create_schema_cls=schemas.group.GroupCreate,
            update_schema_cls=schemas.group.GroupUpdate,
            read_schema_cls=schemas.group.GroupRead,
            model_name="Group"
        )
        logger.info("ModelRegistry configuration complete for Core service.")
    except Exception as e:
        logger.critical("Failed to configure ModelRegistry.", exc_info=True)
        # Ошибка конфигурации реестра может быть критичной
        raise RuntimeError("ModelRegistry configuration failed.") from e

# --- ВЫЗЫВАЕМ КОНФИГУРАЦИЮ СРАЗУ ПРИ ИМПОРТЕ ЭТОГО МОДУЛЯ ---
# Это гарантирует, что реестр будет настроен до того, как он понадобится
# (например, при инициализации CRUDRouterFactory или DAMFactory).
configure_core_registry()
# ----------------------------------------------------------

logger.debug("--- Finished executing registry_config.py ---")