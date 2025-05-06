# core/app/main.py
import logging
from contextlib import asynccontextmanager
# AsyncGenerator не используется напрямую
from typing import Any # Используется для типа engine

# Импорты FastAPI и Starlette
from fastapi import FastAPI, APIRouter, Depends, HTTPException, status # Добавляем HTTPException, status
from starlette.middleware.cors import CORSMiddleware

# Импорты SQLAlchemy и SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, AsyncSession
from sqlmodel import select as sqlmodel_select # SQLModel сам по себе не используется, только select

# --- Импорты из core_sdk ---
from core_sdk.broker.setup import broker
from core_sdk.db.session import init_db, managed_session, close_db, get_current_session
from core_sdk.registry import ModelRegistry # RemoteConfig не используется здесь
from core_sdk.middleware.middleware import DBSessionMiddleware
# global_http_client_lifespan не используется здесь, т.к. нет удаленных DAM в Core?
# Если бы были, нужно было бы его импортировать и использовать в lifespan.
# from core_sdk.data_access import global_http_client_lifespan

# --- Локальные импорты Core ---
# Используем относительные импорты внутри приложения 'app'
from .config import settings
from . import models # Нужен для ModelRegistry.rebuild_models (косвенно)
from . import schemas # Нужен для ModelRegistry.rebuild_models и явного ребилда
from . import registry_config # Этот импорт выполнит конфигурацию Registry

# Импорты API эндпоинтов
from .api.endpoints import (
    auth, users, companies, groups, permissions, i18n,
)
# Импорт функции инициализации прав
from .permissions_init import ensure_base_permissions

# Настройка базового логгирования
# Уровень INFO будет логировать INFO, WARNING, ERROR, CRITICAL
# Для DEBUG нужно установить logging.DEBUG
logging.basicConfig(level=settings.LOGGING_LEVEL.upper()) # Используем уровень из настроек
logger = logging.getLogger("app.main") # Логгер для этого модуля

# --- Создание Engine SQLAlchemy ---
# Используем настройки из settings
database_connect_url = str(settings.DATABASE_URL)
# Явно указываем тип engine для ясности
engine: AsyncEngine = create_async_engine(
    database_connect_url,
    echo=settings.LOGGING_LEVEL.upper() == "DEBUG", # Включаем SQL echo только на уровне DEBUG
    future=True, # Рекомендуется для SQLAlchemy 2.0
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=300 # Время жизни соединения в пуле (секунды)
)
logger.info(f"SQLAlchemy AsyncEngine created for URL: {database_connect_url[:database_connect_url.find('@') + 1]}********")

