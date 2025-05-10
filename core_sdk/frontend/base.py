# core_sdk/frontend/base.py
import logging
import uuid
from typing import Optional, Any, Dict, List
from fastapi import APIRouter, Depends, Request, HTTPException, Path as FastAPIPath, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ValidationError, create_model # create_model используется в update_inline_field

from core_sdk.data_access import get_dam_factory, DataAccessManagerFactory
from core_sdk.frontend.dependencies import (
    get_view_mode_renderer, get_edit_form_renderer, get_create_form_renderer,
    get_list_mode_renderer, get_list_rows_renderer,
    get_table_cell_renderer, get_inline_edit_field_renderer, get_filter_form_renderer
)
# Убираем FallbackFormDataModel из импортов renderer
from core_sdk.frontend.renderer import ViewRenderer, RenderMode
from core_sdk.frontend.templating import get_templates
from core_sdk.frontend.config import STATIC_URL_PATH
from core_sdk.registry import ModelRegistry
from core_sdk.exceptions import ConfigurationError # Используем SDK-шный
from core_sdk.schemas.auth_user import AuthenticatedUser
from dependencies.auth import get_optional_current_user

# Импорты, которые могут быть специфичны для frontend приложения, если они используются
# from dependencies.auth import get_optional_current_user # get_optional_current_user уже используется в SDK зависимостях рендерера
# from frontend.utils import get_base_type # Используется в update_inline_field

logger = logging.getLogger("core_sdk.frontend.router")
router = APIRouter(
    prefix="/sdk",
    tags=["SDK UI Components"],
)
logger_titles = logging.getLogger("core_sdk.frontend.titles")

# --- Ручка для получения обертки модального окна ---
@router.get("/modal-wrapper", response_class=HTMLResponse, name="get_modal_wrapper")
async def get_modal_wrapper(
        request: Request,
        content_url: str = Query(..., description="URL для загрузки содержимого модального окна"),
        modal_title: str = Query("Модальное окно", description="Заголовок модального окна"),
        modal_id: Optional[str] = Query(None, description="Опциональный ID для модального окна"),
        modal_size: str = Query("modal-lg", description="Размер модального окна")
):
    templates = get_templates()
    final_modal_id = modal_id or f"htmx-modal-{uuid.uuid4().hex[:8]}"
    context = {
        "request": request, "modal_id": final_modal_id, "modal_title": modal_title,
        "modal_size": modal_size, "content_url": content_url,
        "SDK_STATIC_URL": STATIC_URL_PATH, "url_for": request.url_for
    }
    return templates.TemplateResponse("components/_modal_wrapper.html", context)

# --- Pydantic модели для resolve_titles ---
class ResolveTitlesRequest(BaseModel):
    model_name: str
    ids: List[uuid.UUID]

class ResolveTitlesResponse(BaseModel):
    root: Dict[uuid.UUID, str]

@router.post("/resolve-titles", response_model=ResolveTitlesResponse, name="resolve_titles")
async def resolve_titles_endpoint(
        request: Request, payload: ResolveTitlesRequest,
        dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
):
    # ... (код resolve_titles_endpoint как был, он не меняется)
    model_name = payload.model_name
    ids_to_resolve = payload.ids
    if not ids_to_resolve: return ResolveTitlesResponse(root={})
    try: manager = dam_factory.get_manager(model_name, request=request)
    except ConfigurationError as e: raise HTTPException(status_code=404, detail=f"Model '{model_name}' not configured.")
    resolved_titles: Dict[uuid.UUID, str] = {}
    title_field_candidates = ['title', 'name', 'email', 'display_name', 'label', 'username']
    items_map: Dict[uuid.UUID, Any] = {}
    try:
        list_result = await manager.list(filters={"id__in": ids_to_resolve}, limit=len(ids_to_resolve) + 10)
        for item in list_result.get("items", []):
            if hasattr(item, 'id'): items_map[item.id] = item
    except Exception as e: items_map = {} # fallback
    for item_id_val in ids_to_resolve:
        item = items_map.get(item_id_val)
        if not item: item = await manager.get(item_id_val)
        if item:
            item_title = next((str(getattr(item, fld)) for fld in title_field_candidates if hasattr(item, fld) and getattr(item, fld)), None)
            resolved_titles[item_id_val] = item_title or f"{model_name} {str(item_id_val)[:8]}..."
        else: resolved_titles[item_id_val] = f"ID: {str(item_id_val)[:8]} (не найден)"
    return ResolveTitlesResponse(root=resolved_titles)

