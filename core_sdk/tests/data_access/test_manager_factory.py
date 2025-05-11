# core_sdk/tests/data_access/test_manager_factory.py
import pytest
import httpx # Убедимся, что httpx импортирован для AsyncClient
from unittest import mock
from typing import Optional, Any, Type, List

import pytest_asyncio
from pydantic import HttpUrl, BaseModel as PydanticBaseModel
from sqlmodel import SQLModel, Field

from core_sdk.registry import ModelRegistry, ModelInfo, RemoteConfig
from core_sdk.data_access.manager_factory import DataAccessManagerFactory, get_dam_factory
from core_sdk.data_access.base_manager import BaseDataAccessManager
from core_sdk.data_access.remote_manager import RemoteDataAccessManager
from core_sdk.exceptions import ConfigurationError
from fastapi import Request as FastAPIRequest # Для мокирования типа Request

# Используем тестовые модели и схемы из основного conftest, если они там определены и подходят.
# Если нет, определяем здесь. Для изоляции тестов SDK лучше определить их здесь или в conftest SDK.

# --- Вспомогательные классы (модели и схемы для тестов) ---
# Эти классы используются только в этом тестовом файле.

class FactoryTestItem(SQLModel, table=True):
    __tablename__ = "factory_test_items_sdk" # Уникальное имя таблицы для тестов SDK
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

class CustomLocalFactoryItemManager(BaseDataAccessManager[FactoryTestItem, FactoryTestItemCreate, FactoryTestItemUpdate]):
    # model, create_schema, update_schema могут быть установлены фабрикой
    pass

class AnotherFactoryItem(SQLModel, table=True):
    __tablename__ = "another_factory_items_sdk"
    id: Optional[int] = Field(default=None, primary_key=True)
    value: str

class AnotherFactoryItemRead(AnotherFactoryItem): pass


# --- Фикстуры ---
@pytest.fixture(autouse=True)
def clear_registry_before_each_test_in_factory_module(): # Уникальное имя фикстуры
    """Очищает ModelRegistry перед каждым тестом в этом файле."""
    ModelRegistry.clear()
    yield
    ModelRegistry.clear()

@pytest.fixture
def configured_registry_for_factory_tests(http_client: httpx.AsyncClient) -> Type[ModelRegistry]: # Уникальное имя
    """Предоставляет ModelRegistry с несколькими зарегистрированными моделями для тестов фабрики."""
    ModelRegistry.register_local(
        model_name="FactoryLocalItem",
        model_cls=FactoryTestItem,
        manager_cls=CustomLocalFactoryItemManager,
        create_schema_cls=FactoryTestItemCreate,
        update_schema_cls=FactoryTestItemUpdate,
        read_schema_cls=FactoryTestItemRead
    )
    ModelRegistry.register_local(
        model_name="FactoryLocalItemWithBaseDam",
        model_cls=AnotherFactoryItem,
        read_schema_cls=AnotherFactoryItemRead
    )
    ModelRegistry.register_remote(
        model_name="FactoryRemoteItem",
        model_cls=FactoryTestItemRead,
        config=RemoteConfig(service_url=HttpUrl("http://remote-factory-service.com"), model_endpoint="/api/v1/factoryremoteitems"),
        create_schema_cls=FactoryTestItemCreate,
        update_schema_cls=FactoryTestItemUpdate,
        read_schema_cls=FactoryTestItemRead
    )
    assert ModelRegistry.is_configured()
    return ModelRegistry

@pytest_asyncio.fixture
async def http_client() -> httpx.AsyncClient:
    async with httpx.AsyncClient() as client:
        yield client

# --- Тесты ---

def test_factory_init_raises_if_registry_not_configured():
    ModelRegistry.clear()
    with pytest.raises(ConfigurationError, match="ModelRegistry has not been configured"):
        DataAccessManagerFactory(registry=ModelRegistry)

def test_get_local_manager_custom(configured_registry_for_factory_tests: Type[ModelRegistry], http_client: httpx.AsyncClient):
    factory = DataAccessManagerFactory(http_client=http_client, registry=configured_registry_for_factory_tests)
    manager = factory.get_manager("FactoryLocalItem")

    assert isinstance(manager, CustomLocalFactoryItemManager)
    assert manager.model_name == "FactoryLocalItem" # Ожидаем оригинальное имя
    assert manager.model is FactoryTestItem
    assert manager.create_schema is FactoryTestItemCreate
    assert manager.update_schema is FactoryTestItemUpdate
    assert manager._http_client is http_client

def test_get_local_manager_base_if_none_registered(configured_registry_for_factory_tests: Type[ModelRegistry]):
    factory = DataAccessManagerFactory(registry=configured_registry_for_factory_tests)
    manager = factory.get_manager("FactoryLocalItemWithBaseDam")

    assert isinstance(manager, BaseDataAccessManager)
    assert not isinstance(manager, CustomLocalFactoryItemManager)
    assert manager.model_name == "FactoryLocalItemWithBaseDam" # Ожидаем оригинальное имя
    assert manager.model is AnotherFactoryItem
    assert manager.create_schema is None
    assert manager.update_schema is None

def test_get_local_manager_invalid_manager_cls(configured_registry_for_factory_tests: Type[ModelRegistry]):
    class NotADam: pass
    ModelRegistry.register_local(model_name="FactoryInvalidDamItem", model_cls=FactoryTestItem, manager_cls=NotADam) # type: ignore

    factory = DataAccessManagerFactory(registry=configured_registry_for_factory_tests)
    with pytest.raises(TypeError, match="is not a subclass of BaseDataAccessManager"):
        factory.get_manager("FactoryInvalidDamItem")

