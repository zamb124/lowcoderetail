# core_sdk/tests/crud/test_crud_router_factory.py
import pytest
import uuid
from typing import Any
from unittest import mock

from fastapi import FastAPI, Depends, APIRouter
from fastapi.testclient import TestClient

from core_sdk.crud.factory import CRUDRouterFactory
from core_sdk.data_access import (
    BaseDataAccessManager,
    DataAccessManagerFactory,
    get_dam_factory,
)
from core_sdk.exceptions import ConfigurationError
from core_sdk.filters.base import DefaultFilter  # Импортируем наш DefaultFilter

# Используем тестовые модели и схемы из общего conftest.py для SDK
from core_sdk.tests.conftest import (
    CrudFactoryItem,
    CrudFactoryItemCreate,
    CrudFactoryItemUpdate,
    CrudFactoryItemRead,
    CrudFactoryItemFilter,  # Используем эти для тестов CRUD factory
    CrudSimpleItem,
)

pytestmark = pytest.mark.asyncio


def dep_func_ok():
    return True


@pytest.fixture(autouse=True)
def manage_registry_for_crud_tests(
    manage_model_registry_for_tests: Any,
):  # Зависим от общей фикстуры
    """Эта фикстура просто существует, чтобы показать зависимость от общей настройки реестра."""
    pass


@pytest.fixture
def mock_dam_factory() -> mock.Mock:
    factory_mock = mock.Mock(spec=DataAccessManagerFactory)
    mocked_dam_instance = mock.AsyncMock(spec=BaseDataAccessManager)
    factory_mock.get_manager.return_value = mocked_dam_instance
    return factory_mock


# --- Тесты инициализации CRUDRouterFactory ---


def test_factory_init_success():  # manage_registry_for_crud_tests уже отработала
    factory = CRUDRouterFactory(
        model_name="CrudFactoryItem", prefix="/cfitems", tags=["CFTest"]
    )
    assert factory.model_name == "CrudFactoryItem"
    assert factory.model_cls is CrudFactoryItem
    assert factory.create_schema_cls is CrudFactoryItemCreate
    assert factory.update_schema_cls is CrudFactoryItemUpdate
    assert factory.read_schema_cls is CrudFactoryItemRead
    assert (
        factory.filter_cls is CrudFactoryItemFilter
    )  # CrudFactoryItemFilter зарегистрирован в conftest
    assert isinstance(factory.router, APIRouter)


def test_factory_init_model_not_found_raises_error():
    with pytest.raises(
        ConfigurationError,
        match="Configuration Error: Model name 'NonExistent' not found in registry. Available models",
    ):  # Ожидаем оригинальный регистр
        CRUDRouterFactory(model_name="NonExistent", prefix="/none")


def test_factory_init_default_filter_created_if_none_registered():
    # CrudSimpleItem зарегистрирован в conftest без явного фильтра
    factory = CRUDRouterFactory(model_name="CrudSimpleItem", prefix="/itemnofilter")
    assert factory.filter_cls is not None
    assert factory.filter_cls.__name__ == "CrudSimpleItemDefaultCRUDFilter"
    assert issubclass(factory.filter_cls, DefaultFilter)
    assert hasattr(factory.filter_cls, "Constants")
    assert factory.filter_cls.Constants.model is CrudSimpleItem
    assert hasattr(
        factory.filter_cls.Constants, "ordering_field_name"
    )  # Проверяем наличие


# --- Тесты генерации маршрутов ---


def test_factory_generates_all_routes_if_deps_provided():
    deps = [Depends(dep_func_ok)]
    # Используем CrudFactoryItem, так как для него все схемы зарегистрированы в conftest
    factory = CRUDRouterFactory(
        model_name="CrudFactoryItem",
        prefix="/items",
        list_deps=deps,
        get_deps=deps,
        create_deps=deps,
        update_deps=deps,
        delete_deps=deps,
    )
    paths = {route.path for route in factory.router.routes}
    assert "/items" in paths

    methods_for_root = {
        m for r in factory.router.routes if r.path == "/items" for m in r.methods
    }
    methods_for_id = {
        m
        for r in factory.router.routes
        if r.path == "/items/{item_id}"
        for m in r.methods
    }

    assert "GET" in methods_for_root
    assert "POST" in methods_for_root
    assert "GET" in methods_for_id
    assert "PUT" in methods_for_id
    assert "DELETE" in methods_for_id


def test_factory_skips_routes_if_deps_are_none():
    factory = CRUDRouterFactory(
        model_name="CrudFactoryItem",
        prefix="/items",
        list_deps=[Depends(dep_func_ok)],
        get_deps=None,
        create_deps=[Depends(dep_func_ok)],
        update_deps=None,
        delete_deps=[Depends(dep_func_ok)],
    )
    has_get_id_route = any(
        route.path == "/{item_id}" and "GET" in route.methods
        for route in factory.router.routes
    )
    has_put_id_route = any(
        route.path == "/{item_id}" and "PUT" in route.methods
        for route in factory.router.routes
    )
    assert not has_get_id_route
    assert not has_put_id_route
    assert any(
        route.path == "/items" and "GET" in route.methods
        for route in factory.router.routes
    )


def test_factory_skips_create_if_no_create_schema():
    # CrudSimpleItem зарегистрирован без create_schema_cls в conftest
    factory = CRUDRouterFactory(
        model_name="CrudSimpleItem",
        prefix="/simple",
        create_deps=[Depends(dep_func_ok)],
    )
    has_post_route = any(
        route.path == "" and "POST" in route.methods for route in factory.router.routes
    )
    assert not has_post_route


