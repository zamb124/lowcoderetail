# core_sdk/tests/frontend/test_frontend_base_router.py
import pytest
import uuid
from unittest import mock
from typing import Optional, Any, Dict

from fastapi import FastAPI, Request as FastAPIRequest, HTTPException as FastAPIHTTPException, Path as FastAPIPath
from fastapi.testclient import TestClient
from fastapi.responses import HTMLResponse

from core_sdk.frontend.base import router as frontend_router
from core_sdk.frontend.renderer import ViewRenderer, RenderContext, FieldRenderContext # Добавил RenderContext, FieldRenderContext
from core_sdk.frontend.templating import initialize_templates, SDK_TEMPLATES_DIR
from core_sdk.data_access import DataAccessManagerFactory, BaseDataAccessManager, get_dam_factory
from core_sdk.registry import ModelRegistry
from core_sdk.exceptions import ConfigurationError
from core_sdk.tests.conftest import Item, ItemCreate, ItemUpdate, ItemFilter, ItemRead as MockItemRead

from core_sdk.middleware.auth import AuthMiddleware
from core_sdk.tests.conftest import AppSetupTestSettings
from core_sdk.dependencies.auth import get_optional_current_user
from core_sdk.frontend.dependencies import (
    get_view_form_renderer, get_create_form_renderer, get_edit_form_renderer,
    get_list_table_renderer, get_list_table_rows_renderer,
    get_filter_form_renderer, get_delete_confirm_renderer
)
from core_sdk.frontend.types import ComponentMode, FieldState

pytestmark = pytest.mark.asyncio

@pytest.fixture(scope="module", autouse=True)
def setup_templates_for_frontend_tests():
    try:
        initialize_templates(service_template_dir=SDK_TEMPLATES_DIR)
    except RuntimeError as e:
        if "Templates already initialized" not in str(e):
            raise

@pytest.fixture
def mock_dam_factory_fixture() -> mock.Mock:
    factory_mock = mock.Mock(spec=DataAccessManagerFactory)
    return factory_mock

@pytest.fixture
def mock_dam_instance() -> mock.AsyncMock:
    dam_instance_mock = mock.AsyncMock(spec=BaseDataAccessManager)
    dam_instance_mock.model_name = "Item"
    dam_instance_mock.read_schema_cls = MockItemRead
    # Для тестов, где DAM используется для создания/обновления,
    # и результат потом валидируется в read_schema_cls
    dam_instance_mock.model_cls = Item # SQLModel
    dam_instance_mock.create_schema_cls = ItemCreate
    dam_instance_mock.update_schema_cls = ItemUpdate
    return dam_instance_mock

@pytest.fixture
def test_settings() -> AppSetupTestSettings:
    return AppSetupTestSettings()

@pytest.fixture
def app_with_frontend_router(
        mock_dam_factory_fixture: mock.Mock,
        manage_model_registry_for_tests: Any,
        test_settings: AppSetupTestSettings
) -> FastAPI:
    app = FastAPI()
    allowed_paths_for_auth = ["/sdk*"]
    app.add_middleware(
        AuthMiddleware,
        secret_key=test_settings.SECRET_KEY,
        algorithm=test_settings.ALGORITHM,
        allowed_paths=allowed_paths_for_auth,
        api_prefix=""
    )
    app.include_router(frontend_router)
    app.dependency_overrides[get_dam_factory] = lambda: mock_dam_factory_fixture
    async def _get_mock_optional_user_none_override(request: FastAPIRequest): return None
    app.dependency_overrides[get_optional_current_user] = _get_mock_optional_user_none_override
    return app

@pytest.fixture
def client(app_with_frontend_router: FastAPI) -> TestClient:
    return TestClient(app_with_frontend_router)

# --- Тесты ---

def test_get_modal_wrapper(client: TestClient):
    content_url = "/some/content"; modal_title = "My Test Modal"; modal_id = "test-modal-123"; modal_size = "modal-sm"
    response = client.get(f"/sdk/modal-wrapper?content_url={content_url}&modal_title={modal_title}&modal_id={modal_id}&modal_size={modal_size}")
    assert response.status_code == 200; html = response.text
    assert f'id="{modal_id}"' in html; assert f'<h5 class="modal-title">{modal_title}</h5>' in html
    assert f'class="modal-dialog {modal_size} ' in html; assert f'hx-get="{content_url}"' in html

