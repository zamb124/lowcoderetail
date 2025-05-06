# core_sdk/app_setup.py
import logging
from contextlib import asynccontextmanager, AsyncExitStack
from typing import List, Optional, Callable, Any, Sequence, Dict, Awaitable

from fastapi import FastAPI, APIRouter, Depends, HTTPException, status
from fastapi.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, select as sqlmodel_select
from sqlalchemy.ext.asyncio import AsyncSession

# Импорты из SDK
from core_sdk.broker.setup import broker
from core_sdk.db.session import init_db, managed_session, close_db, get_current_session
from core_sdk.registry import ModelRegistry
from core_sdk.middleware.middleware import DBSessionMiddleware
from core_sdk.config import BaseAppSettings # Используем базовый класс настроек
from core_sdk.exceptions import CoreSDKError
from core_sdk.data_access import DataAccessManagerFactory, BaseDataAccessManager, global_http_client_lifespan
from core_sdk.constants.permissions import get_all_base_permissions

logger = logging.getLogger("core_sdk.app_setup")

# --- Хелпер для инициализации прав (перенесен из bootstrap.py для удобства) ---
async def initialize_base_permissions(dam_factory: DataAccessManagerFactory):
    """
    Проверяет и создает базовые права доступа, определенные в SDK.
    Должна вызываться внутри контекста managed_session.

    :param dam_factory: Фабрика DataAccessManager для получения менеджера Permission.
    :raises RuntimeError: Если не удалось получить менеджер или произошла критическая ошибка.
    """
    logger.info("Ensuring base permissions exist using DAM Factory...")
    try:
        permission_manager: BaseDataAccessManager = dam_factory.get_manager("Permission")
    except CoreSDKError as e:
        logger.critical(f"Failed to get Permission manager during bootstrap: {e}", exc_info=True)
        raise RuntimeError("Cannot initialize permissions: failed to get Permission manager.") from e

    try:
        base_permissions_data = get_all_base_permissions()
        if not base_permissions_data:
            logger.warning("No base permissions defined in get_all_base_permissions(). Skipping initialization.")
            return

        created_count = 0
        checked_count = 0
        skipped_count = 0
        error_count = 0

        logger.info(f"Checking/creating {len(base_permissions_data)} base permissions...")
        for codename, name in base_permissions_data:
            checked_count += 1
            try:
                existing_result = await permission_manager.list(filters={"codename": codename}, limit=1)
                existing_items = existing_result.get("items", [])

                if not existing_items:
                    logger.info(f"  Permission '{codename}' not found, attempting to create...")
                    perm_data = {
                        "codename": codename,
                        "name": name,
                        "description": f"Allows to {name.lower()}"
                    }
                    await permission_manager.create(perm_data)
                    logger.info(f"    Successfully created permission: {codename}")
                    created_count += 1
                else:
                    logger.debug(f"  Permission '{codename}' already exists. Skipping.")
                    skipped_count += 1
            except Exception as e: # Ловим все ошибки на уровне одного пермишена
                 logger.error(f"    ERROR processing permission '{codename}': {e}", exc_info=True)
                 error_count += 1

        log_message = (
            f"Finished ensuring base permissions. "
            f"Checked: {checked_count}, Created: {created_count}, "
            f"Skipped: {skipped_count}, Errors: {error_count}"
        )
        if error_count > 0:
            logger.error(log_message)
        else:
             logger.info(log_message)

    except Exception as e:
         logger.critical("Critical error during base permissions processing loop.", exc_info=True)
         raise RuntimeError("Failed to process base permissions.") from e


