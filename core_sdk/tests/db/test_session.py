# core_sdk/tests/db/test_session.py
import pytest
import asyncio
from unittest import mock
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, async_sessionmaker
from sqlalchemy.exc import OperationalError
from sqlmodel import SQLModel

import core_sdk.db.session as sdk_db_session_module
from core_sdk.db.session import (
    init_db,
    close_db,
    managed_session,
    get_current_session,
    get_session_dependency,
    create_db_and_tables,
)
from core_sdk.tests.conftest import Item

pytestmark = pytest.mark.asyncio

TEST_DB_URL_FOR_SPECIFIC_INIT_TESTS = (
    "sqlite+aiosqlite:///:memory:?unique_test_session_db"
)


@pytest.fixture
def pristine_db_module_state(monkeypatch: pytest.MonkeyPatch):
    # Эта фикстура нужна только для тестов, которые проверяют init_db/close_db с нуля.
    # Она должна "отменить" действие auto_init_sdk_db_for_tests для этих конкретных тестов.

    # Сохраняем состояние, установленное auto_init_sdk_db_for_tests (если оно было)
    # чтобы восстановить его, хотя это может быть избыточно, т.к. auto_init сработает снова.
    original_engine = sdk_db_session_module._db_engine
    original_session_maker = sdk_db_session_module._db_session_maker
    original_current_session_token = sdk_db_session_module._current_session.set(
        None
    )  # Устанавливаем None и получаем токен

    monkeypatch.setattr(sdk_db_session_module, "_db_engine", None)
    monkeypatch.setattr(sdk_db_session_module, "_db_session_maker", None)

    yield

    # Очистка после теста (если тест сам не вызвал close_db)
    if sdk_db_session_module._db_engine:

        async def _dispose_engine():
            if sdk_db_session_module._db_engine:
                await sdk_db_session_module._db_engine.dispose()

        try:
            loop = asyncio.get_running_loop()
            loop.run_until_complete(_dispose_engine())
        except RuntimeError:
            asyncio.run(_dispose_engine())

    monkeypatch.setattr(sdk_db_session_module, "_db_engine", original_engine)
    monkeypatch.setattr(
        sdk_db_session_module, "_db_session_maker", original_session_maker
    )
    sdk_db_session_module._current_session.reset(original_current_session_token)


def test_init_db_success(pristine_db_module_state):
    assert sdk_db_session_module._db_engine is None
    assert sdk_db_session_module._db_session_maker is None

    init_db(
        TEST_DB_URL_FOR_SPECIFIC_INIT_TESTS,
        echo=True,
        engine_options={"pool_pre_ping": True},
    )

    assert sdk_db_session_module._db_engine is not None
    assert isinstance(sdk_db_session_module._db_engine, AsyncEngine)
    assert sdk_db_session_module._db_session_maker is not None
    assert isinstance(sdk_db_session_module._db_session_maker, async_sessionmaker)


def test_init_db_already_initialized_logs_warning(pristine_db_module_state, caplog):
    init_db(TEST_DB_URL_FOR_SPECIFIC_INIT_TESTS)
    engine_after_first_call = sdk_db_session_module._db_engine
    caplog.clear()
    init_db(TEST_DB_URL_FOR_SPECIFIC_INIT_TESTS)

    assert "already initialized. Skipping re-initialization" in caplog.text
    assert sdk_db_session_module._db_engine is engine_after_first_call


@mock.patch(
    "core_sdk.db.session.create_async_engine",
    side_effect=Exception("Engine creation failed"),
)
def test_init_db_engine_creation_failure_raises_runtime_error(
    mock_create_engine_func, pristine_db_module_state
):
    with pytest.raises(
        RuntimeError, match="Failed to initialize database infrastructure"
    ):
        init_db(TEST_DB_URL_FOR_SPECIFIC_INIT_TESTS)
    mock_create_engine_func.assert_called_once()


async def test_close_db_success(pristine_db_module_state):
    init_db(TEST_DB_URL_FOR_SPECIFIC_INIT_TESTS)
    assert sdk_db_session_module._db_engine is not None

    await close_db()

    assert sdk_db_session_module._db_engine is None
    assert sdk_db_session_module._db_session_maker is None


