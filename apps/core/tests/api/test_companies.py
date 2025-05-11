# core/app/tests/api/test_companies.py
import asyncio
from uuid import uuid4, UUID
import pytest
from httpx import AsyncClient
from taskiq import InMemoryBroker

from apps.core import schemas, models  # Импортируем схемы и модели
from apps.core.config import settings
from core_sdk.data_access import DataAccessManagerFactory
from core_sdk.db.session import managed_session

pytestmark = pytest.mark.asyncio

API_PREFIX = settings.API_V1_STR
COMPANIES_ENDPOINT = f"{API_PREFIX}/companies"


async def test_create_company_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,  # Нужен суперюзер для создания
):
    """Тест успешного создания компании."""
    company_name = f"New Test Company {uuid4()}"
    data = {
        "name": company_name,
        "description": "A successfully created test company",
        "is_active": True,
        "vat_id": "1234567890",
    }
    response = await async_client.post(
        COMPANIES_ENDPOINT, headers=superuser_token_headers, json=data
    )
    assert response.status_code == 201, response.text
    content = response.json()
    assert content["name"] == company_name
    assert content["description"] == data["description"]
    assert content["is_active"] == data["is_active"]
    assert content["vat_id"] == data["vat_id"]
    assert "id" in content
    assert "lsn" in content


async def test_create_company_duplicate_name(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_company: models.company.Company,  # Используем уже созданную компанию
):
    """Тест создания компании с существующим именем."""
    data = {"name": test_company.name}  # Используем имя существующей компании
    response = await async_client.post(
        COMPANIES_ENDPOINT, headers=superuser_token_headers, json=data
    )
    # Ожидаем конфликт (409) или ошибку валидации (400/422),
    # зависит от реализации уникальности в БД/модели
    assert response.status_code in [409, 400, 422], response.text


async def test_create_company_unauthenticated(async_client: AsyncClient):
    """Тест создания компании без аутентификации."""
    data = {"name": "Unauthorized Company"}
    response = await async_client.post(COMPANIES_ENDPOINT, json=data)
    assert response.status_code == 401  # Ожидаем ошибку аутентификации


async def test_create_company_insufficient_permissions(
    async_client: AsyncClient,
    normal_user_token_headers: dict,  # Используем токен обычного пользователя
):
    """Тест создания компании с недостаточными правами."""
    data = {"name": "Forbidden Company"}
    response = await async_client.post(
        COMPANIES_ENDPOINT, headers=normal_user_token_headers, json=data
    )
    assert response.status_code == 403  # Ожидаем ошибку авторизации


async def test_get_company_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,  # Доступ к деталям может требовать прав
    test_company: models.company.Company,
):
    """Тест успешного получения компании по ID."""
    response = await async_client.get(
        f"{COMPANIES_ENDPOINT}/{test_company.id}", headers=superuser_token_headers
    )
    assert response.status_code == 200, response.text
    content = response.json()
    assert content["id"] == str(test_company.id)
    assert content["name"] == test_company.name


async def test_get_company_not_found(
    async_client: AsyncClient,
    superuser_token_headers: dict,
):
    """Тест получения несуществующей компании."""
    non_existent_id = uuid4()
    response = await async_client.get(
        f"{COMPANIES_ENDPOINT}/{non_existent_id}", headers=superuser_token_headers
    )
    assert response.status_code == 404


async def test_list_companies_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_company: models.company.Company,  # Хотя бы одна компания должна быть
):
    """Тест успешного получения списка компаний."""
    response = await async_client.get(
        COMPANIES_ENDPOINT,
        headers=superuser_token_headers,
        params={"limit": 10},  # Пример параметра
    )
    assert response.status_code == 200, response.text
    content = response.json()
    assert isinstance(content["items"], list)
    # Проверяем, что наша тестовая компания есть в списке (могут быть и другие)
    assert any(c["id"] == str(test_company.id) for c in content["items"])


