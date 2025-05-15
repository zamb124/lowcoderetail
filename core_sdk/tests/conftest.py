# core_sdk/tests/conftest.py
import asyncio
import contextvars
import contextlib # Добавил, если используется где-то неявно
import os
import sys
from typing import (
    AsyncGenerator,
    Generator,
    Type,
    Dict,
    Any,
    Optional as TypingOptional, # Переименовал, чтобы не конфликтовать с Optional из typing
    List as TypingList, # Переименовал
    Optional, # Стандартный Optional
    Union,
    Literal,
    Mapping,
    TypeVar # Добавил TypeVar
)
from unittest import mock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine,
)

from sqlmodel import SQLModel, Field as SQLModelField
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, HttpUrl, Field as PydanticField

from core_sdk.db import session as sdk_db_session_module
from core_sdk.db.session import (
    managed_session as sdk_managed_session,
    # get_current_session, # Не используется напрямую в этом файле фикстур
    # init_db as sdk_init_db_func, # Не используется напрямую
    # close_db as sdk_close_db_func, # Не используется напрямую
)
from core_sdk.registry import ModelRegistry, RemoteConfig, ModelInfo
from core_sdk.data_access.base_manager import BaseDataAccessManager, DM_CreateSchemaType, DM_UpdateSchemaType, DM_ReadSchemaType, DM_SQLModelType
from core_sdk.data_access.local_manager import LocalDataAccessManager
from core_sdk.data_access.manager_factory import DataAccessManagerFactory
from core_sdk.filters.base import DefaultFilter
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter
from core_sdk.config import BaseAppSettings
from taskiq import AsyncBroker
import logging
import uuid

logger = logging.getLogger("core_sdk.tests.conftest")


# --- Вспомогательные классы (модели и схемы для тестов) ---

# Для test_manager_factory.py
class FactoryTestItem(SQLModel, table=True):
    __tablename__ = "factory_test_items_sdk_v2" # Обновил имя для избежания конфликтов
    __table_args__ = {"extend_existing": True}
    id: Optional[uuid.UUID] = SQLModelField(default_factory=uuid.uuid4, primary_key=True) # UUID ID
    name: str = SQLModelField(index=True)
    description: Optional[str] = None

class FactoryTestItemCreate(PydanticBaseModel):
    name: str
    description: Optional[str] = None
    model_config = ConfigDict(extra='allow')

