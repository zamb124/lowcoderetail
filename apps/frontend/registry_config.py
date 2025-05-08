# apps/frontend/app/registry_config.py
import logging
from pydantic import HttpUrl
logger = logging.getLogger("frontend.registry_config.py")
from core_sdk.registry import ModelRegistry, RemoteConfig
# Импортируем схемы и модели, к которым нужен удаленный доступ
# Лучше импортировать их из SDK, если они там определены, или из сервисов напрямую
# Пример импорта из Core (предполагаем, что структура позволяет)
try:
    # Пытаемся импортировать напрямую из сервиса Core (может не работать в некоторых структурах deploy)
    from apps.core.models import User as CoreUserModel, Company as CoreCompanyModel, Group as CoreGroupModel # Модели
    from apps.core.schemas import UserRead as CoreUserRead, CompanyRead as CoreCompanyRead, GroupRead as CoreGroupRead # Схемы чтения
    from apps.core.schemas import UserCreate as CoreUserCreate, CompanyCreate as CoreCompanyCreate, GroupCreate as CoreGroupCreate # Схемы создания
    from apps.core.schemas import UserUpdate as CoreUserUpdate, CompanyUpdate as CoreCompanyUpdate, GroupUpdate as CoreGroupUpdate # Схемы обновления
except ImportError:
    logger.error("Could not import models/schemas directly from 'apps.core'. "
                 "Ensure services share a common base or use SDK schemas if available.")
    # Заглушки, если прямой импорт не удался. В этом случае нужны схемы в SDK.
    from core_sdk.schemas.user import UserRead as CoreUserRead # Пример из SDK
    # Определите остальные заглушки или убедитесь, что они есть в SDK
    CoreUserModel = CoreUserRead # Используем схему чтения как базовую модель для удаленного доступа
    CoreCompanyModel = None # Заглушка
    CoreGroupModel = None # Заглушка
    CoreCompanyRead = None
    CoreGroupRead = None
    CoreUserCreate = None
    CoreCompanyCreate = None
    CoreGroupCreate = None
    CoreUserUpdate = None
    CoreCompanyUpdate = None
    CoreGroupUpdate = None


# Импортируем настройки, чтобы получить URL сервисов
from .config import settings as frontend_settings

logger = logging.getLogger("app.registry_config")

def _get_api_endpoint(base_url: HttpUrl, path: str) -> str:
    """Формирует полный URL к API эндпоинту."""
    # Убираем /api/v1 из базового URL, если он там есть, т.к. он уже в пути
    base = str(base_url).rstrip('/')
    # Добавляем префикс API из настроек SDK (обычно /api/v1) и путь к модели
    # Предполагаем, что BaseAppSettings.API_V1_STR содержит нужный префикс
    api_prefix = getattr(frontend_settings, 'API_V1_STR', '/api/v1')
    full_path = f"{api_prefix}/{path.lstrip('/')}"
    logger.debug(f"Constructed remote endpoint: base='{base}', path='{full_path}'")
    return full_path

def configure_remote_registry():
    """Конфигурирует ModelRegistry для доступа к удаленным моделям."""
    if ModelRegistry.is_configured():
        logger.warning("ModelRegistry already configured. Skipping remote configuration.")
        # Важно: Если разные сервисы вызывают конфигурацию, убедитесь, что они не перезаписывают друг друга,
        # или вызывайте ModelRegistry.clear() перед конфигурацией, если это нужно для изоляции.
        return

    logger.info("Configuring ModelRegistry for remote access from Frontend service...")
    try:
        # --- Регистрация моделей из Core Service ---
        if CoreUserModel and CoreCompanyModel and CoreGroupModel and frontend_settings.CORE_SERVICE_URL:
            core_base_url = frontend_settings.CORE_SERVICE_URL

            # User (Core)
            ModelRegistry.register_remote(
                model_cls=CoreUserModel, # Класс-представление (может быть схемой Read)
                config=RemoteConfig(
                    service_url=core_base_url,
                    model_endpoint=_get_api_endpoint(core_base_url, "users") # Путь к CRUD User в Core
                ),
                read_schema_cls=CoreUserRead, # Схема для чтения ответа
                create_schema_cls=CoreUserCreate, # Схема для отправки запроса на создание
                update_schema_cls=CoreUserUpdate, # Схема для отправки запроса на обновление
                model_name="User" # Имя для доступа через DAM Factory
            )

            # Company (Core)
            ModelRegistry.register_remote(
                model_cls=CoreCompanyModel,
                config=RemoteConfig(
                    service_url=core_base_url,
                    model_endpoint=_get_api_endpoint(core_base_url, "companies")
                ),
                read_schema_cls=CoreCompanyRead,
                create_schema_cls=CoreCompanyCreate,
                update_schema_cls=CoreCompanyUpdate,
                model_name="Company"
            )

            # Group (Core)
            ModelRegistry.register_remote(
                model_cls=CoreGroupModel,
                config=RemoteConfig(
                    service_url=core_base_url,
                    model_endpoint=_get_api_endpoint(core_base_url, "groups")
                ),
                read_schema_cls=CoreGroupRead,
                create_schema_cls=CoreGroupCreate,
                update_schema_cls=CoreGroupUpdate,
                model_name="Group"
            )
        else:
            logger.warning("Skipping Core Service models registration due to missing models/schemas or CORE_SERVICE_URL.")

        # --- Регистрация моделей из других сервисов ---
        # if frontend_settings.ORDER_SERVICE_URL and OrderModel:
        #     order_base_url = frontend_settings.ORDER_SERVICE_URL
        #     ModelRegistry.register_remote(
        #         model_cls=OrderModel,
        #         config=RemoteConfig(
        #             service_url=order_base_url,
        #             model_endpoint=_get_api_endpoint(order_base_url, "orders")
        #         ),
        #         read_schema_cls=OrderRead,
        #         # ... схемы create/update ...
        #         model_name="Order"
        #     )

        logger.info("ModelRegistry remote configuration complete for Frontend service.")

    except ImportError as e:
         logger.error(f"ImportError during remote registry configuration: {e}. Check paths and dependencies.", exc_info=True)
         # Можно решить, критична ли эта ошибка
    except Exception as e:
        logger.critical("Failed to configure ModelRegistry for remote access.", exc_info=True)
        raise RuntimeError("ModelRegistry remote configuration failed.") from e

# Вызываем конфигурацию при импорте модуля
configure_remote_registry()