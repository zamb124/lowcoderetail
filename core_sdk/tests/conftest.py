# core_sdk/tests/conftest.py
import asyncio
import contextvars
import contextlib
import os
import sys
from typing import (
    AsyncGenerator,
    Generator,
    Type,
    Dict,
    Any,
    Optional as TypingOptional,
    List as TypingList,
    Optional, Union, Literal, Mapping,
)
from unittest import mock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine,
)

# StaticPool убран, будем использовать дефолтный пул для sqlite
from sqlmodel import SQLModel, Field as SQLModelField, Field
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, HttpUrl

from core_sdk.db import session as sdk_db_session_module
from core_sdk.db.session import (
    managed_session as sdk_managed_session,
    get_current_session,
    init_db as sdk_init_db_func,
    close_db as sdk_close_db_func,
)
from core_sdk.registry import ModelRegistry, RemoteConfig, ModelInfo
from core_sdk.data_access.base_manager import BaseDataAccessManager
from core_sdk.data_access.local_manager import LocalDataAccessManager # Добавить импорт
from core_sdk.data_access.manager_factory import DataAccessManagerFactory
from core_sdk.filters.base import DefaultFilter
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter
from core_sdk.config import BaseAppSettings
from taskiq import AsyncBroker
import logging
import uuid

logger = logging.getLogger("core_sdk.tests.conftest")


# --- Вспомогательные классы (модели и схемы для тестов) ---
# (Без изменений, оставляем как есть)
class FactoryTestItem(SQLModel, table=True):
    __tablename__ = "factory_test_items_sdk"
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None


class FactoryTestItemCreate(PydanticBaseModel):
    name: str
    description: Optional[str] = None