class FactoryTestItemUpdate(PydanticBaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    model_config = ConfigDict(extra='allow')

class FactoryTestItemRead(PydanticBaseModel): # Теперь это Pydantic, а не SQLModel
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# Кастомный менеджер для FactoryTestItem
class CustomLocalFactoryItemManager(
    LocalDataAccessManager[FactoryTestItem, FactoryTestItemCreate, FactoryTestItemUpdate, FactoryTestItemRead]
):
    async def get(self, item_id: uuid.UUID) -> Optional[FactoryTestItem]: return FactoryTestItem(id=item_id, name="from_custom_get") if item_id else None
    async def list(self, *, cursor: Optional[int] = None, limit: int = 50, filters: Any = None, direction: Any = "asc") -> Dict[str, Any]: return {"items": [FactoryTestItem(id=uuid.uuid4(), name="custom_list_item")]}
    async def create(self, data: FactoryTestItemCreate) -> FactoryTestItem: return FactoryTestItem(id=uuid.uuid4(), name=data.name, description=data.description)
    async def update(self, item_id: uuid.UUID, data: FactoryTestItemUpdate) -> FactoryTestItem: return FactoryTestItem(id=item_id, name=data.name or "updated", description=data.description)
    async def delete(self, item_id: uuid.UUID) -> bool: return True


class AnotherFactoryItem(SQLModel, table=True):
    __tablename__ = "another_factory_items_sdk_v2" # Обновил имя
    id: Optional[uuid.UUID] = SQLModelField(default_factory=uuid.uuid4, primary_key=True) # UUID ID
    value: str

class AnotherFactoryItemRead(PydanticBaseModel): # Pydantic
    id: uuid.UUID
    value: str
    model_config = ConfigDict(from_attributes=True)

# Для test_local_manager.py и других общих тестов SDK
class Item(SQLModel, table=True):
    __tablename__ = "sdk_test_items_global_v3" # Обновил имя
    id: Optional[uuid.UUID] = SQLModelField(default_factory=uuid.uuid4, primary_key=True)
    name: str = SQLModelField(index=True)
    description: Optional[str] = SQLModelField(default=None)
    value: Optional[int] = SQLModelField(default=None)
    lsn: Optional[int] = SQLModelField(default=None, unique=True, index=True, sa_column_kwargs={"autoincrement": True}) # autoincrement для SQLite

class ItemCreate(PydanticBaseModel):
    name: str
    description: Optional[str] = None
    value: Optional[int] = None
    # lsn не должен быть здесь, он генерируется БД
    model_config = ConfigDict(extra="allow")

class ItemUpdate(PydanticBaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    value: Optional[int] = None
    model_config = ConfigDict(extra="allow")

class ItemRead(PydanticBaseModel): # Pydantic
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    value: Optional[int] = None
    lsn: Optional[int] = None # lsn может быть None до первого сохранения, если не генерируется сразу
    model_config = ConfigDict(from_attributes=True)

class ItemFilter(DefaultFilter):
    name: Optional[str] = None
    name__like: Optional[str] = None
    value__gt: Optional[int] = None
    class Constants(DefaultFilter.Constants):
        model = Item
        search_model_fields = ["name", "description"]

# Для test_crud_router_factory.py
class CrudFactoryItem(SQLModel, table=True):
    __tablename__ = "sdk_crud_factory_items_v3" # Обновил имя
    id: Optional[uuid.UUID] = SQLModelField(default_factory=uuid.uuid4, primary_key=True)
    name: str
    description: Optional[str] = SQLModelField(default=None)
    value: Optional[int] = SQLModelField(default=None)
    lsn: Optional[int] = SQLModelField(default=None, unique=True, index=True, sa_column_kwargs={"autoincrement": True})

class CrudFactoryItemCreate(PydanticBaseModel):
    name: str
    description: Optional[str] = None
    value: Optional[int] = None
    model_config = ConfigDict(extra="allow")

class CrudFactoryItemUpdate(PydanticBaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    value: Optional[int] = None
    model_config = ConfigDict(extra="allow")

class CrudFactoryItemRead(PydanticBaseModel): # Pydantic
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    value: Optional[int] = None
    lsn: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)

class CrudFactoryItemFilter(DefaultFilter):
    name: Optional[str] = None
    class Constants(DefaultFilter.Constants):
        model = CrudFactoryItem

class CrudSimpleItem(SQLModel, table=True):
    __tablename__ = "sdk_crud_simple_items_v3" # Обновил имя
    id: Optional[uuid.UUID] = SQLModelField(default_factory=uuid.uuid4, primary_key=True)
    name: str

class CrudSimpleItemRead(PydanticBaseModel): # Pydantic
    id: uuid.UUID
    name: str
    model_config = ConfigDict(from_attributes=True)


class AppSetupTestSettings(BaseAppSettings):
    PROJECT_NAME: str = "SDKTestAppSetupProject"
    API_V1_STR: str = "/api/sdktest_app"
    DATABASE_URL: str = "sqlite+aiosqlite:///:memory:?cache=shared&check_same_thread=false" # Добавил check_same_thread
    SECRET_KEY: str = "sdk_test_secret_appsetup"
    ALGORITHM: str = "HS256"
    DB_POOL_SIZE: int = 2
    DB_MAX_OVERFLOW: int = 1
    LOGGING_LEVEL: str = "DEBUG"
    BACKEND_CORS_ORIGINS: TypingList[str] = ["http://test-origin.com"]
    model_config = ConfigDict(extra="ignore")


@pytest.fixture(scope="session", autouse=True)
def set_sdk_test_environment(request: pytest.FixtureRequest):
    logger.info("Setting ENV=test for SDK test session.")
    original_env_value = os.environ.get("ENV")
    os.environ["ENV"] = "test"
    def finalizer():
        logger.info("Restoring original ENV after SDK test session.")
        if original_env_value is None:
            if "ENV" in os.environ: del os.environ["ENV"]
        else: os.environ["ENV"] = original_env_value
    request.addfinalizer(finalizer)

@pytest_asyncio.fixture(scope="session")
async def sdk_test_engine_instance():
    logger.info("Creating SDK test engine instance (session scope)...")
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:?cache=shared&check_same_thread=false", # Добавил check_same_thread
        echo=False,
        # Для SQLite in-memory poolclass=StaticPool может быть полезен, но не обязателен
        # connect_args={"check_same_thread": False} # Уже в URL
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("SDK test tables created (or ensured to exist).")
    yield engine
    logger.info("Disposing SDK test engine instance (session scope)...")
    await engine.dispose()

@pytest_asyncio.fixture(scope="session")
async def sdk_test_session_maker_instance(
        sdk_test_engine_instance: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    logger.debug("Creating SDK test session_maker instance (session scope)...")
    return async_sessionmaker(
        bind=sdk_test_engine_instance, class_=AsyncSession, expire_on_commit=False
    )

@pytest_asyncio.fixture(scope="function", autouse=True)
async def auto_init_sdk_db_for_tests(
        sdk_test_engine_instance: AsyncEngine,
        sdk_test_session_maker_instance: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
):
    logger.debug("auto_init_sdk_db_for_tests: Patching SDK's global DB variables.")
    monkeypatch.setattr(sdk_db_session_module, "_db_engine", sdk_test_engine_instance)
    monkeypatch.setattr(sdk_db_session_module, "_db_session_maker", sdk_test_session_maker_instance)
    sdk_db_session_module._current_session.set(None)
    yield
    logger.debug("auto_init_sdk_db_for_tests: Cleaning up SDK's global DB variables after test.")
    sdk_db_session_module._db_engine = None
    sdk_db_session_module._db_session_maker = None
    sdk_db_session_module._current_session.set(None)

@pytest.fixture(scope="function", autouse=True)
def manage_model_registry_for_tests():
    logger.debug("manage_model_registry_for_tests: Clearing ModelRegistry before test function.")
    ModelRegistry.clear()

    ModelRegistry.register_local(model_name="Item", model_cls=Item, read_schema_cls=ItemRead, create_schema_cls=ItemCreate, update_schema_cls=ItemUpdate, filter_cls=ItemFilter)
    ModelRegistry.register_local(model_name="CrudFactoryItem", model_cls=CrudFactoryItem, read_schema_cls=CrudFactoryItemRead, create_schema_cls=CrudFactoryItemCreate, update_schema_cls=CrudFactoryItemUpdate, filter_cls=CrudFactoryItemFilter)
    ModelRegistry.register_local(model_name="CrudSimpleItem", model_cls=CrudSimpleItem, read_schema_cls=CrudSimpleItemRead)
    ModelRegistry.register_local(model_name="FactoryLocalItem", model_cls=FactoryTestItem, read_schema_cls=FactoryTestItemRead, manager_cls=CustomLocalFactoryItemManager, create_schema_cls=FactoryTestItemCreate, update_schema_cls=FactoryTestItemUpdate)
    ModelRegistry.register_local(model_name="FactoryLocalItemWithBaseDam", model_cls=AnotherFactoryItem, read_schema_cls=AnotherFactoryItemRead)
    ModelRegistry.register_remote(
        model_name="FactoryRemoteItem",
        model_cls=FactoryTestItemRead, # Pydantic ReadSchema
        config=RemoteConfig(service_url=HttpUrl("http://remote-factory-service.com"), model_endpoint="/api/v1/factoryremoteitems"),
        create_schema_cls=FactoryTestItemCreate,
        update_schema_cls=FactoryTestItemUpdate,
        # read_schema_cls для remote такой же как model_cls, ModelRegistry.register_remote это учтет
    )
    if not ModelRegistry.is_configured():
        pytest.fail("manage_model_registry_for_tests: ModelRegistry failed to configure after setup.")
    yield
    logger.debug("manage_model_registry_for_tests: Clearing ModelRegistry after test function.")
    ModelRegistry.clear()

@pytest_asyncio.fixture(scope="function")
async def db_session(
        sdk_test_session_maker_instance: async_sessionmaker[AsyncSession],
        auto_init_sdk_db_for_tests: Any,
        manage_model_registry_for_tests: Any,
) -> AsyncGenerator[AsyncSession, None]:
    logger.debug("db_session fixture: Creating new session and setting contextvar...")
    async with sdk_managed_session() as session:
        logger.debug("db_session fixture: Clearing data from tables...")
        async with session.begin_nested(): # Используем begin_nested для SQLite
            for table in reversed(SQLModel.metadata.sorted_tables):
                try:
                    # Для SQLite TRUNCATE не работает, используем DELETE
                    await session.execute(text(f"DELETE FROM {table.name}"))
                except Exception as e_del:
                    logger.error(f"Error clearing table {table.name}: {e_del}")
        await session.commit() # Коммитим удаление
        logger.debug("db_session fixture: Tables cleared.")
        yield session

@pytest.fixture(scope="function")
def dam_factory(manage_model_registry_for_tests: Any) -> DataAccessManagerFactory:
    logger.debug("dam_factory fixture: Creating DataAccessManagerFactory instance.")
    return DataAccessManagerFactory(registry=ModelRegistry)

@pytest.fixture(scope="function")
def item_manager(
        dam_factory: DataAccessManagerFactory,
        db_session: AsyncSession
) -> LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead]:
    logger.debug("item_manager fixture: Getting 'Item' manager.")
    manager = dam_factory.get_manager("Item")
    assert isinstance(manager, LocalDataAccessManager), "Expected LocalDataAccessManager for 'Item'"
    assert manager.model_cls is Item
    assert manager.read_schema_cls is ItemRead
    return manager # type: ignore

@pytest_asyncio.fixture
async def sample_items(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        db_session: AsyncSession,
) -> TypingList[Item]:
    logger.debug("sample_items fixture: Creating sample items...")
    items_data_for_create = [ # Убрал lsn, так как он генерируется БД
        {"name": "Apple", "description": "Red fruit", "value": 10, "lsn": 1},
        {"name": "Banana", "description": "Yellow fruit", "value": 20, "lsn": 2},
        {"name": "Cherry", "description": "Red small fruit", "value": 15, "lsn": 3},
        {"name": "Date", "description": "Brown sweet fruit", "value": 20, "lsn": 4},
        {"name": "Elderberry", "description": "Dark berry", "value": 25, "lsn": 5},
    ]
    created_items_sqlmodel: TypingList[Item] = []
    for data in items_data_for_create:
        item_create_data = ItemCreate(**data)
        created_item = await item_manager.create(item_create_data)
        created_items_sqlmodel.append(created_item)
    # Сортируем по lsn, который должен быть установлен БД
    # Добавляем проверку, что lsn не None
    return sorted(created_items_sqlmodel, key=lambda x: x.lsn if x.lsn is not None else -1)


# --- Фикстуры для test_app_setup.py и test_worker_setup.py ---
@pytest.fixture
def app_setup_settings() -> AppSetupTestSettings:
    return AppSetupTestSettings()

worker_settings = app_setup_settings # Алиас для worker_setup тестов

# --- Моки для IO и глобальных объектов ---
@pytest.fixture
def mock_broker():
    broker = mock.AsyncMock(spec=AsyncBroker)
    broker.startup = mock.AsyncMock(name="broker_startup")
    broker.shutdown = mock.AsyncMock(name="broker_shutdown")
    return broker

@pytest.fixture
def mock_before_startup(): return mock.AsyncMock(name="mock_before_startup")
@pytest.fixture
def mock_after_startup(): return mock.AsyncMock(name="mock_after_startup")
@pytest.fixture
def mock_before_shutdown(): return mock.AsyncMock(name="mock_before_shutdown")
@pytest.fixture
def mock_after_shutdown(): return mock.AsyncMock(name="mock_after_shutdown")

@pytest.fixture
def mock_sdk_init_db(): return mock.Mock(name="mock_sdk_init_db_app_setup")
@pytest.fixture
def mock_sdk_close_db(): return mock.AsyncMock(name="mock_sdk_close_db_app_setup")
@pytest.fixture
def mock_model_registry_rebuild(): return mock.Mock(name="mock_mr_rebuild_app_setup")

@pytest.fixture
def mock_app_http_client_lifespan_cm():
    @contextlib.asynccontextmanager
    async def _cm(app):
        logger.debug("Mock app_http_client_lifespan entered.")
        original_client = getattr(app.state, "http_client", None)
        app.state.http_client = mock.AsyncMock(spec=httpx.AsyncClient, name="mock_http_client_in_lifespan")
        app.state.http_client_mocked = True
        try: yield
        finally:
            logger.debug("Mock app_http_client_lifespan exiting.")
            app.state.http_client = original_client
            app.state.http_client_mocked = False
    return _cm

# Фикстуры для test_frontend_base_router
@pytest.fixture
def mock_templates_response_method(monkeypatch: pytest.MonkeyPatch) -> mock.Mock:
    """Мокирует метод TemplateResponse у Jinja2Templates."""
    from starlette.templating import Jinja2Templates
    mock_method = mock.Mock(return_value="<div>Mocked TemplateResponse HTML</div>")
    # Патчим метод на уровне класса, чтобы все экземпляры использовали мок
    monkeypatch.setattr(Jinja2Templates, "TemplateResponse", mock_method, raising=False)
    return mock_method

@pytest.fixture
def mock_generic_renderer_instance() -> mock.AsyncMock:
    from core_sdk.frontend.renderer import ViewRenderer # Локальный импорт
    renderer_mock = mock.AsyncMock(spec=ViewRenderer)
    renderer_mock.render_to_response = mock.AsyncMock(return_value="<div>Mocked Generic Render Output</div>")
    renderer_mock.render_field_to_response = mock.AsyncMock(return_value="<span>Mocked Generic Field Output</span>")
    return renderer_mock