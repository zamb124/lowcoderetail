# core_sdk/worker_setup.py
import logging
import importlib
import os
from typing import Optional, Any, Dict

# Импорты из SDK
from core_sdk.db.session import init_db, close_db
from core_sdk.registry import ModelRegistry
from core_sdk.config import BaseAppSettings  # Базовый класс настроек

logger = logging.getLogger("core_sdk.worker_setup")


async def initialize_worker_context(
    settings: BaseAppSettings,
    registry_config_module: Optional[str] = None,
    rebuild_models: bool = True,
    # Можно добавить другие функции инициализации, специфичные для воркера
):
    """
    Инициализирует контекст, необходимый для работы воркера Taskiq.
    Выполняет инициализацию БД и конфигурацию ModelRegistry.

    :param settings: Экземпляр настроек приложения (наследник BaseAppSettings).
    :param registry_config_module: Строка с путем к модулю, который конфигурирует
                                   ModelRegistry (например, 'app.registry_config').
                                   Если None, конфигурация реестра пропускается.
    :param rebuild_models: Выполнять ли ModelRegistry.rebuild_models().
    """
    logger.info("Initializing worker context...")

    # 1. Инициализация базы данных SDK
    logger.info("Initializing SDK Database for worker...")
    try:
        # Используем настройки пула из settings, но можно задать меньшие значения через env для воркера
        worker_pool_size = int(
            os.getenv("WORKER_DB_POOL_SIZE", str(getattr(settings, "DB_POOL_SIZE", 5)))
        )
        worker_max_overflow = int(
            os.getenv(
                "WORKER_DB_MAX_OVERFLOW", str(getattr(settings, "DB_MAX_OVERFLOW", 2))
            )
        )

        db_pool_opts: Dict[str, Any] = {
            "pool_size": worker_pool_size,
            "max_overflow": worker_max_overflow,
            "pool_recycle": 300,
        }
        init_db(
            str(settings.DATABASE_URL),
            engine_options=db_pool_opts,
            echo=settings.LOGGING_LEVEL.upper() == "DEBUG",
        )
        logger.info(
            f"SDK Database initialized for worker (pool_size={worker_pool_size})."
        )
    except Exception as e:
        logger.critical("Failed to initialize SDK Database for worker.", exc_info=True)
        raise RuntimeError(
            "Database initialization failed, worker cannot start."
        ) from e

    # 2. Конфигурация ModelRegistry (через импорт модуля)
    if registry_config_module:
        logger.info(
            f"Configuring ModelRegistry by importing module: {registry_config_module}"
        )
        try:
            importlib.import_module(registry_config_module)
            if not ModelRegistry.is_configured():
                logger.warning(
                    f"Module {registry_config_module} imported, but ModelRegistry is still not configured."
                )
            else:
                logger.info("ModelRegistry configured successfully for worker.")
        except ImportError:
            logger.error(
                f"Could not import registry configuration module: {registry_config_module}"
            )
            # Решите, критично ли это для воркера
            # raise RuntimeError(f"Failed to import registry config module: {registry_config_module}")
        except Exception as e:
            logger.error(
                f"Error configuring ModelRegistry from module {registry_config_module}.",
                exc_info=True,
            )
            # raise RuntimeError(f"Failed to configure ModelRegistry: {e}") from e
    else:
        logger.warning(
            "No registry_config_module provided. ModelRegistry might not be configured for worker tasks."
        )

    # 3. Пересборка моделей
    if rebuild_models:
        logger.info("Rebuilding Pydantic/SQLModel models for worker...")
        try:
            ModelRegistry.rebuild_models(force=True)
            # Примечание: явный вызов rebuild для схем с ForwardRefs вне реестра
            # должен выполняться в коде инициализации конкретного воркера, если необходимо.
            logger.info("Pydantic/SQLModel models rebuild complete for worker.")
        except Exception as e:
            logger.error(
                "Error during Pydantic/SQLModel model rebuild for worker.",
                exc_info=True,
            )
    else:
        logger.info("Skipping model rebuild for worker.")

    logger.info("Worker context initialized successfully.")


async def shutdown_worker_context():
    """Выполняет очистку ресурсов при остановке воркера (закрытие БД)."""
    logger.info("Shutting down worker context...")
    await close_db()  # Функция close_db уже содержит логирование
    logger.info("Worker context shut down complete.")
