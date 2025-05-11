# apps/frontend/app/main.py
import logging
import os
from fastapi import (
    FastAPI,
    Request,
    WebSocket,
)  # WebSocketDisconnect убран, если не используется
from fastapi.staticfiles import StaticFiles

# --- SDK Imports ---
from core_sdk.app_setup import create_app_with_sdk_setup
from core_sdk.registry import ModelRegistry
from core_sdk.frontend import (
    mount_static_files,
    initialize_templates,
)  # get_templates убран, т.к. используется в api/ui.py

# --- Frontend Service Imports ---
from .config import settings
from . import registry_config  # noqa F401
from .ws_manager import manager as ws_manager  # Оставляем, если WS нужен
from .api import bff_api_router  # Импортируем главный роутер

# --- Настройка логгирования ---
logging.basicConfig(level=settings.LOGGING_LEVEL.upper())
logger = logging.getLogger("frontend.app.main")

# --- Проверка конфигурации ModelRegistry ---
if not ModelRegistry.is_configured():
    logger.critical("ModelRegistry was not configured!")
    # exit(1)

logger.info("--- Starting Frontend Service Application Setup ---")

SERVICE_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
SERVICE_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

try:
    initialize_templates(SERVICE_TEMPLATE_DIR)
except Exception as e:
    logger.critical(f"Failed to initialize templates: {e}", exc_info=True)
    exit(1)

# --- Создание приложения FastAPI ---
# Передаем bff_api_router, который уже включает все остальные
app = create_app_with_sdk_setup(
    settings=settings,
    api_routers=[bff_api_router],
    enable_broker=False,
    rebuild_models=True,
    manage_http_client=True,
    enable_auth_middleware=True,
    auth_allowed_paths=[
        settings.SDK_STATIC_URL_PATH + "/*",
        "/static/*",
        "/favicon.ico",
        "/login",  # Доступ к странице /login
        "/auth/login",  # Доступ к эндпоинту POST /auth/login
        # Добавьте другие публичные пути, если они есть (например, эндпоинты healthcheck SDK)
    ],
    title=settings.PROJECT_NAME,
    description="Frontend BFF Service using Core SDK, HTMX and Datta Able.",
    version="0.1.0",
    include_health_check=True,
)

# --- Монтирование статики ---
mount_static_files(app)  # Статика SDK (Datta Able)
if os.path.exists(SERVICE_STATIC_DIR):
    app.mount(
        "/static", StaticFiles(directory=SERVICE_STATIC_DIR), name="frontend_static"
    )
    logger.info(
        f"Mounted service static files from '{SERVICE_STATIC_DIR}' at '/static'."
    )
else:
    logger.warning(f"Service static directory not found at '{SERVICE_STATIC_DIR}'.")


# --- WebSocket эндпоинт (если нужен) ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Ваш код для WebSocket...
    # await ws_manager.connect(...)
    pass


logger.info("--- Frontend Service Application Setup Complete ---")

# --- Запуск Uvicorn ---
if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = settings.FRONTEND_PORT
    log_level = settings.LOGGING_LEVEL.lower()
    workers = int(os.getenv("WEB_CONCURRENCY", "1"))

    logger.info(
        f"Starting Uvicorn for Frontend on {host}:{port} with {workers} worker(s)..."
    )
    uvicorn.run(
        "apps.frontend.app.main:app",  # Путь к объекту app
        host=host,
        port=port,
        log_level=log_level,
        reload=(settings.ENV == "dev"),
        workers=workers,
    )
