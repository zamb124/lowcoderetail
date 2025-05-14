# core_sdk/tests/data_access/test_manager_factory.py
import pytest
import httpx
from unittest import mock
from typing import Optional, Any, Type, List

import pytest_asyncio
from pydantic import HttpUrl, BaseModel as PydanticBaseModel
from sqlmodel import SQLModel, Field
from starlette.requests import Request as StarletteRequest
from fastapi import Request as FastAPIRequest

from core_sdk.registry import ModelRegistry, RemoteConfig, ModelInfo
from core_sdk.data_access.manager_factory import (
    DataAccessManagerFactory,
    get_dam_factory,
)
from core_sdk.data_access.base_manager import BaseDataAccessManager
from core_sdk.data_access.local_manager import LocalDataAccessManager # Импортируем для isinstance
from core_sdk.data_access.remote_manager import RemoteDataAccessManager
from core_sdk.exceptions import ConfigurationError
from core_sdk.tests.conftest import (
    FactoryTestItem,
    FactoryTestItemCreate,
    FactoryTestItemUpdate,
    FactoryTestItemRead,
    AnotherFactoryItem,
    AnotherFactoryItemRead,
    manage_model_registry_for_tests, # Фикстура
    CustomLocalFactoryItemManager,
)
import logging # Для отладки

logger_test_mf = logging.getLogger("test_manager_factory")


@pytest_asyncio.fixture
async def http_client() -> httpx.AsyncClient:
    async with httpx.AsyncClient() as client:
        yield client

# --- Тесты ---

def test_factory_init_raises_if_registry_not_configured():
    ModelRegistry.clear() # Убедимся, что реестр пуст для этого теста
    with pytest.raises(
            ConfigurationError, match="ModelRegistry has not been configured"
    ):
        DataAccessManagerFactory(registry=ModelRegistry)
    # Восстанавливаем реестр для других тестов, если manage_model_registry_for_tests не autouse=True для этого модуля
    # Но manage_model_registry_for_tests должна быть autouse=True на уровне conftest или применена к каждому тесту.
    # Если она применяется к каждому тесту, то здесь ModelRegistry.is_configured() будет True.
    # Для этого конкретного теста мы хотим, чтобы он был False.
    # Поэтому ModelRegistry.clear() в начале этого теста - это правильно.

def test_get_local_manager_custom(http_client: httpx.AsyncClient, manage_model_registry_for_tests): # Добавил фикстуру реестра
    factory = DataAccessManagerFactory(http_client=http_client, registry=ModelRegistry)
    manager = factory.get_manager("FactoryLocalItem")

    assert isinstance(manager, CustomLocalFactoryItemManager)
    assert manager.model_name == "FactoryLocalItem"
    assert manager.model_cls is FactoryTestItemRead # ReadSchema
    assert manager.db_model_cls is FactoryTestItem # SQLModel
    assert manager.create_schema_cls is FactoryTestItemCreate
    assert manager.update_schema_cls is FactoryTestItemUpdate
    assert manager._http_client is None

def test_get_local_manager_base_if_none_registered(manage_model_registry_for_tests): # Добавил фикстуру реестра
    factory = DataAccessManagerFactory(registry=ModelRegistry)
    manager = factory.get_manager("FactoryLocalItemWithBaseDam")

    # --- Отладка для isinstance ---
    logger_test_mf.error(f"DEBUG: Type of manager: {type(manager)}, id: {id(type(manager))}, module: {type(manager).__module__}")
    logger_test_mf.error(f"DEBUG: Imported LocalDataAccessManager type: {LocalDataAccessManager}, id: {id(LocalDataAccessManager)}, module: {LocalDataAccessManager.__module__}")
    # -----------------------------

    assert isinstance(manager, LocalDataAccessManager) # Проверяем, что это LocalDataAccessManager
    assert not isinstance(manager, CustomLocalFactoryItemManager)
    assert manager.model_name == "FactoryLocalItemWithBaseDam"
    assert manager.db_model_cls is AnotherFactoryItem
    assert manager.model_cls is AnotherFactoryItemRead
    assert manager.create_schema_cls is None
    assert manager.update_schema_cls is None

