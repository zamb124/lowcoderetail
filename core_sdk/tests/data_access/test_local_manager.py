# core_sdk/tests/data_access/test_local_manager.py
import pytest
import uuid
from typing import List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException

from core_sdk.data_access.local_manager import LocalDataAccessManager
from core_sdk.tests.conftest import Item, ItemCreate, ItemUpdate, ItemRead, ItemFilter
import logging

from core_sdk.data_access import DataAccessManagerFactory
from core_sdk.registry import ModelRegistry

test_logger = logging.getLogger("core_sdk.tests.test_local_manager")

pytestmark = pytest.mark.asyncio

# Фикстура item_manager уже определена в core_sdk/tests/conftest.py
# и возвращает LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead]

# --- Тесты для CREATE ---
async def test_create_item_success(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        db_session: AsyncSession
):
    test_logger.info("--- test_create_item_success START ---")
    item_data = ItemCreate(name="Test Item 1", description="Description 1", value=100)

    created_item_sqlmodel = await item_manager.create(item_data)

    assert created_item_sqlmodel is not None
    assert isinstance(created_item_sqlmodel, Item)
    assert created_item_sqlmodel.id is not None
    assert created_item_sqlmodel.name == item_data.name
    assert created_item_sqlmodel.description == item_data.description
    assert created_item_sqlmodel.value == item_data.value
    #assert created_item_sqlmodel.lsn is not None

    fetched_item = await db_session.get(Item, created_item_sqlmodel.id)
    assert fetched_item is not None
    assert fetched_item.name == item_data.name
    test_logger.info("--- test_create_item_success END ---")


async def test_create_item_with_dict(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        db_session: AsyncSession,
):
    item_data_dict = {"name": "Test Item Dict", "value": 200}
    created_item_sqlmodel = await item_manager.create(item_data_dict)

    assert created_item_sqlmodel is not None
    assert isinstance(created_item_sqlmodel, Item)
    assert created_item_sqlmodel.name == item_data_dict["name"]
    assert created_item_sqlmodel.value == item_data_dict["value"]


async def test_create_item_validation_error(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
):
    invalid_data = {"description": "Only description"} # name - обязательное поле в ItemCreate
    with pytest.raises(HTTPException) as exc_info:
        await item_manager.create(invalid_data) # type: ignore
    assert exc_info.value.status_code == 422


# --- Тесты для GET ---
async def test_get_item_success(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        db_session: AsyncSession
):
    item_data = ItemCreate(name="Get Item SQLModel")
    created_item_for_get = await item_manager.create(item_data)

    fetched_item_sqlmodel = await item_manager.get(created_item_for_get.id) # type: ignore
    assert fetched_item_sqlmodel is not None
    assert isinstance(fetched_item_sqlmodel, Item)
    assert fetched_item_sqlmodel.id == created_item_for_get.id
    assert fetched_item_sqlmodel.name == "Get Item SQLModel"


async def test_get_item_not_found(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
):
    non_existent_id = uuid.uuid4()
    fetched_item_sqlmodel = await item_manager.get(non_existent_id)
    assert fetched_item_sqlmodel is None


# --- Тесты для UPDATE ---
async def test_update_item_success(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
):
    created_item_sqlmodel = await item_manager.create(ItemCreate(name="Original Name", value=10))

    update_data = ItemUpdate(name="Updated Name", value=20)
    updated_item_sqlmodel = await item_manager.update(created_item_sqlmodel.id, update_data) # type: ignore

    assert updated_item_sqlmodel is not None
    assert isinstance(updated_item_sqlmodel, Item)
    assert updated_item_sqlmodel.id == created_item_sqlmodel.id
    assert updated_item_sqlmodel.name == "Updated Name"
    assert updated_item_sqlmodel.value == 20
    assert updated_item_sqlmodel.description == created_item_sqlmodel.description


async def test_update_item_with_dict(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
):
    created_item_sqlmodel = await item_manager.create(ItemCreate(name="Dict Update Original"))
    update_data_dict = {"description": "Updated via Dict"}
    updated_item_sqlmodel = await item_manager.update(created_item_sqlmodel.id, update_data_dict) # type: ignore

    assert isinstance(updated_item_sqlmodel, Item)
    assert updated_item_sqlmodel.description == "Updated via Dict"
    assert updated_item_sqlmodel.name == "Dict Update Original"


async def test_update_item_not_found(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
):
    non_existent_id = uuid.uuid4()
    update_data = ItemUpdate(name="Won't Update")
    with pytest.raises(HTTPException) as exc_info:
        await item_manager.update(non_existent_id, update_data)
    assert exc_info.value.status_code == 404