def test_get_remote_manager_success(configured_registry_for_factory_tests: Type[ModelRegistry], http_client: httpx.AsyncClient):
    factory_token = "test_token_factory_main"
    factory = DataAccessManagerFactory(http_client=http_client, auth_token=factory_token, registry=configured_registry_for_factory_tests)

    mock_req_with_token = mock.Mock(spec=FastAPIRequest)
    mock_req_with_token.headers = {"Authorization": "Bearer request_specific_token"}
    mock_req_with_token.cookies = {}

    manager = factory.get_manager("FactoryRemoteItem", request=mock_req_with_token)

    assert isinstance(manager, RemoteDataAccessManager)
    assert manager.auth_token == "Bearer request_specific_token"
    assert manager.client._http_client is http_client
    assert str(manager.client.base_url) == "http://remote-factory-service.com"
    assert manager.client.model_endpoint == "/api/v1/factoryremoteitems"
    assert manager.model is FactoryTestItemRead
    assert manager.read_schema is FactoryTestItemRead
    assert manager.create_schema is FactoryTestItemCreate
    assert manager.update_schema is FactoryTestItemUpdate

def test_get_remote_manager_uses_factory_token_if_no_request_token(configured_registry_for_factory_tests: Type[ModelRegistry], http_client: httpx.AsyncClient):
    factory_auth_token = "factory_default_token"
    factory = DataAccessManagerFactory(http_client=http_client, auth_token=factory_auth_token, registry=configured_registry_for_factory_tests)

    mock_req_no_token = mock.Mock(spec=FastAPIRequest); mock_req_no_token.headers = {}; mock_req_no_token.cookies = {}
    manager_with_empty_req = factory.get_manager("FactoryRemoteItem", request=mock_req_no_token)
    assert manager_with_empty_req.auth_token == factory_auth_token

    manager_no_request = factory.get_manager("FactoryRemoteItem") # request=None
    assert manager_no_request.auth_token == factory_auth_token

def test_get_remote_manager_no_http_client_raises_error(configured_registry_for_factory_tests: Type[ModelRegistry]):
    factory = DataAccessManagerFactory(registry=configured_registry_for_factory_tests, http_client=None)
    with pytest.raises(ConfigurationError, match="HTTP client required for remote manager 'FactoryRemoteItem'"):
        factory.get_manager("FactoryRemoteItem")

def test_manager_caching(configured_registry_for_factory_tests: Type[ModelRegistry], http_client: httpx.AsyncClient):
    factory = DataAccessManagerFactory(registry=configured_registry_for_factory_tests, http_client=http_client)

    manager1 = factory.get_manager("FactoryLocalItemWithBaseDam")
    manager2 = factory.get_manager("FactoryLocalItemWithBaseDam")
    assert manager1 is manager2

    mock_req = mock.Mock(spec=FastAPIRequest); mock_req.headers = {}; mock_req.cookies = {}
    # При первом вызове создается и кэшируется с токеном None (т.к. auth_token фабрики None и в mock_req нет токена)
    remote_manager1 = factory.get_manager("FactoryRemoteItem", request=mock_req)
    # При втором вызове возвращается кэшированный экземпляр.
    # Если бы в mock_req был другой токен, а кэш был бы умнее, экземпляры были бы разные.
    # Но с текущим кэшом и отсутствием токена в mock_req, они будут одинаковые.
    remote_manager2 = factory.get_manager("FactoryRemoteItem", request=mock_req)
    assert remote_manager1 is remote_manager2

def test_get_manager_model_not_found(configured_registry_for_factory_tests: Type[ModelRegistry]):
    factory = DataAccessManagerFactory(registry=configured_registry_for_factory_tests)
    # ModelRegistry.get_model_info выбрасывает ошибку с оригинальным именем (не lowercased)
    with pytest.raises(ConfigurationError, match="Model name 'NonExistentFactoryModel' not found in registry"):
        factory.get_manager("NonExistentFactoryModel")

def test_get_manager_invalid_access_config(configured_registry_for_factory_tests: Type[ModelRegistry]):
    # ModelRegistry хранит ключи в нижнем регистре
    model_key_in_registry = "factorylocalitem"
    original_model_name_case = "FactoryLocalItem"

    assert model_key_in_registry in ModelRegistry._registry
    original_info = ModelRegistry._registry[model_key_in_registry]

    modified_info = original_info.model_copy(update={"access_config": "invalid_string_config"}) # type: ignore
    ModelRegistry._registry[model_key_in_registry] = modified_info

    factory = DataAccessManagerFactory(registry=configured_registry_for_factory_tests)
    # Сообщение об ошибке будет содержать имя модели в том виде, в каком оно было передано в get_manager
    with pytest.raises(ConfigurationError, match=f"Invalid access config type for '{original_model_name_case}'"):
        factory.get_manager(original_model_name_case)

async def test_get_dam_factory_dependency(http_client: httpx.AsyncClient):
    mock_request = mock.Mock(spec=FastAPIRequest)
    mock_request.headers = {}
    mock_request.cookies = {}

    async def mock_get_global_http_client_dep(): return http_client
    async def mock_get_optional_token_dep(): return "dep_token"

    ModelRegistry.register_local(model_name="FactoryDepTestItem", model_cls=FactoryTestItem)

    factory = get_dam_factory(
        http_client=await mock_get_global_http_client_dep(),
        auth_token=await mock_get_optional_token_dep()
    )
    assert isinstance(factory, DataAccessManagerFactory)
    assert factory.http_client is http_client
    assert factory.auth_token == "dep_token"
    assert factory.registry is ModelRegistry

    manager = factory.get_manager("FactoryDepTestItem") # Будет "factorydeptestitem"
    assert isinstance(manager, BaseDataAccessManager)
    assert manager.model_name == "FactoryDepTestItem" # Проверяем оригинальное имя