# purchase/app/worker.py
import logging
import os

log_level_str = os.getenv("LOGGING_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level_str)
logger = logging.getLogger("app.worker")

from core_sdk.worker_setup import initialize_worker_context, shutdown_worker_context
# from core_sdk.broker import tasks # noqa: F401 # Если у вас есть глобальные задачи в SDK

from .config import settings  # Настройки сервиса Purchase


async def startup():
    """Асинхронная функция, выполняемая при старте воркера."""
    logger.info("Purchase Worker starting up...")
    await initialize_worker_context(
        settings=settings,
        registry_config_module="purchase.app.registry_config",  # Путь к конфигурации реестра Purchase
        rebuild_models=True,
    )
    logger.info("Purchase Worker context initialized.")


async def shutdown():
    """Асинхронная функция, выполняемая при остановке воркера."""
    logger.info("Purchase Worker shutting down...")
    await shutdown_worker_context()
    logger.info("Purchase Worker context shut down.")


if __name__ == "__main__":
    logger.warning("This script is intended to be used with Taskiq CLI.")
    logger.warning("Example CLI command:")
    logger.warning(
        "taskiq worker purchase.app.worker:broker --reload --fs-discover --on-startup purchase.app.worker:startup --on-shutdown purchase.app.worker:shutdown"
    )
