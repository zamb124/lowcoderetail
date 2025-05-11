# core_sdk/tests/data_access/test_remote_manager.py
import pytest
import httpx
import uuid
import json  # Добавим для route.calls[0].request.content
from typing import List, Optional, Dict, Any

import pytest_asyncio
from pydantic import HttpUrl

from respx import (
    MockRouter,
)  # MockRouter - это то, что мы используем для respx_mock.api или respx_mock.route()

from core_sdk.registry import RemoteConfig
from core_sdk.data_access.remote_manager import RemoteDataAccessManager
from core_sdk.exceptions import (
    ServiceCommunicationError,
    ConfigurationError,
)  # ConfigurationError используется
from fastapi import HTTPException

from core_sdk.tests.conftest import Item, ItemCreate, ItemUpdate, ItemRead

pytestmark = pytest.mark.asyncio

SERVICE_BASE_URL = "http://test-remote-service.com"
API_PREFIX = "/api/v1"
MODEL_ENDPOINT_PATH = "items"
# RemoteDataAccessManager сам добавляет / к model_endpoint, если его нет,
# и конкатенирует с base_url.
# FULL_MODEL_URL будет формироваться внутри RemoteDataAccessManager как self.api_base_url
# Для мокирования нам нужен полный URL, который будет запрашиваться.
# remote_config.model_endpoint уже содержит API_PREFIX.
# RemoteDataAccessManager.api_base_url будет SERVICE_BASE_URL + remote_config.model_endpoint
# Это не совсем так. RemoteDataAccessManager.api_base_url = SERVICE_BASE_URL + "/" + MODEL_ENDPOINT_PATH (если MODEL_ENDPOINT_PATH не начинается с /)
# А remote_config.model_endpoint это /api/v1/items
# Значит, RemoteServiceClient.api_base_url будет SERVICE_BASE_URL + /api/v1/items

# Давайте определим URL, который будет использоваться в respx.route()
# RemoteServiceClient._request будет использовать self.api_base_url + "/" + item_id
# self.api_base_url = self.base_url + self.model_endpoint
# В нашем случае:
# remote_config.service_url = "http://test-remote-service.com"
# remote_config.model_endpoint = "/api/v1/items"
# Значит, RemoteServiceClient.api_base_url = "http://test-remote-service.com/api/v1/items"

MOCKED_API_BASE_URL = f"{SERVICE_BASE_URL}{API_PREFIX}/{MODEL_ENDPOINT_PATH}"


@pytest.fixture
def remote_config() -> RemoteConfig:
    return RemoteConfig(
        service_url=HttpUrl(SERVICE_BASE_URL),
        model_endpoint=f"{API_PREFIX}/{MODEL_ENDPOINT_PATH}",
    )


@pytest_asyncio.fixture
async def mock_http_client() -> httpx.AsyncClient:  # Убираем AsyncGenerator
    # Просто создаем и возвращаем клиент.
    # Его закрытие не так критично для тестов, где запросы мокируются,
    # но для чистоты можно было бы использовать async with, если бы мы его здесь же и использовали.
    # Так как мы его только передаем, просто создадим.
    # respx будет перехватывать его вызовы.
    client = httpx.AsyncClient()
    yield client  # Для фикстур pytest, yield все еще используется для предоставления значения
    # и выполнения кода очистки после.
    await client.aclose()  # Закрываем клиент после теста


@pytest.fixture
def remote_item_manager(
    remote_config: RemoteConfig, mock_http_client: httpx.AsyncClient
) -> RemoteDataAccessManager[Item, ItemCreate, ItemUpdate]:
    return RemoteDataAccessManager(
        remote_config=remote_config,
        http_client=mock_http_client,
        model_cls=Item,
        create_schema_cls=ItemCreate,
        update_schema_cls=ItemUpdate,
        read_schema_cls=ItemRead,
    )


