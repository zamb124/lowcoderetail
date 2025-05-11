# core/app/tests/conftest.py

import asyncio
import os
import sys
import importlib  # Для перезагрузки модулей
from typing import AsyncGenerator, Generator, Dict
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncEngine,
)
from sqlalchemy.pool import NullPool
from alembic.config import Config
from alembic import command
from taskiq import (
    InMemoryBroker,
    AsyncBroker,
)  # Используем AsyncBroker для type hinting


# --- Добавляем корень проекта в sys.path ---
project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if project_root not in sys.path:
    print(f"Adding project root to sys.path: {project_root}")
    sys.path.insert(0, project_root)
# -------------------------------------------

# --- Импорты после добавления пути ---
# Основные настройки и приложение
from apps.core.config import Settings as AppSettingsClass
from apps.core.main import app as fastapi_app

# Модели и конфигурация Registry
from apps.core import models
from core_sdk.registry import ModelRegistry
from apps.core.registry_config import configure_core_registry

# Компоненты SDK для БД и DAM
from core_sdk.db.session import (
    init_db,
    close_db,
    managed_session,
)  # Используем новую зависимость
from core_sdk.data_access import (
    DataAccessManagerFactory,
)

# Конкретные менеджеры для type hinting (опционально, но полезно)
from apps.core.data_access.user_manager import UserDataAccessManager
from apps.core.data_access.company_manager import CompanyDataAccessManager
from core_sdk.data_access import BaseDataAccessManager


# --- Фикстура для установки переменной окружения ---
@pytest.fixture(scope="session", autouse=True)
def set_test_environment():
    """Устанавливает переменную окружения для тестового режима Taskiq и БД."""
    test_env_vars = {
        "Env": "test",
        # Можно добавить другие переменные, специфичные для тестов, если нужно
        # "SOME_OTHER_TEST_SETTING": "value"
    }
    original_values = {}

    print("\n--- Setting Test Environment Variables ---")
    for key, value in test_env_vars.items():
        print(f"Setting {key}={value}")
        original_values[key] = os.environ.get(key)
        os.environ[key] = value

    # --- Перезагрузка модулей, зависящих от env var ---
    # Важно перезагрузить ПОСЛЕ установки переменных
    modules_to_reload = [
        "core_sdk.broker.setup",
        "core_sdk.broker.tasks",  # Перезагружаем, т.к. он импортирует setup.broker
        "core_sdk.db.session",  # Перезагружаем, т.к. init_db может зависеть от env var (хотя сейчас нет)
        "apps.core.config",  # Перезагружаем, чтобы он прочитал .env.test (если он зависит от ENV)
    ]
    for module_name in modules_to_reload:
        try:
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
                print(f"Reloaded {module_name} to apply test mode.")
            else:
                print(f"{module_name} not imported yet, no need to reload.")
        except Exception as e:
            print(f"Warning: Could not reload {module_name}: {e}")
    # --------------------------------------------------

    yield  # Запускаем тесты

    # --- Очистка после тестов ---
    print("\n--- Cleaning Up Test Environment Variables ---")
    for key, original_value in original_values.items():
        print(f"Restoring {key}")
        if original_value is None:
            if key in os.environ:
                del os.environ[key]
        else:
            os.environ[key] = original_value

    # --- Перезагрузка модулей снова, чтобы вернуть обычные настройки ---
    print("--- Restoring Production/Development Environment ---")
    for module_name in modules_to_reload:
        try:
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
                print(f"Reloaded {module_name} to restore original settings.")
            else:
                print(f"{module_name} not imported yet.")
        except Exception as e:
            print(f"Warning: Could not reload {module_name} during cleanup: {e}")
    # --------------------------------------------------------------------