# --- РУЧКИ ДЛЯ ФОРМ И ПРЕДСТАВЛЕНИЙ (ВОЗВРАЩАЮТ ТОЛЬКО КОНТЕНТ) ---
@router.get("/view/{model_name}/{item_id}", response_class=HTMLResponse, name="get_view")
async def get_view_content(renderer: ViewRenderer = Depends(get_view_mode_renderer)):
    return await renderer.render_to_response()

@router.get("/form/edit/{model_name}/{item_id}", response_class=HTMLResponse, name="get_edit_form")
async def get_edit_form_content(renderer: ViewRenderer = Depends(get_edit_form_renderer)):
    return await renderer.render_to_response()

@router.get("/form/create/{model_name}", response_class=HTMLResponse, name="get_create_form")
async def get_create_form_content(renderer: ViewRenderer = Depends(get_create_form_renderer)):
    return await renderer.render_to_response()

@router.get("/list/{model_name}", response_class=HTMLResponse, name="get_list_view")
async def get_list_view_content(renderer: ViewRenderer = Depends(get_list_mode_renderer)):
    return await renderer.render_to_response()

# --- РУЧКИ ОБРАБОТКИ ДАННЫХ ФОРМ ---
@router.post("/item/{model_name}", response_class=HTMLResponse, name="create_item")
async def create_item(
        request: Request, model_name: str = FastAPIPath(...),
        form_renderer: ViewRenderer = Depends(get_create_form_renderer) # form_renderer в режиме CREATE
):
    json_data: Dict[str, Any] = {}
    try:
        json_data = await request.json()
    except Exception:
        form_renderer.errors = {"_form": ["Неверный формат JSON."]}
        target_schema_cls = form_renderer._get_schema_for_mode()
        try: form_renderer.item = target_schema_cls() # Пустой экземпляр для формы
        except Exception: form_renderer.item = None
        return await form_renderer.render_to_response(status_code=422) # Возвращаем form.html с ошибкой

    try:
        new_item = await form_renderer.manager.create(json_data)
        response = Response(status_code=204, content=None)
        response.headers["HX-Trigger"] = f"closeModal, itemCreated_{model_name}, refreshData"
        return response
    except HTTPException as e:
        form_renderer.errors = e.detail
        target_schema_cls = form_renderer._get_schema_for_mode()
        instance_with_user_data = target_schema_cls() # Создаем пустой экземпляр
        for key, value in json_data.items(): # Заполняем его данными пользователя
            if hasattr(instance_with_user_data, key):
                setattr(instance_with_user_data, key, value)
        form_renderer.item = instance_with_user_data
        return await form_renderer.render_to_response(status_code=e.status_code) # form.html с ошибками
    except Exception as e:
        logger.exception(f"Error creating {model_name}: {e}")
        form_renderer.errors = {"_form": ["Внутренняя ошибка сервера при создании."]}
        target_schema_cls = form_renderer._get_schema_for_mode()
        instance_with_user_data = target_schema_cls()
        for key, value in json_data.items():
            if hasattr(instance_with_user_data, key): setattr(instance_with_user_data, key, value)
        form_renderer.item = instance_with_user_data
        return await form_renderer.render_to_response(status_code=422) # Возвращаем form.html с ошибкой


