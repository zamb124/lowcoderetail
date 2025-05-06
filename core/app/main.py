# core/app/main.py
import logging
import os # Нужен для uvicorn.run, если используется

# Импортируем фабрику создания приложения из SDK
from core_sdk.app_setup import create_app_with_sdk_setup

# Локальные импорты Core
from .config import settings
# Импортируем модуль registry_config, чтобы конфигурация реестра выполнилась при старте
# Это важно сделать ДО вызова create_app_with_sdk_setup, если он использует ModelRegistry
from . import registry_config # noqa: F401 (выполнит код при импорте)
# Импортируем функцию инициализации прав, чтобы передать ее в фабрику
from .permissions_init import ensure_base_permissions

# Импорты роутеров API, которые нужно подключить
from .api.endpoints import (
    auth, users, companies, groups, permissions, i18n,
)

# Настройка логгера
logging.basicConfig(level=settings.LOGGING_LEVEL.upper())
logger = logging.getLogger("app.main")

logger.info("--- Starting Core Service Application Setup ---")

# Список роутеров для включения в приложение
# Каждый элемент должен быть экземпляром APIRouter
api_routers_to_include = [
    auth.router,
    users.user_factory.router,
    companies.company_factory.router,
    groups.group_factory.router,
    permissions.permission_factory.router,
    i18n.router,
]

# --- Хуки жизненного цикла (примеры, если нужны) ---
async def core_before_startup():
    logger.info("Running Core specific actions BEFORE SDK startup...")
    # Например, проверка доступности внешнего сервиса, не управляемого SDK

async def core_after_startup():
    logger.info("Running Core specific actions AFTER SDK startup...")
    # Например, загрузка данных в кэш, инициализация специфичных компонентов

async def core_before_shutdown():
    logger.info("Running Core specific actions BEFORE SDK shutdown...")
    # Например, сохранение состояния, уведомление других сервисов

async def core_after_shutdown():
    logger.info("Running Core specific actions AFTER SDK shutdown...")
    # Например, финальная очистка

# --- Создание приложения с помощью фабрики SDK ---
app = create_app_with_sdk_setup(
    settings=settings,
    api_routers=api_routers_to_include,
    run_base_permissions_init=True, # Включаем инициализацию прав для Core
    enable_broker=True,             # Включаем брокер для Core
    rebuild_models=True,            # Включаем ребилд моделей
    manage_http_client=True,        # Управляем HTTP клиентом (на случай будущих удаленных вызовов)
    # Передаем хуки
    before_startup_hook=core_before_startup,
    after_startup_hook=core_after_startup,
    before_shutdown_hook=core_before_shutdown,
    after_shutdown_hook=core_after_shutdown,
    # extra_middleware=None, # Дополнительные middleware, если нужны
    title=settings.PROJECT_NAME,
    description="Core service for the platform.",
    version="0.1.0",
    include_health_check=True # Включаем стандартный health check
)

logger.info("--- Core Service Application Setup Complete ---")

# --- Точка входа для Uvicorn (для локальной разработки) ---
if __name__ == "__main__":
    import uvicorn
    # Используем настройки из settings для порта и уровня логов
    # Host 0.0.0.0 делает приложение доступным извне контейнера/сети
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    log_level = settings.LOGGING_LEVEL.lower()
    workers = int(os.getenv("WEB_CONCURRENCY", "1")) # Количество воркеров Uvicorn

    logger.info(f"Starting Uvicorn development server on {host}:{port} with {workers} worker(s)...")
    uvicorn.run(
        "core.app.main:app", # Путь к экземпляру FastAPI app
        host=host,
        port=port,
        log_level=log_level,
        reload=True, # Включаем автоперезагрузку для разработки
        workers=workers # Количество воркеров
    )