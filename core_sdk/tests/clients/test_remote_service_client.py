# core_sdk/tests/clients/test_remote_service_client.py
from unittest import mock

import pytest
import httpx
import uuid
import json
from typing import Optional, List, Dict, Any, cast  # Добавил cast

import pytest_asyncio
from pydantic import HttpUrl, BaseModel as PydanticBaseModel

from respx import MockRouter

from core_sdk.clients.base import RemoteServiceClient
from core_sdk.exceptions import ServiceCommunicationError, ConfigurationError
from fastapi import HTTPException  # Для проверки типов исключений в тестах DAM

# Используем тестовые модели из conftest основного data_access
# Убедитесь, что Item.id в conftest.py это uuid.UUID
from core_sdk.tests.conftest import (
    Item as TestItemModel,
    ItemCreate,
    ItemUpdate,
    ItemRead,
)

pytestmark = pytest.mark.asyncio

SERVICE_URL_STR = "http://fake-service.io"
MODEL_ENDPOINT_STR = "/api/v1/tests"
FULL_API_URL = f"{SERVICE_URL_STR}{MODEL_ENDPOINT_STR}"


@pytest_asyncio.fixture
async def http_client() -> httpx.AsyncClient:
    """Предоставляет httpx.AsyncClient, управляемый контекстным менеджером."""
    async with httpx.AsyncClient(base_url=SERVICE_URL_STR) as client:
        yield client
    # client.aclose() вызовется автоматически


@pytest.fixture
def service_client(
    http_client: httpx.AsyncClient,
) -> RemoteServiceClient[TestItemModel, ItemCreate, ItemUpdate]:
    return RemoteServiceClient(
        base_url=HttpUrl(SERVICE_URL_STR),
        model_endpoint=MODEL_ENDPOINT_STR.lstrip("/"),
        model_cls=TestItemModel,
        http_client=http_client,
    )


@pytest.fixture
def service_client_with_auth(
    http_client: httpx.AsyncClient,
) -> RemoteServiceClient[TestItemModel, ItemCreate, ItemUpdate]:
    return RemoteServiceClient(
        base_url=HttpUrl(SERVICE_URL_STR),
        model_endpoint=MODEL_ENDPOINT_STR.lstrip("/"),
        model_cls=TestItemModel,
        http_client=http_client,
        auth_token="test-auth-token",
    )


# --- Тесты ---


async def test_get_success(service_client: RemoteServiceClient, respx_mock: MockRouter):
    item_id = uuid.uuid4()
    # В TestItemModel id это UUID, lsn это int.
    expected_data = {
        "id": str(item_id),
        "name": "Test Get",
        "lsn": 1,
        "description": None,
        "value": None,
    }

    respx_mock.get(f"{FULL_API_URL}/{item_id}").respond(200, json=expected_data)

    result = await service_client.get(item_id)

    assert result is not None
    assert isinstance(result, TestItemModel)  # model_cls используется для парсинга
    assert result.id == item_id
    assert result.name == "Test Get"
    assert result.lsn == 1


async def test_get_not_found_returns_none(
    service_client: RemoteServiceClient, respx_mock: MockRouter
):
    item_id = uuid.uuid4()
    respx_mock.get(f"{FULL_API_URL}/{item_id}").respond(404)
    result = await service_client.get(item_id)
    assert result is None


async def test_get_server_error_raises_service_communication_error(
    service_client: RemoteServiceClient, respx_mock: MockRouter
):
    item_id = uuid.uuid4()
    respx_mock.get(f"{FULL_API_URL}/{item_id}").respond(500, text="Server Down")
    with pytest.raises(ServiceCommunicationError) as exc_info:
        await service_client.get(item_id)
    assert exc_info.value.status_code == 500
    assert "Server Down" in exc_info.value.message


async def test_list_success(
    service_client: RemoteServiceClient, respx_mock: MockRouter
):
    item1_id, item2_id = uuid.uuid4(), uuid.uuid4()
    mock_items_data = [
        {
            "id": str(item1_id),
            "name": "Item 1",
            "lsn": 1,
            "description": None,
            "value": None,
        },
        {
            "id": str(item2_id),
            "name": "Item 2",
            "lsn": 2,
            "description": None,
            "value": None,
        },
    ]
    # RemoteServiceClient.list теперь возвращает List[ModelType]
    # Он ожидает, что API вернет либо список, либо словарь с ключом "items"
    respx_mock.get(FULL_API_URL).respond(
        200, json={"items": mock_items_data}
    )  # API возвращает словарь

    result_list_of_models = await service_client.list(limit=2)

    assert isinstance(result_list_of_models['items'], list)
    assert len(result_list_of_models['items']) == 2
    assert isinstance(result_list_of_models['items'][0], TestItemModel)
    assert result_list_of_models['items'][0].name == "Item 1"


async def test_list_api_returns_direct_list(
    service_client: RemoteServiceClient, respx_mock: MockRouter
):
    mock_items_data = [{"id": str(uuid.uuid4()), "name": "Direct List Item", "lsn": 3}]
    respx_mock.get(FULL_API_URL).respond(
        200, json=mock_items_data
    )  # API возвращает просто список

    result_list_of_models = await service_client.list()
    assert len(result_list_of_models['items']) == 1
    assert result_list_of_models['items'][0].name == "Direct List Item"