@router.put("/item/{model_name}/{item_id}", response_class=HTMLResponse, name="update_item")
async def update_item(
        request: Request, model_name: str = FastAPIPath(...), item_id: uuid.UUID = FastAPIPath(...),
        form_renderer: ViewRenderer = Depends(get_edit_form_renderer) # form_renderer в режиме EDIT
):
    json_data: Dict[str, Any] = {}
    try:
        json_data = await request.json()
    except Exception:
        # form_renderer.item уже должен быть загружен из БД (через get_edit_form_renderer)
        if form_renderer.item is None: await form_renderer._load_data() # На всякий случай
        form_renderer.errors = {"_form": ["Неверный формат JSON."]}
        return await form_renderer.render_to_response(status_code=422) # form.html с ошибкой

    try:
        updated_item = await form_renderer.manager.update(item_id, json_data)
        # Успех: возвращаем HTML обновленного представления (view.html)
        view_renderer = ViewRenderer(
            request, model_name, form_renderer.dam_factory,
            form_renderer.user, item_id, RenderMode.VIEW
        )
        view_renderer.item = updated_item
        response = await view_renderer.render_to_response(status_code=200)
        return response
    except HTTPException as e:
        form_renderer.errors = e.detail
        # form_renderer.item содержит данные из БД. Обновляем его невалидными данными из json_data.
        if form_renderer.item is None: await form_renderer._load_data()

        target_schema_cls = form_renderer._get_schema_for_mode() # EditSchema
        # Создаем "пустой" экземпляр схемы, чтобы потом заполнить его
        instance_with_user_data = target_schema_cls()

        # Сначала заполняем данными из БД (если они есть в form_renderer.item)
        if form_renderer.item and hasattr(form_renderer.item, 'model_fields'):
            for field_name in target_schema_cls.model_fields.keys(): # Итерируемся по полям схемы
                if hasattr(form_renderer.item, field_name) and hasattr(instance_with_user_data, field_name):
                    setattr(instance_with_user_data, field_name, getattr(form_renderer.item, field_name))

        # Затем перезаписываем/добавляем значения из json_data (от пользователя)
        for key, value in json_data.items():
            if hasattr(instance_with_user_data, key):
                setattr(instance_with_user_data, key, value)

        form_renderer.item = instance_with_user_data
        return await form_renderer.render_to_response(status_code=e.status_code) # form.html с ошибками
    except Exception as e:
        logger.exception(f"Unexpected error updating {model_name}/{item_id}: {e}")
        if form_renderer.item is None: await form_renderer._load_data()
        form_renderer.errors = {"_form": ["Внутренняя ошибка сервера при обновлении."]}

        target_schema_cls = form_renderer._get_schema_for_mode()
        instance_with_user_data = target_schema_cls()
        if form_renderer.item and hasattr(form_renderer.item, 'model_fields'):
            for field_name in target_schema_cls.model_fields.keys():
                if hasattr(form_renderer.item, field_name) and hasattr(instance_with_user_data, field_name):
                    setattr(instance_with_user_data, field_name, getattr(form_renderer.item, field_name))
        for key, value in json_data.items(): # json_data может быть пустым
            if hasattr(instance_with_user_data, key): setattr(instance_with_user_data, key, value)
        form_renderer.item = instance_with_user_data
        return await form_renderer.render_to_response(status_code=422)


@router.delete("/item/{model_name}/{item_id}", response_class=Response, name="delete_item")
async def delete_item(renderer: ViewRenderer = Depends(get_view_mode_renderer)):
    # ... (без изменений) ...
    logger.info(f"Attempting to delete {renderer.model_name}/{renderer.item_id}")
    try:
        success = await renderer.manager.delete(renderer.item_id)
        if success:
            response = Response(status_code=204)
            response.headers["HX-Trigger"] = "itemDeleted, closeModal"
            return response
        else: raise HTTPException(status_code=500, detail="Delete operation failed unexpectedly.")
    except HTTPException as e: raise e
    except Exception as e:
        logger.exception(f"Error deleting {renderer.model_name}/{renderer.item_id}")
        raise HTTPException(status_code=500, detail="Internal server error during deletion.")