async def test_resolve_titles_success(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
    item_id1, item_id2 = uuid.uuid4(), uuid.uuid4()
    # list возвращает SQLModel, которые потом преобразуются в read_schema для ответа, если нужно
    # Но resolve_titles просто берет поля name/title
    mock_dam_instance.list.return_value = {"items": [Item(id=item_id1, name="Title One", lsn=1), Item(id=item_id2, name="Title Two", lsn=2)], "next_cursor": None, "limit": 2, "count": 2}
    payload = {"model_name": "Item", "ids": [str(item_id1), str(item_id2)]}
    response = client.post("/sdk/resolve-titles", json=payload)
    assert response.status_code == 200; data = response.json()
    assert str(item_id1) in data["root"]; assert data["root"][str(item_id1)] == "Title One"
    assert str(item_id2) in data["root"]; assert data["root"][str(item_id2)] == "Title Two"
    mock_dam_factory_fixture.get_manager.assert_called_once_with("Item", request=mock.ANY)

async def test_resolve_titles_model_not_configured(client: TestClient, mock_dam_factory_fixture: mock.Mock):
    mock_dam_factory_fixture.get_manager.side_effect = ConfigurationError("Model not found")
    response = client.post("/sdk/resolve-titles", json={"model_name": "NonExistentModel", "ids": [str(uuid.uuid4())]})
    assert response.status_code == 404

async def test_resolve_titles_ids_not_found(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance; unknown_id = uuid.uuid4()
    mock_dam_instance.list.return_value = {"items": [], "next_cursor": None, "limit": 1, "count": 0}
    mock_dam_instance.get.return_value = None
    response = client.post("/sdk/resolve-titles", json={"model_name": "Item", "ids": [str(unknown_id)]})
    assert response.status_code == 200; data = response.json()
    assert str(unknown_id) in data["root"]; assert f"ID: {str(unknown_id)[:8]} (не найден)" in data["root"][str(unknown_id)]

@pytest.fixture
def mock_full_component_renderer() -> mock.AsyncMock:
    renderer_mock = mock.AsyncMock(spec=ViewRenderer)
    renderer_mock.render_to_response = mock.AsyncMock(return_value=HTMLResponse("<div>Mocked Full Component Output</div>", status_code=200))
    return renderer_mock

async def test_get_view_form_content_calls_renderer(client: TestClient, mock_full_component_renderer: mock.AsyncMock, app_with_frontend_router: FastAPI):
    item_id_for_test = uuid.uuid4()
    async def _get_mock_renderer_override(): return mock_full_component_renderer
    app_with_frontend_router.dependency_overrides[get_view_form_renderer] = _get_mock_renderer_override
    response = client.get(f"/sdk/view/Item/{item_id_for_test}")
    assert response.status_code == 200; assert response.text == "<div>Mocked Full Component Output</div>"
    mock_full_component_renderer.render_to_response.assert_awaited_once()
    del app_with_frontend_router.dependency_overrides[get_view_form_renderer]

async def test_create_item_success(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
    created_item_id = uuid.uuid4()
    mock_dam_instance.create.return_value = Item(id=created_item_id, name="New SQLModel", lsn=1)
    item_data = {"name": "New Item", "description": "Test create"}
    response = client.post("/sdk/item/Item", json=item_data)
    assert response.status_code == 204; assert "HX-Trigger" in response.headers
    assert "closeModal" in response.headers["HX-Trigger"]; assert "itemCreated_Item" in response.headers["HX-Trigger"]
    mock_dam_instance.create.assert_awaited_once()
    call_arg = mock_dam_instance.create.call_args[0][0]
    assert isinstance(call_arg, dict); assert call_arg["name"] == item_data["name"]

async def test_create_item_validation_error_returns_form_html(
        client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock,
        app_with_frontend_router: FastAPI, mock_templates_response_method: mock.Mock
):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
    validation_error_detail = [{"loc": ("body", "name"), "msg": "Name is too short", "type": "value_error"}]
    mock_dam_instance.create.side_effect = FastAPIHTTPException(status_code=422, detail=validation_error_detail)
    item_data = {"name": "S"}
    response = client.post("/sdk/item/Item", json=item_data)

    assert response.status_code == 422 # Проверяем статус ответа
    assert response.text == "<div>Mocked TemplateResponse HTML</div>"
    mock_templates_response_method.assert_called_once()
    template_name, context, status_code_kw = mock_templates_response_method.call_args[0][0], mock_templates_response_method.call_args[0][1], mock_templates_response_method.call_args[1].get('status_code')
    assert template_name == "components/form.html"; assert status_code_kw == 422
    assert context["ctx"].errors == {'name': ['Name is too short']}
    assert context["ctx"].item.name == "S"

async def test_get_select_options_with_query(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance; item_id = uuid.uuid4()
    mock_dam_instance.list.return_value = {"items": [Item(id=item_id, name="Option Q", lsn=1)], "next_cursor": None, "limit": 1, "count": 1}
    response = client.get("/sdk/select-options/Item?q=Opt")
    assert response.status_code == 200; data = response.json()
    assert len(data) == 1; assert data[0]["value"] == str(item_id); assert data[0]["label"] == "Option Q"
    mock_dam_instance.list.assert_called_once(); called_args, called_kwargs = mock_dam_instance.list.call_args
    assert called_kwargs.get("limit") == 20; assert called_kwargs.get("filters") == {"search": "Opt"}; assert called_kwargs.get("cursor") is None

async def test_get_select_options_with_id(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance; item_id = uuid.uuid4()
    mock_dam_instance.get.return_value = Item(id=item_id, name="Option ID", lsn=1)
    response = client.get(f"/sdk/select-options/Item?id={item_id}")
    assert response.status_code == 200; data = response.json()
    assert len(data) == 1; assert data[0]["value"] == str(item_id); assert data[0]["label"] == "Option ID"
    mock_dam_instance.get.assert_called_once_with(item_id)

async def test_get_confirm_delete_modal_content(
    client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock,
    app_with_frontend_router: FastAPI
):
    item_id_for_test = uuid.uuid4()
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
    mock_dam_instance.get.return_value = Item(id=item_id_for_test, name="Item To Delete", lsn=1)
    response = client.get(f"/sdk/view/delete/Item/{item_id_for_test}")
    assert response.status_code == 200; html = response.text
    assert "Вы уверены, что хотите удалить" in html
    assert f"ID: {item_id_for_test}" in html
    assert f'/sdk/item/Item/{item_id_for_test}"' in html # Проверяем относительный путь
    assert 'hx-delete=' in html

@pytest.fixture
def mock_view_renderer_for_field_fragment(monkeypatch: pytest.MonkeyPatch) -> Dict[str, mock.Mock]:
    mock_renderer_instance = mock.AsyncMock(spec=ViewRenderer)
    mock_renderer_instance.render_field_fragment_response = mock.AsyncMock(
        return_value=HTMLResponse("<span>Mocked Field Fragment Output</span>", status_code=200)
    )
    # Мокируем конструктор ViewRenderer, чтобы он возвращал наш мок-экземпляр
    mock_constructor = mock.Mock(return_value=mock_renderer_instance)
    monkeypatch.setattr("core_sdk.frontend.base.ViewRenderer", mock_constructor) # Патчим там, где он используется
    return {"constructor": mock_constructor, "instance": mock_renderer_instance}

async def test_get_field_fragment_for_edit(
        client: TestClient, mock_view_renderer_for_field_fragment: Dict[str, mock.Mock],
        mock_dam_factory_fixture: mock.Mock,
):
    item_id_for_test = uuid.uuid4()
    model_name = "Item"; field_name = "name"; parent_mode_str = ComponentMode.TABLE_CELL.value # Используем str
    response = client.get(f"/sdk/field-fragment/{parent_mode_str}/{model_name}/{item_id_for_test}/{field_name}?field_state=edit")
    assert response.status_code == 200
    assert response.text == "<span>Mocked Field Fragment Output</span>"
    constructor_mock = mock_view_renderer_for_field_fragment["constructor"]
    instance_mock = mock_view_renderer_for_field_fragment["instance"]

    constructor_mock.assert_called_once()
    # ViewRenderer(request, model_name, dam_factory, user, item_id, component_mode, field_to_focus)
    # request - первый позиционный аргумент
    args, kwargs = constructor_mock.call_args
    assert len(args) >= 5 # request, model_name, dam_factory, user, item_id
    assert args[1] == model_name # model_name
    assert args[4] == item_id_for_test # item_id

    assert kwargs.get("component_mode") == ComponentMode.TABLE_CELL
    assert kwargs.get("field_to_focus") == field_name

    instance_mock.render_field_fragment_response.assert_awaited_once_with(field_name, FieldState.EDIT)

async def test_get_field_fragment_for_view(
        client: TestClient, mock_view_renderer_for_field_fragment: Dict[str, mock.Mock],
        mock_dam_factory_fixture: mock.Mock,
):
    item_id_for_test = uuid.uuid4()
    model_name = "Item"; field_name = "description"; parent_mode_str = ComponentMode.VIEW_FORM.value
    response = client.get(f"/sdk/field-fragment/{parent_mode_str}/{model_name}/{item_id_for_test}/{field_name}?field_state=view")
    assert response.status_code == 200
    assert response.text == "<span>Mocked Field Fragment Output</span>"
    constructor_mock = mock_view_renderer_for_field_fragment["constructor"]
    instance_mock = mock_view_renderer_for_field_fragment["instance"]

    constructor_mock.assert_called_once()
    args, kwargs = constructor_mock.call_args
    assert len(args) >= 5
    assert args[1] == model_name
    assert args[4] == item_id_for_test

    assert kwargs.get("component_mode") == ComponentMode.VIEW_FORM
    assert kwargs.get("field_to_focus") is None

    instance_mock.render_field_fragment_response.assert_awaited_once_with(field_name, FieldState.VIEW)

async def test_get_edit_form_content(client: TestClient, mock_full_component_renderer: mock.AsyncMock, app_with_frontend_router: FastAPI):
    item_id_for_test = uuid.uuid4()
    async def _get_mock_renderer(): return mock_full_component_renderer
    app_with_frontend_router.dependency_overrides[get_edit_form_renderer] = _get_mock_renderer
    response = client.get(f"/sdk/form/edit/Item/{item_id_for_test}")
    assert response.status_code == 200; assert response.text == "<div>Mocked Full Component Output</div>"
    mock_full_component_renderer.render_to_response.assert_awaited_once()
    del app_with_frontend_router.dependency_overrides[get_edit_form_renderer]

async def test_get_create_form_content(client: TestClient, mock_full_component_renderer: mock.AsyncMock, app_with_frontend_router: FastAPI):
    async def _get_mock_renderer(): return mock_full_component_renderer
    app_with_frontend_router.dependency_overrides[get_create_form_renderer] = _get_mock_renderer
    response = client.get("/sdk/form/create/Item")
    assert response.status_code == 200; assert response.text == "<div>Mocked Full Component Output</div>"
    mock_full_component_renderer.render_to_response.assert_awaited_once()
    del app_with_frontend_router.dependency_overrides[get_create_form_renderer]

async def test_get_list_table_content(client: TestClient, mock_full_component_renderer: mock.AsyncMock, app_with_frontend_router: FastAPI):
    async def _get_mock_renderer(): return mock_full_component_renderer
    app_with_frontend_router.dependency_overrides[get_list_table_renderer] = _get_mock_renderer
    response = client.get("/sdk/list/Item")
    assert response.status_code == 200; assert response.text == "<div>Mocked Full Component Output</div>"
    mock_full_component_renderer.render_to_response.assert_awaited_once()
    del app_with_frontend_router.dependency_overrides[get_list_table_renderer]

async def test_update_item_success(
        client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock,
        app_with_frontend_router: FastAPI, mock_templates_response_method: mock.Mock
):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
    item_id = uuid.uuid4(); update_data = {"name": "Updated Item", "description": "Updated desc"}
    updated_item_sqlmodel = Item(id=item_id, name=update_data["name"], description=update_data["description"], lsn=2)
    mock_dam_instance.update.return_value = updated_item_sqlmodel
    # Мокируем get, который будет вызван ViewRenderer для режима VIEW_FORM
    mock_dam_instance.get.return_value = updated_item_sqlmodel

    response = client.put(f"/sdk/item/Item/{item_id}", json=update_data)
    assert response.status_code == 200; assert response.text == "<div>Mocked TemplateResponse HTML</div>"
    mock_dam_instance.update.assert_awaited_once()
    mock_templates_response_method.assert_called_once()
    template_name, context, status_code_kw = mock_templates_response_method.call_args[0][0], mock_templates_response_method.call_args[0][1], mock_templates_response_method.call_args[1].get('status_code')
    assert template_name == "components/view.html"; assert status_code_kw == 200
    assert context["ctx"].item.name == update_data["name"]


async def test_delete_item_success(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock, app_with_frontend_router: FastAPI):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance; item_id = uuid.uuid4()
    mock_dam_instance.delete.return_value = True
    mock_dam_instance.get.return_value = Item(id=item_id, name="To Delete", lsn=1)
    response = client.delete(f"/sdk/item/Item/{item_id}")
    assert response.status_code == 204; assert "HX-Trigger" in response.headers
    assert "itemDeleted" in response.headers["HX-Trigger"]; assert "closeModal" in response.headers["HX-Trigger"]
    mock_dam_instance.delete.assert_awaited_once_with(item_id)

async def test_delete_item_not_found(client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance; item_id = uuid.uuid4()
    mock_dam_instance.delete.side_effect = FastAPIHTTPException(status_code=404, detail="Not Found")
    mock_dam_instance.get.return_value = None
    response = client.delete(f"/sdk/item/Item/{item_id}")
    assert response.status_code == 404

async def test_update_inline_field_success(
        client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock,
        app_with_frontend_router: FastAPI, mock_templates_response_method: mock.Mock
):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
    item_id, field_name = uuid.uuid4(), "name"; new_value = "Inline Updated Name"
    payload = {field_name: new_value}
    updated_item_sqlmodel = Item(id=item_id, name=new_value, lsn=3)
    mock_dam_instance.update.return_value = updated_item_sqlmodel
    mock_dam_instance.get.return_value = updated_item_sqlmodel # Для ViewRenderer
    parent_mode = ComponentMode.TABLE_CELL.value
    response = client.put(f"/sdk/inline-update-field/{parent_mode}/Item/{item_id}/{field_name}", json=payload)
    assert response.status_code == 200; assert response.text == "<div>Mocked TemplateResponse HTML</div>"
    # Проверяем, что manager.update был вызван с правильными аргументами
    mock_dam_instance.update.assert_awaited_once_with(item_id, {field_name: new_value})
    mock_templates_response_method.assert_called_once()
    # Исправляем распаковку call_args
    call_obj = mock_templates_response_method.call_args
    template_name, context = call_obj.args
    status_code_kw = call_obj.kwargs.get('status_code')

    assert template_name == "components/_field_layout_wrapper.html" # Обертка для поля
    assert isinstance(context["field_ctx"], FieldRenderContext)
    assert context["field_ctx"].name == field_name
    assert context["field_ctx"].value == new_value

async def test_update_inline_field_validation_error(
        client: TestClient, mock_dam_factory_fixture: mock.Mock, mock_dam_instance: mock.AsyncMock,
        app_with_frontend_router: FastAPI, mock_templates_response_method: mock.Mock
):
    mock_dam_factory_fixture.get_manager.return_value = mock_dam_instance
    item_id, field_name = uuid.uuid4(), "value"; invalid_value = "not-a-number"
    payload = {field_name: invalid_value}
    mock_dam_instance.get.return_value = Item(id=item_id, name="Original", value=10, lsn=1)
    parent_mode = ComponentMode.TABLE_CELL.value
    response = client.put(f"/sdk/inline-update-field/{parent_mode}/Item/{item_id}/{field_name}", json=payload)
    assert response.status_code == 422
    assert response.text == "<div>Mocked TemplateResponse HTML</div>"

    mock_templates_response_method.assert_called_once()
    call_obj = mock_templates_response_method.call_args
    template_name, context = call_obj.args
    status_code_kw = call_obj.kwargs.get('status_code')

    assert template_name == "components/_field_layout_wrapper.html"
    assert status_code_kw == 422
    assert isinstance(context["field_ctx"], FieldRenderContext)
    assert context["field_ctx"].name == field_name
    assert context["field_ctx"].value == invalid_value
    assert context["field_ctx"].errors is not None
    assert "Input should be a valid integer" in context["field_ctx"].errors[0]

async def test_get_list_table_rows_content(client: TestClient, mock_full_component_renderer: mock.AsyncMock, app_with_frontend_router: FastAPI):
    async def _get_mock_renderer(): return mock_full_component_renderer
    app_with_frontend_router.dependency_overrides[get_list_table_rows_renderer] = _get_mock_renderer
    response = client.get("/sdk/list-rows/Item")
    assert response.status_code == 200; assert response.text == "<div>Mocked Full Component Output</div>"
    mock_full_component_renderer.render_to_response.assert_awaited_once()
    del app_with_frontend_router.dependency_overrides[get_list_table_rows_renderer]

async def test_get_filter_form_content(client: TestClient, mock_full_component_renderer: mock.AsyncMock, app_with_frontend_router: FastAPI):
    async def _get_mock_renderer(): return mock_full_component_renderer
    app_with_frontend_router.dependency_overrides[get_filter_form_renderer] = _get_mock_renderer
    response = client.get("/sdk/filter/Item")
    assert response.status_code == 200; assert response.text == "<div>Mocked Full Component Output</div>"
    mock_full_component_renderer.render_to_response.assert_awaited_once()
    del app_with_frontend_router.dependency_overrides[get_filter_form_renderer]