async def test_list_params_are_sent(
    service_client: RemoteServiceClient, respx_mock: MockRouter
):
    route = respx_mock.get(url__regex=rf"{FULL_API_URL}\?.*").respond(200, json=[])

    await service_client.list(
        limit=10,
        cursor=50,
        filters={"name": "test", "active": True, "ids": [uuid.uuid4(), uuid.uuid4()]},
    )

    assert route.called
    request_url = str(route.calls.last.request.url)
    assert "limit=10" in request_url
    assert "cursor=50" in request_url
    assert "name=test" in request_url
    assert "active=True" in request_url
    assert (
        "ids=" in request_url
    )  # Проверяем, что параметр ids передается (httpx сделает ids=uuid1&ids=uuid2)


async def test_create_success(
    service_client: RemoteServiceClient, respx_mock: MockRouter
):
    create_data = ItemCreate(
        name="New Item", description="Desc"
    )  # lsn и value будут None
    item_id = uuid.uuid4()
    response_data = {
        "id": str(item_id),
        "name": "New Item",
        "description": "Desc",
        "lsn": 1,
        "value": None,
    }

    route = respx_mock.post(f"{FULL_API_URL}/").respond(201, json=response_data)
    result = await service_client.create(create_data)

    assert route.called
    sent_payload = json.loads(route.calls.last.request.content)
    assert sent_payload["name"] == "New Item"
    assert sent_payload["description"] == "Desc"
    assert (
        sent_payload.get("value") is None
    )  # Проверяем, что value None, если не передано

    assert isinstance(result, TestItemModel)
    assert result.id == item_id


async def test_update_success(
    service_client: RemoteServiceClient, respx_mock: MockRouter
):
    item_id = uuid.uuid4()
    update_data = ItemUpdate(description="Updated")
    response_data = {
        "id": str(item_id),
        "name": "Original",
        "description": "Updated",
        "lsn": 2,
        "value": None,
    }
    route = respx_mock.put(f"{FULL_API_URL}/{item_id}").respond(200, json=response_data)
    result = await service_client.update(item_id, update_data)
    assert route.called
    sent_payload = json.loads(route.calls.last.request.content)
    assert sent_payload == {"description": "Updated"}
    assert isinstance(result, TestItemModel)
    assert result.description == "Updated"


async def test_delete_success_204(
    service_client: RemoteServiceClient, respx_mock: MockRouter
):
    item_id = uuid.uuid4()
    respx_mock.delete(f"{FULL_API_URL}/{item_id}").respond(204)
    result = await service_client.delete(item_id)
    assert result is True


async def test_delete_success_404(
    service_client: RemoteServiceClient, respx_mock: MockRouter
):
    item_id = uuid.uuid4()
    respx_mock.delete(f"{FULL_API_URL}/{item_id}").respond(404)
    result = await service_client.delete(item_id)
    assert result is True


async def test_delete_server_error_raises_exception(
    service_client: RemoteServiceClient, respx_mock: MockRouter
):
    item_id = uuid.uuid4()
    respx_mock.delete(f"{FULL_API_URL}/{item_id}").respond(500)
    with pytest.raises(ServiceCommunicationError):
        await service_client.delete(item_id)


async def test_auth_header_is_sent(
    service_client_with_auth: RemoteServiceClient, respx_mock: MockRouter
):
    item_id = uuid.uuid4()
    # Добавляем все поля TestItemModel в мок ответа
    route = respx_mock.get(f"{FULL_API_URL}/{item_id}").respond(
        200,
        json={
            "id": str(item_id),
            "name": "Auth Item",
            "lsn": 1,
            "description": None,
            "value": None,
        },
    )
    await service_client_with_auth.get(item_id)
    assert route.called
    assert route.calls.last.request.headers["authorization"] == "Bearer test-auth-token"


async def test_client_closes_if_owned():
    client_owner = RemoteServiceClient(
        base_url=HttpUrl(SERVICE_URL_STR),
        model_endpoint=MODEL_ENDPOINT_STR.lstrip("/"),
        model_cls=TestItemModel,
    )  # http_client не передан, создается внутри
    assert client_owner._owns_client is True

    # Мокируем httpx.AsyncClient.aclose для проверки вызова
    # Нужно мокировать его на экземпляре _http_client, который уже создан
    with mock.patch.object(
        client_owner._http_client, "aclose", new_callable=mock.AsyncMock
    ) as mock_aclose:
        await client_owner.close()
        mock_aclose.assert_awaited_once()


async def test_client_does_not_close_if_not_owned(http_client: httpx.AsyncClient):
    client_not_owner = RemoteServiceClient(
        base_url=HttpUrl(SERVICE_URL_STR),
        model_endpoint=MODEL_ENDPOINT_STR.lstrip("/"),
        model_cls=TestItemModel,
        http_client=http_client,  # http_client передан извне
    )
    assert client_not_owner._owns_client is False

    # Мокируем aclose на переданном клиенте
    with mock.patch.object(
        http_client, "aclose", new_callable=mock.AsyncMock
    ) as mock_aclose_external:
        await client_not_owner.close()
        mock_aclose_external.assert_not_awaited()  # Не должен был вызваться