def test_get_local_manager_invalid_manager_cls(manage_model_registry_for_tests): # Добавил фикстуru реестра
    class NotADam:
        pass

    # Перерегистрируем с невалидным менеджером, т.к. manage_model_registry_for_tests уже зарегистрировала
    # FactoryInvalidDamItem может не существовать, лучше использовать существующую модель и переопределить ее менеджер
    ModelRegistry.register_local(
        model_name="FactoryLocalItem", # Используем существующую модель
        model_cls=FactoryTestItem,
        manager_cls=NotADam, # Переопределяем менеджер на невалидный
    )

    factory = DataAccessManagerFactory(registry=ModelRegistry)
    with pytest.raises(TypeError, match="is not a subclass of LocalDataAccessManager"): # <--- ИЗМЕНЕННЫЙ MATCHER
        factory.get_manager("FactoryLocalItem") # Используем имя модели, для которой переопределили менеджер

def test_get_remote_manager_success(http_client: httpx.AsyncClient, manage_model_registry_for_tests): # Добавил фикстуру реестра
    factory_token = "test_token_factory_main"
    factory = DataAccessManagerFactory(
        http_client=http_client, auth_token=factory_token, registry=ModelRegistry
    )

    mock_req_with_token = mock.Mock(spec=FastAPIRequest)
    mock_req_with_token.headers = {"Authorization": "Bearer request_specific_token"}
    mock_req_with_token.cookies = {}

    manager = factory.get_manager("FactoryRemoteItem", request=mock_req_with_token)

    assert isinstance(manager, RemoteDataAccessManager)
    assert manager.auth_token == "Bearer request_specific_token"
    assert manager.client._http_client is http_client # client это RemoteServiceClient

    # RemoteServiceClient.api_base_url = base_url + "/" + model_endpoint_path
    # base_url_str = "http://remote-factory-service.com"
    # model_endpoint_path = "api/v1/factoryremoteitems" (после strip("/"))
    # Ожидаемый URL до эндпоинта модели
    expected_api_base_url = "http://remote-factory-service.com/api/v1/factoryremoteitems"
    assert str(manager.client.api_base_url) == expected_api_base_url

    assert manager.model_cls is FactoryTestItemRead
    assert manager.create_schema_cls is FactoryTestItemCreate
    assert manager.update_schema_cls is FactoryTestItemUpdate

def test_get_remote_manager_uses_factory_token_if_no_request_token(
        http_client: httpx.AsyncClient, manage_model_registry_for_tests # Добавил фикстуру реестра
):
    factory_auth_token = "factory_default_token"
    factory = DataAccessManagerFactory(
        http_client=http_client, auth_token=factory_auth_token, registry=ModelRegistry
    )

    mock_req_no_token = mock.Mock(spec=FastAPIRequest)
    mock_req_no_token.headers = {}
    mock_req_no_token.cookies = {}
    manager_with_empty_req = factory.get_manager(
        "FactoryRemoteItem", request=mock_req_no_token
    )
    assert manager_with_empty_req.auth_token == factory_auth_token

    manager_no_request = factory.get_manager("FactoryRemoteItem")
    assert manager_no_request.auth_token == factory_auth_token

def test_get_remote_manager_no_http_client_raises_error(manage_model_registry_for_tests): # Добавил фикстуру реестра
    factory = DataAccessManagerFactory(registry=ModelRegistry, http_client=None)
    with pytest.raises(
            ConfigurationError,
            match="HTTP client required for remote manager 'FactoryRemoteItem'",
    ):
        factory.get_manager("FactoryRemoteItem")

