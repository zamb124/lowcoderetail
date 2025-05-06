# core_sdk/app_setup.py
import logging
from contextlib import asynccontextmanager, AsyncExitStack
from typing import List, Optional, Callable, Any, Sequence, Dict, Awaitable, Type

from fastapi import FastAPI, APIRouter, Depends, HTTPException, status
# --- ВОССТАНАВЛИВАЕМ ИМПОРТ Middleware ---
from fastapi.middleware import Middleware
# -----------------------------------------
from starlette.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, select as sqlmodel_select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

# Импорты из SDK
from core_sdk.broker.setup import broker
from core_sdk.db.session import init_db, managed_session, close_db, get_current_session
from core_sdk.registry import ModelRegistry
from core_sdk.middleware.middleware import DBSessionMiddleware
from core_sdk.config import BaseAppSettings
from core_sdk.exceptions import CoreSDKError
from core_sdk.data_access import DataAccessManagerFactory, BaseDataAccessManager, global_http_client_lifespan
from core_sdk.constants.permissions import get_all_base_permissions

logger = logging.getLogger("core_sdk.app_setup")

# --- Хелпер для инициализации прав (без изменений) ---
async def initialize_base_permissions(dam_factory: DataAccessManagerFactory):
    # ... (код без изменений) ...
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


