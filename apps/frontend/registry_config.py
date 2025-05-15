# apps/frontend/app/registry_config.py
import logging
from pydantic import HttpUrl

logger = logging.getLogger("frontend.registry_config.py") # Используем имя файла для логгера
from core_sdk.registry import ModelRegistry, RemoteConfig

# Импортируем схемы и модели, к которым нужен удаленный доступ
# Лучше импортировать их из SDK, если они там определены, или из сервисов напрямую
# Пример импорта из Core (предполагаем, что структура позволяет)
from apps.core import models as core_models  # Модели (для фильтров)
from apps.core import schemas as core_schemas  # Схемы (для model_cls, create_schema_cls, update_schema_cls)


# Импортируем настройки, чтобы получить URL сервисов
from .config import settings as frontend_settings

# logger = logging.getLogger("app.registry_config") # Дублирование, можно убрать


def _get_api_endpoint(base_url: HttpUrl, path: str) -> str:
    """Формирует полный URL к API эндпоинту."""
    base = str(base_url).rstrip("/")
    api_prefix = getattr(frontend_settings, "API_V1_STR", "/api/v1") # API_V1_STR должен быть для Core сервиса, а не фронтенда
                                                                    # Лучше, если CORE_SERVICE_URL уже содержит /api/v1 или есть отдельная настройка
                                                                    # Предположим, что API_V1_STR из настроек SDK - это префикс для *этого* сервиса,
                                                                    # а для удаленных сервисов URL должен быть полным или иметь свой префикс.
                                                                    # Для простоты, если CORE_SERVICE_URL это http://core:8000, то path должен быть "api/v1/users"
                                                                    # Либо, если CORE_SERVICE_URL это http://core:8000/api/v1, то path "users"
                                                                    # Текущая реализация _get_api_endpoint добавляет api_prefix из frontend_settings, что неверно для Core.
                                                                    # Исправим: model_endpoint должен быть относительным путем *внутри* API удаленного сервиса.
    # full_path = f"{api_prefix}/{path.lstrip('/')}" # Старая логика
    full_path = path.lstrip('/') # Новая логика: model_endpoint это путь от корня API сервиса
    logger.debug(f"Constructed remote endpoint: base='{base}', path='{full_path}'")
    return full_path


def configure_remote_registry():
    """Конфигурирует ModelRegistry для доступа к удаленным моделям."""
    if ModelRegistry.is_configured():
        # Проверим, не были ли уже зарегистрированы эти конкретные модели
        user_info = ModelRegistry.get_model_info("user", raise_error=False)
        company_info = ModelRegistry.get_model_info("company", raise_error=False)
        if user_info and company_info:
            logger.warning(
                "Core models appear to be already registered for remote access. Skipping remote configuration."
            )
            return

    logger.info("Configuring ModelRegistry for remote access from Frontend service...")
    core_base_url = frontend_settings.CORE_SERVICE_URL

    # User (Core)
    ModelRegistry.register_remote(
        # ИЗМЕНЕНИЕ: model_cls теперь это Pydantic схема для чтения
        model_cls=core_schemas.user.UserRead,
        config=RemoteConfig(
            service_url=core_base_url,
            # ИЗМЕНЕНИЕ: model_endpoint теперь должен быть относительным путем API Core сервиса
            model_endpoint="users" # Предполагаем, что CORE_SERVICE_URL уже включает /api/v1
                                   # или что RemoteServiceClient сам добавит префикс API
                                   # Если CORE_SERVICE_URL = http://core:8000, то здесь должно быть "api/v1/users"
                                   # Если CORE_SERVICE_URL = http://core:8000/api/v1, то здесь "users"
                                   # Для консистентности, пусть model_endpoint будет "users", а CORE_SERVICE_URL - базовым URL сервиса.
                                   # RemoteServiceClient добавит /api/v1 и /users
        ),
        # ИЗМЕНЕНИЕ: read_schema_cls УДАЛЕН из вызова
        create_schema_cls=core_schemas.user.UserCreate,
        update_schema_cls=core_schemas.user.UserUpdate,
        filter_cls=core_models.user.UserFilter, # Фильтр может остаться SQLModel-based, если RemoteDAM его поддерживает
        model_name="user",
    )

    # Company (Core)
    ModelRegistry.register_remote(
        model_cls=core_schemas.company.CompanyRead, # ИЗМЕНЕНИЕ
        config=RemoteConfig(
            service_url=core_base_url,
            model_endpoint="companies" # ИЗМЕНЕНИЕ
        ),
        # read_schema_cls УДАЛЕН
        create_schema_cls=core_schemas.company.CompanyCreate,
        update_schema_cls=core_schemas.company.CompanyUpdate,
        filter_cls=core_models.company.CompanyFilter,
        model_name="company",
    )

    # Group (Core)
    ModelRegistry.register_remote(
        model_cls=core_schemas.group.GroupRead, # ИЗМЕНЕНИЕ
        config=RemoteConfig(
            service_url=core_base_url,
            model_endpoint="groups" # ИЗМЕНЕНИЕ
        ),
        # read_schema_cls УДАЛЕН
        create_schema_cls=core_schemas.group.GroupCreate,
        update_schema_cls=core_schemas.group.GroupUpdate,
        filter_cls=core_models.group.GroupFilter,
        model_name="group", # ИЗМЕНЕНИЕ: model_name в нижнем регистре для консистентности
    )
    logger.info("ModelRegistry remote configuration complete for Frontend service.")


# Вызываем конфигурацию при импорте модуля
# (Оставляем вызов здесь, так как он должен происходить при старте frontend сервиса)
configure_remote_registry()