# core_sdk/tests/data_access/test_manager_factory.py
import pytest
import httpx
from unittest import mock

import pytest_asyncio
from fastapi import Request as FastAPIRequest

from core_sdk.registry import ModelRegistry
from core_sdk.data_access.manager_factory import (
    DataAccessManagerFactory,
    get_dam_factory,
)
# Импортируем правильные базовые классы и дженерики
from core_sdk.data_access.local_manager import LocalDataAccessManager
from core_sdk.data_access.remote_manager import RemoteDataAccessManager
from core_sdk.exceptions import ConfigurationError

# Импортируем тестовые модели и схемы из conftest SDK
from core_sdk.tests.conftest import (
    FactoryTestItem, # SQLModel
    FactoryTestItemCreate,
    FactoryTestItemUpdate,
    FactoryTestItemRead, # Pydantic ReadSchema
    AnotherFactoryItem, # SQLModel
    AnotherFactoryItemRead, # Pydantic ReadSchema
    CustomLocalFactoryItemManager, # Этот менеджер уже адаптирован в conftest
)
import logging

logger_test_mf = logging.getLogger("test_manager_factory")


@pytest_asyncio.fixture
async def http_client() -> httpx.AsyncClient:
    async with httpx.AsyncClient() as client:
        yield client

# --- Тесты ---

def test_factory_init_raises_if_registry_not_configured():
    ModelRegistry.clear()
    with pytest.raises(
            ConfigurationError, match="ModelRegistry has not been configured"
    ):
        DataAccessManagerFactory(registry=ModelRegistry)

def test_get_local_manager_custom(http_client: httpx.AsyncClient, manage_model_registry_for_tests):
    factory = DataAccessManagerFactory(http_client=http_client, registry=ModelRegistry)
    # "FactoryLocalItem" зарегистрирован с CustomLocalFactoryItemManager,
    # FactoryTestItem (SQLModel) как model_cls, и FactoryTestItemRead (Pydantic) как read_schema_cls
    manager = factory.get_manager("FactoryLocalItem")

    assert isinstance(manager, CustomLocalFactoryItemManager)
    assert manager.model_name == "FactoryLocalItem"
    # ИЗМЕНЕНИЕ: manager.model_cls теперь SQLModel
    assert manager.model_cls is FactoryTestItem
    # ИЗМЕНЕНИЕ: manager.read_schema_cls теперь Pydantic ReadSchema
    assert manager.read_schema_cls is FactoryTestItemRead
    assert manager.create_schema_cls is FactoryTestItemCreate
    assert manager.update_schema_cls is FactoryTestItemUpdate
    assert manager._http_client is None # Для LocalManager

def test_get_local_manager_base_if_none_registered(manage_model_registry_for_tests):
    factory = DataAccessManagerFactory(registry=ModelRegistry)
    # "FactoryLocalItemWithBaseDam" зарегистрирован с AnotherFactoryItem (SQLModel) как model_cls
    # и AnotherFactoryItemRead (Pydantic) как read_schema_cls, без кастомного менеджера
    manager = factory.get_manager("FactoryLocalItemWithBaseDam")

    assert isinstance(manager, LocalDataAccessManager)
    assert not isinstance(manager, CustomLocalFactoryItemManager) # Убедимся, что это не кастомный
    assert manager.model_name == "FactoryLocalItemWithBaseDam"
    # ИЗМЕНЕНИЕ: manager.model_cls теперь SQLModel, нет db_model_cls
    assert manager.model_cls is AnotherFactoryItem
    assert manager.read_schema_cls is AnotherFactoryItemRead
    assert manager.create_schema_cls is None
    assert manager.update_schema_cls is None

def test_get_local_manager_invalid_manager_cls(manage_model_registry_for_tests):
    class NotADam:
        pass

    # ИЗМЕНЕНИЕ: ModelRegistry.register_local теперь требует read_schema_cls
    ModelRegistry.register_local(
        model_name="FactoryLocalItemForInvalidDam", # Новое имя, чтобы не конфликтовать
        model_cls=FactoryTestItem, # SQLModel
        read_schema_cls=FactoryTestItemRead, # Pydantic ReadSchema
        manager_cls=NotADam,
    )

    factory = DataAccessManagerFactory(registry=ModelRegistry)
    with pytest.raises(TypeError, match="is not a subclass of LocalDataAccessManager"):
        factory.get_manager("FactoryLocalItemForInvalidDam")

