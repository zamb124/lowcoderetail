from fastapi import FastAPI, Depends, APIRouter
from contextlib import asynccontextmanager
from typing import AsyncGenerator

# 1. Импорты из core_sdk
from core_sdk.registry import ModelRegistry, RemoteConfig
from core_sdk.data_access import DataAccessManager, get_data_access_manager, global_http_client_lifespan # Импорт lifespan для клиента
from core_sdk.db.session import create_db_and_tables # Опционально, для инициализации БД
# Импортируем представление удаленной модели и класс клиента из SDK
from core_sdk.clients.core_client import CoreUserRead, CoreUserClient
# Импортируем базовую модель для примера, если Product/StockLevel от нее наследуются
from core_sdk.models import BaseModelWithMeta

# 2. Импорты локальных компонентов WMS
from .config import settings # Загружаем настройки (включая CORE_SERVICE_URL)
from .models.product import Product # Локальная модель WMS
from .models.stock import StockLevel # Другая локальная модель WMS
from .api.endpoints import products as product_router # Пример API роутера WMS

# --- Конфигурация Model Registry ---
def configure_registry():
    """Функция для настройки ModelRegistry."""
    print("Configuring Model Registry for WMS Service...")

    # --- Регистрация локальных моделей WMS ---
    # Указываем, что эти модели находятся в БД текущего (WMS) сервиса
    ModelRegistry.register_local(Product)
    ModelRegistry.register_local(StockLevel)
    print(f"Registered local models: {[Product.__name__, StockLevel.__name__]}")

    # --- Регистрация удаленных моделей (из других сервисов) ---
    # Указываем, что CoreUserRead - это модель из Core сервиса
    ModelRegistry.register_remote(
        model_cls=CoreUserRead, # Класс-представление модели из Core
        config=RemoteConfig(
            service_url=settings.CORE_SERVICE_URL, # URL Core сервиса из настроек
            client_class=CoreUserClient,         # Класс клиента для Core сервиса
            model_endpoint="/users"              # Базовый путь API для пользователей в Core
        )
    )
    print(f"Registered remote model: {CoreUserRead.__name__} -> {settings.CORE_SERVICE_URL}")

    # ... здесь можно зарегистрировать другие удаленные модели из OMS, Catalog и т.д. ...

    print("Model Registry configuration complete.")


# --- Lifespan для управления ресурсами приложения ---
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Управляет ресурсами: HTTP клиент, конфигурация реестра."""
    print("WMS Service starting up...")

    # 3. Запускаем lifespan для глобального HTTP клиента
    # Это создаст клиент при старте и закроет при остановке
    async with global_http_client_lifespan():
        print("Global HTTP client managed via lifespan.")

        # 4. Конфигурируем ModelRegistry ПОСЛЕ инициализации зависимостей (если они нужны)
        # В данном случае зависимости для configure_registry не нужны, но если бы были,
        # их нужно было бы инициализировать до вызова configure_registry.
        configure_registry()

        # Опционально: создать таблицы при старте (обычно не для продакшена)
        # await create_db_and_tables()
        # print("Database tables checked/created.")

        # Приложение готово к работе
        yield # <--- Приложение работает здесь

    # --- Код при остановке приложения ---
    print("WMS Service shutting down...")
    # Global HTTP client закрывается автоматически благодаря asynccontextmanager
    # ModelRegistry не требует явного закрытия
    print("WMS Service shut down complete.")


# --- Создание FastAPI приложения ---
app = FastAPI(
    title="WMS Service",
    description="Warehouse Management Service",
    version="0.1.0",
    lifespan=lifespan # 5. Передаем lifespan менеджер в приложение
)

# --- Пример API эндпоинта, использующего DataAccessManager ---
health_router = APIRouter()

@health_router.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "WMS"}

@health_router.get("/test-dam/{user_id}", tags=["Test"])
async def test_dam_access(
    user_id: UUID, # Предполагаем UUID импортирован
    dam: DataAccessManager = Depends(get_data_access_manager) # Используем зависимость
):
    """Тестовый эндпоинт для проверки доступа через DAM."""
    try:
        # Попытка получить пользователя из Core сервиса (удаленный вызов)
        user = await dam.get(CoreUserRead, user_id)
        if user:
            user_info = {"id": user.id, "email": getattr(user, 'email', 'N/A'), "source": "remote (core)"}
        else:
            user_info = {"id": user_id, "status": "not found", "source": "remote (core)"}

        # Попытка получить продукт локально (пример, если есть продукт с ID = user_id)
        # Это просто для демонстрации, ID продукта и пользователя не связаны
        product = await dam.get(Product, user_id)
        if product:
            product_info = {"id": product.id, "name": product.name, "source": "local (wms)"}
        else:
             product_info = {"id": user_id, "status": "not found", "source": "local (wms)"}

        return {"user_check": user_info, "product_check": product_info}

    except Exception as e:
        # Обработка ошибок конфигурации или связи
        return {"error": str(e), "type": type(e).__name__}


# --- Подключение роутеров ---
app.include_router(health_router)
app.include_router(product_router.router) # Подключаем CRUD роутер для продуктов
# ... подключение других роутеров WMS ...