# --- Общий Lifespan менеджер ---
@asynccontextmanager
async def sdk_lifespan_manager(
    app: FastAPI, # Приложение FastAPI (может понадобиться для доступа к state)
    settings: BaseAppSettings, # Настройки приложения
    run_base_permissions_init: bool = True, # Флаг для запуска инициализации прав
    enable_broker: bool = True, # Флаг для запуска брокера
    rebuild_models: bool = True, # Флаг для пересборки моделей
    manage_http_client: bool = True, # Флаг для управления глобальным HTTP клиентом
    # Опциональные хуки для выполнения до/после старта/шатдауна SDK
    before_startup_hook: Optional[Callable[[], Awaitable[None]]] = None,
    after_startup_hook: Optional[Callable[[], Awaitable[None]]] = None,
    before_shutdown_hook: Optional[Callable[[], Awaitable[None]]] = None,
    after_shutdown_hook: Optional[Callable[[], Awaitable[None]]] = None,
):
    """
    Управляет общими ресурсами SDK в рамках жизненного цикла FastAPI приложения.

    :param app: Экземпляр FastAPI приложения.
    :param settings: Экземпляр настроек приложения (наследник BaseAppSettings).
    :param run_base_permissions_init: Запускать ли инициализацию базовых прав доступа.
    :param enable_broker: Запускать/останавливать ли брокер Taskiq.
    :param rebuild_models: Выполнять ли ModelRegistry.rebuild_models().
    :param manage_http_client: Управлять ли жизненным циклом глобального HTTP клиента SDK.
    :param before_startup_hook: Асинхронная функция, вызываемая перед стартом SDK.
    :param after_startup_hook: Асинхронная функция, вызываемая после старта SDK.
    :param before_shutdown_hook: Асинхронная функция, вызываемая перед остановкой SDK.
    :param after_shutdown_hook: Асинхронная функция, вызываемая после остановки SDK.
    """
    logger.info("SDK Lifespan: Starting up...")

    if before_startup_hook:
        logger.info("SDK Lifespan: Running before_startup_hook...")
        await before_startup_hook()

    # Контексты для управления ресурсами
    lifespan_contexts = []
    if manage_http_client:
        lifespan_contexts.append(global_http_client_lifespan())
    if enable_broker and broker:
        lifespan_contexts.append(broker) # Брокер Taskiq сам является контекстным менеджером

    async with AsyncExitStack() as stack:
        # Входим во все необходимые контексты (HTTP клиент, брокер)
        for ctx_index, ctx in enumerate(lifespan_contexts):
            try:
                await stack.enter_async_context(ctx)
                logger.info(f"SDK Lifespan: Entered managed context {ctx_index + 1}/{len(lifespan_contexts)} ({type(ctx).__name__}).")
            except Exception as e:
                 logger.critical(f"SDK Lifespan: Failed to enter managed context {type(ctx).__name__}.", exc_info=True)
                 raise RuntimeError(f"Failed to initialize resource: {type(ctx).__name__}") from e

        # 1. Инициализация БД
        logger.info("SDK Lifespan: Initializing Database...")
        try:
            db_pool_opts = {
                "pool_size": getattr(settings, 'DB_POOL_SIZE', 10),
                "max_overflow": getattr(settings, 'DB_MAX_OVERFLOW', 5),
                "pool_recycle": 300,
            }
            init_db(
                str(settings.DATABASE_URL), # DATABASE_URL должно быть в settings
                engine_options=db_pool_opts,
                echo=settings.LOGGING_LEVEL.upper() == "DEBUG"
            )
            # Регистрируем функцию закрытия БД при выходе из стека
            await stack.push_async_callback(close_db)
            logger.info("SDK Lifespan: Database initialized and close_db registered for shutdown.")
        except Exception as e:
            logger.critical("SDK Lifespan: Database initialization failed.", exc_info=True)
            raise RuntimeError("Database initialization failed.") from e

        # 2. Инициализация прав (внутри сессии)
        if run_base_permissions_init:
            logger.info("SDK Lifespan: Initializing base permissions...")
            try:
                async with managed_session():
                    # Создаем временную фабрику DAM только для этой операции
                    # HTTP клиент и токен не нужны для локальных прав
                    temp_dam_factory = DataAccessManagerFactory(registry=ModelRegistry)
                    await initialize_base_permissions(temp_dam_factory)
                logger.info("SDK Lifespan: Base permissions initialization finished.")
            except Exception as e:
                logger.error("SDK Lifespan: Error during base permissions initialization.", exc_info=True)
                # Не прерываем запуск из-за ошибки прав по умолчанию
        else:
            logger.info("SDK Lifespan: Skipping base permissions initialization.")

        # 3. Пересборка моделей
        if rebuild_models:
            logger.info("SDK Lifespan: Rebuilding Pydantic/SQLModel models...")
            try:
                ModelRegistry.rebuild_models(force=True)
                # Примечание: явный вызов rebuild для схем с ForwardRefs вне реестра
                # должен выполняться в after_startup_hook конкретного сервиса.
                logger.info("SDK Lifespan: Models rebuild complete.")
            except Exception as e:
                logger.error("SDK Lifespan: Error during model rebuild.", exc_info=True)
        else:
            logger.info("SDK Lifespan: Skipping model rebuild.")

        if after_startup_hook:
            logger.info("SDK Lifespan: Running after_startup_hook...")
            await after_startup_hook()

        logger.info("SDK Lifespan: Startup sequence complete. Application running...")
        yield # <--- Приложение работает здесь
        logger.info("SDK Lifespan: Starting shutdown sequence...")

        if before_shutdown_hook:
            logger.info("SDK Lifespan: Running before_shutdown_hook...")
            await before_shutdown_hook()

        # Ресурсы (БД, брокер, HTTP клиент) будут автоматически очищены
        # при выходе из AsyncExitStack в порядке, обратном их добавлению.

    if after_shutdown_hook:
        logger.info("SDK Lifespan: Running after_shutdown_hook...")
        await after_shutdown_hook()
    logger.info("SDK Lifespan: Shutdown sequence complete.")


