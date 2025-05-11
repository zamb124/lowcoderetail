# core_sdk/tests/test_worker_setup.py
import pytest
import os
from unittest import mock  # mock все еще нужен для .object и проверки вызовов
import importlib
from typing import Optional, Dict, Any

from core_sdk.worker_setup import initialize_worker_context, shutdown_worker_context
from core_sdk.config import BaseAppSettings
from core_sdk.registry import ModelRegistry
# db_session_module не нужен для прямого импорта

from core_sdk.tests.conftest import (
    AppSetupTestSettings,
    worker_settings,
)  # Используем worker_settings из conftest
from core_sdk.tests.conftest import Item  # Для имитации регистрации модельки

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def mock_io_for_worker_setup(monkeypatch: pytest.MonkeyPatch):
    """
    Мокирует внешние IO зависимости, вызываемые из core_sdk.worker_setup.
    """
    mock_init = mock.Mock(name="mocked_init_db_in_worker_setup")
    mock_close = mock.AsyncMock(name="mocked_close_db_in_worker_setup")
    mock_import = mock.Mock(name="mocked_import_module_in_worker_setup")

    monkeypatch.setattr("core_sdk.worker_setup.init_db", mock_init)
    monkeypatch.setattr("core_sdk.worker_setup.close_db", mock_close)
    monkeypatch.setattr("core_sdk.worker_setup.importlib.import_module", mock_import)

    yield {
        "init_db": mock_init,
        "close_db": mock_close,
        "import_module": mock_import,
    }


# --- Тесты для initialize_worker_context ---


async def test_initialize_db_called_correctly(
    worker_settings: AppSetupTestSettings,  # Используем фикстуру из conftest
    mock_io_for_worker_setup: Dict[str, mock.Mock],
):
    mock_init_db = mock_io_for_worker_setup["init_db"]

    await initialize_worker_context(
        settings=worker_settings, registry_config_module=None, rebuild_models=False
    )

    mock_init_db.assert_called_once()
    args, kwargs = mock_init_db.call_args
    assert args[0] == str(worker_settings.DATABASE_URL)
    assert isinstance(kwargs.get("engine_options"), dict)
    # Проверяем, что pool_size берется из WORKER_DB_POOL_SIZE или из DB_POOL_SIZE настроек
    expected_pool_size = int(
        os.getenv("WORKER_DB_POOL_SIZE", str(worker_settings.DB_POOL_SIZE))
    )
    assert kwargs["engine_options"]["pool_size"] == expected_pool_size
    assert kwargs.get("echo") == (worker_settings.LOGGING_LEVEL.upper() == "DEBUG")


async def test_initialize_db_raises_runtime_error_on_failure(
    worker_settings: AppSetupTestSettings,
    mock_io_for_worker_setup: Dict[str, mock.Mock],
):
    mock_init_db = mock_io_for_worker_setup["init_db"]
    mock_init_db.side_effect = Exception("DB init failed")

    with pytest.raises(
        RuntimeError, match="Database initialization failed, worker cannot start."
    ):
        await initialize_worker_context(
            settings=worker_settings, registry_config_module=None, rebuild_models=False
        )


async def test_initialize_registry_config_called_and_configures(
    worker_settings: AppSetupTestSettings,
    mock_io_for_worker_setup: Dict[str, mock.Mock],
    # manage_model_registry_for_tests: Управляет состоянием реестра до и после теста
):
    test_module_name = "fake.registry.module"
    mock_import_module = mock_io_for_worker_setup["import_module"]

    # Имитируем, что импортированный модуль конфигурирует ModelRegistry
    def side_effect_import_module(module_name):
        if module_name == test_module_name:
            # В реальном registry_config_module будет вызов ModelRegistry.register...
            # Здесь мы имитируем это
            ModelRegistry.register_local(
                model_cls=Item, model_name="DummyForWorkerSetupTest"
            )
        return mock.DEFAULT  # Возвращаем стандартное поведение мока для других импортов

    mock_import_module.side_effect = side_effect_import_module

    ModelRegistry.clear()  # Очищаем перед тестом, чтобы проверить установку флага
    assert not ModelRegistry.is_configured()

    await initialize_worker_context(
        settings=worker_settings,
        registry_config_module=test_module_name,
        rebuild_models=False,
    )

    mock_import_module.assert_called_once_with(test_module_name)
    assert ModelRegistry.is_configured()  # Проверяем, что реестр сконфигурировался
    ModelRegistry.clear()  # Очищаем после, чтобы не влиять на другие тесты (хотя manage_... это сделает)


async def test_initialize_registry_config_not_called_if_none(
    worker_settings: AppSetupTestSettings,
    mock_io_for_worker_setup: Dict[str, mock.Mock],
):
    mock_import_module = mock_io_for_worker_setup["import_module"]
    await initialize_worker_context(
        settings=worker_settings, registry_config_module=None, rebuild_models=False
    )
    mock_import_module.assert_not_called()


async def test_initialize_registry_import_error_logged(
    worker_settings: AppSetupTestSettings,
    mock_io_for_worker_setup: Dict[str, mock.Mock],
    caplog,
):
    mock_import_module = mock_io_for_worker_setup["import_module"]
    mock_import_module.side_effect = ImportError("Cannot import module")

    await initialize_worker_context(
        settings=worker_settings,
        registry_config_module="bad.module",
        rebuild_models=False,
    )

    assert "Could not import registry configuration module: bad.module" in caplog.text


async def test_initialize_rebuild_models_called(
    worker_settings: AppSetupTestSettings,
    monkeypatch: pytest.MonkeyPatch,  # Для мокирования ModelRegistry.rebuild_models
):
    mock_mr_rebuild = mock.Mock(name="mock_ModelRegistry_rebuild_models_local")
    monkeypatch.setattr(ModelRegistry, "rebuild_models", mock_mr_rebuild)

    await initialize_worker_context(settings=worker_settings, rebuild_models=True)
    mock_mr_rebuild.assert_called_once_with(force=True)


async def test_initialize_rebuild_models_not_called_if_false(
    worker_settings: AppSetupTestSettings,
    monkeypatch: pytest.MonkeyPatch,  # Для мокирования ModelRegistry.rebuild_models
):
    mock_mr_rebuild = mock.Mock(
        name="mock_ModelRegistry_rebuild_models_local_not_called"
    )
    monkeypatch.setattr(ModelRegistry, "rebuild_models", mock_mr_rebuild)

    await initialize_worker_context(settings=worker_settings, rebuild_models=False)
    mock_mr_rebuild.assert_not_called()


# --- Тесты для shutdown_worker_context ---
async def test_shutdown_calls_close_db(mock_io_for_worker_setup: Dict[str, mock.Mock]):
    mock_close_db = mock_io_for_worker_setup["close_db"]
    await shutdown_worker_context()
    mock_close_db.assert_awaited_once()
