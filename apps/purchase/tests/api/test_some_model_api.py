# purchase/app/tests/api/test_some_model_api.py
import pytest
import uuid  # Добавлен uuid
from httpx import AsyncClient
from purchase.app.config import settings as service_settings
from purchase.app.schemas.some_model_schema import SomeModelCreate
from purchase.app.models.some_model import SomeModel

pytestmark = pytest.mark.asyncio
API_PREFIX = service_settings.API_V1_STR
SOME_MODEL_ENDPOINT = f"{API_PREFIX}/some-models"

# TODO: Добавьте фикстуру для аутентификации, если эндпоинты защищены
# Например, superuser_token_headers из conftest.py вашего core сервиса, адаптированная.
# @pytest_asyncio.fixture
# async def auth_headers(async_client_service: AsyncClient, test_settings_service: service_settings):
#     # Логика получения токена...
#     # return {"Authorization": f"Bearer {token}"}
#     return {} # Заглушка


async def test_create_some_model(async_client_service: AsyncClient, db_session):  # Убрал auth_headers пока
    test_company_id = uuid.uuid4()
    data = SomeModelCreate(name="My First SomeModel", value=100, company_id=test_company_id)
    response = await async_client_service.post(SOME_MODEL_ENDPOINT, json=data.model_dump())  # Убрал headers
    assert response.status_code == 201, response.text
    content = response.json()
    assert content["name"] == data.name
    assert content["value"] == data.value


async def test_get_some_model(async_client_service: AsyncClient, test_some_model_item: SomeModel, db_session):
    response = await async_client_service.get(f"{SOME_MODEL_ENDPOINT}/{test_some_model_item.id}")
    assert response.status_code == 200, response.text
    content = response.json()
    assert content["id"] == str(test_some_model_item.id)


async def test_list_some_models(async_client_service: AsyncClient, test_some_model_item: SomeModel, db_session):
    response = await async_client_service.get(SOME_MODEL_ENDPOINT)
    assert response.status_code == 200, response.text
    content = response.json()
    assert isinstance(content["items"], list)
    assert len(content["items"]) >= 1
    assert any(item["id"] == str(test_some_model_item.id) for item in content["items"])