class FactoryTestItemUpdate(PydanticBaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class FactoryTestItemRead(FactoryTestItem):
    pass


class CustomLocalFactoryItemManager(
    LocalDataAccessManager[FactoryTestItemRead, FactoryTestItemCreate, FactoryTestItemUpdate]
):
    # db_model_cls будет установлен фабрикой или при регистрации
    # model_cls (ReadSchema) устанавливается в super().__init__

    # --- ЗАГЛУШКИ ДЛЯ АБСТРАКТНЫХ МЕТОДОВ ---
    async def list(self, *, cursor: Optional[int] = None, limit: int = 50,
                   filters: Optional[Union[BaseSQLAlchemyFilter, Mapping[str, Any]]] = None,
                   direction: Literal["asc", "desc"] = "asc") -> Dict[str, Any]:
        # Эта реализация нужна только для того, чтобы класс не был абстрактным
        # В реальных тестах этот менеджер будет мокирован или будет использоваться его реальная логика,
        # если он не просто мок, а кастомный менеджер с логикой.
        # Для данного теста, где мы проверяем, что фабрика возвращает *ЭТОТ* класс,
        # реализация не так важна.
        if not hasattr(self, 'db_model_cls'): # Проверка на случай, если db_model_cls не установлен
            raise NotImplementedError("db_model_cls not set for CustomLocalFactoryItemManager")
        return {"items": [], "next_cursor": None, "limit": limit, "count": 0} # pragma: no cover

    async def get(self, item_id: uuid.UUID) -> Optional[FactoryTestItemRead]:
        return None # pragma: no cover

    async def create(self, data: Union[FactoryTestItemCreate, Dict[str, Any]]) -> FactoryTestItemRead:
        if isinstance(data, Dict): data_model = FactoryTestItemCreate.model_validate(data)
        else: data_model = data
        # Возвращаем экземпляр ReadSchema
        return FactoryTestItemRead(id=uuid.uuid4(), name=data_model.name, description=data_model.description) # pragma: no cover

    async def update(self, item_id: uuid.UUID, data: Union[FactoryTestItemUpdate, Dict[str, Any]]) -> FactoryTestItemRead:
        if isinstance(data, Dict): data_model = FactoryTestItemUpdate.model_validate(data)
        else: data_model = data
        return FactoryTestItemRead(id=item_id, name=data_model.name or "Updated", description=data_model.description) # pragma: no cover

    async def delete(self, item_id: uuid.UUID) -> bool:
        return True # pragma: no cover


class AnotherFactoryItem(SQLModel, table=True):
    __tablename__ = "another_factory_items_sdk"
    id: Optional[int] = Field(default=None, primary_key=True)
    value: str


class AnotherFactoryItemRead(AnotherFactoryItem):
    pass


class Item(SQLModel, table=True):
    __tablename__ = "sdk_test_items_global_v2"
    id: TypingOptional[uuid.UUID] = SQLModelField(
        default_factory=uuid.uuid4, primary_key=True,
    )
    name: str = SQLModelField(index=True)
    description: TypingOptional[str] = SQLModelField(default=None)
    value: TypingOptional[int] = SQLModelField(default=None)
    lsn: TypingOptional[int] = SQLModelField(default=None, unique=True, index=True)


class ItemCreate(PydanticBaseModel):
    name: str
    description: TypingOptional[str] = None
    value: TypingOptional[int] = None
    lsn: TypingOptional[int] = None
    model_config = ConfigDict(extra="allow")


class ItemUpdate(PydanticBaseModel):
    name: TypingOptional[str] = None
    description: TypingOptional[str] = None
    value: TypingOptional[int] = None
    model_config = ConfigDict(extra="allow")


class ItemRead(Item):
    pass


class ItemFilter(DefaultFilter):
    name: TypingOptional[str] = None
    name__like: TypingOptional[str] = None
    value__gt: TypingOptional[int] = None

    class Constants(DefaultFilter.Constants):
        model = Item
        search_model_fields = ["name", "description"]


class CrudFactoryItem(SQLModel, table=True):
    __tablename__ = "sdk_crud_factory_items_v2"
    id: TypingOptional[uuid.UUID] = SQLModelField(
        default_factory=uuid.uuid4, primary_key=True
    )
    name: str
    description: TypingOptional[str] = SQLModelField(default=None)
    value: TypingOptional[int] = SQLModelField(default=None)
    lsn: TypingOptional[int] = SQLModelField(default=None, unique=True, index=True)


class CrudFactoryItemCreate(PydanticBaseModel):
    name: str
    description: TypingOptional[str] = None
    value: TypingOptional[int] = None
    model_config = ConfigDict(extra="allow")


class CrudFactoryItemUpdate(PydanticBaseModel):
    name: TypingOptional[str] = None
    description: TypingOptional[str] = None
    value: TypingOptional[int] = None
    model_config = ConfigDict(extra="allow")


class CrudFactoryItemRead(CrudFactoryItemCreate):
    id: uuid.UUID
    pass


class CrudFactoryItemFilter(DefaultFilter):
    name: TypingOptional[str] = None

    class Constants(DefaultFilter.Constants):
        model = CrudFactoryItem


class CrudSimpleItem(SQLModel, table=True):
    __tablename__ = "sdk_crud_simple_items_v2"
    id: TypingOptional[uuid.UUID] = SQLModelField(
        default_factory=uuid.uuid4, primary_key=True
    )
    name: str


class CrudSimpleItemRead(CrudSimpleItem):
    pass


class AppSetupTestSettings(BaseAppSettings):
    PROJECT_NAME: str = "SDKTestAppSetupProject"
    API_V1_STR: str = "/api/sdktest_app"
    DATABASE_URL: str = "sqlite+aiosqlite:///:memory:?cache=shared"
    SECRET_KEY: str = "sdk_test_secret_appsetup"
    ALGORITHM: str = "HS256"
    DB_POOL_SIZE: int = 2
    DB_MAX_OVERFLOW: int = 1
    LOGGING_LEVEL: str = "DEBUG"
    BACKEND_CORS_ORIGINS: TypingList[str] = ["http://test-origin.com"]
    model_config = ConfigDict(extra="ignore")


# --- Глобальные фикстуры для управления состоянием SDK ---


@pytest.fixture(scope="session", autouse=True)
def set_sdk_test_environment(request: pytest.FixtureRequest):
    logger.info("Setting ENV=test for SDK test session.")
    original_env_value = os.environ.get("ENV")
    os.environ["ENV"] = "test"

    def finalizer():
        logger.info("Restoring original ENV after SDK test session.")
        if original_env_value is None:
            if "ENV" in os.environ:
                del os.environ["ENV"]
        else:
            os.environ["ENV"] = original_env_value

    request.addfinalizer(finalizer)


# @pytest.fixture(scope="session")
# def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
#     loop = asyncio.get_event_loop_policy().new_event_loop()
#     asyncio.set_event_loop(loop)
#     yield loop
#     loop.close()


@pytest_asyncio.fixture(scope="session")
async def sdk_test_engine_instance():  # Переименовал для ясности
    logger.info("Creating SDK test engine instance (session scope)...")
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:?cache=shared",
        connect_args={"check_same_thread": False},
        echo=False,
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
) -> async_sessionmaker[AsyncSession]:  # Переименовал
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
    """
    Автоматически инициализирует глобальные _db_engine и _db_session_maker
    в модуле core_sdk.db.session перед каждым тестом и очищает их после.
    Это гарантирует, что init_db() в коде SDK увидит "уже инициализированное" состояние,
    а managed_session() будет использовать правильный session_maker.
    """
    logger.debug("auto_init_sdk_db_for_tests: Patching SDK's global DB variables.")
    monkeypatch.setattr(sdk_db_session_module, "_db_engine", sdk_test_engine_instance)
    monkeypatch.setattr(
        sdk_db_session_module, "_db_session_maker", sdk_test_session_maker_instance
    )

    # Также сбрасываем contextvar для чистоты перед тестом
    sdk_db_session_module._current_session.set(None)

    yield  # Тест выполняется здесь

    logger.debug(
        "auto_init_sdk_db_for_tests: Cleaning up SDK's global DB variables after test."
    )
    # monkeypatch автоматически отменит изменения, но для ясности можно и вручную
    # monkeypatch.undo() # или сбросить значения в None
    sdk_db_session_module._db_engine = None
    sdk_db_session_module._db_session_maker = None
    sdk_db_session_module._current_session.set(None)


