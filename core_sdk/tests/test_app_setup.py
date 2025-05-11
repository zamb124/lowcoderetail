# core_sdk/tests/test_app_setup.py
import pytest
import httpx
from unittest import mock # Оставляем mock
from typing import List, Optional, Callable, Awaitable, Type, Sequence

from fastapi import FastAPI, APIRouter as FastAPIAPIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel as PydanticBaseModel # <--- ДОБАВЛЕН ИМПОРТ

from core_sdk.app_setup import create_app_with_sdk_setup # Тестируемая функция
from core_sdk.config import BaseAppSettings
from core_sdk.registry import ModelRegistry
# Пути для патчинга:
# import core_sdk.broker.setup as broker_setup_module # Неправильно, нужно патчить там, где используется
# import core_sdk.db.session as db_session_module
# import core_sdk.data_access.common as data_access_common_module

# Используем фикстуру настроек из conftest
from .conftest import AppSetupTestSettings, app_setup_settings # app_setup_settings уже фикстура
from .conftest import (
    mock_before_startup, mock_after_startup, mock_before_shutdown, mock_after_shutdown,
    mock_broker, mock_model_registry_rebuild, mock_sdk_init_db, mock_sdk_close_db,
    mock_app_http_client_lifespan_cm
)

# --- Тесты для create_app_with_sdk_setup ---

def test_create_app_basic_properties(app_setup_settings: AppSetupTestSettings):
    router1 = FastAPIAPIRouter(prefix="/r1")
    @router1.get("/test")
    async def _():
        return {"ok": True} # Добавил async

    app = create_app_with_sdk_setup(
        settings=app_setup_settings, api_routers=[router1],
        enable_broker=False, rebuild_models=False, manage_http_client=False,
        enable_auth_middleware=False, include_health_check=False
    )
    assert isinstance(app, FastAPI)
    assert app.title == app_setup_settings.PROJECT_NAME
    assert app.openapi_url == f"{app_setup_settings.API_V1_STR}/openapi.json"
    assert app.docs_url == f"{app_setup_settings.API_V1_STR}/docs"

def test_create_app_with_health_check(app_setup_settings: AppSetupTestSettings):
    app = create_app_with_sdk_setup(settings=app_setup_settings, api_routers=[], include_health_check=True, enable_auth_middleware=False)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "project": app_setup_settings.PROJECT_NAME}

def test_create_app_without_health_check(app_setup_settings: AppSetupTestSettings):
    app = create_app_with_sdk_setup(settings=app_setup_settings, api_routers=[], include_health_check=False, enable_auth_middleware=False)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 404

def test_create_app_auth_middleware_enabled(app_setup_settings: AppSetupTestSettings):
    app = create_app_with_sdk_setup(settings=app_setup_settings, api_routers=[], enable_auth_middleware=True)
    auth_mw_found = False
    for mw in app.user_middleware:
        if hasattr(mw, "cls") and mw.cls.__name__ == "AuthMiddleware":
            auth_mw_found = True
            allowed_paths = mw.kwargs.get("allowed_paths", []) # <--- ИСПРАВЛЕНИЕ: mw.kwargs
            assert f"{app_setup_settings.API_V1_STR}/docs" in allowed_paths
            assert "/health" in allowed_paths
            break
    assert auth_mw_found, "AuthMiddleware not found when it should be enabled"

def test_create_app_auth_middleware_disabled(app_setup_settings: AppSetupTestSettings):
    app = create_app_with_sdk_setup(settings=app_setup_settings, api_routers=[], enable_auth_middleware=False)
    auth_mw_found = any(hasattr(mw, "cls") and mw.cls.__name__ == "AuthMiddleware" for mw in app.user_middleware)
    assert not auth_mw_found, "AuthMiddleware found when it should be disabled"

def test_create_app_cors_middleware_enabled(app_setup_settings: AppSetupTestSettings):
    app = create_app_with_sdk_setup(settings=app_setup_settings, api_routers=[])
    cors_mw_found = False
    for mw in app.user_middleware:
        if hasattr(mw, "cls") and mw.cls.__name__ == "CORSMiddleware":
            cors_mw_found = True
            assert set(mw.kwargs.get("allow_origins", [])) == set(app_setup_settings.BACKEND_CORS_ORIGINS) # <--- ИСПРАВЛЕНИЕ: mw.kwargs
            break
    assert cors_mw_found, "CORSMiddleware not found when origins are set"