def test_manager_caching(http_client: httpx.AsyncClient, manage_model_registry_for_tests): # Добавил фикстуру реестра
    factory = DataAccessManagerFactory(registry=ModelRegistry, http_client=http_client)

    manager1 = factory.get_manager("FactoryLocalItemWithBaseDam")
    manager2 = factory.get_manager("FactoryLocalItemWithBaseDam")
    assert manager1 is manager2

    mock_req = mock.Mock(spec=FastAPIRequest)
    mock_req.headers = {}
    mock_req.cookies = {}
    remote_manager1 = factory.get_manager("FactoryRemoteItem", request=mock_req)
    remote_manager2 = factory.get_manager("FactoryRemoteItem", request=mock_req)
    assert remote_manager1 is remote_manager2

def test_get_manager_model_not_found(manage_model_registry_for_tests): # Добавил фикстуру реестра
    factory = DataAccessManagerFactory(registry=ModelRegistry)
    with pytest.raises(
            ConfigurationError,
            match="Model name 'NonExistentFactoryModel' not found in registry",
    ):
        factory.get_manager("NonExistentFactoryModel")

def test_get_manager_invalid_access_config(manage_model_registry_for_tests): # Добавил фикстуру реестра
    model_key_in_registry = "factorylocalitem"
    original_model_name_case = "FactoryLocalItem"

    assert model_key_in_registry in ModelRegistry._registry
    original_info = ModelRegistry._registry[model_key_in_registry]

    # Создаем копию и изменяем ее, чтобы не повредить оригинал для других тестов
    modified_info = original_info.model_copy(
        update={"access_config": "invalid_string_config"}
    )
    # Временно подменяем в реестре для этого теста
    original_registry_entry = ModelRegistry._registry.get(model_key_in_registry)
    ModelRegistry._registry[model_key_in_registry] = modified_info # type: ignore

    factory = DataAccessManagerFactory(registry=ModelRegistry)
    with pytest.raises(
            ConfigurationError,
            match=f"Invalid access config type for '{original_model_name_case}'",
    ):
        factory.get_manager(original_model_name_case)

    # Восстанавливаем оригинальную запись в реестре
    if original_registry_entry:
        ModelRegistry._registry[model_key_in_registry] = original_registry_entry
    else: # Если ее не было (маловероятно, но на всякий случай)
        del ModelRegistry._registry[model_key_in_registry]


@pytest_asyncio.fixture # Используем async фикстуру, так как зависимости async
async def dam_factory_for_dep_test(http_client: httpx.AsyncClient, manage_model_registry_for_tests): # Добавил фикстуру реестра
    # Эта фикстура нужна, чтобы get_dam_factory имела доступ к ModelRegistry
    # и могла создать DataAccessManagerFactory
    # ModelRegistry уже настроен через manage_model_registry_for_tests
    async def mock_get_global_http_client_dep():
        return http_client
    async def mock_get_optional_token_dep():
        return "dep_token"

    # Мокируем зависимости внутри get_dam_factory
    # Это сложнее, так как get_dam_factory сама является зависимостью.
    # Проще протестировать get_dam_factory, вызвав ее напрямую с моками.
    factory = get_dam_factory(
        http_client=await mock_get_global_http_client_dep(),
        auth_token=await mock_get_optional_token_dep(),
    )
    return factory

async def test_get_dam_factory_dependency(dam_factory_for_dep_test: DataAccessManagerFactory, http_client: httpx.AsyncClient):
    factory = dam_factory_for_dep_test # Получаем уже созданную фабрику

    assert isinstance(factory, DataAccessManagerFactory)
    assert factory.http_client is http_client
    assert factory.auth_token == "dep_token"
    assert factory.registry is ModelRegistry

    # Проверяем, что можем получить менеджер
    manager = factory.get_manager("FactoryLocalItem")
    assert isinstance(manager, CustomLocalFactoryItemManager)
    assert manager.model_name == "FactoryLocalItem"