@pytest.fixture(scope="function", autouse=True)
def manage_model_registry_for_tests():
    # (Без изменений)
    logger.debug(
        "manage_model_registry_for_tests: Clearing ModelRegistry before test function."
    )
    ModelRegistry.clear()
    ModelRegistry.register_local(
        model_name="Item",
        model_cls=Item,
        create_schema_cls=ItemCreate,
        update_schema_cls=ItemUpdate,
        read_schema_cls=ItemRead,
        filter_cls=ItemFilter,
    )
    ModelRegistry.register_local(
        model_name="CrudFactoryItem",
        model_cls=CrudFactoryItem,
        create_schema_cls=CrudFactoryItemCreate,
        update_schema_cls=CrudFactoryItemUpdate,
        read_schema_cls=CrudFactoryItemRead,
        filter_cls=CrudFactoryItemFilter,
    )
    ModelRegistry.register_local(
        model_name="CrudSimpleItem",
        model_cls=CrudSimpleItem,
        read_schema_cls=CrudSimpleItemRead,
    )
    ModelRegistry.register_local(
        model_name="FactoryLocalItem",
        model_cls=FactoryTestItem,
        manager_cls=CustomLocalFactoryItemManager,
        create_schema_cls=FactoryTestItemCreate,
        update_schema_cls=FactoryTestItemUpdate,
        read_schema_cls=FactoryTestItemRead,
    )
    ModelRegistry.register_local(
        model_name="FactoryLocalItemWithBaseDam",
        model_cls=AnotherFactoryItem,
        read_schema_cls=AnotherFactoryItemRead,
    )
    ModelRegistry.register_remote(
        model_name="FactoryRemoteItem",
        model_cls=FactoryTestItemRead,
        config=RemoteConfig(
            service_url=HttpUrl("http://remote-factory-service.com"),
            model_endpoint="/api/v1/factoryremoteitems",
        ),
        create_schema_cls=FactoryTestItemCreate,
        update_schema_cls=FactoryTestItemUpdate,
        read_schema_cls=FactoryTestItemRead,
    )
    if not ModelRegistry.is_configured():
        pytest.fail(
            "manage_model_registry_for_tests: ModelRegistry failed to configure after setup."
        )
    yield
    logger.debug(
        "manage_model_registry_for_tests: Clearing ModelRegistry after test function."
    )
    ModelRegistry.clear()


@pytest_asyncio.fixture(scope="function")
async def db_session(
    sdk_test_session_maker_instance: async_sessionmaker[
        AsyncSession
    ],  # Используем переименованную фикстуру
    auto_init_sdk_db_for_tests: Any,  # Зависимость от авто-инициализации
    manage_model_registry_for_tests: Any,
) -> AsyncGenerator[AsyncSession, None]:
    logger.debug("db_session fixture: Creating new session and setting contextvar...")
    # auto_init_sdk_db_for_tests уже установил _db_session_maker в модуле SDK
    # поэтому managed_session должен работать корректно
    async with sdk_managed_session() as session:  # Используем managed_session из SDK
        logger.debug("db_session fixture: Clearing data from tables...")
        async with session.begin_nested():
            for table in reversed(SQLModel.metadata.sorted_tables):
                try:
                    await session.execute(table.delete())
                except Exception as e_del:
                    logger.error(f"Error clearing table {table.name}: {e_del}")
        await session.commit()
        logger.debug("db_session fixture: Tables cleared.")
        yield session
    # managed_session сам закроет сессию и сбросит contextvar


