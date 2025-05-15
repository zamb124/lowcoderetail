# core_sdk/tests/frontend/test_frontend_base_router.py
import pytest
import uuid
from unittest import mock
from typing import Optional, Any

from fastapi import FastAPI, Request as FastAPIRequest, HTTPException as FastAPIHTTPException, Path as FastAPIPath
from fastapi.testclient import TestClient
from pydantic import BaseModel

from core_sdk.frontend.base import router as frontend_router
from core_sdk.frontend.renderer import ViewRenderer, RenderMode
from core_sdk.frontend.templating import initialize_templates, SDK_TEMPLATES_DIR
from core_sdk.data_access import DataAccessManagerFactory, BaseDataAccessManager, get_dam_factory
from core_sdk.registry import ModelRegistry
from core_sdk.exceptions import ConfigurationError
from core_sdk.tests.conftest import Item, ItemCreate, ItemUpdate, ItemFilter

from core_sdk.middleware.auth import AuthMiddleware
from core_sdk.tests.conftest import AppSetupTestSettings
from core_sdk.dependencies.auth import get_optional_current_user
from core_sdk.frontend.dependencies import (
    get_view_mode_renderer, get_create_form_renderer, get_edit_form_renderer,
    get_list_mode_renderer, get_list_rows_renderer,
    get_table_cell_renderer, get_inline_edit_field_renderer, get_filter_form_renderer
)

pytestmark = pytest.mark.asyncio

