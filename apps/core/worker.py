# core/app/worker.py
import asyncio
import logging
import os

# --- Настройка логирования до импортов ---
# Уровень лога берется из окружения или настроек
log_level_str = os.getenv("LOGGING_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level_str)
logger = logging.getLogger("app.worker") # Логгер для воркера

# --- Импорты ---
# Импортируем утилиты для настройки воркера из SDK
from core_sdk.worker_setup import initialize_worker_context, shutdown_worker_context
# Импортируем брокер из SDK (Taskiq CLI будет его использовать)
from core_sdk.broker.setup import broker
# Импортируем задачи, чтобы Taskiq их обнаружил при запуске через этот файл (если нужно)
# Обычно Taskiq CLI находит их сам через --fs-discover
# from core_sdk.broker import tasks # noqa: F401

# Импортируем настройки сервиса
from .config import settings

# --- Хуки для Taskiq CLI ---
# Эти функции будут вызываться Taskiq CLI при использовании опций --on-startup/--on-shutdown

async def startup():
    """Асинхронная функция, выполняемая при старте воркера."""
    logger.info("Worker starting up...")
    await initialize_worker_context(
        settings=settings,
        registry_config_module="app.registry_config", # Путь к конфигурации реестра Core
        rebuild_models=True # Пересобираем модели для воркера
    )
    logger.info("Worker context initialized.")

async def shutdown():
    """Асинхронная функция, выполняемая при остановке воркера."""
    logger.info("Worker shutting down...")
    await shutdown_worker_context()
    logger.info("Worker context shut down.")

# --- Основная часть (для информации и возможного программного запуска) ---
if __name__ == "__main__":
    # Этот блок не выполняется при запуске через `taskiq worker`
    logger.warning("This script is intended to be used with Taskiq CLI.")
    logger.warning("Example CLI command:")
    logger.warning("taskiq worker apps.core.worker:broker --reload --fs-discover --on-startup apps.core.worker:startup --on-shutdown apps.core.worker:shutdown")

    # Пример программного запуска (обычно не используется для продакшена)
    # async def run_programmatic_worker():
    #     await startup()
    #     # Здесь нужен цикл прослушивания брокера, который обычно предоставляет Taskiq CLI
    #     logger.info("Programmatic worker loop started (example only)...")
    #     await asyncio.sleep(3600) # Пример ожидания
    #     await shutdown()
    #
    # try:
    #     asyncio.run(run_programmatic_worker())
    # except KeyboardInterrupt:
    #     logger.info("Programmatic worker stopped.")