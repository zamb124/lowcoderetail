# apps/frontend/app/registry_config.py
import logging
from pydantic import HttpUrl

logger = logging.getLogger("frontend.registry_config.py")
from core_sdk.registry import ModelRegistry, RemoteConfig

# Импортируем схемы и модели, к которым нужен удаленный доступ
# Лучше импортировать их из SDK, если они там определены, или из сервисов напрямую
# Пример импорта из Core (предполагаем, что структура позволяет)
from apps.core import models as core_models  # Модели
from apps.core import schemas as core_schemas  # Схемы


# Импортируем настройки, чтобы получить URL сервисов
from .config import settings as frontend_settings

logger = logging.getLogger("app.registry_config")


def _get_api_endpoint(base_url: HttpUrl, path: str) -> str:
    """Формирует полный URL к API эндпоинту."""
    # Убираем /api/v1 из базового URL, если он там есть, т.к. он уже в пути
    base = str(base_url).rstrip("/")
    # Добавляем префикс API из настроек SDK (обычно /api/v1) и путь к модели
    # Предполагаем, что BaseAppSettings.API_V1_STR содержит нужный префикс
    api_prefix = getattr(frontend_settings, "API_V1_STR", "/api/v1")
    full_path = f"{api_prefix}/{path.lstrip('/')}"
    logger.debug(f"Constructed remote endpoint: base='{base}', path='{full_path}'")
    return full_path


def configure_remote_registry():
    """Конфигурирует ModelRegistry для доступа к удаленным моделям."""
    if ModelRegistry.is_configured():
        logger.warning(
            "ModelRegistry already configured. Skipping remote configuration."
        )
        # Важно: Если разные сервисы вызывают конфигурацию, убедитесь, что они не перезаписывают друг друга,
        # или вызывайте ModelRegistry.clear() перед конфигурацией, если это нужно для изоляции.
        return

    logger.info("Configuring ModelRegistry for remote access from Frontend service...")
    # --- Регистрация моделей из Core Service ---
    core_base_url = frontend_settings.CORE_SERVICE_URL

    # User (Core)
    ModelRegistry.register_remote(
        model_cls=core_models.user.User,  # Класс-представление (может быть схемой Read)
        config=RemoteConfig(
            service_url=core_base_url,
            model_endpoint=_get_api_endpoint(
                core_base_url, "users"
            ),  # Путь к CRUD User в Core
        ),
        read_schema_cls=core_schemas.user.UserRead,  # Схема для чтения ответа
        create_schema_cls=core_schemas.user.UserCreate,  # Схема для отправки запроса на создание
        update_schema_cls=core_schemas.user.UserUpdate,  # Схема для отправки запроса на обновление
        filter_cls=core_models.user.UserFilter,  # Фильтр для поиска
        model_name="user",  # Имя для доступа через DAM Factory
    )

    # Company (Core)
    ModelRegistry.register_remote(
        model_cls=core_models.company.Company,
        config=RemoteConfig(
            service_url=core_base_url,
            model_endpoint=_get_api_endpoint(core_base_url, "companies"),
        ),
        read_schema_cls=core_schemas.company.CompanyRead,
        create_schema_cls=core_schemas.company.CompanyCreate,
        update_schema_cls=core_schemas.company.CompanyUpdate,
        filter_cls=core_models.company.CompanyFilter,
        model_name="company",
    )

    # Group (Core)
    ModelRegistry.register_remote(
        model_cls=core_models.group.Group,
        config=RemoteConfig(
            service_url=core_base_url,
            model_endpoint=_get_api_endpoint(core_base_url, "groups"),
        ),
        read_schema_cls=core_schemas.group.GroupRead,
        create_schema_cls=core_schemas.group.GroupCreate,
        update_schema_cls=core_schemas.group.GroupUpdate,
        filter_cls=core_models.group.GroupFilter,  # Фильтр для поиска
        model_name="Group",
    )
    logger.info("ModelRegistry remote configuration complete for Frontend service.")


# Вызываем конфигурацию при импорте модуля
configure_remote_registry()