def test_create_app_cors_middleware_disabled_if_no_origins():
    settings_no_cors = AppSetupTestSettings(BACKEND_CORS_ORIGINS=[])
    app = create_app_with_sdk_setup(settings=settings_no_cors, api_routers=[])
    cors_mw_found = any(hasattr(mw, "cls") and mw.cls.__name__ == "CORSMiddleware" for mw in app.user_middleware)
    assert not cors_mw_found, "CORSMiddleware found when origins are empty"


@pytest.mark.asyncio
async def test_lifespan_calls_hooks_and_manages_resources(
        app_setup_settings: AppSetupTestSettings,
        mock_before_startup: mock.AsyncMock, mock_after_startup: mock.AsyncMock,
        mock_before_shutdown: mock.AsyncMock, mock_after_shutdown: mock.AsyncMock,
        mock_broker: mock.AsyncMock, mock_model_registry_rebuild: mock.Mock,
        mock_sdk_init_db: mock.Mock, mock_sdk_close_db: mock.AsyncMock,
        mock_app_http_client_lifespan_cm: mock.Mock
):
    # Патчим зависимости ТАМ, ГДЕ ОНИ ИМПОРТИРУЮТСЯ И ИСПОЛЬЗУЮТСЯ,
    # то есть внутри модуля core_sdk.app_setup
    with mock.patch('core_sdk.app_setup.broker', mock_broker), \
            mock.patch('core_sdk.app_setup.ModelRegistry.rebuild_models', mock_model_registry_rebuild), \
            mock.patch('core_sdk.app_setup.init_db', mock_sdk_init_db), \
            mock.patch('core_sdk.app_setup.close_db', mock_sdk_close_db), \
            mock.patch('core_sdk.app_setup.app_http_client_lifespan', mock_app_http_client_lifespan_cm):

        app = create_app_with_sdk_setup(
            settings=app_setup_settings, api_routers=[],
            enable_broker=True, rebuild_models=True, manage_http_client=True,
            before_startup_hook=mock_before_startup, after_startup_hook=mock_after_startup,
            before_shutdown_hook=mock_before_shutdown, after_shutdown_hook=mock_after_shutdown,
            enable_auth_middleware=False, include_health_check=False
        )

        with TestClient(app) as client:
            mock_before_startup.assert_awaited_once()
            mock_sdk_init_db.assert_called_once() # <--- Теперь должно работать
            mock_broker.startup.assert_awaited_once()
            mock_model_registry_rebuild.assert_called_once()
            assert getattr(app.state, 'http_client_mocked', False) is True
            mock_after_startup.assert_awaited_once()

        mock_before_shutdown.assert_awaited_once()
        mock_broker.shutdown.assert_awaited_once()
        mock_sdk_close_db.assert_awaited_once()
        assert getattr(app.state, 'http_client_mocked', True) is False
        mock_after_shutdown.assert_awaited_once()

@pytest.mark.asyncio
async def test_lifespan_rebuild_specific_schemas(
        app_setup_settings: AppSetupTestSettings,
        mock_model_registry_rebuild: mock.Mock
):
    class SchemaA(PydanticBaseModel): pass # PydanticBaseModel теперь импортирован
    class SchemaB(PydanticBaseModel): pass

    SchemaA.model_rebuild = mock.Mock() # type: ignore
    SchemaB.model_rebuild = mock.Mock() # type: ignore

    # Патчим ModelRegistry.rebuild_models в app_setup, если он там используется напрямую
    # или глобально, если sdk_lifespan_manager его так вызывает.
    # sdk_lifespan_manager вызывает ModelRegistry.rebuild_models напрямую.
    with mock.patch.object(ModelRegistry, 'rebuild_models', mock_model_registry_rebuild), \
            mock.patch('core_sdk.app_setup.init_db', mock.Mock()): # Мокируем init_db, чтобы избежать ошибки БД

        app = create_app_with_sdk_setup(
            settings=app_setup_settings, api_routers=[],
            rebuild_models=True,
            schemas_to_rebuild=[SchemaA, SchemaB],
            enable_broker=False, manage_http_client=False, enable_auth_middleware=False,
            include_health_check=False # Отключаем health_check, чтобы не было зависимости от БД
        )
        with TestClient(app):
            pass

    mock_model_registry_rebuild.assert_called_once()
    SchemaA.model_rebuild.assert_called_once_with(force=True)
    SchemaB.model_rebuild.assert_called_once_with(force=True)