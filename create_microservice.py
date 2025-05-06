# create_microservice.py
import os
import shutil
import re
import secrets
from pathlib import Path

def to_snake_case(name):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def to_pascal_case(name):
    return ''.join(word.capitalize() for word in name.split('_'))

def generate_secret_key_value():
    return secrets.token_hex(32)

def create_new_service(service_name_pascal: str, target_dir_name: str = None):
    service_name_snake = to_snake_case(service_name_pascal)
    if not target_dir_name:
        target_dir_name = service_name_snake

    source_dir = Path("core")
    target_dir = Path(target_dir_name)

    if not source_dir.is_dir():
        print(f"Ошибка: Директория-источник '{source_dir}' не найдена. Запустите скрипт из корня проекта.")
        return

    if target_dir.exists():
        print(f"Ошибка: Директория назначения '{target_dir}' уже существует.")
        return

    print(f"Создание нового сервиса '{service_name_pascal}' в директории '{target_dir_name}'...")

    try:
        shutil.copytree(source_dir, target_dir, ignore=shutil.ignore_patterns(
            '__pycache__', '*.pyc', '.pytest_cache', 'alembic/versions/*', '*.egg-info' # Добавлено *.egg-info
        ))
        print(f"Скопировано '{source_dir}' -> '{target_dir}'")
    except Exception as e:
        print(f"Ошибка при копировании директории: {e}")
        return

    (target_dir / "alembic" / "versions").mkdir(parents=True, exist_ok=True)
    (target_dir / "alembic" / "versions" / ".gitkeep").touch()

    replacements = {
        "CoreService": service_name_pascal,
        "core-service": service_name_snake.replace("_", "-"),
        "core.app": f"{service_name_snake}.app",
        "core_sdk": "core_sdk",
        "Core specific": f"{service_name_pascal} specific",
        "Core service": f"{service_name_pascal} service",
        "app.registry_config": f"{service_name_snake}.app.registry_config",
        "from core.app.models import BaseModelWithMeta": f"from {service_name_snake}.app.models.some_model import SomeModel # Пример\nfrom core_sdk.db import BaseModelWithMeta",
        "target_metadata = BaseModelWithMeta.metadata": f"target_metadata = SomeModel.metadata # Пример, используйте metadata ваших моделей",
    }
    secret_key_for_config_val = generate_secret_key_value() # Переименовал, чтобы было ясно, что это значение

    some_model_py_content = f"""# {service_name_snake}/app/models/some_model.py
import logging
import uuid
from typing import Optional
from sqlmodel import Field
from core_sdk.db import BaseModelWithMeta
from core_sdk.filters.base import DefaultFilter

logger = logging.getLogger("app.models.some_model")

class SomeModel(BaseModelWithMeta, table=True):
    __tablename__ = "{service_name_snake}_some_models"

    name: str = Field(index=True, description="Название экземпляра SomeModel")
    description: Optional[str] = Field(default=None, description="Описание")
    value: Optional[int] = Field(default=None, description="Какое-то числовое значение")
    # company_id уже есть в BaseModelWithMeta

class SomeModelFilter(DefaultFilter):
    name: Optional[str] = Field(default=None, description="Фильтр по точному имени")
    name__like: Optional[str] = Field(default=None, description="Фильтр по части имени")
    value__gt: Optional[int] = Field(default=None, description="Фильтр по значению > X")

    class Constants(DefaultFilter.Constants):
        model = SomeModel
        search_model_fields = ["name", "description"]
logger.debug("SomeModel and SomeModelFilter defined.")
"""
    some_model_schema_py_content = f"""# {service_name_snake}/app/schemas/some_model_schema.py
import logging
import uuid
from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime # Добавил для created_at, updated_at

logger = logging.getLogger("app.schemas.some_model_schema")

class SomeModelBase(SQLModel):
    name: str = Field(description="Название экземпляра SomeModel")
    description: Optional[str] = Field(default=None, description="Описание")
    value: Optional[int] = Field(default=None, description="Какое-то числовое значение")
    company_id: uuid.UUID

class SomeModelCreate(SomeModelBase):
    pass

class SomeModelUpdate(SQLModel):
    name: Optional[str] = Field(default=None, description="Новое название")
    description: Optional[str] = Field(default=None, description="Новое описание")
    value: Optional[int] = Field(default=None, description="Новое значение")
    company_id: Optional[uuid.UUID] = Field(default=None, description="Новый ID компании")

class SomeModelRead(SomeModelBase):
    id: uuid.UUID
    lsn: int
    created_at: Optional[datetime] # Используем datetime
    updated_at: Optional[datetime]
logger.debug("SomeModel schemas defined.")
"""
    some_model_manager_py_content = f"""# {service_name_snake}/app/data_access/some_model_manager.py
import logging
from core_sdk.data_access import BaseDataAccessManager
from ..models.some_model import SomeModel
from ..schemas.some_model_schema import SomeModelCreate, SomeModelUpdate

logger = logging.getLogger("app.data_access.some_model_manager")

class SomeModelManager(BaseDataAccessManager[SomeModel, SomeModelCreate, SomeModelUpdate]):
    model = SomeModel
    create_schema = SomeModelCreate
    update_schema = SomeModelUpdate
    pass
logger.debug("SomeModelManager defined.")
"""
    some_model_api_py_content = f"""# {service_name_snake}/app/api/endpoints/some_model_api.py
import logging
from fastapi import Depends
from core_sdk.crud.factory import CRUDRouterFactory
from core_sdk.dependencies.auth import get_current_user

logger = logging.getLogger("app.api.endpoints.some_model_api")

some_model_router_factory = CRUDRouterFactory(
    model_name="SomeModel",
    prefix="/some-models",
    tags=["SomeModels"],
    get_deps=[Depends(get_current_user)], list_deps=[Depends(get_current_user)],
    create_deps=[Depends(get_current_user)], update_deps=[Depends(get_current_user)],
    delete_deps=[Depends(get_current_user)],
)
logger.debug("CRUDRouterFactory for SomeModel initialized.")
"""

    files_to_clear_or_simplify = {
        "app/registry_config.py": f"""# {service_name_snake}/app/registry_config.py
import logging
from core_sdk.registry import ModelRegistry
from core_sdk.data_access import BaseDataAccessManager
from .models.some_model import SomeModel, SomeModelFilter
from .schemas.some_model_schema import SomeModelCreate, SomeModelUpdate, SomeModelRead
from .data_access.some_model_manager import SomeModelManager

logger = logging.getLogger("app.registry_config")

def configure_{service_name_snake}_registry():
    # Очищаем реестр перед конфигурацией, если это необходимо для изолированных тестов сервисов
    # ModelRegistry.clear() # Раскомментируйте, если нужно

    # Проверяем, не был ли уже этот конкретный сервис сконфигурирован
    # (полезно, если configure_..._registry() может вызываться несколько раз)
    try:
        if ModelRegistry.is_configured() and ModelRegistry.get_model_info("SomeModel"):
            logger.warning("Model 'SomeModel' already registered. Skipping configuration for {service_name_pascal}.")
            return
    except Exception: # Если get_model_info падает, значит не настроено
        pass


    logger.info("Configuring ModelRegistry for {service_name_pascal} service...")
    ModelRegistry.register_local(
        model_cls=SomeModel, manager_cls=SomeModelManager, filter_cls=SomeModelFilter,
        create_schema_cls=SomeModelCreate, update_schema_cls=SomeModelUpdate,
        read_schema_cls=SomeModelRead, model_name="SomeModel"
    )
    logger.info("ModelRegistry configuration complete for {service_name_pascal} service.")

configure_{service_name_snake}_registry()
""",
        "app/main.py": f"""# {service_name_snake}/app/main.py
import logging
import os
from core_sdk.app_setup import create_app_with_sdk_setup
from .config import settings
from . import registry_config # noqa: F401
from .api.endpoints.some_model_api import some_model_router_factory

logging.basicConfig(level=settings.LOGGING_LEVEL.upper())
logger = logging.getLogger("app.main")
logger.info("--- Starting {service_name_pascal} Service Application Setup ---")
api_routers_to_include = [some_model_router_factory.router]
app = create_app_with_sdk_setup(
    settings=settings, api_routers=api_routers_to_include, enable_auth_middleware=True,
    title=settings.PROJECT_NAME, description="{service_name_pascal} service with SomeModel.", version="0.1.0",
)
logger.info("--- {service_name_pascal} Service Application Setup Complete ---")
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    default_port = "8001"
    port_env_var = f"PORT_{service_name_snake.upper()}"
    port = int(os.getenv(port_env_var, default_port))
    log_level = settings.LOGGING_LEVEL.lower()
    workers = int(os.getenv("WEB_CONCURRENCY", "1"))
    logger.info("Starting Uvicorn for %s on %s:%s with %s worker(s)...", "{service_name_pascal}", host, port, workers)
    uvicorn.run( "{service_name_snake}.app.main:app", host=host, port=port, log_level=log_level, reload=True, workers=workers)
""",
        "app/worker.py": f"""# {service_name_snake}/app/worker.py
import logging, os
log_level_str = os.getenv("LOGGING_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level_str)
logger = logging.getLogger("app.worker")
from core_sdk.worker_setup import initialize_worker_context, shutdown_worker_context
from core_sdk.broker.setup import broker
from .config import settings
async def startup():
    logger.info("Worker starting up...")
    await initialize_worker_context(settings=settings, registry_config_module="{service_name_snake}.app.registry_config", rebuild_models=True)
    logger.info("Worker context initialized.")
async def shutdown():
    logger.info("Worker shutting down...")
    await shutdown_worker_context()
    logger.info("Worker context shut down.")
if __name__ == "__main__":
    logger.warning("This script is intended to be used with Taskiq CLI.")
    logger.warning(f"Example: taskiq worker {service_name_snake}.app.worker:broker --reload --fs-discover --on-startup {service_name_snake}.app.worker:startup --on-shutdown {service_name_snake}.app.worker:shutdown")
""",
        "app/config.py": f"""# {service_name_snake}/app/config.py
import os, logging
from typing import List, Optional, Union
from core_sdk.config import BaseAppSettings, SettingsConfigDict
from pydantic import PostgresDsn, RedisDsn, Field, field_validator
logger = logging.getLogger("app.config")
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CONFIG_DIR, '..'))
ENV_FILE_PATH = os.path.join(PROJECT_ROOT, '.env')
ENV_TEST_FILE_PATH = os.path.join(PROJECT_ROOT, '.env.test')
_CURRENT_ENV_VAR_LOCAL = os.getenv('ENV', 'prod').lower()
_EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL = ENV_TEST_FILE_PATH if _CURRENT_ENV_VAR_LOCAL == 'test' else ENV_FILE_PATH
logger.info("Current environment (ENV): %s for %s", _CURRENT_ENV_VAR_LOCAL, "{service_name_pascal}")
logger.info("Effective .env file path for %s: %s", "{service_name_pascal}", _EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL)
class Settings(BaseAppSettings):
    PROJECT_NAME: str = "{service_name_pascal}Service"
    DATABASE_URL: PostgresDsn = Field(..., description="URL для PostgreSQL.")
    REDIS_URL: Optional[RedisDsn] = Field(None, description="URL для Redis.")
    SECRET_KEY: str = Field("{secret_key_for_config_val}", description="Секретный ключ сервиса.")
    CORE_SERVICE_URL: Optional[str] = Field(None, description="URL к Core сервису.")
    ENV: str = Field(_CURRENT_ENV_VAR_LOCAL, description="Текущее окружение.")
    API_V1_STR: str = "/api/v1"
    PORT_{service_name_snake.upper()}: int = Field(8001, description="Порт для сервиса")
    model_config = SettingsConfigDict(env_file=_EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL, env_file_encoding='utf-8', case_sensitive=True, extra='ignore')
    @field_validator('BACKEND_CORS_ORIGINS', mode='before')
    @classmethod
    def assemble_cors_origins(cls, v: Optional[Union[str, List[str]]]) -> List[str]:
        if isinstance(v, str) and v: return [o.strip() for o in v.split(',') if o.strip()]
        if isinstance(v, list): return [str(o).strip() for o in v if str(o).strip()]
        return []
try:
    settings = Settings()
    logger.info("Settings loaded for %s (ENV='%s').", settings.PROJECT_NAME, settings.ENV)
except Exception as e:
    logger.critical("Failed to load settings for %s from '%s'.", "{service_name_pascal}", _EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL, exc_info=True)
    raise RuntimeError(f"Could not load {{service_name_pascal}} settings: {{e}}") from e
if not os.path.exists(_EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL):
    logger.warning(".env file for %s not found at %s.", "{service_name_pascal}", _EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL)
""",
        "app/models/__init__.py": f"# {service_name_snake}/app/models/__init__.py\nfrom .some_model import SomeModel, SomeModelFilter\nfrom core_sdk.db.base_model import BaseModelWithMeta\n",
        "app/schemas/__init__.py": f"# {service_name_snake}/app/schemas/__init__.py\nfrom .some_model_schema import SomeModelRead, SomeModelCreate, SomeModelUpdate, SomeModelBase\n",
        "app/api/endpoints/__init__.py": f"# {service_name_snake}/app/api/endpoints/__init__.py\nfrom . import some_model_api\n",
        "app/data_access/__init__.py": f"# {service_name_snake}/app/data_access/__init__.py\nfrom .some_model_manager import SomeModelManager\n",
        "alembic.ini": None, "alembic/env.py": None, "Dockerfile": None, ".env_example": None,
        "pyproject.toml": None, ".env": None,
    }

    files_to_delete_patterns = [
        "app/tests/api/*.py", "app/tests/conftest.py",
        "app/models/*.py", "app/schemas/*.py",
        "app/api/endpoints/*.py", "app/data_access/*.py",
        "app/models/__init__.py", "app/schemas/__init__.py",
        "app/api/endpoints/__init__.py", "app/data_access/__init__.py",
        "app/services/i18n_service.py", "app/permissions.py", "app/init_data.py",
    ]
    for pattern in files_to_delete_patterns:
        for fp in target_dir.glob(pattern):
            if fp.is_file():
                try:
                    fp.unlink()
                    print(f"Удален файл: {fp}")
                except Exception as e:
                    print(f"Ошибка удаления {fp}: {e}")

    new_dirs_to_create = [
        "app/models", "app/schemas", "app/data_access",
        "app/api/endpoints", "app/tests/api"
    ]
    for dir_rel_path in new_dirs_to_create:
        (target_dir / dir_rel_path).mkdir(parents=True, exist_ok=True)

    new_files_content = {
        f"app/models/some_model.py": some_model_py_content,
        f"app/schemas/some_model_schema.py": some_model_schema_py_content,
        f"app/data_access/some_model_manager.py": some_model_manager_py_content,
        f"app/api/endpoints/some_model_api.py": some_model_api_py_content,
    }
    for rel_path, content_template in new_files_content.items():
        file_path = target_dir / rel_path
        try:
            with open(file_path, "w", encoding="utf-8") as f: f.write(content_template)
            print(f"Создан файл: {file_path}")
        except Exception as e: print(f"Ошибка создания файла {file_path}: {e}")

    for root_str, _, files_in_dir in os.walk(target_dir):
        root_path = Path(root_str)
        for name in files_in_dir:
            file_path = root_path / name
            relative_path_str = str(file_path.relative_to(target_dir))
            if "alembic/versions" in relative_path_str and relative_path_str.endswith(".py"): continue
            if relative_path_str in new_files_content: continue # Уже создали

            if relative_path_str in files_to_clear_or_simplify and files_to_clear_or_simplify[relative_path_str] is not None:
                current_template_vars = {
                    "service_name_pascal": service_name_pascal,
                    "service_name_snake": service_name_snake,
                    "secret_key_for_config_val": secret_key_for_config_val,
                }
                try:
                    content = files_to_clear_or_simplify[relative_path_str].format(**current_template_vars)
                    with open(file_path, "w", encoding="utf-8") as f: f.write(content)
                    print(f"Обновлен (специально): {file_path}")
                except KeyError as ke: print(f"Ошибка форматирования {file_path}: Отсутствует ключ {ke}. Доступные: {list(current_template_vars.keys())}")
                except Exception as e: print(f"Ошибка записи специального контента в {file_path}: {e}")
                continue
            if relative_path_str in files_to_clear_or_simplify and files_to_clear_or_simplify[relative_path_str] is None: continue

            try:
                with open(file_path, "r", encoding="utf-8") as f: content = f.read()
            except Exception: continue
            modified = False
            for old, new in replacements.items():
                if old in content: content = content.replace(old, new); modified = True
            if modified:
                try:
                    with open(file_path, "w", encoding="utf-8") as f: f.write(content)
                    print(f"Обновлен (замены): {file_path}")
                except Exception as e: print(f"Ошибка записи в {file_path} после замен: {e}")

    alembic_ini_path = target_dir / "alembic.ini"
    if alembic_ini_path.exists():
        try:
            with open(alembic_ini_path, "r", encoding="utf-8") as f: content = f.read()
            content = content.replace("sqlalchemy.url = postgresql+asyncpg://user:password@host:port/db", f"# sqlalchemy.url = postgresql+asyncpg://user:password@host:port/db\n# Замените на DATABASE_URL из .env для {service_name_pascal}")
            content = content.replace("script_location = alembic", f"script_location = %(here)s/alembic")
            content = content.replace(f"script_location = {target_dir_name}/alembic", f"script_location = %(here)s/alembic")
            content = content.replace("# file_template = %%(rev)s_%%(slug)s", "file_template = %%(year)d_%%(month).2d_%%(day).2d_%%(hour).2d%%(minute).2d-%%(rev)s_%%(slug)s")
            with open(alembic_ini_path, "w", encoding="utf-8") as f: f.write(content)
            print(f"Обновлен alembic.ini: {alembic_ini_path}")
        except Exception as e: print(f"Ошибка обновления alembic.ini: {e}")

    dockerfile_content = f"""
FROM python:3.12-slim as builder
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
WORKDIR /app
RUN pip install poetry==1.7.1
COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.create false && poetry install --no-dev --no-interaction --no-ansi
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY ./{target_dir_name}/app ./app
COPY ./core_sdk ./core_sdk
EXPOSE 8001
CMD ["uvicorn", "{service_name_snake}.app.main:app", "--host", "0.0.0.0", "--port", "8001"]
"""
    try:
        with open(target_dir / "Dockerfile", "w", encoding="utf-8") as f: f.write(dockerfile_content.strip())
        print(f"Создан Dockerfile: {target_dir / 'Dockerfile'}")
    except Exception as e: print(f"Ошибка создания Dockerfile: {e}")

    default_port_for_service = "8001"
    env_example_content = f"""
ENV=dev
PROJECT_NAME={service_name_pascal}Service
LOGGING_LEVEL=INFO
DATABASE_URL=postgresql+asyncpg://main_user:main_password@db:5432/{service_name_snake}_db
REDIS_URL=redis://redis:6379/1
SECRET_KEY={generate_secret_key_value()}
CORE_SERVICE_URL=http://core:8000
PORT_{service_name_snake.upper()}={default_port_for_service}
"""
    try:
        with open(target_dir / ".env_example", "w", encoding="utf-8") as f: f.write(env_example_content.strip())
        print(f"Создан .env_example: {target_dir / '.env_example'}")
        shutil.copyfile(target_dir / ".env_example", target_dir / ".env")
        print(f"Создан .env из .env_example: {target_dir / '.env'}")
    except Exception as e: print(f"Ошибка создания .env_example: {e}")

    conftest_content = f"""# {service_name_snake}/app/tests/conftest.py
import asyncio, os, sys, pytest, pytest_asyncio, uuid # Добавлен uuid
from typing import AsyncGenerator, Generator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import NullPool
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path: sys.path.insert(0, project_root)
from {service_name_snake}.app.config import Settings as AppSettingsClass
from {service_name_snake}.app.main import app as fastapi_app
from {service_name_snake}.app import registry_config
from {service_name_snake}.app.models.some_model import SomeModel # Для фикстуры
from {service_name_snake}.app.schemas.some_model_schema import SomeModelCreate # Для фикстуры
from core_sdk.db.session import init_db as sdk_init_db, close_db as sdk_close_db, managed_session, create_db_and_tables, get_current_session # Добавлен get_current_session
from core_sdk.registry import ModelRegistry
from core_sdk.data_access import DataAccessManagerFactory
from core_sdk.db.session import get_session_dependency as sdk_get_session_dependency # Импортируем зависимость сессии из SDK

@pytest.fixture(scope='session', autouse=True)
def set_test_environment_var():
    os.environ["ENV"] = "test"
    os.environ["PORT_{service_name_snake.upper()}"] = "9901" # Пример порта для тестов
    yield
    del os.environ["ENV"]
    if "PORT_{service_name_snake.upper()}" in os.environ: del os.environ["PORT_{service_name_snake.upper()}"]

@pytest.fixture(scope="session")
def test_settings(set_test_environment_var) -> AppSettingsClass:
    env_test_path = os.path.join(project_root, "{target_dir_name}", ".env.test")
    if not os.path.exists(env_test_path):
        with open(env_test_path, "w") as f:
            f.write(f"DATABASE_URL=postgresql+asyncpg://main_user:main_password@db:5432/{service_name_snake}_test_db\\n")
            f.write(f"REDIS_URL=redis://redis:6379/15\\nSECRET_KEY={generate_secret_key_value()}\\nENV=test\\n")
            f.write(f"PROJECT_NAME={service_name_pascal}TestService\\nPORT_{service_name_snake.upper()}={os.getenv(f'PORT_{service_name_snake.upper()}', '9901')}\\n")
    return AppSettingsClass(_env_file=env_test_path)

@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.get_event_loop_policy().new_event_loop(); yield loop; loop.close()

@pytest_asyncio.fixture(scope="session", autouse=True)
async def manage_service_db_for_tests(test_settings: AppSettingsClass):
    if not test_settings.DATABASE_URL: yield; return
    sdk_init_db(str(test_settings.DATABASE_URL), engine_options={{"poolclass": NullPool, "echo": False}})
    # Импортируем модели ДО создания таблиц, чтобы SQLModel.metadata был заполнен
    from {service_name_snake}.app import models # noqa F401
    await create_db_and_tables()
    ModelRegistry.clear()
    registry_config.configure_{service_name_snake}_registry()
    yield
    await sdk_close_db()

@pytest_asyncio.fixture(scope="function")
async def db_session(manage_service_db_for_tests) -> AsyncGenerator[Any, None]: # AsyncSession тип не определен здесь
    if not fastapi_app.dependency_overrides.get(sdk_get_session_dependency): # Проверяем, не переопределена ли уже зависимость
        async def override_get_session_for_request():
            # print("DEBUG: override_get_session_for_request called")
            async with managed_session() as session:
                # print(f"DEBUG: yielding session {{id(session)}} from override_get_session_for_request")
                yield session
        fastapi_app.dependency_overrides[sdk_get_session_dependency] = override_get_session_for_request

    # Эта сессия для использования напрямую в тестах, если нужно
    async with managed_session() as test_scope_session:
        yield test_scope_session


@pytest_asyncio.fixture(scope="function")
async def async_client_service(test_settings: AppSettingsClass, db_session) -> AsyncGenerator[AsyncClient, None]: # Зависит от db_session для установки override
    transport = ASGITransport(app=fastapi_app); # type: ignore
    async with AsyncClient(transport=transport, base_url=f"http://test_{service_name_snake}") as client:
        yield client
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def dam_factory_service_test(manage_service_db_for_tests) -> DataAccessManagerFactory:
    return DataAccessManagerFactory(registry=ModelRegistry)

@pytest_asyncio.fixture
async def test_some_model_item(dam_factory_service_test: DataAccessManagerFactory, db_session) -> SomeModel:
    test_company_id = uuid.uuid4()
    manager = dam_factory_service_test.get_manager("SomeModel")
    item_data = SomeModelCreate(name="Test SomeModel Item", value=123, company_id=test_company_id)
    # db_session фикстура уже открыла транзакцию (через managed_session в override_get_session или напрямую)
    # Метод create менеджера использует get_current_session(), который должен вернуть эту сессию.
    item = await manager.create(item_data)
    return item
"""
    conftest_path = target_dir / "app" / "tests" / "conftest.py"
    conftest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(conftest_path, "w", encoding="utf-8") as f: f.write(conftest_content.strip())
        print(f"Создан conftest.py: {conftest_path}")
    except Exception as e: print(f"Ошибка создания conftest.py: {e}")

    some_model_test_py_content = f"""# {service_name_snake}/app/tests/api/test_some_model_api.py
import pytest, uuid # Добавлен uuid
from httpx import AsyncClient
from {service_name_snake}.app.config import settings as service_settings
from {service_name_snake}.app.schemas.some_model_schema import SomeModelCreate, SomeModelRead
from {service_name_snake}.app.models.some_model import SomeModel

pytestmark = pytest.mark.asyncio
API_PREFIX = service_settings.API_V1_STR
SOME_MODEL_ENDPOINT = f"{{API_PREFIX}}/some-models"

# TODO: Добавьте фикстуру для аутентификации, если эндпоинты защищены
# Например, superuser_token_headers из conftest.py вашего core сервиса, адаптированная.
# @pytest_asyncio.fixture
# async def auth_headers(async_client_service: AsyncClient, test_settings_service: service_settings):
#     # Логика получения токена...
#     # return {{"Authorization": f"Bearer {{token}}"}}
#     return {{}} # Заглушка

async def test_create_some_model(async_client_service: AsyncClient, db_session): # Убрал auth_headers пока
    test_company_id = uuid.uuid4()
    data = SomeModelCreate(name="My First SomeModel", value=100, company_id=test_company_id)
    response = await async_client_service.post(SOME_MODEL_ENDPOINT, json=data.model_dump()) # Убрал headers
    assert response.status_code == 201, response.text
    content = response.json()
    assert content["name"] == data.name; assert content["value"] == data.value

async def test_get_some_model(async_client_service: AsyncClient, test_some_model_item: SomeModel, db_session):
    response = await async_client_service.get(f"{{SOME_MODEL_ENDPOINT}}/{{test_some_model_item.id}}")
    assert response.status_code == 200, response.text
    content = response.json(); assert content["id"] == str(test_some_model_item.id)

async def test_list_some_models(async_client_service: AsyncClient, test_some_model_item: SomeModel, db_session):
    response = await async_client_service.get(SOME_MODEL_ENDPOINT)
    assert response.status_code == 200, response.text
    content = response.json(); assert isinstance(content["items"], list); assert len(content["items"]) >= 1
    assert any(item["id"] == str(test_some_model_item.id) for item in content["items"])
"""
    test_api_file_path = target_dir / "app" / "tests" / "api" / "test_some_model_api.py"
    test_api_file_path.parent.mkdir(parents=True, exist_ok=True) # Убедимся, что директория существует
    try:
        with open(test_api_file_path, "w", encoding="utf-8") as f: f.write(some_model_test_py_content.strip())
        print(f"Создан тестовый файл API: {test_api_file_path}")
    except Exception as e: print(f"Ошибка создания тестового файла API: {e}")

    print(f"\nСервис '{service_name_pascal}' создан в '{target_dir_name}'.")
    print("Дальнейшие шаги:")
    print(f"1. Проверьте и настройте '{target_dir_name}/.env' и '{target_dir_name}/.env.test'.")
    print(f"2. Настройте '{target_dir_name}/alembic.ini' и '{target_dir_name}/alembic/env.py' (DATABASE_URL, target_metadata для SomeModel).")
    print(f"3. Создайте миграцию: `alembic -c {target_dir_name}/alembic.ini revision -m \"create some_model table\"`.")
    print(f"4. Примените миграцию: `alembic -c {target_dir_name}/alembic.ini upgrade head` (после настройки БД).")
    print(f"5. Добавьте сервис в корневой `docker-compose.yml`.")
    print(f"6. Запустите тесты для нового сервиса: `pytest {target_dir_name}/app/tests/` (после настройки conftest.py и, возможно, фикстур аутентификации).")

if __name__ == "__main__":
    new_service_name_pascal = input("Введите имя нового сервиса (PascalCase, например, OrderService): ")
    if not new_service_name_pascal:
        print("Имя сервиса не может быть пустым.")
    else:
        new_target_dir = input(f"Введите имя директории для сервиса (по умолчанию: {to_snake_case(new_service_name_pascal)}): ") or None
        create_new_service(new_service_name_pascal, new_target_dir)