@router.get("/select-options/{model_name}", name="get_select_options")
async def get_select_options(
        request: Request, model_name: str = FastAPIPath(...),
        q: Optional[str] = Query(None), id: Optional[str] = Query(None),
        dam_factory: DataAccessManagerFactory = Depends(get_dam_factory)
):
    # ... (код как в предыдущем ответе, с поддержкой q и id) ...
    manager = dam_factory.get_manager(model_name, request=request)
    filters = {}; options_limit = 20
    if id:
        try:
            item = await manager.get(uuid.UUID(id))
            if item:
                label = next((str(getattr(item, fld, '')) for fld in ['name', 'title', 'email'] if hasattr(item, fld) and getattr(item, fld)), str(item.id))
                from fastapi.responses import JSONResponse
                return JSONResponse(content=[{"value": str(item.id), "label": label, "id": str(item.id)}])
            return JSONResponse(content=[])
        except Exception: raise HTTPException(status_code=500)
    elif q: filters["search"] = q
    try:
        results_dict = await manager.list(limit=options_limit, filters=filters)
        items = results_dict.get("items", [])
        options_list = []
        for item in items:
            item_id_val = getattr(item, 'id', None)
            label = next((str(getattr(item, fld, '')) for fld in ['name', 'title', 'email'] if hasattr(item, fld) and getattr(item, fld)), str(item_id_val) if item_id_val else "N/A")
            if item_id_val: options_list.append({"value": str(item_id_val), "label": label, "id": str(item_id_val)})
        from fastapi.responses import JSONResponse
        return JSONResponse(content=options_list)
    except Exception: raise HTTPException(status_code=500)


# --- Инлайн-редактирование ---
@router.get("/edit-field/{model_name}/{item_id}/{field_name}", response_class=HTMLResponse, name="get_inline_edit_field")
async def get_inline_edit_field(renderer: ViewRenderer = Depends(get_inline_edit_field_renderer)):
    return await renderer.render_field_to_response(renderer.field_to_focus)

