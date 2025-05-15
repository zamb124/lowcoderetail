# core_sdk/tests/test_worker_setup.py
import pytest
import os
from unittest import mock
import importlib
from typing import Optional, Dict, Any

from core_sdk.worker_setup import initialize_worker_context, shutdown_worker_context
from core_sdk.config import BaseAppSettings
from core_sdk.registry import ModelRegistry

# Используем фикстуры и модели из общего conftest SDK
from core_sdk.tests.conftest import (
    AppSetupTestSettings,
    worker_settings, # Алиас для app_setup_settings
    Item, # SQLModel
    ItemRead # Pydantic ReadSchema
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def mock_io_for_worker_setup(monkeypatch: pytest.MonkeyPatch):
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
    worker_settings: AppSetupTestSettings,
    mock_io_for_worker_setup: Dict[str, mock.Mock],
):
    mock_init_db = mock_io_for_worker_setup["init_db"]
    await initialize_worker_context(settings=worker_settings, registry_config_module=None, rebuild_models=False)
    mock_init_db.assert_called_once()
    args, kwargs = mock_init_db.call_args
    assert args[0] == str(worker_settings.DATABASE_URL)
    assert isinstance(kwargs.get("engine_options"), dict)
    expected_pool_size = int(os.getenv("WORKER_DB_POOL_SIZE", str(worker_settings.DB_POOL_SIZE)))
    assert kwargs["engine_options"]["pool_size"] == expected_pool_size
    assert kwargs.get("echo") == (worker_settings.LOGGING_LEVEL.upper() == "DEBUG")

async def test_initialize_db_raises_runtime_error_on_failure(
    worker_settings: AppSetupTestSettings,
    mock_io_for_worker_setup: Dict[str, mock.Mock],
):
    mock_init_db = mock_io_for_worker_setup["init_db"]
    mock_init_db.side_effect = Exception("DB init failed")
    with pytest.raises(RuntimeError, match="Database initialization failed, worker cannot start."):
        await initialize_worker_context(settings=worker_settings, registry_config_module=None, rebuild_models=False)

async def test_initialize_registry_config_called_and_configures(
    worker_settings: AppSetupTestSettings,
    mock_io_for_worker_setup: Dict[str, mock.Mock],
):
    test_module_name = "fake.registry.module"
    mock_import_module = mock_io_for_worker_setup["import_module"]

    def side_effect_import_module(module_name):
        if module_name == test_module_name:
            # ИЗМЕНЕНИЕ: Добавляем read_schema_cls
            ModelRegistry.register_local(
                model_cls=Item, # SQLModel
                read_schema_cls=ItemRead, # Pydantic ReadSchema
                model_name="DummyForWorkerSetupTest"
            )
        # return mock.DEFAULT # mock.DEFAULT может не работать как ожидается для side_effect
        # Если модуль не тот, который мы мокируем, нужно вернуть что-то, что не вызовет ошибку,
        # или убедиться, что import_module вызывается только для test_module_name.
        # Если import_module может вызываться для других модулей, и они должны импортироваться реально,
        # то мокирование importlib.import_module становится сложнее.
        # Проще всего, если мы уверены, что вызывается только для test_module_name.
        # Если нет, то:
        # elif module_name.startswith("some_real_module_prefix"):
        #     return importlib.import_module(module_name) # Реальный импорт
        # else:
        #     return mock.Mock() # Мок для других непредвиденных импортов
        # Пока оставим так, предполагая, что вызывается только для test_module_name
        # или что mock.DEFAULT сработает для других вызовов (если они есть).
        # Если другие вызовы есть и mock.DEFAULT не подходит, тест может упасть иначе.
        # Для большей надежности, если import_module вызывается для других модулей,
        # лучше использовать более сложный side_effect или патчить более специфично.
        #
        # Альтернатива для side_effect, если нужно разрешить другие импорты:
        # original_import_module = importlib.import_module
        # def side_effect_import_module_with_fallback(name, package=None):
        #     if name == test_module_name:
        #         ModelRegistry.register_local(model_cls=Item, read_schema_cls=ItemRead, model_name="DummyForWorkerSetupTest")
        #         return mock.Mock() # Возвращаем мок модуля, чтобы не выполнять его код
        #     return original_import_module(name, package)
        # mock_import_module.side_effect = side_effect_import_module_with_fallback
        return None # Возвращаем None, если это мокированный импорт

    mock_import_module.side_effect = side_effect_import_module

    ModelRegistry.clear()
    assert not ModelRegistry.is_configured()

    await initialize_worker_context(
        settings=worker_settings,
        registry_config_module=test_module_name,
        rebuild_models=False,
    )

    mock_import_module.assert_called_once_with(test_module_name)
    assert ModelRegistry.is_configured()
    ModelRegistry.clear()

async def test_initialize_registry_config_not_called_if_none(
    worker_settings: AppSetupTestSettings,
    mock_io_for_worker_setup: Dict[str, mock.Mock],
):
    mock_import_module = mock_io_for_worker_setup["import_module"]
    await initialize_worker_context(settings=worker_settings, registry_config_module=None, rebuild_models=False)
    mock_import_module.assert_not_called()

async def test_initialize_registry_import_error_logged(
    worker_settings: AppSetupTestSettings,
    mock_io_for_worker_setup: Dict[str, mock.Mock],
    caplog,
):
    mock_import_module = mock_io_for_worker_setup["import_module"]
    mock_import_module.side_effect = ImportError("Cannot import module")
    await initialize_worker_context(settings=worker_settings, registry_config_module="bad.module", rebuild_models=False)
    assert "Could not import registry configuration module: bad.module" in caplog.text

async def test_initialize_rebuild_models_called(
    worker_settings: AppSetupTestSettings,
    monkeypatch: pytest.MonkeyPatch,
):
    mock_mr_rebuild = mock.Mock(name="mock_ModelRegistry_rebuild_models_local")
    monkeypatch.setattr(ModelRegistry, "rebuild_models", mock_mr_rebuild)
    await initialize_worker_context(settings=worker_settings, rebuild_models=True)
    mock_mr_rebuild.assert_called_once_with(force=True)

async def test_initialize_rebuild_models_not_called_if_false(
    worker_settings: AppSetupTestSettings,
    monkeypatch: pytest.MonkeyPatch,
):
    mock_mr_rebuild = mock.Mock(name="mock_ModelRegistry_rebuild_models_local_not_called")
    monkeypatch.setattr(ModelRegistry, "rebuild_models", mock_mr_rebuild)
    await initialize_worker_context(settings=worker_settings, rebuild_models=False)
    mock_mr_rebuild.assert_not_called()

# --- Тесты для shutdown_worker_context ---
async def test_shutdown_calls_close_db(mock_io_for_worker_setup: Dict[str, mock.Mock]):
    mock_close_db = mock_io_for_worker_setup["close_db"]
    await shutdown_worker_context()
    mock_close_db.assert_awaited_once()