async def test_close_db_not_initialized(pristine_db_module_state):
    assert sdk_db_session_module._db_engine is None
    await close_db()
    assert sdk_db_session_module._db_engine is None
    assert sdk_db_session_module._db_session_maker is None


# Для следующих тестов auto_init_sdk_db_for_tests из conftest.py должна подготовить состояние
def test_managed_session_raises_if_sdk_not_initialized_by_fixture(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(sdk_db_session_module, "_db_session_maker", None)

    async def use_managed_session():
        async with managed_session():
            pass

    with pytest.raises(RuntimeError, match="Session maker not initialized"):
        asyncio.run(use_managed_session())


@pytest.mark.asyncio
async def test_managed_session_provides_closes_session():
    assert sdk_db_session_module._db_session_maker is not None

    session_instance_from_context: Optional[AsyncSession] = None
    async with managed_session() as session:
        session_instance_from_context = session
        assert isinstance(session, AsyncSession)
        assert sdk_db_session_module._current_session.get() is session
        assert session.is_active

    assert sdk_db_session_module._current_session.get() is None
    assert session_instance_from_context is not None


@pytest.mark.asyncio
async def test_managed_session_rolls_back_on_exception():
    assert sdk_db_session_module._db_session_maker is not None
    session_instance_from_context: Optional[AsyncSession] = None

    with pytest.raises(ValueError, match="Test error inside session"):
        async with managed_session() as session:
            session_instance_from_context = session
            test_item = Item(name="Test Item for Rollback")
            session.add(test_item)
            await session.flush()
            raise ValueError("Test error inside session")

    assert sdk_db_session_module._current_session.get() is None
    assert session_instance_from_context is not None


@pytest.mark.asyncio
async def test_managed_session_nested_uses_existing_session():
    assert sdk_db_session_module._db_session_maker is not None
    outer_session_instance: Optional[AsyncSession] = None
    inner_session_instance: Optional[AsyncSession] = None

    async with managed_session() as session1:
        outer_session_instance = session1
        assert sdk_db_session_module._current_session.get() is session1
        async with managed_session() as session2:
            inner_session_instance = session2
            assert sdk_db_session_module._current_session.get() is session1
            assert session2 is session1

    assert outer_session_instance is not None
    assert inner_session_instance is outer_session_instance
    assert sdk_db_session_module._current_session.get() is None


def test_get_current_session_raises_if_no_active_session():
    # auto_init_sdk_db_for_tests устанавливает _current_session.set(None)
    # Поэтому _current_session.get() вернет None, и get_current_session() выбросит RuntimeError.
    # Фикстура pristine_db_module_state здесь не нужна, так как auto_init_sdk_db_for_tests
    # уже обеспечивает нужное начальное состояние для _current_session.
    with pytest.raises(RuntimeError, match="No active session found in context"):
        get_current_session()


@pytest.mark.asyncio
async def test_get_current_session_returns_active_session():
    assert sdk_db_session_module._db_session_maker is not None
    async with managed_session() as session_from_context:
        retrieved_session = get_current_session()
        assert retrieved_session is session_from_context


@pytest.mark.asyncio
async def test_get_session_dependency_provides_session():
    assert sdk_db_session_module._db_session_maker is not None
    session_from_dep: Optional[AsyncSession] = None

    dependency_generator = get_session_dependency()
    try:
        session_from_dep = await dependency_generator.__anext__()
        assert isinstance(session_from_dep, AsyncSession)
        assert sdk_db_session_module._current_session.get() is session_from_dep
        assert session_from_dep.is_active

        with pytest.raises(StopAsyncIteration):
            await dependency_generator.__anext__()
    finally:
        await dependency_generator.aclose()

    assert sdk_db_session_module._current_session.get() is None
    assert session_from_dep is not None


@pytest.mark.asyncio
async def test_create_db_and_tables_calls_metadata_create_all():
    assert sdk_db_session_module._db_engine is not None

    with mock.patch.object(SQLModel.metadata, "create_all") as mock_metadata_create_all:
        await create_db_and_tables()
        assert mock_metadata_create_all.call_count == 1


@pytest.mark.asyncio
async def test_create_db_and_tables_raises_if_engine_not_initialized(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(sdk_db_session_module, "_db_engine", None)
    with pytest.raises(RuntimeError, match="Database engine not initialized"):
        await create_db_and_tables()