# --- Фабрика для создания FastAPI приложения ---
def create_app_with_sdk_setup(
    settings: BaseAppSettings,
    api_routers: Sequence[APIRouter],
    run_base_permissions_init: bool = True,
    enable_broker: bool = True,
    rebuild_models: bool = True,
    manage_http_client: bool = True,
    before_startup_hook: Optional[Callable[[], Awaitable[None]]] = None,
    after_startup_hook: Optional[Callable[[], Awaitable[None]]] = None,
    before_shutdown_hook: Optional[Callable[[], Awaitable[None]]] = None,
    after_shutdown_hook: Optional[Callable[[], Awaitable[None]]] = None,
    extra_middleware: Optional[List[Middleware]] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    version: Optional[str] = "0.1.0",
    include_health_check: bool = True,
) -> FastAPI:
    """
    Создает и конфигурирует экземпляр FastAPI приложения с использованием стандартных настроек SDK.

    :param settings: Экземпляр настроек приложения (наследник BaseAppSettings).
    :param api_routers: Последовательность API роутеров для включения в приложение.
    :param run_base_permissions_init: Запускать ли инициализацию базовых прав доступа.
    :param enable_broker: Запускать/останавливать ли брокер Taskiq.
    :param rebuild_models: Выполнять ли ModelRegistry.rebuild_models().
    :param manage_http_client: Управлять ли жизненным циклом глобального HTTP клиента SDK.
    :param before_startup_hook: Асинхронная функция, вызываемая перед стартом SDK в lifespan.
    :param after_startup_hook: Асинхронная функция, вызываемая после старта SDK в lifespan.
    :param before_shutdown_hook: Асинхронная функция, вызываемая перед остановкой SDK в lifespan.
    :param after_shutdown_hook: Асинхронная функция, вызываемая после остановки SDK в lifespan.
    :param extra_middleware: Список дополнительных Middleware FastAPI (опционально).
    :param title: Заголовок приложения FastAPI.
    :param description: Описание приложения FastAPI.
    :param version: Версия приложения FastAPI.
    :param include_health_check: Включать ли стандартный эндпоинт /health (по умолчанию True).
    :return: Сконфигурированный экземпляр FastAPI.
    """
    effective_title = title or settings.PROJECT_NAME
    logger.info(f"Creating FastAPI app '{effective_title}' with SDK setup...")

    # Создаем обертку lifespan с переданными параметрами
    @asynccontextmanager
    async def app_lifespan_wrapper(app: FastAPI):
        async with sdk_lifespan_manager(
            app=app,
            settings=settings,
            run_base_permissions_init=run_base_permissions_init,
            enable_broker=enable_broker,
            rebuild_models=rebuild_models,
            manage_http_client=manage_http_client,
            before_startup_hook=before_startup_hook,
            after_startup_hook=after_startup_hook,
            before_shutdown_hook=before_shutdown_hook,
            after_shutdown_hook=after_shutdown_hook,
        ):
            yield

    # 1. Создание FastAPI приложения
    app = FastAPI(
        title=effective_title,
        description=description or f"{settings.PROJECT_NAME} application.",
        version=version,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
        lifespan=app_lifespan_wrapper # Передаем обертку lifespan
    )

    # 2. Добавление стандартных Middleware SDK
    app.add_middleware(DBSessionMiddleware)
    logger.debug("DBSessionMiddleware added.")

    # 3. Добавление CORS Middleware
    cors_origins_config = getattr(settings, 'BACKEND_CORS_ORIGINS', [])
    if cors_origins_config:
        # Обработка строки или списка
        if isinstance(cors_origins_config, str):
            origins = [origin.strip() for origin in cors_origins_config.split(',') if origin.strip()]
        else:
            origins = [str(origin).strip() for origin in cors_origins_config if str(origin).strip()]

        allow_all = "*" in origins or not origins
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins if not allow_all else ["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        logger.info(f"CORS middleware enabled for origins: {'*' if allow_all else origins}")
    else:
        logger.warning("CORS middleware is disabled (BACKEND_CORS_ORIGINS not set in settings).")

    # 4. Добавление дополнительных Middleware
    if extra_middleware:
        for mw_instance in extra_middleware: # Предполагаем, что это уже экземпляры Middleware
             if isinstance(mw_instance, Middleware):
                 app.add_middleware(mw_instance.cls, **mw_instance.options)
                 logger.info(f"Added extra middleware: {mw_instance.cls.__name__}")
             else: # Обработка случая, если передан просто класс
                 app.add_middleware(mw_instance)
                 logger.info(f"Added extra middleware: {mw_instance.__name__}")


    # 5. Подключение API роутеров
    # Используем главный роутер с префиксом API_V1_STR из настроек
    main_api_router = APIRouter(prefix=settings.API_V1_STR)
    for router_instance in api_routers:
        if isinstance(router_instance, APIRouter):
            main_api_router.include_router(router_instance)
            logger.debug(f"Included API router with prefix: {router_instance.prefix}")
        else:
            logger.warning(f"Item in api_routers is not an APIRouter instance: {type(router_instance)}. Skipping.")
    app.include_router(main_api_router)
    logger.info(f"All provided API routers included under prefix: {settings.API_V1_STR}")

    # 6. Добавление Health Check эндпоинта
    if include_health_check:
        @app.get(
            "/health",
            tags=["Health"],
            summary="Perform Health Check",
            description="Проверяет статус сервиса и подключение к базе данных."
        )
        async def health_check(session: AsyncSession = Depends(get_current_session)):
            logger.debug("Health check endpoint requested.")
            db_ok = False
            db_detail = "Database status unknown"
            try:
                result = await session.execute(sqlmodel_select(1))
                db_ok = result.scalar_one() == 1
                db_detail = "Connection OK"
                logger.debug("Health check: Database connection successful.")
            except Exception as e:
                db_detail = f"DB connection error: {type(e).__name__}"
                logger.error(f"Health check: Database connection failed. Error: {e}", exc_info=False)
                db_ok = False

            if not db_ok:
                # Возвращаем 503 Service Unavailable, если БД недоступна
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"status": "unhealthy", "project": settings.PROJECT_NAME, "db_connection": False, "detail": db_detail}
                )
            return {"status": "ok", "project": settings.PROJECT_NAME, "db_connection": True, "detail": db_detail}
        logger.info("Standard health check endpoint '/health' added.")

    logger.info(f"FastAPI app '{app.title}' setup complete.")
    return app