class MockItemRead(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    value: Optional[int] = None
    lsn: int

@pytest.fixture(scope="module", autouse=True)
def setup_templates_for_frontend_tests():
    try:
        initialize_templates(service_template_dir=SDK_TEMPLATES_DIR)
    except RuntimeError as e:
        if "Templates already initialized" not in str(e):
            raise

@pytest.fixture
def mock_dam_factory_fixture() -> mock.Mock: # Переименовал, чтобы не конфликтовать с аргументом
    factory_mock = mock.Mock(spec=DataAccessManagerFactory)
    return factory_mock

@pytest.fixture
def mock_dam_instance() -> mock.AsyncMock:
    dam_instance_mock = mock.AsyncMock(spec=BaseDataAccessManager)
    dam_instance_mock.model_name = "Item"
    return dam_instance_mock

@pytest.fixture
def test_settings() -> AppSetupTestSettings:
    return AppSetupTestSettings()

@pytest.fixture
def app_with_frontend_router(
        mock_dam_factory_fixture: mock.Mock, # Используем переименованную фикстуру
        manage_model_registry_for_tests: Any,
        test_settings: AppSetupTestSettings
) -> FastAPI:
    if not ModelRegistry._registry.get("item"):
        ModelRegistry.register_local(
            model_name="Item", model_cls=Item, read_schema_cls=MockItemRead,
            create_schema_cls=ItemCreate, update_schema_cls=ItemUpdate,
            filter_cls=ItemFilter
        )

    app = FastAPI()

    allowed_paths_for_auth = [
        "/sdk/modal-wrapper", "/sdk/resolve-titles", "/sdk/view/Item/",
        "/sdk/form/create/Item", "/sdk/form/edit/Item/",
        "/sdk/item/Item", "/sdk/item/Item/",
        "/sdk/select-options/Item", "/sdk/edit-field/Item/",
        "/sdk/view-field/Item/", "/sdk/list-rows/Item",
        "/sdk/filter/Item", "/sdk/confirm-delete/Item/", "/sdk*"
    ]

    app.add_middleware(
        AuthMiddleware,
        secret_key=test_settings.SECRET_KEY,
        algorithm=test_settings.ALGORITHM,
        allowed_paths=allowed_paths_for_auth,
        api_prefix=""
    )

    app.include_router(frontend_router)
    # Переопределяем get_dam_factory, чтобы он возвращал наш mock_dam_factory_fixture
    app.dependency_overrides[get_dam_factory] = lambda: mock_dam_factory_fixture

    def _get_mock_optional_user_none_override(request: FastAPIRequest):
        return None
    app.dependency_overrides[get_optional_current_user] = _get_mock_optional_user_none_override

    return app

@pytest.fixture
def client(app_with_frontend_router: FastAPI) -> TestClient:
    return TestClient(app_with_frontend_router)

# --- Тесты ---

def test_get_modal_wrapper(client: TestClient):
    # (без изменений)
    content_url = "/some/content"
    modal_title = "My Test Modal"
    modal_id = "test-modal-123"
    modal_size = "modal-sm"
    response = client.get(
        f"/sdk/modal-wrapper?content_url={content_url}&modal_title={modal_title}&modal_id={modal_id}&modal_size={modal_size}"
    )
    assert response.status_code == 200
    html = response.text
    assert f'id="{modal_id}"' in html
    assert f'<h5 class="modal-title">{modal_title}</h5>' in html
    assert f'class="modal-dialog {modal_size} ' in html
    assert f'hx-get="{content_url}"' in html

async def test_resolve_titles_success(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance # get_manager будет вызван внутри эндпоинта
    item_id1 = uuid.uuid4()
    item_id2 = uuid.uuid4()
    mock_dam_instance.list.return_value = {
        "items": [
            MockItemRead(id=item_id1, name="Title One", lsn=1),
            MockItemRead(id=item_id2, name="Title Two", lsn=2)
        ], "next_cursor": None, "limit": 2, "count": 2
    }
    payload = {"model_name": "Item", "ids": [str(item_id1), str(item_id2)]}
    response = client.post("/sdk/resolve-titles", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert str(item_id1) in data["root"]
    assert data["root"][str(item_id1)] == "Title One"
    assert str(item_id2) in data["root"]
    assert data["root"][str(item_id2)] == "Title Two"
    # Проверяем, что get_manager был вызван с request (FastAPI передает его в get_dam_factory)
    mock_dam_factory_fixture.get_manager.assert_called_once_with("Item", request=mock.ANY)


async def test_resolve_titles_model_not_configured(client: TestClient, mock_dam_factory_fixture: mock.Mock):
    mock_dam_factory_fixture.get_manager.side_effect = ConfigurationError("Model not found")
    payload = {"model_name": "NonExistentModel", "ids": [str(uuid.uuid4())]}
    response = client.post("/sdk/resolve-titles", json=payload)
    assert response.status_code == 404

async def test_resolve_titles_ids_not_found(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
    unknown_id = uuid.uuid4()
    mock_dam_instance.list.return_value = {"items": [], "next_cursor": None, "limit": 1, "count": 0}
    mock_dam_instance.get.return_value = None
    payload = {"model_name": "Item", "ids": [str(unknown_id)]}
    response = client.post("/sdk/resolve-titles", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert str(unknown_id) in data["root"]
    assert f"ID: {str(unknown_id)[:8]} (не найден)" in data["root"][str(unknown_id)]

@pytest.fixture
def mock_view_renderer_instance() -> mock.AsyncMock:
    renderer_mock = mock.AsyncMock(spec=ViewRenderer)
    renderer_mock.render_to_response = mock.AsyncMock(return_value="<div>Mocked Render Output</div>")
    renderer_mock.render_field_to_response = mock.AsyncMock(return_value="<span>Mocked Field Output</span>")
    renderer_mock.model_name = "Item" # Будет перезаписано в мок-функции
    renderer_mock.item_id = uuid.uuid4() # Будет перезаписано
    renderer_mock.manager = mock.AsyncMock(spec=BaseDataAccessManager)
    renderer_mock.user = None # По умолчанию, как будто get_optional_current_user вернул None
    return renderer_mock

async def test_get_view_content_calls_renderer(client: TestClient, mock_view_renderer_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
    item_id_for_test = uuid.uuid4()

    # Мок-функция для переопределения get_view_mode_renderer
    # Она должна просто вернуть наш мок ViewRenderer.
    # FastAPI сам передаст request, model_name, item_id и т.д. в ОРИГИНАЛЬНУЮ get_view_mode_renderer,
    # если бы мы ее не переопределяли.
    async def _get_mock_view_renderer_override():
        # Устанавливаем атрибуты на моке, чтобы проверить их позже, если нужно
        # Но для этого теста важно только, что render_to_response вызывается.
        # mock_view_renderer_instance.item_id = item_id_for_test # Это не нужно, если render_to_response мокирован
        return mock_view_renderer_instance

    app_with_frontend_router.dependency_overrides[get_view_mode_renderer] = _get_mock_view_renderer_override

    response = client.get(f"/sdk/view/Item/{item_id_for_test}")
    assert response.status_code == 200
    assert response.text == "<div>Mocked Render Output</div>"
    mock_view_renderer_instance.render_to_response.assert_awaited_once()

    del app_with_frontend_router.dependency_overrides[get_view_mode_renderer]

async def test_create_item_success(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
    created_item_id = uuid.uuid4()
    mock_dam_instance.create.return_value = MockItemRead(id=created_item_id, name="New", lsn=1)

    mock_renderer_returned_by_dependency = mock.AsyncMock(spec=ViewRenderer)
    mock_renderer_returned_by_dependency.manager = mock_dam_instance

    async def _get_mock_create_renderer_override():
        return mock_renderer_returned_by_dependency

    app_with_frontend_router.dependency_overrides[get_create_form_renderer] = _get_mock_create_renderer_override

    item_data = {"name": "New Item", "description": "Test create"}
    response = client.post("/sdk/item/Item", json=item_data)

    assert response.status_code == 204
    assert "HX-Trigger" in response.headers
    assert "closeModal" in response.headers["HX-Trigger"]
    assert "itemCreated_Item" in response.headers["HX-Trigger"]
    mock_dam_instance.create.assert_awaited_once()
    call_arg = mock_dam_instance.create.call_args[0][0]
    assert isinstance(call_arg, dict)
    assert call_arg["name"] == item_data["name"]

    del app_with_frontend_router.dependency_overrides[get_create_form_renderer]

async def test_create_item_validation_error_returns_form_html(
        client: TestClient,
        mock_dam_factory_fixture: mock.Mock, # Используем переименованную фикстуру
        mock_dam_instance: mock.AsyncMock,
        app_with_frontend_router: FastAPI
):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
    validation_error_detail = [{"loc": ("body", "name"), "msg": "Name is too short", "type": "value_error"}]
    mock_dam_instance.create.side_effect = FastAPIHTTPException(status_code=422, detail=validation_error_detail)

    captured_real_renderer_for_error: Optional[ViewRenderer] = None

    # Эта мок-функция будет вызвана FastAPI вместо get_create_form_renderer
    # FastAPI передаст ей аргументы, которые ожидает get_create_form_renderer
    async def _get_mock_create_renderer_for_error_override(
        request: FastAPIRequest,
        model_name: str = FastAPIPath(...)
        # dam_factory: DataAccessManagerFactory = Depends(get_dam_factory), # Убираем
        # user: Optional[AuthenticatedUser] = Depends(get_optional_current_user) # Убираем
    ):
        nonlocal captured_real_renderer_for_error
        # FastAPI передаст mock_dam_factory_fixture и None (для user) в конструктор ViewRenderer
        # благодаря глобальным app.dependency_overrides[get_dam_factory] и app.dependency_overrides[get_optional_current_user]
        captured_real_renderer_for_error = ViewRenderer(
            request=request, model_name=model_name,
            dam_factory=app_with_frontend_router.dependency_overrides.get(get_dam_factory)(), # Получаем мок фабрики
            user=app_with_frontend_router.dependency_overrides.get(get_optional_current_user)(request), # Получаем мок юзера
            mode=RenderMode.CREATE
        )
        return captured_real_renderer_for_error

    app_with_frontend_router.dependency_overrides[get_create_form_renderer] = _get_mock_create_renderer_for_error_override

    item_data = {"name": "S"}
    response = client.post("/sdk/item/Item", json=item_data)

    assert response.status_code == 422
    assert "text/html" in response.headers["content-type"].lower()
    assert "Name is too short" in response.text
    assert 'id="sdk-item-new-create-' in response.text

    assert captured_real_renderer_for_error is not None
    assert captured_real_renderer_for_error.errors is not None
    assert "name" in captured_real_renderer_for_error.errors[0]['loc']
    assert "Name is too short" in captured_real_renderer_for_error.errors[0]["msg"]

    assert captured_real_renderer_for_error.item is not None
    assert getattr(captured_real_renderer_for_error.item, "name", None) == "S"

    del app_with_frontend_router.dependency_overrides[get_create_form_renderer]

async def test_get_select_options_with_query(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
    item_id = uuid.uuid4()
    mock_dam_instance.list.return_value = {
        "items": [MockItemRead(id=item_id, name="Option Q", lsn=1)],
        "next_cursor": None, "limit": 1, "count": 1
    }

    response = client.get("/sdk/select-options/Item?q=Opt")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["value"] == str(item_id)
    assert data[0]["label"] == "Option Q"

    mock_dam_instance.list.assert_called_once()
    called_args, called_kwargs = mock_dam_instance.list.call_args
    assert called_kwargs.get("limit") == 20
    assert called_kwargs.get("filters") == {"search": "Opt"}
    assert called_kwargs.get("cursor") is None

async def test_get_select_options_with_id(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
    item_id = uuid.uuid4()
    mock_dam_instance.get.return_value = MockItemRead(id=item_id, name="Option ID", lsn=1)

    response = client.get(f"/sdk/select-options/Item?id={item_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["value"] == str(item_id)
    assert data[0]["label"] == "Option ID"
    mock_dam_instance.get.assert_called_once_with(item_id)

def test_get_confirm_delete_modal(client: TestClient, mock_view_renderer_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
    item_id_for_test = uuid.uuid4()

    # --- ИЗМЕНЕНИЕ: Мок-функция проще и устанавливает user ---
    async def _get_mock_view_renderer_for_delete_override():
        mock_view_renderer_instance.item_id = item_id_for_test
        mock_view_renderer_instance.model_name = "Item"
        # Ручка get_confirm_delete_modal_content использует renderer.user
        # Наш глобальный override для get_optional_current_user вернет None,
        # поэтому mock_view_renderer_instance.user должен быть None, если мы не установим его здесь.
        # Если get_view_mode_renderer устанавливает user на экземпляре рендерера, то это будет None.
        # Для этого теста, если шаблону нужен user, мы должны его установить на mock_view_renderer_instance.
        # По умолчанию он уже None из фикстуры mock_view_renderer_instance.
        # mock_view_renderer_instance.user = None # Уже установлено в фикстуре
        return mock_view_renderer_instance
    # ----------------------------------------------------

    app_with_frontend_router.dependency_overrides[get_view_mode_renderer] = _get_mock_view_renderer_for_delete_override

    response = client.get(f"/sdk/view/delete/Item/{item_id_for_test}?content_url=/sdk/item/Item/{item_id_for_test}")
    assert response.status_code == 200 # Ожидаем 200, так как FastAPIError должен быть решен
    html = response.text
    assert "Вы уверены, что хотите удалить" in html

    del app_with_frontend_router.dependency_overrides[get_view_mode_renderer]

    # --- Новые тесты ---

    async def test_get_edit_form_content_calls_renderer(client: TestClient, mock_generic_renderer_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
        item_id_for_test = uuid.uuid4()
        async def _get_mock_renderer(): return mock_generic_renderer_instance
        app_with_frontend_router.dependency_overrides[get_edit_form_renderer] = _get_mock_renderer
        response = client.get(f"/sdk/form/edit/Item/{item_id_for_test}")
        assert response.status_code == 200
        assert response.text == "<div>Mocked Generic Render Output</div>"
        mock_generic_renderer_instance.render_to_response.assert_awaited_once()
        del app_with_frontend_router.dependency_overrides[get_edit_form_renderer]

    async def test_get_create_form_content_calls_renderer(client: TestClient, mock_generic_renderer_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
        async def _get_mock_renderer(): return mock_generic_renderer_instance
        app_with_frontend_router.dependency_overrides[get_create_form_renderer] = _get_mock_renderer
        response = client.get("/sdk/form/create/Item")
        assert response.status_code == 200
        assert response.text == "<div>Mocked Generic Render Output</div>"
        mock_generic_renderer_instance.render_to_response.assert_awaited_once()
        del app_with_frontend_router.dependency_overrides[get_create_form_renderer]

    async def test_get_list_view_content_calls_renderer(client: TestClient, mock_generic_renderer_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
        async def _get_mock_renderer(): return mock_generic_renderer_instance
        app_with_frontend_router.dependency_overrides[get_list_mode_renderer] = _get_mock_renderer
        response = client.get("/sdk/list/Item")
        assert response.status_code == 200
        assert response.text == "<div>Mocked Generic Render Output</div>"
        mock_generic_renderer_instance.render_to_response.assert_awaited_once()
        del app_with_frontend_router.dependency_overrides[get_list_mode_renderer]

    async def test_update_item_success(
            client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock,
            app_with_frontend_router: FastAPI, mock_templates_response_method: mock.Mock
    ):
        mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
        item_id = uuid.uuid4()
        update_data = {"name": "Updated Item", "description": "Updated desc"}
        updated_item_model = MockItemRead(id=item_id, name=update_data["name"], description=update_data["description"], lsn=2)
        mock_dam_instance.update.return_value = updated_item_model

        response = client.put(f"/sdk/item/Item/{item_id}", json=update_data)

        assert response.status_code == 200
        assert response.text == "<div>Mocked TemplateResponse HTML</div>"
        mock_dam_instance.update.assert_awaited_once()
        # Проверяем, что ViewRenderer для VIEW mode был вызван для генерации ответа
        mock_templates_response_method.assert_called_once()
        template_name, context, status_code_kw = mock_templates_response_method.call_args[0][0], mock_templates_response_method.call_args[0][1], mock_templates_response_method.call_args[1].get('status_code')
        assert template_name == "components/view.html"
        assert status_code_kw == 200
        assert context["ctx"].item.name == update_data["name"]

    async def test_update_item_validation_error(
            client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock,
            app_with_frontend_router: FastAPI, mock_templates_response_method: mock.Mock
    ):
        mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
        item_id = uuid.uuid4()
        update_data = {"name": "U"} # Невалидные данные
        validation_errors = [{"loc": ("body", "name"), "msg": "Too short", "type": "value_error"}]
        mock_dam_instance.update.side_effect = FastAPIHTTPException(status_code=422, detail=validation_errors)
        # Мокируем get, чтобы form_renderer._load_data() мог "загрузить" исходный элемент
        mock_dam_instance.get.return_value = MockItemRead(id=item_id, name="Original", lsn=1)


        response = client.put(f"/sdk/item/Item/{item_id}", json=update_data)

        assert response.status_code == 422
        assert response.text == "<div>Mocked TemplateResponse HTML</div>"
        mock_templates_response_method.assert_called_once()
        template_name, context, status_code_kw = mock_templates_response_method.call_args[0][0], mock_templates_response_method.call_args[0][1], mock_templates_response_method.call_args[1].get('status_code')

        assert template_name == "components/form.html"
        assert status_code_kw == 422
        assert context["ctx"].errors == validation_errors
        assert context["ctx"].item.name == "U" # Данные пользователя должны быть в форме

    async def test_update_item_not_found(
            client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock,
            app_with_frontend_router: FastAPI
    ):
        mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
        item_id = uuid.uuid4()
        update_data = {"name": "Updated Item"}
        mock_dam_instance.update.side_effect = FastAPIHTTPException(status_code=404, detail="Item not found")

        response = client.put(f"/sdk/item/Item/{item_id}", json=update_data)
        assert response.status_code == 404

    async def test_delete_item_success(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
        mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
        item_id = uuid.uuid4()
        mock_dam_instance.delete.return_value = True
        # Мокируем get, чтобы get_delete_mode_renderer мог "загрузить" элемент
        mock_dam_instance.get.return_value = MockItemRead(id=item_id, name="To Delete", lsn=1)

        response = client.delete(f"/sdk/item/Item/{item_id}")
        assert response.status_code == 204
        assert "HX-Trigger" in response.headers
        assert "itemDeleted" in response.headers["HX-Trigger"]
        assert "closeModal" in response.headers["HX-Trigger"]
        mock_dam_instance.delete.assert_awaited_once_with(item_id)

    async def test_delete_item_not_found(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
        mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
        item_id = uuid.uuid4()
        mock_dam_instance.delete.side_effect = FastAPIHTTPException(status_code=404, detail="Not Found")
        mock_dam_instance.get.return_value = None # Для get_delete_mode_renderer

        response = client.delete(f"/sdk/item/Item/{item_id}")
        assert response.status_code == 404

    async def test_get_inline_edit_field_calls_renderer(client: TestClient, mock_generic_renderer_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
        item_id, field_name = uuid.uuid4(), "name"
        async def _get_mock_renderer():
            mock_generic_renderer_instance.field_to_focus = field_name
            return mock_generic_renderer_instance
        app_with_frontend_router.dependency_overrides[get_inline_edit_field_renderer] = _get_mock_renderer
        response = client.get(f"/sdk/edit-field/Item/{item_id}/{field_name}")
        assert response.status_code == 200
        assert response.text == "<span>Mocked Generic Field Output</span>"
        mock_generic_renderer_instance.render_field_to_response.assert_awaited_once_with(field_name)
        del app_with_frontend_router.dependency_overrides[get_inline_edit_field_renderer]

    async def test_update_inline_field_success(
            client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock,
            app_with_frontend_router: FastAPI, mock_templates_response_method: mock.Mock
    ):
        mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
        item_id, field_name = uuid.uuid4(), "name"
        new_value = "Inline Updated Name"
        payload = {field_name: new_value}
        updated_item_model = MockItemRead(id=item_id, name=new_value, lsn=3)
        mock_dam_instance.update.return_value = updated_item_model
        # Мокируем get для ViewRenderer, который создается для рендера ячейки
        mock_dam_instance.get.return_value = updated_item_model

        response = client.put(f"/sdk/edit-field/Item/{item_id}/{field_name}", json=payload)

        assert response.status_code == 200
        assert response.text == "<div>Mocked TemplateResponse HTML</div>"
        mock_dam_instance.update.assert_awaited_once_with(item_id, {field_name: new_value})
        mock_templates_response_method.assert_called_once()
        template_name, context, _ = mock_templates_response_method.call_args[0]
        assert template_name == "fields/text_table.html" # Ожидаем шаблон ячейки
        assert context["field_ctx"].name == field_name
        assert context["field_ctx"].value == new_value

    async def test_update_inline_field_validation_error(
            client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock,
            app_with_frontend_router: FastAPI, mock_templates_response_method: mock.Mock
    ):
        mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
        item_id, field_name = uuid.uuid4(), "value" # Предположим, value - int
        invalid_value = "not-a-number"
        payload = {field_name: invalid_value}

        # Мокируем get для error_renderer._load_data()
        mock_dam_instance.get.return_value = MockItemRead(id=item_id, name="Original", value=10, lsn=1)

        response = client.put(f"/sdk/edit-field/Item/{item_id}/{field_name}", json=payload)
        assert response.status_code == 422
        assert response.text == "<div>Mocked TemplateResponse HTML</div>"
        mock_templates_response_method.assert_called_once()
        template_name, context, status_code_kw = mock_templates_response_method.call_args[0][0], mock_templates_response_method.call_args[0][1], mock_templates_response_method.call_args[1].get('status_code')

        assert template_name == "fields/_inline_input_wrapper.html"
        assert status_code_kw == 422
        assert context["field_ctx"].name == field_name
        assert context["field_ctx"].value == invalid_value # Значение из формы
        assert context["field_ctx"].errors is not None
        assert "Input should be a valid integer" in context["field_ctx"].errors[0] # Пример сообщения от Pydantic

    async def test_get_table_cell_view_calls_renderer(client: TestClient, mock_generic_renderer_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
        item_id, field_name = uuid.uuid4(), "description"
        async def _get_mock_renderer():
            mock_generic_renderer_instance.field_to_focus = field_name
            return mock_generic_renderer_instance
        app_with_frontend_router.dependency_overrides[get_table_cell_renderer] = _get_mock_renderer
        response = client.get(f"/sdk/view-field/Item/{item_id}/{field_name}")
        assert response.status_code == 200
        assert response.text == "<span>Mocked Generic Field Output</span>"
        mock_generic_renderer_instance.render_field_to_response.assert_awaited_once_with(field_name)
        del app_with_frontend_router.dependency_overrides[get_table_cell_renderer]

    async def test_get_list_rows_content_calls_renderer(client: TestClient, mock_generic_renderer_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
        async def _get_mock_renderer(): return mock_generic_renderer_instance
        app_with_frontend_router.dependency_overrides[get_list_rows_renderer] = _get_mock_renderer
        response = client.get("/sdk/list-rows/Item")
        assert response.status_code == 200
        assert response.text == "<div>Mocked Generic Render Output</div>" # render_to_response
        mock_generic_renderer_instance.render_to_response.assert_awaited_once()
        del app_with_frontend_router.dependency_overrides[get_list_rows_renderer]

    async def test_get_filter_form_content_calls_renderer(client: TestClient, mock_generic_renderer_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
        async def _get_mock_renderer(): return mock_generic_renderer_instance
        app_with_frontend_router.dependency_overrides[get_filter_form_renderer] = _get_mock_renderer
        response = client.get("/sdk/filter/Item")
        assert response.status_code == 200
        assert response.text == "<div>Mocked Generic Render Output</div>"
        mock_generic_renderer_instance.render_to_response.assert_awaited_once()
        del app_with_frontend_router.dependency_overrides[get_filter_form_renderer]