# purchase/app/tests/conftest.py
import asyncio
import os
import sys
import pytest
import pytest_asyncio
import uuid
from typing import AsyncGenerator, Generator, Optional # Добавили Optional

import httpx # <--- ДОБАВИТЬ
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import NullPool

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from purchase.app.config import Settings as AppSettingsClass
from purchase.app.main import app as fastapi_app
from purchase.app import registry_config # Для конфигурации реестра
from purchase.app.models.purchase_order import PurchaseOrder
from purchase.app.schemas.purchase_order_schema import PurchaseOrderCreate

from core_sdk.db.session import (
    init_db as sdk_init_db,
    close_db as sdk_close_db,
    managed_session,
    create_db_and_tables,
    get_session_dependency as sdk_get_session_dependency
)
from core_sdk.registry import ModelRegistry
from core_sdk.data_access import DataAccessManagerFactory
# Для фикстуры core_superuser_token
from core_sdk.security import create_access_token # Понадобится, если будем мокать токен, но лучше логиниться
import secrets # Для генерации SECRET_KEY в .env.test, если его нет

@pytest.fixture(scope='session', autouse=True)
def set_test_environment_var():
    os.environ["ENV"] = "test"
    os.environ["PORT_PURCHASE"] = "9902"
    yield
    if "ENV" in os.environ: del os.environ["ENV"]
    if "PORT_PURCHASE" in os.environ: del os.environ["PORT_PURCHASE"]

@pytest.fixture(scope="session")
def test_settings(set_test_environment_var) -> AppSettingsClass:
    env_test_path = os.path.join(project_root, "purchase", ".env.test")
    if not os.path.exists(env_test_path):
        print(f"Создание .env.test для сервиса Purchase в {env_test_path}")
        with open(env_test_path, "w") as f:
            f.write(f"DATABASE_URL=postgresql+asyncpg://main_user:main_password@db:5432/purchase_test_db\n")
            f.write(f"REDIS_URL=redis://redis:6379/14\n")
            f.write(f"SECRET_KEY={secrets.token_hex(32)}\n")
            f.write(f"ENV=test\n")
            f.write(f"PROJECT_NAME=PurchaseTestService\n")
            f.write(f"PORT_PURCHASE={os.getenv('PORT_PURCHASE', '9902')}\n")
            f.write(f"CORE_SERVICE_URL=http://core:8000\n") # Важно для удаленных тестов
    return AppSettingsClass(_env_file=env_test_path)

@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="session") # Убрал autouse=True, чтобы не конфликтовать с core/conftest.py при совместном запуске
async def manage_service_db_for_tests_purchase(test_settings: AppSettingsClass): # Переименовал для уникальности
    if not test_settings.DATABASE_URL:
        ModelRegistry.clear()
        registry_config.configure_purchase_registry()
        yield
        return

    print(f"\n--- Настройка БД для тестов сервиса: Purchase ---")
    sdk_init_db(str(test_settings.DATABASE_URL), engine_options={"poolclass": NullPool, "echo": False})
    from purchase.app import models as purchase_models # noqa F401
    print(f"Создание таблиц для Purchase в БД: {test_settings.DATABASE_URL}")
    await create_db_and_tables()
    ModelRegistry.clear() # Очищаем перед конфигурацией для изоляции тестов
    registry_config.configure_purchase_registry()
    print(f"ModelRegistry сконфигурирован для Purchase.")
    yield
    print(f"--- Очистка БД после тестов сервиса: Purchase ---")
    await sdk_close_db()

@pytest_asyncio.fixture(scope="function")
async def db_session_purchase(manage_service_db_for_tests_purchase) -> AsyncGenerator[None, None]: # Зависит от переименованной фикстуры
    if not fastapi_app.dependency_overrides.get(sdk_get_session_dependency):
        async def override_get_session_for_request():
            async with managed_session() as session:
                yield session
        fastapi_app.dependency_overrides[sdk_get_session_dependency] = override_get_session_for_request
    async with managed_session() as test_scope_session:
        yield test_scope_session

