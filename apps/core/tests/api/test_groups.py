# core/app/tests/api/test_groups.py
import pytest
import pytest_asyncio
from httpx import AsyncClient
from uuid import uuid4, UUID
from typing import Dict, List

from starlette.exceptions import HTTPException

from apps.core import schemas, models
from apps.core.config import settings
from core_sdk.data_access import DataAccessManagerFactory # Для создания данных в тестах
from core_sdk.db.session import managed_session

pytestmark = pytest.mark.asyncio

API_PREFIX = settings.API_V1_STR
GROUPS_ENDPOINT = f"{API_PREFIX}/groups"

# --- Фикстура для создания тестовой группы ---
@pytest_asyncio.fixture(scope="function")
async def test_group(
    dam_factory_test: DataAccessManagerFactory,
    test_company: models.company.Company
) -> models.group.Group:
    """Создает тестовую группу через DAM."""
    group_name = f"Test Group {uuid4()}"
    print(f"Creating test group via DAM Factory: {group_name}")
    group_data = {
        "name": group_name,
        "description": "A group for testing",
        "company_id": test_company.id
    }
    async with managed_session():

        group_manager = dam_factory_test.get_manager("Group")
        try:
            db_group = await group_manager.create(group_data)
            assert isinstance(db_group, models.group.Group)
            print(f"Test group created via DAM with ID: {db_group.id}")
            return db_group
        except HTTPException as e:
            pytest.fail(f"DAM create group failed: {e.status_code} - {e.detail}")
        except Exception as e:
            pytest.fail(f"Failed to create test group via DAM: {e}")


# --- Тесты для Groups ---

async def test_create_group_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_company: models.company.Company,
):
    """Тест успешного создания группы."""
    group_name = f"New API Group {uuid4()}"
    data = {
        "name": group_name,
        "description": "Group created via API test",
        "company_id": str(test_company.id) # Передаем ID компании
    }
    response = await async_client.post(
        GROUPS_ENDPOINT,
        headers=superuser_token_headers,
        json=data
    )
    assert response.status_code == 201, response.text
    content = response.json()
    assert content["name"] == group_name
    assert content["company_id"] == str(test_company.id)
    assert "id" in content

async def test_get_group_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_group: models.group.Group
):
    """Тест успешного получения группы по ID."""
    response = await async_client.get(
        f"{GROUPS_ENDPOINT}/{test_group.id}",
        headers=superuser_token_headers
    )
    assert response.status_code == 200, response.text
    content = response.json()
    assert content["id"] == str(test_group.id)
    assert content["name"] == test_group.name

async def test_list_groups_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_group: models.group.Group
):
    """Тест получения списка групп."""
    response = await async_client.get(GROUPS_ENDPOINT, headers=superuser_token_headers)
    assert response.status_code == 200, response.text
    content = response.json()
    assert isinstance(content['items'], list)
    assert any(g["id"] == str(test_group.id) for g in content['items'])

async def test_update_group_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_group: models.group.Group
):
    """Тест успешного обновления группы."""
    new_desc = "Updated group description"
    data = {"description": new_desc}
    response = await async_client.put(
        f"{GROUPS_ENDPOINT}/{test_group.id}",
        headers=superuser_token_headers,
        json=data
    )
    assert response.status_code == 200, response.text
    content = response.json()
    assert content["id"] == str(test_group.id)
    assert content["description"] == new_desc

async def test_delete_group_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_group: models.group.Group
):
    """Тест успешного удаления группы."""
    group_id = test_group.id
    response = await async_client.delete(
        f"{GROUPS_ENDPOINT}/{group_id}",
        headers=superuser_token_headers
    )
    assert response.status_code == 204

    # Проверяем удаление
    response_get = await async_client.get(
        f"{GROUPS_ENDPOINT}/{group_id}",
        headers=superuser_token_headers
    )
    assert response_get.status_code == 404

# --- Тесты фильтрации ---
async def test_list_groups_filter_name_like(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    dam_factory_test: DataAccessManagerFactory,
    test_company: models.company.Company,
):
    """Тест фильтрации групп по части имени."""
    prefix = f"GrpLike_{uuid4()}"
    name1 = f"{prefix}_A"
    name2 = f"{prefix}_B"
    name3 = f"Other_{prefix}"
    async with managed_session():
        manager = dam_factory_test.get_manager("Group")
        g1 = await manager.create({"name": name1, "company_id": test_company.id})
        g2 = await manager.create({"name": name2, "company_id": test_company.id})
        g3 = await manager.create({"name": name3, "company_id": test_company.id})

    response = await async_client.get(
        GROUPS_ENDPOINT,
        headers=superuser_token_headers,
        params={"name__like": prefix}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    returned_ids = {item["id"] for item in data["items"]}
    assert str(g1.id) in returned_ids
    assert str(g2.id) in returned_ids
    assert str(g3.id) in returned_ids

async def test_list_groups_filter_company_id(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    dam_factory_test: DataAccessManagerFactory,
    test_company: models.company.Company, # Первая компания
):
    """Тест фильтрации групп по company_id."""
    # Создаем вторую компанию и группу в ней
    company2_name = f"Other Company {uuid4()}"
    group_in_comp2_name = f"Group Comp2 {uuid4()}"
    async with managed_session():
        company_manager = dam_factory_test.get_manager("Company")
        company2 = await company_manager.create({"name": company2_name})
        group_manager = dam_factory_test.get_manager("Group")
        g_comp2 = await group_manager.create({"name": group_in_comp2_name, "company_id": company2.id})
        # Создаем группу в первой компании
        g_comp1 = await group_manager.create({"name": f"Group Comp1 {uuid4()}", "company_id": test_company.id})

    # Фильтруем по ID первой компании
    response = await async_client.get(
        GROUPS_ENDPOINT,
        headers=superuser_token_headers,
        params={"company_id": str(test_company.id)}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 1
    returned_ids = {item["id"] for item in data["items"]}
    assert str(g_comp1.id) in returned_ids
    assert str(g_comp2.id) not in returned_ids