async def test_list_companies_filter_by_name(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_company: models.company.Company,
):
    """Тест фильтрации списка компаний по имени."""
    # Создаем еще одну компанию для чистоты теста
    other_name = f"Other Company {uuid4()}"
    await async_client.post(
        COMPANIES_ENDPOINT, headers=superuser_token_headers, json={"name": other_name}
    )

    # Фильтруем по имени первой компании
    response = await async_client.get(
        COMPANIES_ENDPOINT,
        headers=superuser_token_headers,
        params={"name": test_company.name},  # Фильтр по имени
    )
    assert response.status_code == 200, response.text
    content = response.json()
    assert isinstance(content["items"], list)
    assert len(content["items"]) >= 1
    assert all(c["name"] == test_company.name for c in content["items"])
    assert not any(c["name"] == other_name for c in content["items"])


async def test_update_company_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_company: models.company.Company,
):
    """Тест успешного обновления компании."""
    new_description = "Updated company description"
    data = {"description": new_description, "is_active": False}
    response = await async_client.put(
        f"{COMPANIES_ENDPOINT}/{test_company.id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert response.status_code == 200, response.text
    content = response.json()
    assert content["id"] == str(test_company.id)
    assert content["name"] == test_company.name  # Имя не меняли
    assert content["description"] == new_description
    assert content["is_active"] is False


async def test_update_company_not_found(
    async_client: AsyncClient,
    superuser_token_headers: dict,
):
    """Тест обновления несуществующей компании."""
    non_existent_id = uuid4()
    data = {"name": "Trying to update non-existent"}
    response = await async_client.put(
        f"{COMPANIES_ENDPOINT}/{non_existent_id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert response.status_code == 404


async def test_delete_company_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_company: models.company.Company,
):
    """Тест успешного удаления компании."""
    company_id = test_company.id
    response = await async_client.delete(
        f"{COMPANIES_ENDPOINT}/{company_id}", headers=superuser_token_headers
    )
    assert response.status_code == 204

    # Проверяем, что компания действительно удалена (или недоступна)
    response_get = await async_client.get(
        f"{COMPANIES_ENDPOINT}/{company_id}", headers=superuser_token_headers
    )
    assert response_get.status_code == 404


async def test_delete_company_not_found(
    async_client: AsyncClient,
    superuser_token_headers: dict,
):
    """Тест удаления несуществующей компании."""
    non_existent_id = uuid4()
    response = await async_client.delete(
        f"{COMPANIES_ENDPOINT}/{non_existent_id}", headers=superuser_token_headers
    )
    assert response.status_code == 404


async def test_activate_company_and_wait_success(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    dam_factory_test: DataAccessManagerFactory,  # Нужна для создания компании
    test_taskiq_broker: InMemoryBroker,  # Для проверки задач (опционально)
):
    """Тест успешной активации компании через брокер с ожиданием."""
    # 1. Создаем неактивную компанию напрямую через DAM для теста
    async with managed_session():
        company_manager = dam_factory_test.get_manager("Company")
    company_data = schemas.company.CompanyCreate(
        name=f"Inactive Company {uuid4()}",
        is_active=False,  # <--- Создаем неактивной
    )
    async with managed_session():
        db_company = await company_manager.create(company_data)
        assert not db_company.is_active
        company_id = db_company.id

    # 2. Вызываем API-ручку для активации с ожиданием
    activate_url = f"{COMPANIES_ENDPOINT}/{company_id}/activate-wait"
    print(f"TEST: Calling POST {activate_url}")
    response = await async_client.post(activate_url, headers=superuser_token_headers)

    # 3. Проверяем результат HTTP-запроса
    assert response.status_code == 200, response.text
    content = response.json()
    print(f"TEST: API Response: {content}")
    assert content["id"] == str(company_id)
    assert content["name"] == company_data.name
    assert content["is_active"] is True  # <--- Проверяем, что в ответе компания активна

    # 4. (Опционально) Проверяем состояние в БД напрямую через DAM
    # Это подтвердит, что воркер действительно изменил состояние
    # Используем ту же фабрику, т.к. InMemoryBroker выполнил задачу синхронно
    async with managed_session():
        refreshed_company = await company_manager.get(company_id)
    assert refreshed_company is not None
    assert refreshed_company.is_active is True
    print(f"TEST: Company {company_id} is active in DB.")

    # 5. (Опционально) Проверяем, что задача была обработана брокером
    # InMemoryBroker может предоставлять методы для проверки выполненных задач
    # Это зависит от его API, пример:
    # assert test_taskiq_broker.kicked_tasks_count > 0
    # completed_task = await test_taskiq_broker.get_latest_result(...) # Примерный метод
    # assert completed_task is not None


async def test_activate_company_and_wait_timeout(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    dam_factory_test: DataAccessManagerFactory,
    test_taskiq_broker: InMemoryBroker,
    monkeypatch,
):
    """Тест таймаута при ожидании результата активации."""
    # 1. Создаем неактивную компанию
    async with managed_session():
        company_manager = dam_factory_test.get_manager("Company")
        company_data = schemas.company.CompanyCreate(
            name=f"Timeout Company {uuid4()}", is_active=False
        )
        db_company = await company_manager.create(company_data)
        company_id = db_company.id

    # 3. Вызываем API с коротким таймаутом ожидания
    activate_url = f"{COMPANIES_ENDPOINT}/{company_id}/activate-wait"
    print(f"TEST: Calling POST {activate_url} with short wait timeout")
    response = await async_client.post(
        activate_url,
        headers=superuser_token_headers,
        params={"wait_timeout": 0},  # Устанавливаем минимальный таймаут через query
    )

    # 4. Проверяем, что получили ошибку 408 Timeout
    assert response.status_code == 200
    content = response.json()
    print(f"TEST: API Response: {content}")


async def test_list_companies_filter_name_exact(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    dam_factory_test: DataAccessManagerFactory,
):
    """Тест фильтрации компаний по точному совпадению имени."""
    company_name_target = f"Target Company {uuid4()}"
    company_name_other = f"Other Company {uuid4()}"
    async with managed_session():
        manager = dam_factory_test.get_manager("Company")
        c1 = await manager.create({"name": company_name_target, "is_active": True})
        c2 = await manager.create({"name": company_name_other, "is_active": True})

    response = await async_client.get(
        COMPANIES_ENDPOINT,
        headers=superuser_token_headers,
        params={"name": company_name_target},  # Фильтр по точному имени
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == str(c1.id)
    assert data["items"][0]["name"] == company_name_target


async def test_list_companies_filter_name_like(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    dam_factory_test: DataAccessManagerFactory,
):
    """Тест фильтрации компаний по части имени (like/contains)."""
    prefix = f"LikeTest_{uuid4()}"
    name1 = f"{prefix}_Alpha"
    name2 = f"{prefix}_Beta"
    name3 = f"Gamma_{prefix}"  # Не должен найтись по префиксу
    async with managed_session():
        manager = dam_factory_test.get_manager("Company")
        c1 = await manager.create({"name": name1})
        c2 = await manager.create({"name": name2})
        c3 = await manager.create({"name": name3})

    response = await async_client.get(
        COMPANIES_ENDPOINT,
        headers=superuser_token_headers,
        params={"name__like": prefix},  # Ищем по префиксу
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    assert len(data["items"]) == 3
    returned_ids = {item["id"] for item in data["items"]}
    assert str(c1.id) in returned_ids
    assert str(c2.id) in returned_ids
    assert str(c3.id) in returned_ids
    for item in data["items"]:
        assert prefix in item["name"]


async def test_list_companies_filter_is_active(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    dam_factory_test: DataAccessManagerFactory,
):
    """Тест фильтрации компаний по флагу is_active."""
    base_name = f"ActiveFilter_{uuid4()}"
    async with managed_session():
        manager = dam_factory_test.get_manager("Company")
        c_active1 = await manager.create(
            {"name": f"{base_name}_Active1", "is_active": True}
        )
        c_active2 = await manager.create(
            {"name": f"{base_name}_Active2", "is_active": True}
        )
        c_inactive = await manager.create(
            {"name": f"{base_name}_Inactive", "is_active": False}
        )

    # Фильтр по активным
    response_active = await async_client.get(
        COMPANIES_ENDPOINT,
        headers=superuser_token_headers,
        params={"is_active": "true"},  # FastAPI сконвертирует в bool
    )
    assert response_active.status_code == 200
    data_active = response_active.json()
    # Внимание: count может быть больше 2, если есть другие активные компании
    assert data_active["count"] >= 2
    active_ids = {item["id"] for item in data_active["items"]}
    assert str(c_active1.id) in active_ids
    assert str(c_active2.id) in active_ids
    assert str(c_inactive.id) not in active_ids
    assert all(
        item["is_active"]
        for item in data_active["items"]
        if item["id"] in [str(c_active1.id), str(c_active2.id)]
    )

    # Фильтр по неактивным
    response_inactive = await async_client.get(
        COMPANIES_ENDPOINT,
        headers=superuser_token_headers,
        params={"is_active": "false"},
    )
    assert response_inactive.status_code == 200
    data_inactive = response_inactive.json()
    assert data_inactive["count"] >= 1
    inactive_ids = {item["id"] for item in data_inactive["items"]}
    assert str(c_inactive.id) in inactive_ids
    assert str(c_active1.id) not in inactive_ids
    assert all(
        not item["is_active"]
        for item in data_inactive["items"]
        if item["id"] == str(c_inactive.id)
    )


async def test_list_companies_filter_vat_id_isnull(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    dam_factory_test: DataAccessManagerFactory,
):
    """Тест фильтрации компаний по наличию/отсутствию vat_id."""
    base_name = f"VatNullFilter_{uuid4()}"
    async with managed_session():
        manager = dam_factory_test.get_manager("Company")
        c_with_vat = await manager.create(
            {"name": f"{base_name}_With", "vat_id": "12345"}
        )
        c_without_vat = await manager.create(
            {"name": f"{base_name}_Without", "vat_id": None}
        )

    # Ищем те, у которых vat_id IS NULL
    response_null = await async_client.get(
        COMPANIES_ENDPOINT,
        headers=superuser_token_headers,
        params={"vat_id__isnull": "true"},
    )
    assert response_null.status_code == 200
    data_null = response_null.json()
    assert data_null["count"] >= 1
    null_ids = {item["id"] for item in data_null["items"]}
    assert str(c_without_vat.id) in null_ids
    assert str(c_with_vat.id) not in null_ids

    # Ищем те, у которых vat_id IS NOT NULL
    response_not_null = await async_client.get(
        COMPANIES_ENDPOINT,
        headers=superuser_token_headers,
        params={"vat_id__isnull": "false"},
    )
    assert response_not_null.status_code == 200
    data_not_null = response_not_null.json()
    assert data_not_null["count"] >= 1
    not_null_ids = {item["id"] for item in data_not_null["items"]}
    assert str(c_with_vat.id) in not_null_ids
    assert str(c_without_vat.id) not in not_null_ids


# --- Добавить тесты для других операторов: __in, __gt, __lt и т.д., если они определены в CompanyFilter ---
# --- Добавить тесты для комбинации фильтров ---
async def test_list_companies_filter_combined(
    async_client: AsyncClient,
    superuser_token_headers: dict,
    dam_factory_test: DataAccessManagerFactory,
):
    """Тест комбинации фильтров."""
    prefix = f"Combined_{uuid4()}"
    async with managed_session():
        manager = dam_factory_test.get_manager("Company")
        c1 = await manager.create({"name": f"{prefix}_Active", "is_active": True})
        c2 = await manager.create({"name": f"{prefix}_Inactive", "is_active": False})
        c3 = await manager.create({"name": f"Other_{prefix}_Active", "is_active": True})

    response = await async_client.get(
        COMPANIES_ENDPOINT,
        headers=superuser_token_headers,
        params={"name__like": prefix, "is_active": "true"},  # Ищем активные с префиксом
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["id"] == str(c1.id)