async def test_update_item_partial_update(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
):
    created_item_sqlmodel = await item_manager.create(
        ItemCreate(name="Partial Original", description="Desc", value=50)
    )
    update_data = ItemUpdate(value=55) # Только value
    updated_item_sqlmodel = await item_manager.update(created_item_sqlmodel.id, update_data) # type: ignore

    assert isinstance(updated_item_sqlmodel, Item)
    assert updated_item_sqlmodel.name == "Partial Original"
    assert updated_item_sqlmodel.description == "Desc"
    assert updated_item_sqlmodel.value == 55


# --- Тесты для DELETE ---
async def test_delete_item_success(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        db_session: AsyncSession,
):
    created_item_sqlmodel = await item_manager.create(ItemCreate(name="To Be Deleted"))
    item_id = created_item_sqlmodel.id

    delete_success = await item_manager.delete(item_id) # type: ignore
    assert delete_success is True

    deleted_item_from_db = await db_session.get(Item, item_id) # type: ignore
    assert deleted_item_from_db is None


async def test_delete_item_not_found(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
):
    non_existent_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc_info:
        await item_manager.delete(non_existent_id)
    assert exc_info.value.status_code == 404


# --- Тесты для LIST (пагинация и фильтрация) ---
# Фикстура sample_items из conftest.py уже возвращает List[Item] (SQLModel)

async def test_list_items_default_pagination(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        sample_items: List[Item], # sample_items из conftest.py
):
    result = await item_manager.list(limit=3)
    assert len(result["items"]) == 3
    assert result["count"] == 3
    assert isinstance(result["items"][0], Item)
    assert result["items"][0].name == "Apple" # Имена из sample_items
    assert result["items"][1].name == "Banana"
    assert result["items"][2].name == "Cherry"
    assert result["next_cursor"] == result["items"][2].lsn

    result_page2 = await item_manager.list(cursor=result["items"][2].lsn, limit=3) # type: ignore
    assert len(result_page2["items"]) == 2
    assert isinstance(result_page2["items"][0], Item)
    assert result_page2["items"][0].name == "Date"
    assert result_page2["items"][1].name == "Elderberry"
    assert result_page2["next_cursor"] == result_page2["items"][1].lsn

    result_page3 = await item_manager.list(cursor=result_page2["next_cursor"], limit=3)
    assert len(result_page3["items"]) == 0
    assert result_page3["count"] == 0
    assert result_page3["next_cursor"] == result_page2["next_cursor"]


async def test_list_items_desc_pagination(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        sample_items: List[Item],
):
    result_desc1 = await item_manager.list(limit=3, direction="desc")
    assert len(result_desc1["items"]) == 3
    assert isinstance(result_desc1["items"][0], Item)
    assert result_desc1["items"][0].name == "Elderberry"
    assert result_desc1["items"][1].name == "Date"
    assert result_desc1["items"][2].name == "Cherry"
    assert result_desc1["next_cursor"] == result_desc1["items"][-1].lsn

    result_desc2 = await item_manager.list(cursor=result_desc1["next_cursor"], limit=3, direction="desc")
    assert len(result_desc2["items"]) == 2
    assert isinstance(result_desc2["items"][0], Item)
    assert result_desc2["items"][0].name == "Banana"
    assert result_desc2["items"][1].name == "Apple"
    assert result_desc2["next_cursor"] == result_desc2["items"][-1].lsn


async def test_list_items_filter_exact_name(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        sample_items: List[Item],
):
    filters_dict = {"name": "Banana"}
    result = await item_manager.list(filters=filters_dict)
    assert len(result["items"]) == 1
    assert isinstance(result["items"][0], Item)
    assert result["items"][0].name == "Banana"


async def test_list_items_filter_name_like(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        sample_items: List[Item],
):
    filter_obj = ItemFilter(name__like="berry")
    result = await item_manager.list(filters=filter_obj)
    assert len(result["items"]) == 1
    assert isinstance(result["items"][0], Item)
    assert result["items"][0].name == "Elderberry"


async def test_list_items_filter_value_gt(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        sample_items: List[Item],
):
    filter_obj = ItemFilter(value__gt=15)
    result = await item_manager.list(filters=filter_obj, limit=10)
    assert len(result["items"]) == 3
    names = {item.name for item in result["items"]}
    assert "Banana" in names and "Date" in names and "Elderberry" in names


async def test_list_items_search_filter(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        sample_items: List[Item],
):
    filter_obj = ItemFilter(search="fruit")
    result = await item_manager.list(filters=filter_obj, limit=10)
    assert len(result["items"]) == 4
    names = {item.name for item in result["items"]}
    assert "Apple" in names and "Banana" in names and "Cherry" in names and "Date" in names
    assert "Elderberry" not in names


async def test_list_items_combined_filters(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        sample_items: List[Item],
):
    filters_dict = {"search": "Red", "value__gt": 10}
    result = await item_manager.list(filters=filters_dict)
    assert len(result["items"]) == 1
    assert isinstance(result["items"][0], Item)
    assert result["items"][0].name == "Cherry"