# --- Lifespan для управления ресурсами приложения ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Асинхронный контекстный менеджер для управления жизненным циклом приложения FastAPI.
    Выполняет инициализацию при старте и очистку при остановке.
    """
    logger.info(f"Starting up {settings.PROJECT_NAME}...")

    # 1. Инициализация базы данных SDK
    logger.info("Initializing SDK Database...")
    try:
        init_db(
            str(settings.DATABASE_URL),
            engine_options={
                "pool_size": settings.DB_POOL_SIZE,
                "max_overflow": settings.DB_MAX_OVERFLOW,
                "pool_recycle": 300,
                # echo управляется уровнем логгера SQLAlchemy, а не здесь напрямую
            },
            echo=settings.LOGGING_LEVEL.upper() == "DEBUG" # Передаем echo для create_engine внутри init_db
        )
    except Exception as e:
        logger.critical("Failed to initialize SDK Database during startup.", exc_info=True)
        # Если БД критична для старта, можно выбросить исключение, чтобы FastAPI не запустился
        raise RuntimeError("Database initialization failed, cannot start application.") from e

    # 2. Инициализация базовых прав доступа (внутри managed_session)
    logger.info("Ensuring base permissions...")
    try:
        async with managed_session(): # Создает сессию для этой операции
             await ensure_base_permissions()
        logger.info("Base permissions check/creation complete.")
    except Exception as e:
        # Логируем ошибку, но позволяем приложению запуститься,
        # если отсутствие прав не является критичным для старта.
        logger.error("Error during initial setup of base permissions.", exc_info=True)
        # Если это критично, можно раскомментировать raise:
        # raise RuntimeError("Failed to ensure base permissions, cannot start application.") from e

    # 3. Запуск брокера Taskiq
    logger.info("Starting Taskiq broker...")
    try:
        if broker:
            await broker.startup()
            logger.info("Taskiq broker started successfully.")
        else:
            logger.warning("Taskiq broker is not configured (None). Skipping broker startup.")
    except Exception as e:
        logger.error("Failed to start Taskiq broker.", exc_info=True)
        # Решите, является ли ошибка брокера критичной для старта
        # raise RuntimeError("Taskiq broker startup failed, cannot start application.") from e

    # 4. Пересборка моделей Pydantic/SQLModel (важно после импорта всех моделей и схем)
    logger.info("Rebuilding Pydantic/SQLModel models...")
    try:
        ModelRegistry.rebuild_models(force=True)
        # Явно пересобираем схемы с ForwardRefs, если они не в реестре
        schemas.group.GroupReadWithDetails.model_rebuild(force=True)
        schemas.user.UserReadWithGroups.model_rebuild(force=True)
        # schemas.permission.PermissionRead не использует ForwardRefs
        logger.info("Pydantic/SQLModel models rebuild complete.")
    except Exception as e:
        logger.error("Error during Pydantic/SQLModel model rebuild.", exc_info=True)
        # Ошибка здесь может указывать на проблемы с ForwardRefs или определениями моделей/схем

    # --- Приложение готово к работе ---
    logger.info(f"{settings.PROJECT_NAME} startup complete. Ready to accept connections.")
    yield # <--- Приложение работает здесь
    # ----------------------------------

    # --- Код при остановке приложения ---
    logger.info(f"Shutting down {settings.PROJECT_NAME}...")

    # 1. Остановка брокера Taskiq
    logger.info("Shutting down Taskiq broker...")
    try:
        if broker:
            await broker.shutdown()
            logger.info("Taskiq broker shut down successfully.")
        else:
            logger.info("Taskiq broker was not configured. Skipping shutdown.")
    except Exception as e:
        logger.error("Error shutting down Taskiq broker.", exc_info=True)

    # 2. Закрытие соединений с БД SDK
    logger.info("Closing SDK Database connections...")
    await close_db() # Функция close_db уже содержит логирование

    logger.info(f"{settings.PROJECT_NAME} shut down complete.")


# --- Создание FastAPI приложения ---
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Core service for the platform, managing users, companies, groups, and permissions.",
    version="0.1.0", # TODO: Вынести версию в настройки или отдельный файл
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan # Передаем менеджер жизненного цикла
)

# --- Middleware ---
# Middleware для управления сессиями БД через contextvars
app.add_middleware(DBSessionMiddleware)
logger.info("DBSessionMiddleware added.")

# Middleware для CORS
if settings.BACKEND_CORS_ORIGINS:
    # Преобразуем строки в список, если они заданы как строка через запятую в .env
    origins = [str(origin).strip() for origin in settings.BACKEND_CORS_ORIGINS]
    # Если BACKEND_CORS_ORIGINS пустой список или содержит "*", разрешаем все
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
    logger.warning("CORS middleware is disabled (BACKEND_CORS_ORIGINS not set).")


# --- Подключение API роутеров ---
# Создаем главный роутер с префиксом /api/v1
api_router = APIRouter(prefix=settings.API_V1_STR)

# Подключаем роутеры эндпоинтов к главному роутеру
api_router.include_router(auth.router, tags=["Authentication"])
api_router.include_router(users.user_factory.router, tags=["Users"]) # Тег из фабрики или здесь
api_router.include_router(companies.company_factory.router, tags=["Companies"])
api_router.include_router(groups.group_factory.router, tags=["Groups"])
api_router.include_router(permissions.permission_factory.router, tags=["Permissions"])
api_router.include_router(i18n.router, tags=["I18n"]) # Тег из i18n.py

# Подключаем главный роутер к приложению
app.include_router(api_router)
logger.info(f"API routers included under prefix: {settings.API_V1_STR}")

# --- Health Check эндпоинт ---
@app.get(
    "/health",
    tags=["Health"],
    summary="Perform Health Check",
    description="Проверяет статус сервиса и подключение к базе данных."
)
async def health_check(session: AsyncSession = Depends(get_current_session)):
    """
    Проверяет работоспособность сервиса и его зависимостей (например, БД).
    """
    logger.debug("Health check requested.")
    db_ok = False
    db_detail = "Database status unknown"
    try:
        # Простой запрос к БД для проверки соединения
        result = await session.execute(sqlmodel_select(1))
        db_ok = result.scalar_one() == 1
        db_detail = "Connection OK"
        logger.debug("Health check: Database connection successful.")
    except Exception as e:
        db_detail = f"DB connection error: {type(e).__name__}"
        logger.error(f"Health check: Database connection failed. Error: {e}", exc_info=False) # Не логируем весь стектрейс ошибки БД
        db_ok = False

    # Проверка инициализации session_maker (хотя init_db должна была упасть раньше, если ошибка)
    # Убрана проверка app.state, т.к. используем init_db из SDK
    # if not _db_session_maker: # Проверяем глобальную переменную SDK
    #     logger.error("Health check: Session maker not initialized.")
    #     return {"status": "error", "detail": "Session maker not initialized", "db_connection": db_ok, "db_detail": db_detail}

    if not db_ok:
         # Возвращаем 503 Service Unavailable, если БД недоступна
         raise HTTPException(
             status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
             detail={"status": "unhealthy", "project": settings.PROJECT_NAME, "db_connection": False, "detail": db_detail}
         )

    # Если все проверки прошли успешно
    return {"status": "ok", "project": settings.PROJECT_NAME, "db_connection": True, "detail": db_detail}

# Можно добавить эндпоинт для информации о версии/сборке
# @app.get("/version", tags=["Health"])
# async def get_version():
#     return {"version": settings.VERSION, "build": settings.BUILD_NUMBER}