# --- Общий Lifespan менеджер (без изменений в этой части) ---
@asynccontextmanager
async def sdk_lifespan_manager(
    app: FastAPI,
    settings: BaseAppSettings,
    run_base_permissions_init: bool = True,
    enable_broker: bool = True,
    rebuild_models: bool = True,
    manage_http_client: bool = True,
    schemas_to_rebuild: Optional[Sequence[Type[BaseModel]]] = None,
    before_startup_hook: Optional[Callable[[], Awaitable[None]]] = None,
    after_startup_hook: Optional[Callable[[], Awaitable[None]]] = None,
    before_shutdown_hook: Optional[Callable[[], Awaitable[None]]] = None,
    after_shutdown_hook: Optional[Callable[[], Awaitable[None]]] = None,
):
    # ... (код lifespan без изменений) ...
    logger.info("SDK Lifespan: Starting up...")

    if before_startup_hook:
        logger.info("SDK Lifespan: Running before_startup_hook...")
        await before_startup_hook()

    async with AsyncExitStack() as stack:
        if manage_http_client:
            try:
                await stack.enter_async_context(global_http_client_lifespan())
                logger.info("SDK Lifespan: Entered global_http_client_lifespan context.")
            except Exception as e:
                logger.critical("SDK Lifespan: Failed to enter global_http_client_lifespan context.", exc_info=True)
                raise RuntimeError("Failed to initialize HTTP client resource.") from e

        logger.info("SDK Lifespan: Initializing Database...")
        try:
            db_pool_opts = {
                "pool_size": getattr(settings, 'DB_POOL_SIZE', 10),
                "max_overflow": getattr(settings, 'DB_MAX_OVERFLOW', 5),
                "pool_recycle": 300,
            }
            init_db(
                str(settings.DATABASE_URL),
                engine_options=db_pool_opts,
                echo=settings.LOGGING_LEVEL.upper() == "DEBUG"
            )
            stack.push_async_callback(close_db)
            logger.info("SDK Lifespan: Database initialized and close_db registered for shutdown.")
        except Exception as e:
            logger.critical("SDK Lifespan: Database initialization failed.", exc_info=True)
            raise RuntimeError("Database initialization failed.") from e

        if enable_broker:
            logger.info("SDK Lifespan: Starting Taskiq broker...")
            if broker and hasattr(broker, 'startup') and callable(broker.startup):
                try:
                    await broker.startup()
                    logger.info("SDK Lifespan: Taskiq broker started successfully.")
                    if hasattr(broker, 'shutdown') and callable(broker.shutdown):
                        stack.push_async_callback(broker.shutdown)
                        logger.info("SDK Lifespan: Taskiq broker shutdown registered.")
                    else:
                        logger.warning("SDK Lifespan: Taskiq broker does not have a shutdown method.")
                except Exception as e:
                    logger.error("SDK Lifespan: Failed to start Taskiq broker.", exc_info=True)
            elif broker:
                 logger.warning(f"SDK Lifespan: Broker '{type(broker).__name__}' does not have a startup method or is not callable. Skipping startup.")
            else:
                logger.warning("SDK Lifespan: Taskiq broker is None, cannot start.")
        else:
            logger.info("SDK Lifespan: Skipping Taskiq broker startup.")

        if run_base_permissions_init:
            logger.info("SDK Lifespan: Initializing base permissions...")
            try:
                async with managed_session():
                    temp_dam_factory = DataAccessManagerFactory(registry=ModelRegistry)
                    await initialize_base_permissions(temp_dam_factory)
                logger.info("SDK Lifespan: Base permissions initialization finished.")
            except Exception as e:
                logger.error("SDK Lifespan: Error during base permissions initialization.", exc_info=True)
        else:
            logger.info("SDK Lifespan: Skipping base permissions initialization.")

        if rebuild_models:
            logger.info("SDK Lifespan: Rebuilding Pydantic/SQLModel models...")
            try:
                ModelRegistry.rebuild_models(force=True)
                if schemas_to_rebuild:
                    logger.debug(f"Explicitly rebuilding {len(schemas_to_rebuild)} provided schemas...")
                    rebuilt_count = 0
                    for schema_cls in schemas_to_rebuild:
                        if schema_cls and issubclass(schema_cls, BaseModel) and hasattr(schema_cls, 'model_rebuild'):
                            try:
                                schema_cls.model_rebuild(force=True)
                                logger.debug(f"Rebuilt: {schema_cls.__module__}.{schema_cls.__name__}")
                                rebuilt_count += 1
                            except Exception as rebuild_err:
                                logger.error(f"Error explicitly rebuilding schema {schema_cls.__name__}: {rebuild_err}", exc_info=True)
                        else:
                            logger.warning(f"Item in schemas_to_rebuild is not a valid Pydantic model with rebuild method: {schema_cls}")
                    logger.debug(f"Finished explicitly rebuilding {rebuilt_count} schemas.")
                logger.info("SDK Lifespan: Models rebuild complete.")
            except Exception as e:
                logger.error("SDK Lifespan: Error during model rebuild.", exc_info=True)
        else:
            logger.info("SDK Lifespan: Skipping model rebuild.")

        if after_startup_hook:
            logger.info("SDK Lifespan: Running after_startup_hook...")
            await after_startup_hook()

        logger.info("SDK Lifespan: Startup sequence complete. Application running...")
        yield
        logger.info("SDK Lifespan: Starting shutdown sequence...")

        if before_shutdown_hook:
            logger.info("SDK Lifespan: Running before_shutdown_hook...")
            await before_shutdown_hook()

    if after_shutdown_hook:
        logger.info("SDK Lifespan: Running after_shutdown_hook...")
        await after_shutdown_hook()
    logger.info("SDK Lifespan: Shutdown sequence complete.")


