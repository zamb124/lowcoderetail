# core_sdk/tests/conftest.py
import asyncio
import os
import sys
import importlib
from typing import AsyncGenerator, Generator, Type, Dict, Any, Optional as TypingOptional, List as TypingList

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool # Используем StaticPool для SQLite in-memory
from sqlmodel import SQLModel, Field, create_engine as sqlmodel_create_engine
from pydantic import BaseModel as PydanticBaseModel

# Добавляем корень проекта, если нужно (предполагаем, что тесты запускаются так, что core_sdk уже в пути)

# Импорты из SDK
from core_sdk.db.session import init_db as sdk_init_db, close_db as sdk_close_db, managed_session as sdk_managed_session, get_current_session as sdk_get_current_session
from core_sdk.registry import ModelRegistry
from core_sdk.data_access.base_manager import BaseDataAccessManager
from core_sdk.data_access.manager_factory import DataAccessManagerFactory
from core_sdk.filters.base import DefaultFilter
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter
import logging

logger = logging.getLogger("core_sdk.tests.conftest")

# --- Тестовая модель и схемы (оставляем как есть) ---
class Item(SQLModel, table=True):
    __tablename__ = "sdk_test_items" # Уникальное имя таблицы для тестов SDK
    id: TypingOptional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: TypingOptional[str] = None
    value: TypingOptional[int] = None
    lsn: TypingOptional[int] = Field(default=None, unique=True, index=True) # Ручная установка

class ItemCreate(PydanticBaseModel): # Используем PydanticBaseModel для схем
    name: str
    description: TypingOptional[str] = None
    value: TypingOptional[int] = None
    lsn: TypingOptional[int] = None

class ItemUpdate(PydanticBaseModel):
    name: TypingOptional[str] = None
    description: TypingOptional[str] = None
    value: TypingOptional[int] = None

class ItemRead(Item): pass # SQLModel может быть и схемой Pydantic

class ItemFilter(DefaultFilter):
    name: TypingOptional[str] = None
    name__like: TypingOptional[str] = None
    value__gt: TypingOptional[int] = None
    class Constants:
        model = Item
        search_model_fields = ["name", "description"]

# --- Фикстуры ---