# --- Тесты ---
async def test_remote_get_success(
    remote_item_manager: RemoteDataAccessManager, respx_mock: MockRouter
):  # ИЗМЕНЕНО
    item_id = uuid.uuid4()
    expected_item_data = {"id": str(item_id), "name": "Remote Item 1", "lsn": 1}

    # MOCKED_API_BASE_URL это "http://test-remote-service.com/api/v1/items"
    respx_mock.get(f"{MOCKED_API_BASE_URL}/{item_id}").respond(
        200, json=expected_item_data
    )

    item = await remote_item_manager.get(item_id)

    assert item is not None
    assert isinstance(item, ItemRead)
    assert item.id == item_id
    assert item.name == "Remote Item 1"


async def test_remote_get_not_found(
    remote_item_manager: RemoteDataAccessManager, respx_mock: MockRouter
):  # ИЗМЕНЕНО
    item_id = uuid.uuid4()
    respx_mock.get(f"{MOCKED_API_BASE_URL}/{item_id}").respond(404)
    item = await remote_item_manager.get(item_id)
    assert item is None


async def test_remote_get_server_error(
    remote_item_manager: RemoteDataAccessManager, respx_mock: MockRouter
):  # ИЗМЕНЕНО
    item_id = uuid.uuid4()
    respx_mock.get(f"{MOCKED_API_BASE_URL}/{item_id}").respond(
        500, json={"detail": "Internal Server Error"}
    )
    with pytest.raises(HTTPException) as exc_info:
        await remote_item_manager.get(item_id)
    assert exc_info.value.status_code == 500


async def test_remote_list_success(
    remote_item_manager: RemoteDataAccessManager, respx_mock: MockRouter
):  # ИЗМЕНЕНО
    item1_id, item2_id = uuid.uuid4(), uuid.uuid4()
    # Предположим, что RemoteDataAccessManager.list теперь возвращает словарь, как BaseDataAccessManager
    mock_response_data = {
        "items": [
            {"id": str(item1_id), "name": "Item A", "lsn": 10},
            {"id": str(item2_id), "name": "Item B", "lsn": 11},
        ],
        "next_cursor": 11,  # Пример
        "limit": 2,
        "count": 2,
    }
    # URL для списка это MOCKED_API_BASE_URL (без item_id)
    respx_mock.get(MOCKED_API_BASE_URL).respond(200, json=mock_response_data)

    items_list_dict = await remote_item_manager.list(limit=2)

    items = items_list_dict
    assert len(items) == 2
    assert isinstance(items[0], ItemRead)
    assert items[0].name == "Item A"


async def test_remote_list_with_params(
    remote_item_manager: RemoteDataAccessManager, respx_mock: MockRouter
):  # ИЗМЕНЕНО
    route = respx_mock.get(url__regex=rf"{MOCKED_API_BASE_URL}\?.*").respond(
        200, json={"items": [], "next_cursor": None, "limit": 10, "count": 0}
    )
    await remote_item_manager.list(
        limit=10, cursor=100, filters={"name__like": "test", "value": 5}
    )
    assert route.called
    called_url = str(route.calls[0].request.url)
    assert "limit=10" in called_url
    assert "cursor=100" in called_url
    assert "name__like=test" in called_url  # FastAPI-Filter параметры
    assert "value=5" in called_url


async def test_remote_create_success(
    remote_item_manager: RemoteDataAccessManager, respx_mock: MockRouter
):  # ИЗМЕНЕНО
    create_data = ItemCreate(name="New Remote Item", value=50)
    item_id = uuid.uuid4()
    mock_response_data = {
        "id": str(item_id),
        "name": "New Remote Item",
        "value": 50,
        "lsn": 1,
    }
    # URL для создания - MOCKED_API_BASE_URL + "/" (RemoteServiceClient добавляет / если нужно)
    route = respx_mock.post(f"{MOCKED_API_BASE_URL}/").respond(
        201, json=mock_response_data
    )
    created_item = await remote_item_manager.create(create_data)
    assert route.called
    sent_json = json.loads(route.calls[0].request.content)
    assert sent_json["name"] == "New Remote Item"
    assert isinstance(created_item, ItemRead)
    assert created_item.id == item_id


