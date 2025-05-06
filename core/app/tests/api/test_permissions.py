# core/app/tests/api/test_permissions.py
import pytest
import pytest_asyncio
from httpx import AsyncClient
from uuid import uuid4, UUID
from typing import Dict, List

from starlette.exceptions import HTTPException

from core.app import schemas, models
from core.app.config import settings
from core_sdk.data_access import DataAccessManagerFactory
from core_sdk.db.session import managed_session

pytestmark = pytest.mark.asyncio

API_PREFIX = settings.API_V1_STR
PERMISSIONS_ENDPOINT = f"{API_PREFIX}/permissions"

# --- Фикстура для создания тестового права (если нужно для тестов GET) ---
# Обычно права создаются при инициализации, но для теста GET создадим одно
@pytest_asyncio.fixture(scope="function")
async def test_permission(
    dam_factory_test: DataAccessManagerFactory,
    test_company: models.company.Company # <--- Добавить зависимость от компании
) -> models.permission.Permission:
    codename = f"test.perm_{uuid4()}"
    perm_data = {
        "codename": codename,
        "name": f"Test Permission {codename}",
        "description": "Permission for testing GET",
        "company_id": test_company.id # <--- Передать ID компании
    }
    async with managed_session():
        perm_manager = dam_factory_test.get_manager("Permission")
        try:
            db_perm = await perm_manager.create(perm_data)
            assert isinstance(db_perm, models.permission.Permission)
            print(f"Test permission created via DAM with ID: {db_perm.id}")
            return db_perm
        except HTTPException as e:
            pytest.fail(f"DAM create permission failed: {e.status_code} - {e.detail}")
        except Exception as e:
            pytest.fail(f"Failed to create test permission via DAM: {e}")

# --- Тесты для Permissions (в основном чтение) ---

async def test_list_permissions_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_permission: models.permission.Permission # Убедимся, что хотя бы одно право есть
):
    """Тест получения списка прав (суперюзером)."""
    response = await async_client.get(PERMISSIONS_ENDPOINT, headers=superuser_token_headers)
    assert response.status_code == 200, response.text
    content = response.json()
    assert isinstance(content['items'], list)
    # Проверяем, что базовые права (из ensure_base_permissions) и наше тестовое присутствуют
    codenames = {p["codename"] for p in content['items']}
    assert test_permission.codename in codenames

async def test_list_permissions_forbidden(
    async_client: AsyncClient,
    normal_user_token_headers: dict,
):
    """Тест запрета получения списка прав обычным пользователем."""
    response = await async_client.get(PERMISSIONS_ENDPOINT, headers=normal_user_token_headers)
    assert response.status_code == 403

async def test_get_permission_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_permission: models.permission.Permission
):
    """Тест успешного получения права по ID."""
    response = await async_client.get(
        f"{PERMISSIONS_ENDPOINT}/{test_permission.id}",
        headers=superuser_token_headers
    )
    assert response.status_code == 200, response.text
    content = response.json()
    assert content["id"] == str(test_permission.id)
    assert content["codename"] == test_permission.codename

async def test_get_permission_not_found(
    async_client: AsyncClient,
    superuser_token_headers: dict,
):
    """Тест получения несуществующего права."""
    non_existent_id = uuid4()
    response = await async_client.get(
        f"{PERMISSIONS_ENDPOINT}/{non_existent_id}",
        headers=superuser_token_headers
    )
    assert response.status_code == 404

async def test_list_permissions_filter_codename_exact(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_permission: models.permission.Permission, # Используем созданное право
    dam_factory_test: DataAccessManagerFactory,
):
    """Тест фильтрации прав по точному codename."""
    # Создадим еще одно право для контраста
    other_codename = f"other.perm_{uuid4()}"
    async with managed_session():
        manager = dam_factory_test.get_manager("Permission")
        p_other = await manager.create({"codename": other_codename, "name": "Other"})

    response = await async_client.get(
        PERMISSIONS_ENDPOINT,
        headers=superuser_token_headers,
        params={"codename": test_permission.codename}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == str(test_permission.id)
    assert data["items"][0]["codename"] == test_permission.codename

async def test_list_permissions_filter_codename_like(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    dam_factory_test: DataAccessManagerFactory,
):
    """Тест фильтрации прав по части codename."""
    prefix = f"perm.test.like.{uuid4()}"
    code1 = f"{prefix}.view"
    code2 = f"{prefix}.edit"
    code3 = f"other.{prefix}.delete"
    async with managed_session():
        manager = dam_factory_test.get_manager("Permission")
        p1 = await manager.create({"codename": code1, "name": "View"})
        p2 = await manager.create({"codename": code2, "name": "Edit"})
        p3 = await manager.create({"codename": code3, "name": "Delete"})

    response = await async_client.get(
        PERMISSIONS_ENDPOINT,
        headers=superuser_token_headers,
        params={"codename__like": prefix} # Ищем по префиксу
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    returned_ids = {item["id"] for item in data["items"]}
    assert str(p1.id) in returned_ids
    assert str(p2.id) in returned_ids
    assert str(p3.id) in returned_ids