async def test_list_items_filter_with_registered_filter_class(
        item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead],
        sample_items: List[Item],
):
    filter_instance = ItemFilter(name="Apple")
    result = await item_manager.list(filters=filter_instance)
    assert len(result["items"]) == 1
    assert isinstance(result["items"][0], Item)
    assert result["items"][0].name == "Apple"


# --- Тесты для хуков ---
# CustomItemManagerForSQLModel из conftest.py уже адаптирован
# для работы с Item (SQLModel) и ItemCreate/ItemRead (Pydantic)

@pytest.fixture
def custom_item_manager( # Переопределяем фикстуру из test_base_manager, если она там была
        db_session: AsyncSession,
        manage_model_registry_for_tests: Any
) -> LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead]: # Возвращает типизированный менеджер
    # Используем CustomLocalFactoryItemManager из conftest, который уже LocalManager
    # или создаем новый кастомный менеджер здесь, если нужно.
    # Для простоты, предположим, что CustomLocalFactoryItemManager подходит.
    # Если нет, нужно создать новый класс CustomItemManagerForLocalTests,
    # наследуемый от LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead]
    # и переопределяющий хуки.

    class HookTestingManager(LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead]):
        _create_hook_called = False
        _update_hook_called = False
        _delete_hook_called = False

        async def _prepare_for_create(self, validated_data: ItemCreate) -> Item:
            HookTestingManager._create_hook_called = True
            if validated_data.name == "Hook Test Create":
                validated_data.description = "Set by create hook"
            # model_cls здесь Item (SQLModel)
            return self.model_cls.model_validate(validated_data) # Pydantic -> SQLModel

        async def _prepare_for_update(
                self, db_item: Item, update_payload: Dict[str, Any]
        ) -> tuple[Item, bool]:
            HookTestingManager._update_hook_called = True
            if update_payload.get("name") == "Hook Test Update":
                update_payload["description"] = "Set by update hook"
            return await super()._prepare_for_update(db_item, update_payload)

        async def _prepare_for_delete(self, db_item: Item) -> None:
            HookTestingManager._delete_hook_called = True
            if db_item.name == "Prevent Delete Hook":
                raise HTTPException(status_code=403, detail="Deletion prevented by hook")
            await super()._prepare_for_delete(db_item)

    # Регистрируем этот менеджер для тестов хуков
    ModelRegistry.register_local(
        model_cls=Item,
        read_schema_cls=ItemRead,
        manager_cls=HookTestingManager,
        create_schema_cls=ItemCreate,
        update_schema_cls=ItemUpdate,
        filter_cls=ItemFilter,
        model_name="ItemForLocalHookTests",
    )
    factory = DataAccessManagerFactory(registry=ModelRegistry)
    manager = factory.get_manager("ItemForLocalHookTests")

    HookTestingManager._create_hook_called = False
    HookTestingManager._update_hook_called = False
    HookTestingManager._delete_hook_called = False
    return manager # type: ignore


async def test_create_hook(custom_item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead]):
    item_data = ItemCreate(name="Hook Test Create")
    created_item_sqlmodel = await custom_item_manager.create(item_data) # Возвращает Item (SQLModel)
    assert getattr(custom_item_manager.__class__, '_create_hook_called', False) is True # Доступ через __class__
    assert isinstance(created_item_sqlmodel, Item)
    assert created_item_sqlmodel.description == "Set by create hook"


async def test_update_hook(custom_item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead]):
    item_sqlmodel = await custom_item_manager.create(ItemCreate(name="Item for Update Hook"))
    update_data = ItemUpdate(name="Hook Test Update")
    updated_item_sqlmodel = await custom_item_manager.update(item_sqlmodel.id, update_data) # type: ignore
    assert getattr(custom_item_manager.__class__, '_update_hook_called', False) is True
    assert isinstance(updated_item_sqlmodel, Item)
    assert updated_item_sqlmodel.description == "Set by update hook"


async def test_delete_hook_success(custom_item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead]):
    item_sqlmodel = await custom_item_manager.create(ItemCreate(name="Item for Delete Hook"))
    await custom_item_manager.delete(item_sqlmodel.id) # type: ignore
    assert getattr(custom_item_manager.__class__, '_delete_hook_called', False) is True


async def test_delete_hook_prevent(custom_item_manager: LocalDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead]):
    item_sqlmodel = await custom_item_manager.create(ItemCreate(name="Prevent Delete Hook"))
    with pytest.raises(HTTPException) as exc_info:
        await custom_item_manager.delete(item_sqlmodel.id) # type: ignore
    assert getattr(custom_item_manager.__class__, '_delete_hook_called', False) is True
    assert exc_info.value.status_code == 403
    assert "Deletion prevented by hook" in exc_info.value.detail