async def test_remote_create_validation_error(
    remote_item_manager: RemoteDataAccessManager, respx_mock: MockRouter
):  # ИЗМЕНЕНО
    create_data = ItemCreate(name="Bad Data")
    mock_error_response = {
        "detail": [{"loc": ["body", "value"], "msg": "field required"}]
    }
    respx_mock.post(f"{MOCKED_API_BASE_URL}/").respond(422, json=mock_error_response)
    with pytest.raises(HTTPException) as exc_info:
        await remote_item_manager.create(create_data)
    assert exc_info.value.status_code == 422


async def test_remote_update_success(
    remote_item_manager: RemoteDataAccessManager, respx_mock: MockRouter
):  # ИЗМЕНЕНО
    item_id = uuid.uuid4()
    update_data = ItemUpdate(description="Updated Description")
    mock_response_data = {
        "id": str(item_id),
        "name": "Existing",
        "description": "Updated Description",
        "lsn": 2,
    }
    route = respx_mock.put(f"{MOCKED_API_BASE_URL}/{item_id}").respond(
        200, json=mock_response_data
    )
    updated_item = await remote_item_manager.update(item_id, update_data)
    assert route.called
    sent_json = json.loads(route.calls[0].request.content)
    assert sent_json == {"description": "Updated Description"}
    assert isinstance(updated_item, ItemRead)


async def test_remote_update_not_found(
    remote_item_manager: RemoteDataAccessManager, respx_mock: MockRouter
):  # ИЗМЕНЕНО
    item_id = uuid.uuid4()
    update_data = ItemUpdate(name="No matter")
    respx_mock.put(f"{MOCKED_API_BASE_URL}/{item_id}").respond(404)
    with pytest.raises(HTTPException) as exc_info:
        await remote_item_manager.update(item_id, update_data)
    assert exc_info.value.status_code == 404


async def test_remote_delete_success(
    remote_item_manager: RemoteDataAccessManager, respx_mock: MockRouter
):  # ИЗМЕНЕНО
    item_id = uuid.uuid4()
    route = respx_mock.delete(f"{MOCKED_API_BASE_URL}/{item_id}").respond(204)
    success = await remote_item_manager.delete(item_id)
    assert route.called
    assert success is True


async def test_remote_delete_already_deleted_is_success(
    remote_item_manager: RemoteDataAccessManager, respx_mock: MockRouter
):  # ИЗМЕНЕНО
    item_id = uuid.uuid4()
    respx_mock.delete(f"{MOCKED_API_BASE_URL}/{item_id}").respond(404)
    success = await remote_item_manager.delete(item_id)
    assert success is True


async def test_remote_delete_server_error(
    remote_item_manager: RemoteDataAccessManager, respx_mock: MockRouter
):  # ИЗМЕНЕНО
    item_id = uuid.uuid4()
    respx_mock.delete(f"{MOCKED_API_BASE_URL}/{item_id}").respond(500)
    with pytest.raises(HTTPException) as exc_info:
        await remote_item_manager.delete(item_id)
    assert exc_info.value.status_code == 500


async def test_remote_manager_with_auth_token(
    remote_config: RemoteConfig,
    mock_http_client: httpx.AsyncClient,
    respx_mock: MockRouter,
):  # ИЗМЕНЕНО
    auth_token = "test_bearer_token"
    manager = RemoteDataAccessManager(
        remote_config=remote_config,
        http_client=mock_http_client,
        model_cls=Item,
        read_schema_cls=ItemRead,
        auth_token=auth_token,
    )
    item_id = uuid.uuid4()
    route = respx_mock.get(f"{MOCKED_API_BASE_URL}/{item_id}").respond(
        200, json={"id": str(item_id), "name": "Auth Item", "lsn": 1}
    )
    await manager.get(item_id)
    assert route.called
    assert route.calls[0].request.headers["authorization"] == f"Bearer {auth_token}"