# Фикстура для HTTP клиента, который будет использоваться DAM для внешних запросов
@pytest_asyncio.fixture(scope="session")
async def external_http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Предоставляет httpx.AsyncClient для тестов, делающих внешние запросы."""
    # Можно настроить таймауты и лимиты, если нужно
    # timeouts = httpx.Timeout(10.0, connect=5.0)
    # limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    # async with httpx.AsyncClient(timeout=timeouts, limits=limits) as client:
    async with httpx.AsyncClient() as client:
        print("External HTTP client created for Purchase tests.")
        yield client
        print("External HTTP client closed for Purchase tests.")

# Фикстура для токена суперпользователя Core сервиса
@pytest_asyncio.fixture(scope="session")
async def core_superuser_token(test_settings: AppSettingsClass, external_http_client: httpx.AsyncClient) -> Optional[str]:
    """
    Логинится в Core сервис и возвращает токен. Возвращает None, если не удалось.
    Эта фикстура предполагает, что Core сервис запущен и доступен,
    и что у него есть стандартный суперпользователь (например, из FIRST_SUPERUSER_EMAIL/PASSWORD).
    """
    if not test_settings.CORE_SERVICE_URL:
        print("CORE_SERVICE_URL not set in purchase test_settings, cannot get core_superuser_token.")
        return None

    # Эти креды должны соответствовать тестовому суперпользователю в Core сервисе
    # Лучше их брать из переменных окружения, специфичных для тестов Core
    core_admin_email = os.getenv("TEST_CORE_ADMIN_EMAIL", "admin@example.com")
    core_admin_password = os.getenv("TEST_CORE_ADMIN_PASSWORD", "changethis")

    login_url = f"{test_settings.CORE_SERVICE_URL}/api/v1/auth/login"
    print(f"Attempting to login to Core service at {login_url} as {core_admin_email} to get token for Purchase tests...")
    try:
        response = await external_http_client.post(login_url, data={"username": core_admin_email, "password": core_admin_password})
        if response.status_code == 200:
            token_data = response.json()
            print("Successfully obtained superuser token from Core service.")
            return token_data["access_token"]
        else:
            print(f"Failed to login to Core service. Status: {response.status_code}, Response: {response.text[:200]}")
            return None
    except httpx.RequestError as e:
        print(f"HTTPX RequestError while trying to login to Core service: {e}")
        return None
    except Exception as e:
        print(f"Unexpected exception while trying to login to Core service: {e}")
        return None

@pytest_asyncio.fixture(scope="function")
async def dam_factory_purchase_test(
    manage_service_db_for_tests_purchase, # Зависимость от БД Purchase
    external_http_client: httpx.AsyncClient, # HTTP клиент для удаленных DAM
    core_superuser_token: Optional[str]      # Токен для Core сервиса
) -> DataAccessManagerFactory:
    """
    Фабрика DAM для тестов сервиса Purchase.
    Конфигурируется с HTTP клиентом и токеном для возможных удаленных вызовов.
    """
    print(f"Creating DAM Factory for Purchase tests. Core token provided: {core_superuser_token is not None}")
    return DataAccessManagerFactory(
        registry=ModelRegistry,
        http_client=external_http_client,
        auth_token=core_superuser_token
    )

@pytest_asyncio.fixture(scope="function")
async def async_client_purchase(test_settings: AppSettingsClass, db_session_purchase) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=fastapi_app) # type: ignore
    async with AsyncClient(transport=transport, base_url=f"http://test_purchase") as client:
        yield client
    fastapi_app.dependency_overrides.clear()

@pytest_asyncio.fixture
async def test_purchase_order_item(dam_factory_purchase_test: DataAccessManagerFactory, db_session_purchase) -> PurchaseOrder:
    test_company_id = uuid.uuid4() # Для PurchaseOrder нужен company_id
    manager = dam_factory_purchase_test.get_manager("PurchaseOrder")
    order_data = PurchaseOrderCreate(
        order_number=f"PO-REM-TEST-{uuid.uuid4().hex[:6]}", # Уникальный номер
        company_id=test_company_id
    )
    item = await manager.create(order_data)
    return item