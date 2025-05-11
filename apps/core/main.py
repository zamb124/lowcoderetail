# core/app/main.py
import logging
import os

# Импортируем фабрику создания приложения из SDK
from core_sdk.app_setup import create_app_with_sdk_setup

# Локальные импорты Core
from .config import settings
from . import registry_config

# --- ИМПОРТИРУЕМ СХЕМЫ ДЛЯ REBUILD ---
from . import schemas as app_schemas
# ------------------------------------

# Импорты роутеров API
from .api.endpoints import (
    auth,
    users,
    companies,
    groups,
    i18n,
)

# Настройка логгера
logging.basicConfig(level=settings.LOGGING_LEVEL.upper())
logger = logging.getLogger("app.main")

logger.info("--- Starting Core Service Application Setup ---")

# Список роутеров для включения
api_routers_to_include = [
    auth.router,
    users.user_factory.router,
    companies.company_factory.router,
    groups.group_factory.router,
    i18n.router,
]

# --- СПИСОК СХЕМ ДЛЯ ЯВНОГО REBUILD ---
# Добавьте сюда все схемы вашего приложения, использующие ForwardRefs
schemas_requiring_rebuild = [
    app_schemas.group.GroupReadWithDetails,
    app_schemas.user.UserReadWithGroups,
    # app_schemas.company.CompanyReadWithDetails, # Если она тоже использует ForwardRefs
]
# ------------------------------------


# Хуки жизненного цикла (без изменений)
async def core_before_startup():
    logger.info("Running Core specific actions BEFORE SDK startup...")


async def core_after_startup():
    logger.info("Running Core specific actions AFTER SDK startup...")


async def core_before_shutdown():
    logger.info("Running Core specific actions BEFORE SDK shutdown...")


async def core_after_shutdown():
    logger.info("Running Core specific actions AFTER SDK shutdown...")


# Создаем приложение с помощью фабрики SDK
app = create_app_with_sdk_setup(
    settings=settings,
    api_routers=api_routers_to_include,
    enable_broker=True,
    rebuild_models=True,
    manage_http_client=True,
    schemas_to_rebuild=schemas_requiring_rebuild,
    # --- Управляем AuthMiddleware ---
    enable_auth_middleware=True,  # Включаем AuthMiddleware
    auth_allowed_paths=[
        f"{settings.API_V1_STR}/docs",
        f"{settings.API_V1_STR}/redoc",
        f"{settings.API_V1_STR}/service-worker.js",
        f"{settings.API_V1_STR}/openapi.json",
        f"{settings.API_V1_STR}/service-worker.js",
        f"{settings.API_V1_STR}/auth/login",
    ],
    # -------------------------------
    before_startup_hook=core_before_startup,
    after_startup_hook=core_after_startup,
    before_shutdown_hook=core_before_shutdown,
    after_shutdown_hook=core_after_shutdown,
    title=settings.PROJECT_NAME,
    description="Core service for the platform.",
    version="0.1.0",
    include_health_check=True,
)

logger.info("--- Core Service Application Setup Complete ---")

# Точка входа для Uvicorn (без изменений)
if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    log_level = settings.LOGGING_LEVEL.lower()
    workers = int(os.getenv("WEB_CONCURRENCY", "1"))

    logger.info(
        f"Starting Uvicorn development server on {host}:{port} with {workers} worker(s)..."
    )
    uvicorn.run(
        "apps.core.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=True,
        workers=workers,
    )