@router.put("/edit-field/{model_name}/{item_id}/{field_name}", response_class=HTMLResponse, name="update_inline_field")
async def update_inline_field(
        request: Request, model_name: str = FastAPIPath(...), item_id: uuid.UUID = FastAPIPath(...),
        field_name: str = FastAPIPath(...), dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
        user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)
):
    json_data, raw_value_from_json = {}, None
    try:
        json_data = await request.json()
        if field_name not in json_data: return HTMLResponse(f'<div class="text-danger p-1">Error: field {field_name} missing.</div>', status_code=400)
        raw_value_from_json = json_data[field_name]
    except Exception: return HTMLResponse(f'<div class="text-danger p-1">Error: invalid JSON.</div>', status_code=400)

    manager = dam_factory.get_manager(model_name, request=request)
    # error_renderer создается с режимом EDIT для рендеринга _inline_input_wrapper.html
    error_renderer = ViewRenderer(request, model_name, dam_factory, user, item_id, RenderMode.EDIT, field_to_focus=field_name)
    # Загружаем item в error_renderer, чтобы он был доступен для предзаполнения и получения FieldInfo
    if error_renderer.item is None: await error_renderer._load_data()


    try:
        update_schema = manager.update_schema or manager.model
        if field_name not in update_schema.model_fields:
            error_renderer.errors = {field_name: [f"Unknown field: {field_name}"]}
            if error_renderer.item and hasattr(error_renderer.item, field_name): setattr(error_renderer.item, field_name, raw_value_from_json)
            return await error_renderer.render_field_to_response(field_name, status_code=400)

        field_info_obj = update_schema.model_fields[field_name] # Используем field_info_obj
        annotation = field_info_obj.annotation
        try:
            ValidatorModel = create_model('FieldValidator', **{field_name: (annotation, ...)})
            validated_field_data = ValidatorModel.model_validate({field_name: raw_value_from_json})
            validated_value = getattr(validated_field_data, field_name)
        except ValidationError as ve:
            error_messages = [e_detail.get('msg', 'Invalid value.') for e_detail in ve.errors()]
            error_renderer.errors = {field_name: error_messages}
            if error_renderer.item and hasattr(error_renderer.item, field_name): setattr(error_renderer.item, field_name, raw_value_from_json)
            return await error_renderer.render_field_to_response(field_name, status_code=422)

        updated_item = await manager.update(item_id, {field_name: validated_value})

        success_cell_renderer = ViewRenderer(request, model_name, dam_factory, user, item_id, RenderMode.TABLE_CELL, field_to_focus=field_name)
        success_cell_renderer.item = updated_item
        return await success_cell_renderer.render_field_to_response(field_name)
    except HTTPException as e:
        error_renderer.errors = {field_name: [str(e.detail)]}
        if error_renderer.item and hasattr(error_renderer.item, field_name): setattr(error_renderer.item, field_name, raw_value_from_json)
        return await error_renderer.render_field_to_response(field_name, status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Unexpected error during inline update of {model_name}.{field_name}")
        error_renderer.errors = {field_name: ["Server error during update."]}
        if error_renderer.item and hasattr(error_renderer.item, field_name): setattr(error_renderer.item, field_name, raw_value_from_json)
        return await error_renderer.render_field_to_response(field_name, status_code=500)

@router.get("/view-field/{model_name}/{item_id}/{field_name}", response_class=HTMLResponse, name="get_table_cell_view")
async def get_table_cell_view(renderer: ViewRenderer = Depends(get_table_cell_renderer)):
    return await renderer.render_field_to_response(renderer.field_to_focus)

@router.get("/list-rows/{model_name}", response_class=HTMLResponse, name="get_list_rows")
async def get_list_rows_content(renderer: ViewRenderer = Depends(get_list_rows_renderer)):
    r = await renderer.render_to_response()
    return r

@router.get("/filter/{model_name}", response_class=HTMLResponse, name="get_filter_form", include_in_schema=False)
async def get_filter_form_content(renderer: ViewRenderer = Depends(get_filter_form_renderer)):
    return await renderer.render_to_response()

@router.get("/confirm-delete/{model_name}/{item_id}", response_class=HTMLResponse, name="get_confirm_delete_modal")
async def get_confirm_delete_modal_content(
        request: Request, renderer: ViewRenderer = Depends(get_view_mode_renderer)
):
    templates = get_templates()
    # ctx для _confirm_delete_modal.html ожидает model_name, item_id, html_id
    # html_id для модалки генерируем здесь, так как ViewRenderer для этого не используется
    modal_actual_id = f"modal-delete-{renderer.model_name}-{renderer.item_id}"
    render_ctx_for_modal = {"model_name": renderer.model_name, "item_id": renderer.item_id, "html_id": modal_actual_id}

    context_dict = {
        "request": request, "user": renderer.user, "SDK_STATIC_URL": STATIC_URL_PATH,
        "url_for": request.url_for,
        "ctx": render_ctx_for_modal, # Передаем только то, что нужно шаблону
        "modal_id": modal_actual_id # Передаем modal_id для _modal_wrapper, если он используется как базовый
    }
    # _confirm_delete_modal.html сам является полной модалкой, наследуя _modal_wrapper.html
    # Поэтому ему нужен modal_id, modal_title и т.д.
    # Ручка get_modal_wrapper здесь не используется.
    return templates.TemplateResponse("components/_confirm_delete_modal.html", context_dict)