def test_factory_skips_update_if_no_update_schema():
    # CrudSimpleItem зарегистрирован без update_schema_cls в conftest
    factory = CRUDRouterFactory(
        model_name="CrudSimpleItem",
        prefix="/simple",
        update_deps=[Depends(dep_func_ok)],
    )
    has_put_route = any(
        route.path == "/{item_id}" and "PUT" in route.methods
        for route in factory.router.routes
    )
    assert not has_put_route


# --- Интеграционные тесты для сгенерированных эндпоинтов ---
@pytest.fixture
def app_with_crud_router(
    mock_dam_factory: mock.Mock,
) -> (
    FastAPI
):  # manage_registry_for_crud_tests не нужна, т.к. manage_model_registry_sdk - autouse
    factory = CRUDRouterFactory(
        model_name="CrudFactoryItem",
        prefix="/crud_items",  # Используем модель со всеми схемами
        list_deps=[],
        get_deps=[],
        create_deps=[],
        update_deps=[],
        delete_deps=[],
    )
    app = FastAPI()
    app.include_router(factory.router)
    app.dependency_overrides[get_dam_factory] = lambda: mock_dam_factory
    return app


@pytest.fixture
def client(app_with_crud_router: FastAPI) -> TestClient:
    return TestClient(app_with_crud_router)


@pytest.fixture
def mock_dam(mock_dam_factory: mock.Mock) -> mock.AsyncMock:
    dam_instance = mock_dam_factory.get_manager.return_value
    dam_instance.model_name = "CrudFactoryItem"
    return dam_instance


async def test_generated_list_endpoint(client: TestClient, mock_dam: mock.AsyncMock):
    item_id_list = uuid.uuid4()
    # Мок DAM.list должен вернуть словарь, где items - это список экземпляров CrudFactoryItemRead
    mock_items_list_instances = [
        CrudFactoryItemRead(id=item_id_list, name="Item 1", description=None)
    ]
    mock_dam.list.return_value = {
        "items": mock_items_list_instances,
        "next_cursor": None,
        "limit": 1,
        "count": 1,
    }

    response = client.get("/crud_items?limit=1&name__like=Test")
    assert response.status_code == 200
    data = response.json()  # FastAPI сериализует mock_items_list_instances

    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "Item 1"

    mock_dam.list.assert_awaited_once()
    call_kwargs = mock_dam.list.call_args.kwargs
    assert isinstance(call_kwargs["filters"], CrudFactoryItemFilter)


async def test_generated_create_endpoint(client: TestClient, mock_dam: mock.AsyncMock):
    item_id_create = uuid.uuid4()
    post_data = {"name": "New CRUD Item", "description": "Created via factory"}
    mock_dam.create.return_value = CrudFactoryItemRead(
        id=item_id_create, name=post_data["name"], description=post_data["description"]
    )
    response = client.post("/crud_items", json=post_data)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == post_data["name"]
    assert data["id"] == str(item_id_create)
    mock_dam.create.assert_awaited_once()
    arg_passed_to_create = mock_dam.create.call_args.args[0]
    assert isinstance(arg_passed_to_create, CrudFactoryItemCreate)
    assert arg_passed_to_create.name == post_data["name"]


async def test_generated_get_endpoint(client: TestClient, mock_dam: mock.AsyncMock):
    item_id_get = uuid.uuid4()
    mock_dam.get.return_value = CrudFactoryItemRead(
        id=item_id_get, name="Fetched Item", description=None
    )
    response = client.get(f"/crud_items/{item_id_get}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(item_id_get)
    mock_dam.get.assert_awaited_once_with(item_id_get)


async def test_generated_get_endpoint_not_found(
    client: TestClient, mock_dam: mock.AsyncMock
):
    item_id_get_nf = uuid.uuid4()
    mock_dam.get.return_value = None
    response = client.get(f"/crud_items/{item_id_get_nf}")
    assert response.status_code == 404


async def test_generated_update_endpoint(client: TestClient, mock_dam: mock.AsyncMock):
    item_id_update = uuid.uuid4()
    update_data = {"name": "Updated CRUD Item"}
    mock_dam.update.return_value = CrudFactoryItemRead(
        id=item_id_update, name="Updated CRUD Item", description=None
    )
    response = client.put(f"/crud_items/{item_id_update}", json=update_data)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated CRUD Item"
    mock_dam.update.assert_awaited_once()
    call_args = mock_dam.update.call_args.args
    assert call_args[0] == item_id_update
    assert isinstance(call_args[1], CrudFactoryItemUpdate)
    assert call_args[1].name == update_data["name"]


async def test_generated_delete_endpoint(client: TestClient, mock_dam: mock.AsyncMock):
    item_id_delete = uuid.uuid4()
    mock_dam.delete.return_value = True
    response = client.delete(f"/crud_items/{item_id_delete}")
    assert response.status_code == 204
    mock_dam.delete.assert_awaited_once_with(item_id_delete)


async def test_generated_delete_endpoint_fails_returns_500(
    client: TestClient, mock_dam: mock.AsyncMock
):
    item_id_delete_fail = uuid.uuid4()
    mock_dam.delete.return_value = False
    response = client.delete(f"/crud_items/{item_id_delete_fail}")
    assert response.status_code == 500
