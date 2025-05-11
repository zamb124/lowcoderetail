# apps/frontend/app/tests/conftest.py
import asyncio
import os
import sys
import pytest
import pytest_asyncio
from typing import AsyncGenerator, Generator, Any, Dict
from httpx import AsyncClient, ASGITransport

# --- Добавляем корень проекта в sys.path ---
# Путь к директории apps/
apps_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# Путь к корню проекта (на уровень выше apps/)
project_root = os.path.dirname(apps_root)
if project_root not in sys.path:
    print(f"Adding project root to sys.path: {project_root}")
    sys.path.insert(0, project_root)
# -------------------------------------------

# --- Импорты после добавления пути ---
from frontend.app.config import (
    FrontendSettings as AppSettingsClass,
)  # Настройки Frontend
from frontend.app.main import app as fastapi_app  # Наше FastAPI приложение
from frontend.app import registry_config  # Для инициализации registry
from core_sdk.registry import ModelRegistry
from core_sdk.data_access import (
    get_global_http_client,
)


# Фикстура для установки тестового окружения
@pytest.fixture(scope="session", autouse=True)
def set_test_environment_var():
    """Устанавливает переменную окружения ENV=test."""
    original_env = os.environ.get("ENV")
    os.environ["ENV"] = "test"
    print("\n--- Set ENV=test for session ---")
    yield
    if original_env is None:
        del os.environ["ENV"]
    else:
        os.environ["ENV"] = original_env
    print("\n--- Restored original ENV ---")


# Фикстура для тестовых настроек
@pytest.fixture(scope="session")
def test_settings(set_test_environment_var) -> AppSettingsClass:
    """Загружает настройки из .env.test."""
    # Используем основной класс настроек, он сам подхватит .env.test благодаря ENV=test
    print("\nLoading test settings for Frontend...")
    try:
        settings = AppSettingsClass()
        # Проверка критичных настроек
        assert settings.ENV == "test", "ENV is not 'test' in test settings!"
        assert settings.SECRET_KEY, "Test SECRET_KEY not loaded."
        assert settings.CORE_SERVICE_URL, "Test CORE_SERVICE_URL not loaded."
        print(
            f"Test settings loaded: PROJECT_NAME={settings.PROJECT_NAME}, CORE_URL={settings.CORE_SERVICE_URL}"
        )
        return settings
    except Exception as e:
        pytest.fail(f"Failed to load test settings for Frontend: {e}")


# Фикстура Event Loop
@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Предоставляет event loop для сессии тестов."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Фикстура жизненного цикла SDK (DB и HTTP клиент)
@pytest_asyncio.fixture(scope="session", autouse=True)
async def manage_sdk_lifecycles(test_settings: AppSettingsClass):
    """Управляет инициализацией/закрытием ресурсов SDK (DB, HTTP)."""
    print("\n--- Initializing SDK resources for Frontend Test Session ---")
    # Инициализация HTTP клиента (важно для Remote DAM)
    async with get_global_http_client(
        manage=True
    ):  # Используем менеджер контекста из SDK
        # Инициализация БД (даже если не используется, SDK может этого ожидать)
        # if test_settings.DATABASE_URL:
        #     sdk_init_db(str(test_settings.DATABASE_URL), engine_options={"poolclass": NullPool})
        # else:
        #     print("Skipping DB init as DATABASE_URL is not set in test settings.")

        # Конфигурируем ModelRegistry (важно сделать после инициализации настроек)
        print("Configuring ModelRegistry for remote access in tests...")
        ModelRegistry.clear()  # Очищаем на всякий случай
        try:
            registry_config.configure_remote_registry()
            assert ModelRegistry.is_configured(), (
                "ModelRegistry failed to configure in tests!"
            )
            print("ModelRegistry configured for tests.")
        except Exception as e:
            pytest.fail(f"Failed to configure ModelRegistry during test setup: {e}")

        yield  # Запускаем тесты

        # Закрытие БД (если инициализировалась)
        # if test_settings.DATABASE_URL:
        #     await sdk_close_db()
    print("\n--- Closed SDK resources after Frontend Test Session ---")


# Фикстура тестового HTTP клиента для Frontend приложения
@pytest_asyncio.fixture(scope="function")
async def async_client_frontend(
    test_settings: AppSettingsClass, manage_sdk_lifecycles
) -> AsyncGenerator[AsyncClient, None]:
    """Создает HTTP клиент для взаимодействия с тестовым приложением Frontend."""
    print("\nCreating test async client for Frontend service...")
    # Используем транспорт ASGI для взаимодействия с приложением напрямую
    transport = ASGITransport(app=fastapi_app)  # type: ignore
    async with AsyncClient(
        transport=transport, base_url="http://testfrontend"
    ) as client:
        yield client
    # Очистка переопределений зависимостей FastAPI (если были)
    fastapi_app.dependency_overrides.clear()
    print("Cleared FastAPI dependency overrides for Frontend.")


# --- Фикстуры для аутентификации (пример) ---
# Эти фикстуры нужно будет адаптировать. Они могут:
# 1. Мокировать вызов Core сервиса для получения токена.
# 2. Использовать реальный Core сервис (если он запущен в тестовом окружении).
# 3. Генерировать тестовый токен с нужными данными напрямую.


# Пример фикстуры с генерацией тестового токена
@pytest.fixture(scope="function")
def test_user_auth_data() -> Dict[str, Any]:
    """Данные для тестового пользователя в токене."""
    from uuid import uuid4

    return {
        "sub": f"test.user.{uuid4()}@example.com",
        "user_id": str(uuid4()),
        "company_id": str(uuid4()),
        "is_active": True,
        "is_superuser": False,
        "perms": ["users:view", "companies:view"],  # Пример прав
    }


@pytest.fixture(scope="function")
def test_superuser_auth_data() -> Dict[str, Any]:
    """Данные для тестового суперпользователя в токене."""
    from uuid import uuid4

    return {
        "sub": f"test.superuser.{uuid4()}@example.com",
        "user_id": str(uuid4()),
        "company_id": str(uuid4()),
        "is_active": True,
        "is_superuser": True,
        "perms": [],  # Суперюзеру права не нужны, is_superuser=True важнее
    }


@pytest.fixture(scope="function")
def auth_headers(
    test_settings: AppSettingsClass, test_user_auth_data: Dict[str, Any]
) -> Dict[str, str]:
    """Генерирует заголовки с тестовым токеном обычного пользователя."""
    from core_sdk.security import create_access_token
    from datetime import timedelta

    token = create_access_token(
        data=test_user_auth_data,
        secret_key=test_settings.SECRET_KEY,
        algorithm=test_settings.ALGORITHM,
        expires_delta=timedelta(minutes=15),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def superuser_auth_headers(
    test_settings: AppSettingsClass, test_superuser_auth_data: Dict[str, Any]
) -> Dict[str, str]:
    """Генерирует заголовки с тестовым токеном суперпользователя."""
    from core_sdk.security import create_access_token
    from datetime import timedelta

    token = create_access_token(
        data=test_superuser_auth_data,
        secret_key=test_settings.SECRET_KEY,
        algorithm=test_settings.ALGORITHM,
        expires_delta=timedelta(minutes=15),
    )
    return {"Authorization": f"Bearer {token}"}