# --- Фикстура для тестовых настроек ---
@pytest.fixture(scope="session")
def test_settings(
    set_test_environment,
) -> AppSettingsClass:  # Зависит от установки env var
    """Загружает настройки из .env.test или переменных окружения."""
    # Путь к .env.test
    env_file_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", ".env.test")
    )
    print(f"\nAttempting to load test settings from: {env_file_path}")

    # Используем основной класс настроек, он должен сам подхватить .env.test
    # благодаря перезагрузке модуля config в set_test_environment
    # или можно явно указать путь здесь, если перезагрузка не сработала
    loaded_settings = None
    try:
        # Создаем экземпляр основного класса настроек
        # Он должен использовать .env.test, если он указан в его model_config
        # или если мы переопределяем env_file здесь
        class TestSettingsConfig(AppSettingsClass):
            model_config = AppSettingsClass.model_config.copy()
            # Указываем .env.test явно на всякий случай
            model_config["env_file"] = env_file_path

        loaded_settings = TestSettingsConfig()
        print(
            f"Test settings loaded successfully: PROJECT_NAME={loaded_settings.PROJECT_NAME}"
        )
        # Проверка критичных настроек
        if not getattr(loaded_settings, "DATABASE_URL", None):
            pytest.fail(f"TEST DATABASE_URL not loaded. Check {env_file_path}.")
        if not getattr(loaded_settings, "REDIS_URL", None):
            pytest.fail(f"TEST REDIS_URL not loaded. Check {env_file_path}.")
        if not getattr(loaded_settings, "SECRET_KEY", None):
            pytest.fail(f"TEST SECRET_KEY not loaded. Check {env_file_path}.")
    except Exception as e:
        pytest.fail(f"Failed to load test settings: {e}")

    return loaded_settings


# --- Фикстура Event Loop ---
@pytest.fixture(scope="session")
def event_loop(request) -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Предоставляет event loop для сессии тестов."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# --- Фикстура тестового движка БД ---
@pytest_asyncio.fixture(scope="session")
async def test_engine(test_settings: AppSettingsClass):
    """Создает асинхронный движок SQLAlchemy для тестовой БД."""
    db_url = str(test_settings.DATABASE_URL)
    print(f"Creating test engine for: {db_url}")
    # Используем NullPool для тестов, чтобы избежать проблем с соединениями между тестами
    engine = create_async_engine(db_url, poolclass=NullPool, future=True, echo=False)
    yield engine
    print("Disposing test engine...")
    await engine.dispose()