def test_get_remote_manager_success(http_client: httpx.AsyncClient, manage_model_registry_for_tests):
    factory_token = "test_token_factory_main"
    factory = DataAccessManagerFactory(
        http_client=http_client, auth_token=factory_token, registry=ModelRegistry
    )

    mock_req_with_token = mock.Mock(spec=FastAPIRequest)
    mock_req_with_token.headers = {"Authorization": "Bearer request_specific_token"}
    mock_req_with_token.cookies = {}

    # "FactoryRemoteItem" зарегистрирован с FactoryTestItemRead (Pydantic) как model_cls и read_schema_cls
    manager = factory.get_manager("FactoryRemoteItem", request=mock_req_with_token)

    assert isinstance(manager, RemoteDataAccessManager)
    assert manager.auth_token == "Bearer request_specific_token" # Токен из запроса
    assert manager.client._http_client is http_client

    expected_api_base_url = "http://remote-factory-service.com/api/v1/factoryremoteitems"
    assert str(manager.client.api_base_url) == expected_api_base_url

    # Для RemoteManager, model_cls и read_schema_cls это одно и то же (Pydantic ReadSchema)
    assert manager.model_cls is FactoryTestItemRead
    assert manager.read_schema_cls is FactoryTestItemRead
    assert manager.create_schema_cls is FactoryTestItemCreate
    assert manager.update_schema_cls is FactoryTestItemUpdate

def test_get_remote_manager_uses_factory_token_if_no_request_token(
        http_client: httpx.AsyncClient, manage_model_registry_for_tests
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

def test_get_remote_manager_no_http_client_raises_error(manage_model_registry_for_tests):
    factory = DataAccessManagerFactory(registry=ModelRegistry, http_client=None)
    with pytest.raises(
            ConfigurationError,
            match="HTTP client required for remote manager 'FactoryRemoteItem'",
    ):
        factory.get_manager("FactoryRemoteItem")

def test_manager_caching(http_client: httpx.AsyncClient, manage_model_registry_for_tests):
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

def test_get_manager_model_not_found(manage_model_registry_for_tests):
    factory = DataAccessManagerFactory(registry=ModelRegistry)
    with pytest.raises(
            ConfigurationError,
            match="Model name 'NonExistentFactoryModel' not found in registry",
    ):
        factory.get_manager("NonExistentFactoryModel")

def test_get_manager_invalid_access_config(manage_model_registry_for_tests):
    model_key_in_registry = "factorylocalitem"
    original_model_name_case = "FactoryLocalItem"

    assert model_key_in_registry in ModelRegistry._registry

    # Получаем существующий ModelInfo
    original_info = ModelRegistry._registry[model_key_in_registry]

    # Сохраняем оригинальное значение access_config, чтобы восстановить его
    saved_access_config = original_info.access_config

    # "Вручную" устанавливаем невалидное значение, обходя валидацию Pydantic
    # Это делается для имитации ситуации, когда в реестре может оказаться
    # некорректно сконфигурированный ModelInfo (например, из-за ошибки в коде регистрации).
    # ВАЖНО: Это хак для теста, в реальном коде так делать не нужно.
    try:
        # Пытаемся присвоить напрямую. Если ModelInfo заморожен (frozen=True), это не сработает.
        # ModelInfo по умолчанию не frozen.
        original_info.access_config = "invalid_string_config_for_test" # type: ignore
    except Exception as e:
        pytest.skip(f"Could not directly modify ModelInfo.access_config for test: {e}")


    factory = DataAccessManagerFactory(registry=ModelRegistry)
    with pytest.raises(
            ConfigurationError,
            match=f"Invalid access config type for '{original_model_name_case}'",
    ):
        factory.get_manager(original_model_name_case)

    # Восстанавливаем оригинальное значение access_config
    original_info.access_config = saved_access_config
    # Перепроверяем, что реестр вернулся в корректное состояние (опционально)
    assert ModelRegistry._registry[model_key_in_registry].access_config == "local"


@pytest_asyncio.fixture
async def dam_factory_for_dep_test(http_client: httpx.AsyncClient, manage_model_registry_for_tests):
    async def mock_get_global_http_client_dep(): return http_client
    async def mock_get_optional_token_dep(): return "dep_token"

    factory = get_dam_factory(
        http_client=await mock_get_global_http_client_dep(),
        auth_token=await mock_get_optional_token_dep(),
    )
    return factory

async def test_get_dam_factory_dependency(dam_factory_for_dep_test: DataAccessManagerFactory, http_client: httpx.AsyncClient):
    factory = dam_factory_for_dep_test

    assert isinstance(factory, DataAccessManagerFactory)
    assert factory.http_client is http_client
    assert factory.auth_token == "dep_token"
    assert factory.registry is ModelRegistry

    manager = factory.get_manager("FactoryLocalItem")
    assert isinstance(manager, CustomLocalFactoryItemManager)
    assert manager.model_name == "FactoryLocalItem"