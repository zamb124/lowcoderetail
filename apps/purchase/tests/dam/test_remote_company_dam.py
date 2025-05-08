# purchase/app/tests/dam/test_remote_company_dam.py
import pytest
import uuid
from typing import Optional, List

from core_sdk.data_access import DataAccessManagerFactory, RemoteDataAccessManager
from purchase.app.schemas.company_schema import CompanyReadPurchase, CompanyCreatePurchase, CompanyUpdatePurchase
from purchase.app.config import settings as purchase_settings # Настройки purchase

pytestmark = pytest.mark.asyncio

# Пропускаем тесты, если CORE_SERVICE_URL не настроен
if not purchase_settings.CORE_SERVICE_URL:
    pytest.skip("CORE_SERVICE_URL not configured, skipping remote Company DAM tests", allow_module_level=True)

async def get_company_manager(dam_factory: DataAccessManagerFactory) -> RemoteDataAccessManager:
    """Вспомогательная функция для получения и проверки типа менеджера."""
    manager = dam_factory.get_manager("CoreCompany") # Используем имя, указанное при регистрации
    assert isinstance(manager, RemoteDataAccessManager), \
        f"Expected RemoteDataAccessManager for 'CoreCompany', got {type(manager)}"
    return manager

@pytest.mark.integration_remote # Помечаем как интеграционный тест с удаленным сервисом
async def test_remote_create_and_delete_company(
        dam_factory_purchase_test: DataAccessManagerFactory,
        core_superuser_token: Optional[str] # Токен для аутентификации в Core
):
    """Тест создания и удаления компании через удаленный DAM."""
    if not core_superuser_token:
        pytest.skip("Core superuser token not available, skipping remote create/delete company test.")

    manager = await get_company_manager(dam_factory_purchase_test)

    company_name = f"Remote TestCo {uuid.uuid4().hex[:6]}"
    company_data = CompanyCreatePurchase(name=company_name, description="Created remotely via Purchase DAM")

    created_company: Optional[CompanyReadPurchase] = None
    try:
        # Создание
        created_company = await manager.create(company_data)
        assert created_company is not None, "Remote company creation returned None"
        assert created_company.name == company_name
        assert created_company.id is not None
        print(f"Remotely created company: ID {created_company.id}, Name '{created_company.name}'")

        # Получение для проверки
        fetched_company: Optional[CompanyReadPurchase] = await manager.get(created_company.id)
        assert fetched_company is not None, "Failed to fetch remotely created company"
        assert fetched_company.id == created_company.id
        assert fetched_company.name == company_name

    finally:
        # Очистка: удаляем компанию, если она была создана
        if created_company and created_company.id:
            print(f"Cleaning up: deleting remotely created company {created_company.id}")
            deleted = await manager.delete(created_company.id)
            assert deleted is True, f"Failed to delete remotely created company {created_company.id}"

            # Дополнительная проверка, что компания действительно удалена
            fetched_after_delete = await manager.get(created_company.id)
            assert fetched_after_delete is None, "Company still exists after remote delete"
            print(f"Company {created_company.id} confirmed deleted.")

