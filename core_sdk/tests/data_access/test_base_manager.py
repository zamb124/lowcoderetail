# core_sdk/tests/data_access/test_base_manager.py
import pytest
import uuid # Не используется напрямую, но может понадобиться для других моделей
from typing import List, Optional, Dict, Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession # Для type hinting
from pydantic import BaseModel, Field as PydanticField, ValidationError
from starlette.exceptions import HTTPException

from core_sdk.data_access.base_manager import BaseDataAccessManager
from data_access import DataAccessManagerFactory
from registry import ModelRegistry
from core_sdk.tests.conftest import Item, ItemCreate, ItemUpdate, ItemRead, ItemFilter # Импортируем тестовые модели/схемы

pytestmark = pytest.mark.asyncio # Все тесты в этом файле асинхронные

# --- Тесты для CREATE ---
async def test_create_item_success(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], db_session: AsyncSession):
    item_data = ItemCreate(name="Test Item 1", description="Description 1", value=100, lsn=1)
    created_item = await item_manager.create(item_data)

    assert created_item is not None
    assert created_item.id is not None
    assert created_item.name == item_data.name
    assert created_item.description == item_data.description
    assert created_item.value == item_data.value
    assert created_item.lsn is not None

    # Проверяем, что объект действительно в БД
    fetched_item = await db_session.get(Item, created_item.id)
    assert fetched_item is not None
    assert fetched_item.name == item_data.name

async def test_create_item_with_dict(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], db_session: AsyncSession):
    item_data_dict = {"name": "Test Item Dict", "value": 200}
    created_item = await item_manager.create(item_data_dict) # Передаем dict

    assert created_item is not None
    assert created_item.name == item_data_dict["name"]
    assert created_item.value == item_data_dict["value"]

async def test_create_item_validation_error(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate]):
    # ItemCreate требует name, передаем невалидные данные (без name)
    invalid_data = {"description": "Only description"}
    with pytest.raises(HTTPException) as exc_info: # Ожидаем HTTPException от Pydantic ValidationError
        await item_manager.create(invalid_data) # type: ignore
    assert exc_info.value.status_code == 422

# --- Тесты для GET ---
async def test_get_item_success(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], db_session):
    item_data = ItemCreate(name="Get Item")
    created_item = await item_manager.create(item_data)

    fetched_item = await item_manager.get(created_item.id)
    assert fetched_item is not None
    assert fetched_item.id == created_item.id
    assert fetched_item.name == "Get Item"

async def test_get_item_not_found(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate]):
    # Используем фиктивный ID, которого нет в БД
    # В SQLite ID обычно int, но для общего случая можно использовать UUID, если модель его поддерживает
    # Наша тестовая модель Item использует int ID.
    non_existent_id = uuid.uuid4()
    fetched_item = await item_manager.get(non_existent_id) # type: ignore
    assert fetched_item is None

# --- Тесты для UPDATE ---
async def test_update_item_success(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate]):
    created_item = await item_manager.create(ItemCreate(name="Original Name", value=10))

    update_data = ItemUpdate(name="Updated Name", value=20)
    updated_item = await item_manager.update(created_item.id, update_data)

    assert updated_item is not None
    assert updated_item.id == created_item.id
    assert updated_item.name == "Updated Name"
    assert updated_item.value == 20
    assert updated_item.description == created_item.description # Не меняли

async def test_update_item_with_dict(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate]):
    created_item = await item_manager.create(ItemCreate(name="Dict Update Original"))
    update_data_dict = {"description": "Updated via Dict"}
    updated_item = await item_manager.update(created_item.id, update_data_dict) # Передаем dict

    assert updated_item.description == "Updated via Dict"
    assert updated_item.name == "Dict Update Original" # Не меняли

async def test_update_item_not_found(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate]):
    non_existent_id = uuid.uuid4()
    update_data = ItemUpdate(name="Won't Update")
    with pytest.raises(HTTPException) as exc_info:
        await item_manager.update(non_existent_id, update_data) # type: ignore
    assert exc_info.value.status_code == 404

async def test_update_item_partial_update(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate]):
    created_item = await item_manager.create(ItemCreate(name="Partial Original", description="Desc", value=50))
    # ItemUpdate все поля Optional, так что это частичное обновление
    update_data = ItemUpdate(value=55)
    updated_item = await item_manager.update(created_item.id, update_data)

    assert updated_item.name == "Partial Original" # Должно остаться
    assert updated_item.description == "Desc"     # Должно остаться
    assert updated_item.value == 55               # Должно измениться

# --- Тесты для DELETE ---
async def test_delete_item_success(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], db_session: AsyncSession):
    created_item = await item_manager.create(ItemCreate(name="To Be Deleted"))
    item_id = created_item.id

    delete_success = await item_manager.delete(item_id)
    assert delete_success is True

    # Проверяем, что объект действительно удален из БД
    deleted_item_from_db = await db_session.get(Item, item_id)
    assert deleted_item_from_db is None