# --- Фабрика для создания FastAPI приложения (ВОССТАНОВЛЕН extra_middleware) ---
def create_app_with_sdk_setup(
    settings: BaseAppSettings,
    api_routers: Sequence[APIRouter],
    run_base_permissions_init: bool = True,
    enable_broker: bool = True,
    rebuild_models: bool = True,
    manage_http_client: bool = True,
    schemas_to_rebuild: Optional[Sequence[Type[BaseModel]]] = None,
    before_startup_hook: Optional[Callable[[], Awaitable[None]]] = None,
    after_startup_hook: Optional[Callable[[], Awaitable[None]]] = None,
    before_shutdown_hook: Optional[Callable[[], Awaitable[None]]] = None,
    after_shutdown_hook: Optional[Callable[[], Awaitable[None]]] = None,
    # --- ВОССТАНАВЛИВАЕМ ПАРАМЕТР ---
    extra_middleware: Optional[List[Middleware]] = None,
    # -------------------------------
    title: Optional[str] = None,
    description: Optional[str] = None,
    version: Optional[str] = "0.1.0",
    include_health_check: bool = True,
) -> FastAPI:
    """
    Создает и конфигурирует экземпляр FastAPI приложения с использованием стандартных настроек SDK.

    :param extra_middleware: Список экземпляров `fastapi.middleware.Middleware`
                             для добавления к приложению (опционально).
    (Остальные параметры без изменений)
    """
    effective_title = title or settings.PROJECT_NAME
    logger.info(f"Creating FastAPI app '{effective_title}' with SDK setup...")

    @asynccontextmanager
    async def app_lifespan_wrapper(app: FastAPI):
        async with sdk_lifespan_manager(
            app=app,
            settings=settings,
            run_base_permissions_init=run_base_permissions_init,
            enable_broker=enable_broker,
            rebuild_models=rebuild_models,
            manage_http_client=manage_http_client,
            schemas_to_rebuild=schemas_to_rebuild,
            before_startup_hook=before_startup_hook,
            after_startup_hook=after_startup_hook,
            before_shutdown_hook=before_shutdown_hook,
            after_shutdown_hook=after_shutdown_hook,
        ):
            yield

    app = FastAPI(
        title=effective_title,
        description=description or f"{settings.PROJECT_NAME} application.",
        version=version,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
        lifespan=app_lifespan_wrapper
    )

    # --- Добавление стандартных Middleware SDK ---
    app.add_middleware(DBSessionMiddleware)
    logger.debug("DBSessionMiddleware added.")

    # --- Добавление CORS Middleware ---
    cors_origins_config = getattr(settings, 'BACKEND_CORS_ORIGINS', [])
    if cors_origins_config:
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

    # --- ВОССТАНАВЛИВАЕМ ДОБАВЛЕНИЕ ДОПОЛНИТЕЛЬНЫХ MIDDLEWARE ---
    if extra_middleware:
        logger.info(f"Adding {len(extra_middleware)} extra middleware(s)...")
        for mw_instance in extra_middleware:
             # Предполагаем, что передаются экземпляры fastapi.middleware.Middleware
             if isinstance(mw_instance, Middleware):
                 app.add_middleware(mw_instance.cls, **mw_instance.options)
                 logger.info(f"Added extra middleware: {mw_instance.cls.__name__}")
             else:
                 # Если передан просто класс, пытаемся добавить без опций
                 # Это менее предпочтительно, лучше передавать Middleware(...)
                 try:
                    app.add_middleware(mw_instance)
                    logger.info(f"Added extra middleware (class only): {mw_instance.__name__}")
                 except Exception as mw_err:
                     logger.error(f"Failed to add extra middleware {mw_instance}: {mw_err}", exc_info=True)
    # ---------------------------------------------------------

    # --- Подключение API роутеров ---
    main_api_router = APIRouter(prefix=settings.API_V1_STR)
    for router_instance in api_routers:
        if isinstance(router_instance, APIRouter):
            main_api_router.include_router(router_instance)
            logger.debug(f"Included API router with prefix: {router_instance.prefix}")
        else:
            logger.warning(f"Item in api_routers is not an APIRouter instance: {type(router_instance)}. Skipping.")
    app.include_router(main_api_router)
    logger.info(f"All provided API routers included under prefix: {settings.API_V1_STR}")

    # --- Добавление Health Check эндпоинта ---
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
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"status": "unhealthy", "project": settings.PROJECT_NAME, "db_connection": False, "detail": db_detail}
                )
            return {"status": "ok", "project": settings.PROJECT_NAME, "db_connection": True, "detail": db_detail}
        logger.info("Standard health check endpoint '/health' added.")

    logger.info(f"FastAPI app '{app.title}' setup complete.")
    return app