@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="session")
async def test_sqlite_engine_sdk(): # Переименовал, чтобы не конфликтовать, если тесты SDK и Core запускаются вместе
    """Асинхронный SQLite in-memory движок для тестов SDK."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", # Новый in-memory для каждого запуска сессии
        connect_args={"check_same_thread": False},
        poolclass=StaticPool, # Важно для in-memory SQLite и create_all
        echo=False
    )
    # Создаем все таблицы один раз за сессию
    async with engine.begin() as conn:
        logger.info("Creating all SQLModel tables for SDK tests...")
        await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("SQLModel tables created for SDK tests.")

    yield engine

    logger.info("Disposing SDK test engine...")
    await engine.dispose()
    logger.info("SDK test engine disposed.")

# Эта фикстура будет управлять глобальным состоянием DB в SDK для ВСЕХ тестов в этой сессии
@pytest_asyncio.fixture(scope="session", autouse=True)
async def manage_sdk_db_for_test_session(test_sqlite_engine_sdk: Any):
    """
    Инициализирует глобальные переменные DB в core_sdk.db.session, используя тестовый движок.
    Выполняется один раз за тестовую сессию.
    """
    logger.info("manage_sdk_db_for_test_session: Initializing SDK's global DB state with test engine.")
    # Передаем URL, но engine_options будут использовать наш тестовый движок через StaticPool
    # Важно, чтобы init_db не создавал новый движок, если мы хотим использовать существующий.
    # Оригинальный init_db создает новый движок. Нам нужно либо передать движок в init_db,
    # либо установить глобальные _db_engine и _db_session_maker напрямую.
    # Давайте попробуем установить напрямую, как в apps/core/conftest.py для manage_sdk_db_lifecycle
    # но там init_db вызывается с DATABASE_URL.

    # Проблема: init_db в SDK создает свой движок. Нам нужно, чтобы он использовал НАШ тестовый.
    # Решение: Патчить create_async_engine внутри init_db или передавать engine.
    # Самый простой вариант для тестов SDK - напрямую установить глобальные переменные SDK.

    from core_sdk.db import session as sdk_session_globals

    original_sdk_engine = sdk_session_globals._db_engine
    original_sdk_session_maker = sdk_session_globals._db_session_maker

    sdk_session_globals._db_engine = test_sqlite_engine_sdk
    sdk_session_globals._db_session_maker = async_sessionmaker(
        bind=test_sqlite_engine_sdk, class_=AsyncSession, expire_on_commit=False
    )
    logger.info(f"SDK's global _db_engine and _db_session_maker now point to test_sqlite_engine_sdk for session.")

    yield

    logger.info("manage_sdk_db_for_test_session: Restoring original SDK DB state (if any) and closing test setup.")
    # await sdk_close_db() # Это попытается закрыть наш тестовый движок, что нормально.
    # Но лучше восстановить оригинальные значения, если они были, а движок закроется своей фикстурой.
    sdk_session_globals._db_engine = original_sdk_engine
    sdk_session_globals._db_session_maker = original_sdk_session_maker
    # sdk_close_db() здесь не нужен, так как test_sqlite_engine_sdk сам себя закроет.


# Эта фикстура будет управлять ModelRegistry для КАЖДОГО теста функции
@pytest.fixture(scope="function", autouse=True)
def manage_model_registry_for_test_function(manage_sdk_db_for_test_session: Any): # Зависит от инициализации БД SDK
    """Очищает и настраивает ModelRegistry для каждого теста функции."""
    ModelRegistry.clear()
    ModelRegistry.register_local(
        model_cls=Item, create_schema_cls=ItemCreate, update_schema_cls=ItemUpdate,
        read_schema_cls=ItemRead, filter_cls=ItemFilter, model_name="Item"
    )
    if not ModelRegistry.is_configured(): # Добавим проверку
        pytest.fail("manage_model_registry_for_test_function: ModelRegistry failed to configure.")
    yield
    ModelRegistry.clear()

@pytest_asyncio.fixture(scope="function")
async def db_session(manage_model_registry_for_test_function: Any) -> AsyncGenerator[AsyncSession, None]:
    """
    Предоставляет сессию БД для одного теста, используя sdk_managed_session.
    Зависит от manage_model_registry_for_test_function для правильного порядка.
    Также очищает таблицы перед каждым тестом.
    """
    # sdk_managed_session будет использовать глобальный _db_session_maker,
    # который был установлен фикстурой manage_sdk_db_for_test_session.
    logger.debug(f"db_session fixture: Entering sdk_managed_session.")
    async with sdk_managed_session() as session:
        logger.debug(f"db_session fixture: Test session (id: {id(session)}) obtained.")
        # Очистка таблиц перед каждым тестом
        async with session.begin_nested(): # Используем begin_nested для независимости от внешней транзакции, если она есть
            for table in reversed(SQLModel.metadata.sorted_tables):
                await session.execute(table.delete())
        await session.commit() # Коммитим очистку
        logger.debug(f"db_session fixture: Tables cleared. Yielding session.")
        yield session
    logger.debug(f"db_session fixture: Exited sdk_managed_session.")


@pytest.fixture(scope="function")
def dam_factory(manage_model_registry_for_test_function: Any) -> DataAccessManagerFactory:
    # Зависит от manage_model_registry_for_test_function, чтобы реестр был готов.
    # Сессия будет получена DAM через sdk_get_current_session(), который использует sdk_managed_session.
    return DataAccessManagerFactory(registry=ModelRegistry)

@pytest.fixture(scope="function")
def item_manager(dam_factory: DataAccessManagerFactory, db_session) -> BaseDataAccessManager[Item, ItemCreate, ItemUpdate]:
    return dam_factory.get_manager("Item")

@pytest_asyncio.fixture(scope="function")
async def sample_items(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate]) -> TypingList[Item]:
    # ... (код фикстуры sample_items как был, с ручной установкой lsn) ...
    # Убедимся, что он использует item_manager, который уже работает с правильной сессией
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
        # Проверка и принудительная установка LSN, если create не установил его из схемы
        if created_item.lsn != data["lsn"]:
            logger.warning(f"LSN mismatch for {data['name']}: expected {data['lsn']}, got {created_item.lsn}. Forcing LSN.")
            # Используем сессию, которую получит item_manager
            async with item_manager.session.begin_nested():
                stmt = Item.__table__.update().where(Item.id == created_item.id).values(lsn=data["lsn"])
                await item_manager.session.execute(stmt)
            await item_manager.session.commit() # Коммитим обновление LSN
            await item_manager.session.refresh(created_item, attribute_names=['lsn'])
        created_items.append(created_item)
    return sorted(created_items, key=lambda x: x.lsn if x.lsn is not None else 0)