# --- Фикстура применения миграций ---
@pytest_asyncio.fixture(scope="session")
async def apply_migrations(test_engine: AsyncEngine, test_settings: AppSettingsClass):
    alembic_cfg_path = os.path.join(project_root, "apps/core/alembic.ini")
    script_location = os.path.join(project_root, "apps/core", "migrations")

    # Check for alembic configuration and migration script location
    if not os.path.exists(alembic_cfg_path):
        pytest.fail(f"Alembic config not found at: {alembic_cfg_path}")
    if not os.path.exists(script_location):
        pytest.fail(f"Alembic script location not found at: {script_location}")

    db_url_to_migrate = str(test_settings.DATABASE_URL)
    print(
        f"\nApplying migrations from {script_location} using {alembic_cfg_path} to {db_url_to_migrate}..."
    )

    # Set up alembic configuration
    alembic_cfg = Config(alembic_cfg_path)
    alembic_cfg.set_main_option("sqlalchemy.url", db_url_to_migrate)
    alembic_cfg.set_main_option("script_location", script_location)

    async with test_engine.begin() as conn:
        print("Dropping and recreating public schema...")
        try:
            # Drop and recreate public schema with necessary extensions
            await conn.execute(text("DROP SCHEMA public CASCADE;"))
            await conn.execute(text("CREATE SCHEMA public;"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto;"))
            print("Public schema dropped and recreated.")
        except Exception as e:
            pytest.fail(f"Failed to reset schema: {e}")

    print("Upgrading DB to head...")
    try:
        # Upgrade the database schema using Alembic
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, command.upgrade, alembic_cfg, "head")
        print("Migrations applied successfully.")
    except Exception as e:
        pytest.fail(f"Alembic upgrade failed: {e}")

    yield


# --- Фикстура конфигурации Registry ---
@pytest.fixture(scope="session", autouse=True)
def configure_test_model_registry(apply_migrations):  # Зависит от миграций
    """Конфигурирует ModelRegistry один раз за сессию."""
    print("\nConfiguring ModelRegistry for test session...")
    if not ModelRegistry.is_configured():
        try:
            configure_core_registry()  # Функция из вашего приложения
            print("ModelRegistry configured for tests.")
            assert ModelRegistry.is_configured(), "ModelRegistry failed to configure!"
        except Exception as e:
            pytest.fail(f"Failed to configure ModelRegistry during test setup: {e}")
    else:
        print("ModelRegistry already configured for test session.")


# --- Фикстура инициализации/закрытия БД SDK ---
@pytest_asyncio.fixture(scope="session", autouse=True)
async def manage_sdk_db_lifecycle(
    test_engine: AsyncEngine, apply_migrations, test_settings
):  # Зависит от engine и миграций
    """Инициализирует БД SDK с тестовым engine перед тестами и закрывает после."""
    print("\n--- Initializing SDK Database for Test Session ---")
    # Инициализируем глобальные переменные SDK тестовым движком
    # Передаем URL из engine
    db_url = str(test_settings.DATABASE_URL)
    init_db(db_url, engine_options={"poolclass": NullPool})
    yield
    print("\n--- Closing SDK Database after Test Session ---")
    await close_db()


# --- Фикстура ФАБРИКИ DataAccessManager (без сессии) ---
@pytest_asyncio.fixture(scope="function")
async def dam_factory_test() -> DataAccessManagerFactory:
    """Предоставляет экземпляр ФАБРИКИ DataAccessManager для тестов."""
    # print("Creating test DataAccessManagerFactory instance...")
    factory = DataAccessManagerFactory(
        registry=ModelRegistry,
        http_client=None,  # Замените на тестовый httpx клиент, если нужен для каких-то DAM
        auth_token=None,
    )
    return factory


# --- Фикстура тестового клиента HTTP (async_client) ---
@pytest_asyncio.fixture(scope="function")
async def async_client(
    test_settings: AppSettingsClass,
    manage_sdk_db_lifecycle,  # Зависимость от инициализации БД SDK
) -> AsyncGenerator[AsyncClient, None]:
    """Создает HTTP клиент для взаимодействия с тестовым приложением FastAPI."""

    # --- УДАЛЯЕМ переопределение get_session_dependency ---
    # fastapi_app.dependency_overrides[get_session_dependency] = ...
    # ----------------------------------------------------

    # --- Переопределение get_dam_factory (ОПЦИОНАЛЬНО, если нужно для http/token) ---
    # ...

    print("Creating test async client...")
    transport = ASGITransport(app=fastapi_app)  # type: ignore
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        # Очищаем переопределения после теста
        print("Clearing dependency overrides...")
        fastapi_app.dependency_overrides.clear()  # Очищаем все для простоты


# --- Фикстуры создания данных через DAM и managed_session ---
@pytest_asyncio.fixture(scope="function")
async def test_company(
    dam_factory_test: DataAccessManagerFactory,
) -> models.company.Company:
    """Создает тестовую компанию в БД, используя DAM внутри managed_session."""
    company_name = f"Test Company {uuid4()}"
    print(f"Creating test company: {company_name}")
    company_data_dict = {
        "name": company_name,
        "description": "A company created for testing purposes via DAM.",
        "is_active": True,
    }
    async with managed_session():  # Управляем сессией здесь
        try:
            company_manager: CompanyDataAccessManager = dam_factory_test.get_manager(
                "Company"
            )
            # Метод create сам получит сессию через get_current_session() и сделает commit
            db_company = await company_manager.create(company_data_dict)
            print(f"Test company created via DAM with ID: {db_company.id}")
            # Возвращаем объект; сессия закроется/откатится после выхода из 'with'
            return db_company
        except Exception as e:
            pytest.fail(f"Failed to create test company via DAM Factory: {e}")


@pytest.fixture(scope="function")
def superuser_email() -> str:
    """Генерирует уникальный email для суперпользователя."""
    return f"test_superuser_{uuid4()}@example.com"


@pytest.fixture(scope="session")
def superuser_password() -> str:
    """Стандартный пароль для тестового суперпользователя."""
    return "testpassword"


@pytest_asyncio.fixture(scope="function")
async def test_superuser(
    dam_factory_test: DataAccessManagerFactory,
    test_company: models.company.Company,  # Зависимость от созданной компании
    superuser_email: str,
    superuser_password: str,
) -> models.user.User:
    """Создает тестового суперпользователя через DAM внутри managed_session."""
    print(f"Creating test superuser: {superuser_email}")
    user_data_dict = {
        "email": superuser_email,
        "password": superuser_password,
        "company_id": test_company.id,
        "is_active": True,
        "is_superuser": True,
        "first_name": "Test",
        "last_name": "Superuser",
    }
    async with managed_session():
        try:
            user_manager: UserDataAccessManager = dam_factory_test.get_manager("User")
            db_user = await user_manager.create(user_data_dict)
            print(f"Test superuser created via DAM with ID: {db_user.id}")
            # Добавляем пароль для использования в тестах логина
            db_user._test_password = superuser_password  # type: ignore
            return db_user
        except Exception as e:
            pytest.fail(f"Failed to create test superuser via DAM Factory: {e}")


@pytest.fixture(scope="function")
def normal_user_email() -> str:
    """Генерирует уникальный email для обычного пользователя."""
    return f"test_normal_user_{uuid4()}@example.com"


@pytest.fixture(scope="session")
def normal_user_password() -> str:
    """Стандартный пароль для тестового обычного пользователя."""
    return "testpassword"


# --- Фикстуры токенов (используют async_client) ---
@pytest_asyncio.fixture(scope="function")
async def superuser_token_headers(
    async_client: AsyncClient,
    test_superuser: models.user.User,  # Зависит от созданного суперюзера
    superuser_email: str,
    superuser_password: str,
    test_settings: AppSettingsClass,
) -> Dict[str, str]:
    """Получает токен для тестового суперпользователя."""
    print(f"Logging in superuser: {superuser_email}")
    login_data = {"username": superuser_email, "password": superuser_password}
    login_url = f"{test_settings.API_V1_STR}/auth/login"
    try:
        response = await async_client.post(login_url, data=login_data)
        response.raise_for_status()  # Проверка на ошибки HTTP
        tokens = response.json()
        a_token = tokens["access_token"]
        headers = {"Authorization": f"Bearer {a_token}"}
        print("Superuser logged in successfully.")
        return headers
    except Exception as e:
        pytest.fail(
            f"Could not log in superuser '{superuser_email}'. Error: {e}, Response: {getattr(response, 'text', 'N/A')}"
        )


@pytest_asyncio.fixture(scope="function")
async def normal_user_token_headers(
    async_client: AsyncClient,
    test_user: models.user.User,  # Зависит от созданного обычного юзера
    normal_user_email: str,
    normal_user_password: str,  # Используем пароль из фикстуры
    test_settings: AppSettingsClass,
) -> Dict[str, str]:
    """Получает токен для тестового обычного пользователя."""
    print(f"Logging in normal user: {normal_user_email}")
    # Используем пароль из фикстуры, а не сохраненный в _test_password
    login_data = {"username": normal_user_email, "password": normal_user_password}
    login_url = f"{test_settings.API_V1_STR}/auth/login"
    try:
        response = await async_client.post(login_url, data=login_data)
        response.raise_for_status()
        tokens = response.json()
        a_token = tokens["access_token"]
        headers = {"Authorization": f"Bearer {a_token}"}
        print("Normal user logged in successfully.")
        return headers
    except Exception as e:
        pytest.fail(
            f"Could not log in normal user '{normal_user_email}'. Error: {e}, Response: {getattr(response, 'text', 'N/A')}"
        )


# --- Фикстура для тестового брокера Taskiq ---
@pytest.fixture(scope="session")
def test_taskiq_broker(
    set_test_environment,
) -> AsyncBroker:  # Зависит от установки env var
    """
    Импортирует и возвращает экземпляр брокера, созданный в setup.py.
    В тестовом режиме это должен быть InMemoryBroker.
    """
    print("\nGetting broker instance for tests...")
    # Импортируем брокер ПОСЛЕ установки переменной окружения
    from core_sdk.broker.setup import broker

    print(f"Imported broker type in test_taskiq_broker fixture: {type(broker)}")
    # Проверяем, что это действительно InMemoryBroker
    assert isinstance(broker, InMemoryBroker), (
        f"Expected InMemoryBroker in test mode, but got {type(broker)}. Check  env var and setup.py."
    )
    return broker


@pytest_asyncio.fixture(scope="function")
async def test_group(
    dam_factory_test: DataAccessManagerFactory,
    test_company: models.company.Company,  # Группа должна принадлежать компании
) -> models.group.Group:
    """Создает тестовую группу в БД, используя DAM внутри managed_session."""
    group_name = f"Test Group {uuid4()}"
    print(f"Creating test group: {group_name}")
    group_data_dict = {
        "name": group_name,
        "description": "A group created for testing purposes via DAM.",
        "company_id": test_company.id,  # Привязываем к тестовой компании
        "permissions": ["me", "assign_user_to_group"],  # Права по умолчанию пустые
        # Поле permissions (список строк) по умолчанию будет пустым
    }
    async with managed_session():
        try:
            # Используем BaseDataAccessManager, т.к. для Group нет кастомного
            group_manager: BaseDataAccessManager = dam_factory_test.get_manager("Group")
            db_group = await group_manager.create(group_data_dict)
            print(f"Test group created via DAM with ID: {db_group.id}")
            return db_group
        except Exception as e:
            pytest.fail(f"Failed to create test group via DAM Factory: {e}")


@pytest_asyncio.fixture(scope="function")
async def test_user(
    dam_factory_test: DataAccessManagerFactory,
    test_company: models.company.Company,
    test_group: models.group.Group,  # <--- Добавляем зависимость от тестовой группы
    normal_user_email: str,
    normal_user_password: str,
) -> models.user.User:
    """
    Создает обычного тестового пользователя и назначает его в тестовую группу.
    """
    print(f"Creating test normal user: {normal_user_email}")
    user_data_dict = {
        "email": normal_user_email,
        "password": normal_user_password,
        "company_id": test_company.id,
        "is_active": True,
        "is_superuser": False,
    }
    async with managed_session():  # Управляем сессией здесь
        try:
            user_manager: UserDataAccessManager = dam_factory_test.get_manager("User")
            # Шаг 1: Создаем пользователя
            db_user = await user_manager.create(user_data_dict)
            print(f"Test normal user created via DAM with ID: {db_user.id}")
            db_user._test_password = normal_user_password  # type: ignore

            # Шаг 2: Назначаем пользователя в тестовую группу
            # Используем новый метод assign_to_group из UserDataAccessManager
            # Этот метод сам обработает коммит и refresh для пользователя
            print(f"Assigning user {db_user.id} to group {test_group.id}...")
            # Важно: assign_to_group возвращает обновленного пользователя,
            # но мы уже имеем db_user в текущей сессии.
            # Если assign_to_group делает commit, то db_user уже будет обновлен
            # (или его нужно будет обновить через refresh, если assign_to_group не делает этого).
            # Метод assign_to_group в UserDataAccessManager уже делает commit и refresh.
            await user_manager.assign_to_group(
                user_id=db_user.id, group_id=test_group.id
            )

            # Перезагружаем пользователя, чтобы убедиться, что связь с группой установлена
            # Это может быть избыточно, если assign_to_group уже делает refresh.
            await user_manager.session.refresh(db_user, attribute_names=["groups"])
            print(
                f"User {db_user.id} assigned to group. Groups: {[g.name for g in db_user.groups]}"
            )

            return db_user
        except Exception as e:
            pytest.fail(f"Failed to create test normal user or assign to group: {e}")