@pytest.fixture(scope="function")
def dam_factory(
    manage_model_registry_for_tests: Any,
) -> DataAccessManagerFactory:
    logger.debug("dam_factory fixture: Creating DataAccessManagerFactory instance.")
    return DataAccessManagerFactory(registry=ModelRegistry)


@pytest.fixture(scope="function")
def item_manager(
    dam_factory: DataAccessManagerFactory, # dam_factory уже настроена с ModelRegistry
    db_session: AsyncSession # Для установки сессии, если менеджер ее использует напрямую (хотя должен через get_current_session)
) -> LocalDataAccessManager[ItemRead, ItemCreate, ItemUpdate]: # Уточняем тип
    logger.debug("item_manager fixture: Getting 'Item' manager.")
    # Фабрика вернет LocalDataAccessManager, так как "Item" зарегистрирован как локальный
    manager = dam_factory.get_manager("Item")
    assert isinstance(manager, LocalDataAccessManager), "Expected LocalDataAccessManager for 'Item'"
    return manager # type: ignore


@pytest_asyncio.fixture
async def sample_items(
    item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate],
    db_session: AsyncSession,
) -> TypingList[Item]:
    # (Без изменений)
    logger.debug("sample_items fixture: Creating sample items...")
    items_data_with_lsn = [
        {"name": "Apple", "description": "Red fruit", "value": 10, "lsn": 100},
        {"name": "Banana", "description": "Yellow fruit", "value": 20, "lsn": 101},
        {"name": "Cherry", "description": "Red small fruit", "value": 15, "lsn": 102},
        {"name": "Date", "description": "Brown sweet fruit", "value": 20, "lsn": 103},
        {"name": "Elderberry", "description": "Dark berry", "value": 25, "lsn": 104},
    ]
    created_items = []
    for data in items_data_with_lsn:
        item_create_data = ItemCreate(**data)
        created_item = await item_manager.create(item_create_data)
        if created_item.lsn is None and data.get("lsn") is not None:
            logger.warning(
                f"LSN for {data['name']} is None, setting manually to {data['lsn']}."
            )
            created_item.lsn = data["lsn"]
            item_manager.session.add(created_item)
            await item_manager.session.commit()
            await item_manager.session.refresh(created_item)
        created_items.append(created_item)
    return sorted(created_items, key=lambda x: x.lsn if x.lsn is not None else 0)


# --- Фикстуры для test_app_setup.py и test_worker_setup.py ---
@pytest.fixture
def app_setup_settings() -> AppSetupTestSettings:
    return AppSetupTestSettings()


worker_settings = app_setup_settings


# --- Моки для IO и глобальных объектов ---
@pytest.fixture
def mock_broker():
    broker = mock.AsyncMock(spec=AsyncBroker)
    broker.startup = mock.AsyncMock(name="broker_startup")
    broker.shutdown = mock.AsyncMock(name="broker_shutdown")
    return broker


@pytest.fixture
def mock_before_startup():
    return mock.AsyncMock(name="mock_before_startup")


@pytest.fixture
def mock_after_startup():
    return mock.AsyncMock(name="mock_after_startup")


@pytest.fixture
def mock_before_shutdown():
    return mock.AsyncMock(name="mock_before_shutdown")


@pytest.fixture
def mock_after_shutdown():
    return mock.AsyncMock(name="mock_after_shutdown")


# Эти моки теперь не нужны глобально, если auto_init_sdk_db_for_tests работает
@pytest.fixture
def mock_sdk_init_db():
    return mock.Mock(name="mock_sdk_init_db_app_setup")


@pytest.fixture
def mock_sdk_close_db():
    return mock.AsyncMock(name="mock_sdk_close_db_app_setup")


@pytest.fixture
def mock_model_registry_rebuild():
    return mock.Mock(name="mock_mr_rebuild_app_setup")


@pytest.fixture
def mock_app_http_client_lifespan_cm():
    @contextlib.asynccontextmanager
    async def _cm(app):
        logger.debug("Mock app_http_client_lifespan entered.")
        original_client = getattr(app.state, "http_client", None)
        app.state.http_client = mock.AsyncMock(
            spec=httpx.AsyncClient, name="mock_http_client_in_lifespan"
        )
        app.state.http_client_mocked = True
        try:
            yield
        finally:
            logger.debug("Mock app_http_client_lifespan exiting.")
            app.state.http_client = original_client
            app.state.http_client_mocked = False

    return _cm