@pytest.mark.integration_remote
async def test_remote_list_companies_with_filters(
        dam_factory_purchase_test: DataAccessManagerFactory,
        core_superuser_token: Optional[str]
):
    """Тест получения списка компаний с фильтрацией через удаленный DAM."""
    if not core_superuser_token:
        pytest.skip("Core superuser token not available, skipping remote list companies test.")

    manager = await get_company_manager(dam_factory_purchase_test)

    # Создаем несколько компаний для теста фильтрации
    unique_prefix = f"FilterableCo_{uuid.uuid4().hex[:4]}"
    name1 = f"{unique_prefix}_ActiveAlpha"
    name2 = f"{unique_prefix}_InactiveBeta"
    name3 = f"{unique_prefix}_ActiveGamma"
    other_name = f"NonFilterable_{uuid.uuid4().hex[:4]}"

    companies_to_create_data = [
        CompanyCreatePurchase(name=name1, is_active=True, description="First filterable"),
        CompanyCreatePurchase(name=name2, is_active=False, description="Second filterable"),
        CompanyCreatePurchase(name=name3, is_active=True, description="Third filterable"),
        CompanyCreatePurchase(name=other_name, is_active=True, description="Should not be in name__like results"),
    ]

    created_ids: List[uuid.UUID] = []
    try:
        for data in companies_to_create_data:
            c = await manager.create(data)
            assert c is not None and c.id is not None
            created_ids.append(c.id)

        print(f"Created {len(created_ids)} companies for list/filter test.")

        # Тест 1: Фильтр по части имени (name__like)
        # API Core сервиса должен поддерживать query-параметр `name__like`
        list_params_name_like = {"name__like": unique_prefix, "limit": 5}
        companies_liked: List[CompanyReadPurchase] = await manager.list(filters=list_params_name_like)
        assert len(companies_liked) == 3, f"Expected 3 companies with prefix '{unique_prefix}', got {len(companies_liked)}"
        liked_names = {c.name for c in companies_liked}
        assert name1 in liked_names
        assert name2 in liked_names
        assert name3 in liked_names
        print(f"Filtered by name__like '{unique_prefix}', found names: {liked_names}")

        # Тест 2: Фильтр по is_active=True и части имени
        list_params_active_true = {"name__like": unique_prefix, "is_active": "true", "limit": 5}
        companies_active: List[CompanyReadPurchase] = await manager.list(filters=list_params_active_true)
        assert len(companies_active) == 2, f"Expected 2 active companies with prefix, got {len(companies_active)}"
        active_names = {c.name for c in companies_active}
        assert name1 in active_names
        assert name3 in active_names
        print(f"Filtered by name__like '{unique_prefix}' and is_active=true, found names: {active_names}")

        # Тест 3: Фильтр по is_active=False и части имени
        list_params_active_false = {"name__like": unique_prefix, "is_active": "false", "limit": 5}
        companies_inactive: List[CompanyReadPurchase] = await manager.list(filters=list_params_active_false)
        assert len(companies_inactive) == 1, f"Expected 1 inactive company with prefix, got {len(companies_inactive)}"
        assert companies_inactive[0].name == name2
        print(f"Filtered by name__like '{unique_prefix}' and is_active=false, found name: {companies_inactive[0].name}")

        # Тест 4: Пагинация (проверка limit)
        # RemoteDataAccessManager.list возвращает просто список, без информации о next_cursor.
        # Поэтому полноценную курсорную пагинацию так не проверить. Проверим только limit.
        list_params_limit_check = {"name__like": unique_prefix, "limit": 1}
        limited_companies: List[CompanyReadPurchase] = await manager.list(filters=list_params_limit_check)
        assert len(limited_companies) == 1, "Limit check failed"
        print(f"Limit check: requested 1, got {len(limited_companies)}")

    finally:
        # Очистка созданных компаний
        print(f"Cleaning up {len(created_ids)} companies from list/filter test...")
        for company_id in created_ids:
            await manager.delete(company_id)
        print("Cleanup complete for list/filter test.")


@pytest.mark.integration_remote
async def test_remote_update_company(
        dam_factory_purchase_test: DataAccessManagerFactory,
        core_superuser_token: Optional[str]
):
    """Тест обновления компании через удаленный DAM."""
    if not core_superuser_token:
        pytest.skip("Core superuser token not available, skipping remote update company test.")

    manager = await get_company_manager(dam_factory_purchase_test)

    company_name = f"Remote UpdateCo {uuid.uuid4().hex[:6]}"
    company_data = CompanyCreatePurchase(name=company_name, description="Initial Description", is_active=True)

    created_company: Optional[CompanyReadPurchase] = None
    try:
        created_company = await manager.create(company_data)
        assert created_company is not None and created_company.id is not None

        updated_description = "Description Updated Remotely via Purchase"
        update_payload = CompanyUpdatePurchase(description=updated_description, is_active=False)

        updated_company: Optional[CompanyReadPurchase] = await manager.update(created_company.id, update_payload)
        assert updated_company is not None, "Remote company update returned None"
        assert updated_company.id == created_company.id
        assert updated_company.name == company_name # Имя не меняли
        assert updated_company.description == updated_description
        assert updated_company.is_active is False
        print(f"Remotely updated company: ID {updated_company.id}, Desc '{updated_company.description}', Active: {updated_company.is_active}")

    finally:
        if created_company and created_company.id:
            await manager.delete(created_company.id)