async def test_delete_item_not_found(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate]):
    non_existent_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc_info:
        await item_manager.delete(non_existent_id) # type: ignore
    assert exc_info.value.status_code == 404

# --- Тесты для LIST (пагинация и фильтрация) ---
@pytest_asyncio.fixture(scope="function")
async def sample_items(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], db_session) -> List[Item]:
    """Создает несколько тестовых элементов для пагинации и фильтрации."""
    items_data = [
        ItemCreate(name="Apple", description="Red fruit", value=10, lsn=1),
        ItemCreate(name="Banana", description="Yellow fruit", value=20, lsn=2),
        ItemCreate(name="Cherry", description="Red small fruit", value=15, lsn=3),
        ItemCreate(name="Date", description="Brown sweet fruit", value=20, lsn=4),
        ItemCreate(name="Elderberry", description="Dark berry", value=25, lsn=5),
    ]
    created = []
    for data in items_data:
        # Небольшая задержка, чтобы lsn гарантированно отличались, если БД быстрая
        # await asyncio.sleep(0.001) # Для SQLite in-memory это может не понадобиться
        created.append(await item_manager.create(data))
    return created

async def test_list_items_default_pagination(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], sample_items: List[Item]):
    result = await item_manager.list(limit=3) # Запрашиваем первые 3
    assert len(result["items"]) == 3
    assert result["count"] == 3
    assert result["items"][0].name == "Apple"
    assert result["items"][1].name == "Banana"
    assert result["items"][2].name == "Cherry"
    assert result["next_cursor"] == result["items"][2].lsn # Курсор на последний элемент

    # Запрашиваем следующую страницу
    result_page2 = await item_manager.list(cursor=3, limit=3)
    assert len(result_page2["items"]) == 2 # Осталось 2 элемента
    assert result_page2["count"] == 2
    assert result_page2["items"][0].name == "Date"
    assert result_page2["items"][1].name == "Elderberry"
    assert result_page2["next_cursor"] == result_page2["items"][1].lsn

    # Запрашиваем еще страницу (должно быть пусто)
    result_page3 = await item_manager.list(cursor=result_page2["next_cursor"], limit=3)
    assert len(result_page3["items"]) == 0
    assert result_page3["count"] == 0
    assert result_page3["next_cursor"] == result_page2["next_cursor"] # Курсор не должен измениться

async def test_list_items_desc_pagination(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], sample_items: List[Item]):
    # Сначала получаем последнюю страницу в DESC (самые новые)
    # Так как cursor=None, он возьмет самые "большие" LSN
    result_desc1 = await item_manager.list(limit=3, direction="desc")
    assert len(result_desc1["items"]) == 3
    assert result_desc1["items"][0].name == "Elderberry" # Самый новый (наибольший LSN)
    assert result_desc1["items"][1].name == "Date"
    assert result_desc1["items"][2].name == "Cherry"
    # next_cursor в DESC указывает на LSN первого элемента в текущем наборе (самого нового из этой пачки)
    assert result_desc1["next_cursor"] == result_desc1["items"][-1].lsn

    # Запрашиваем "предыдущую" страницу в DESC (элементы с меньшим LSN)
    result_desc2 = await item_manager.list(cursor=result_desc1["next_cursor"], limit=3, direction="desc")
    assert len(result_desc2["items"]) == 2
    assert result_desc2["items"][0].name == "Banana"
    assert result_desc2["items"][1].name == "Apple"
    assert result_desc2["next_cursor"] == result_desc2["items"][-1].lsn

async def test_list_items_filter_exact_name(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], sample_items: List[Item]):
    # Используем словарь для фильтров
    filters_dict = {"name": "Banana"}
    result = await item_manager.list(filters=filters_dict)
    assert len(result["items"]) == 1
    assert result["items"][0].name == "Banana"

async def test_list_items_filter_name_like(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], sample_items: List[Item]):
    # Используем объект фильтра
    filter_obj = ItemFilter(name__like="berry") # Elderberry
    result = await item_manager.list(filters=filter_obj)
    assert len(result["items"]) == 1
    assert result["items"][0].name == "Elderberry"

async def test_list_items_filter_value_gt(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], sample_items: List[Item]):
    # Banana (20), Date (20), Elderberry (25)
    filter_obj = ItemFilter(value__gt=15)
    result = await item_manager.list(filters=filter_obj, limit=10) # Увеличим лимит, чтобы все вошли
    assert len(result["items"]) == 3
    names = {item.name for item in result["items"]}
    assert "Banana" in names
    assert "Date" in names
    assert "Elderberry" in names

async def test_list_items_search_filter(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], sample_items: List[Item]):
    # Ищем "fruit" в name или description
    # Apple, Banana, Cherry, Date
    filter_obj = ItemFilter(search="fruit")
    result = await item_manager.list(filters=filter_obj, limit=10)
    assert len(result["items"]) == 4
    names = {item.name for item in result["items"]}
    assert "Apple" in names and "Banana" in names and "Cherry" in names and "Date" in names
    assert "Elderberry" not in names # "Dark berry"

