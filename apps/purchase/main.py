# purchase/app/main.py
import logging
import os
from core_sdk.app_setup import create_app_with_sdk_setup
from .config import settings
from . import registry_config # noqa: F401, Важно для инициализации ModelRegistry
from .api.endpoints.purchase_order_api import purchase_order_router_factory

logging.basicConfig(level=settings.LOGGING_LEVEL.upper())
logger = logging.getLogger("app.main")

logger.info("--- Starting Purchase Service Application Setup ---")

api_routers_to_include = [
    purchase_order_router_factory.router,
]

# Если есть схемы с ForwardRefs, которые нужно явно пересобрать:
# from . import schemas as app_schemas
# schemas_requiring_rebuild = [
#     app_schemas.purchase_order_schema.PurchaseOrderReadWithLines, # Пример
# ]

app = create_app_with_sdk_setup(
    settings=settings,
    api_routers=api_routers_to_include,
    # schemas_to_rebuild=schemas_requiring_rebuild, # Раскомментируйте, если нужно
    enable_auth_middleware=True, # Включаем AuthMiddleware из SDK
    # auth_allowed_paths=[], # Дополнительные публичные пути для Purchase сервиса, если есть
    title=settings.PROJECT_NAME,
    description="Service for managing purchase orders.",
    version="0.1.0",
    include_health_check=True
)

logger.info("--- Purchase Service Application Setup Complete ---")

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    # Используем порт из настроек, который читает переменную PORT_PURCHASE
    port = settings.PORT_PURCHASE
    log_level = settings.LOGGING_LEVEL.lower()
    workers = int(os.getenv("WEB_CONCURRENCY", "1"))

    logger.info("Starting Uvicorn for PurchaseService on %s:%s with %s worker(s)...", host, port, workers)
    uvicorn.run(
        "purchase.app.main:app", # Путь к вашему FastAPI app объекту
        host=host,
        port=port,
        log_level=log_level,
        reload=True, # Для разработки
        workers=workers
    )