async def test_list_items_combined_filters(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], sample_items: List[Item]):
    # Ищем "Red" и value > 10
    # Apple (value=10, desc="Red fruit") - не подойдет, т.к. value не > 10
    # Cherry (value=15, desc="Red small fruit") - подойдет
    filters_dict = {"search": "Red", "value__gt": 10}
    result = await item_manager.list(filters=filters_dict)
    assert len(result["items"]) == 1
    assert result["items"][0].name == "Cherry"

async def test_list_items_filter_with_registered_filter_class(item_manager: BaseDataAccessManager[Item, ItemCreate, ItemUpdate], sample_items: List[Item]):
    # Проверяем, что менеджер использует ItemFilter, зарегистрированный в ModelRegistry
    # Этот тест косвенно проверяет _get_filter_class()
    filter_instance = ItemFilter(name="Apple") # Создаем экземпляр зарегистрированного фильтра
    result = await item_manager.list(filters=filter_instance)
    assert len(result["items"]) == 1
    assert result["items"][0].name == "Apple"

# --- Тесты для хуков (пример) ---
class CustomItemManager(BaseDataAccessManager[Item, ItemCreate, ItemUpdate]):
    model = Item # Нужно явно указать для _get_filter_class
    create_schema = ItemCreate
    update_schema = ItemUpdate

    _create_hook_called = False
    _update_hook_called = False
    _delete_hook_called = False

    async def _prepare_for_create(self, validated_data: ItemCreate) -> Item:
        self.__class__._create_hook_called = True
        # Можно изменить validated_data или создать Item по-своему
        if validated_data.name == "Hook Test Create":
            validated_data.description = "Set by create hook"
        return await super()._prepare_for_create(validated_data)

    async def _prepare_for_update(self, db_item: Item, update_payload: Dict[str, Any]) -> tuple[Item, bool]:
        self.__class__._update_hook_called = True
        if update_payload.get("name") == "Hook Test Update":
            update_payload["description"] = "Set by update hook"
        return await super()._prepare_for_update(db_item, update_payload)

    async def _prepare_for_delete(self, db_item: Item) -> None:
        self.__class__._delete_hook_called = True
        # Можно выполнить действия перед удалением, например, проверить условия
        if db_item.name == "Prevent Delete Hook":
            raise HTTPException(status_code=403, detail="Deletion prevented by hook")
        await super()._prepare_for_delete(db_item)

@pytest.fixture
def custom_item_manager(db_session) -> CustomItemManager: # Зависит от db_session_management для ModelRegistry
    # Регистрируем CustomItemManager для модели "Item" на время этого теста
    # Важно, чтобы ModelRegistry был очищен/восстановлен после теста
    # Фикстура db_session_management уже это делает.

    # Сначала очистим, если там что-то есть от предыдущих тестов (хотя db_session_management должна это делать)
    # ModelRegistry.clear()
    ModelRegistry.register_local(
        model_cls=Item,
        manager_cls=CustomItemManager, # Используем наш кастомный менеджер
        create_schema_cls=ItemCreate,
        update_schema_cls=ItemUpdate,
        read_schema_cls=ItemRead,
        filter_cls=ItemFilter,
        model_name="ItemForHookTests" # Используем другое имя, чтобы не конфликтовать с "Item"
    )
    factory = DataAccessManagerFactory(registry=ModelRegistry)
    manager = factory.get_manager("ItemForHookTests")
    # Сбрасываем флаги перед каждым тестом, использующим эту фикстуру
    CustomItemManager._create_hook_called = False
    CustomItemManager._update_hook_called = False
    CustomItemManager._delete_hook_called = False
    return manager # type: ignore

async def test_create_hook(custom_item_manager: CustomItemManager):
    item_data = ItemCreate(name="Hook Test Create")
    created_item = await custom_item_manager.create(item_data)
    assert CustomItemManager._create_hook_called is True
    assert created_item.description == "Set by create hook"

async def test_update_hook(custom_item_manager: CustomItemManager):
    item = await custom_item_manager.create(ItemCreate(name="Item for Update Hook"))
    update_data = ItemUpdate(name="Hook Test Update")
    updated_item = await custom_item_manager.update(item.id, update_data)
    assert CustomItemManager._update_hook_called is True
    assert updated_item.description == "Set by update hook"

async def test_delete_hook_success(custom_item_manager: CustomItemManager):
    item = await custom_item_manager.create(ItemCreate(name="Item for Delete Hook"))
    await custom_item_manager.delete(item.id)
    assert CustomItemManager._delete_hook_called is True

async def test_delete_hook_prevent(custom_item_manager: CustomItemManager):
    item = await custom_item_manager.create(ItemCreate(name="Prevent Delete Hook"))
    with pytest.raises(HTTPException) as exc_info:
        await custom_item_manager.delete(item.id)
    assert CustomItemManager._delete_hook_called is True # Хук вызвался
    assert exc_info.value.status_code == 403
    assert "Deletion prevented by hook" in exc_info.value.detail