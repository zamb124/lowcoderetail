# core_sdk/frontend/base.py
import logging
import uuid
from typing import Optional, Any, Dict, List
from fastapi import (
    APIRouter,
    Depends,
    Request,
    HTTPException,
    Path as FastAPIPath,
    Query,
)
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ValidationError, create_model # Убедимся, что create_model импортирован

from core_sdk.data_access import get_dam_factory, DataAccessManagerFactory
from core_sdk.frontend.dependencies import (
    get_view_form_renderer,
    get_edit_form_renderer,
    get_create_form_renderer,
    get_list_table_renderer,
    get_list_table_rows_renderer,
    # get_table_cell_renderer, # Больше не используется напрямую
    # get_inline_edit_field_renderer, # Больше не используется напрямую
    get_filter_form_renderer,
    get_delete_confirm_renderer,
    get_renderer, # Общая зависимость для новых ручек фрагментов
)
from core_sdk.frontend.renderer import ViewRenderer
from core_sdk.frontend.types import ComponentMode, FieldState
from core_sdk.frontend.templating import get_templates
from core_sdk.frontend.config import STATIC_URL_PATH
from core_sdk.exceptions import ConfigurationError, RenderingError
from core_sdk.schemas.auth_user import AuthenticatedUser
from core_sdk.dependencies.auth import get_optional_current_user

logger = logging.getLogger("core_sdk.frontend.router")
router = APIRouter(
    prefix="/sdk",
    tags=["SDK UI Components"],
)

# --- Ручка для модальной обертки и resolve_titles (без изменений) ---
@router.get("/modal-wrapper", response_class=HTMLResponse, name="get_modal_wrapper")
async def get_modal_wrapper(request: Request, content_url: str = Query(...), modal_title: str = Query("Модальное окно"), modal_id: Optional[str] = Query(None), modal_size: str = Query("modal-lg")):
    templates = get_templates(); final_modal_id = modal_id or f"htmx-modal-{uuid.uuid4().hex[:8]}"
    context = {"request": request, "modal_id": final_modal_id, "modal_title": modal_title, "modal_size": modal_size, "content_url": content_url, "SDK_STATIC_URL": STATIC_URL_PATH, "url_for": request.url_for}
    return templates.TemplateResponse("components/_modal_wrapper.html", context)

class ResolveTitlesRequest(BaseModel): model_name: str; ids: List[uuid.UUID]
class ResolveTitlesResponse(BaseModel): root: Dict[uuid.UUID, str]
@router.post("/resolve-titles", response_model=ResolveTitlesResponse, name="resolve_titles")
async def resolve_titles_endpoint(request: Request, payload: ResolveTitlesRequest, dam_factory: DataAccessManagerFactory = Depends(get_dam_factory)):
    model_name = payload.model_name; ids_to_resolve = payload.ids
    if not ids_to_resolve: return ResolveTitlesResponse(root={})
    try: manager = dam_factory.get_manager(model_name, request=request)
    except ConfigurationError: raise HTTPException(status_code=404, detail=f"Model '{model_name}' not configured.")
    resolved_titles: Dict[uuid.UUID, str] = {}; title_field_candidates = ["title", "name", "email", "display_name", "label", "username"]
    items_map: Dict[uuid.UUID, Any] = {}
    try:
        list_result = await manager.list(filters={"id__in": ids_to_resolve}, limit=len(ids_to_resolve) + 10)
        for item in list_result.get("items", []):
            if hasattr(item, "id"): items_map[item.id] = item
    except Exception: items_map = {}
    for item_id_val in ids_to_resolve:
        item = items_map.get(item_id_val)
        if not item: item = await manager.get(item_id_val)
        if item:
            item_title = next((str(getattr(item, fld)) for fld in title_field_candidates if hasattr(item, fld) and getattr(item, fld)), None)
            resolved_titles[item_id_val] = item_title or f"{model_name} {str(item_id_val)[:8]}..."
        else: resolved_titles[item_id_val] = f"ID: {str(item_id_val)[:8]} (не найден)"
    return ResolveTitlesResponse(root=resolved_titles)

# --- РУЧКИ ДЛЯ ПОЛНЫХ КОМПОНЕНТОВ (ФОРМЫ, ТАБЛИЦЫ) ---
@router.get("/view/{model_name}/{item_id}", response_class=HTMLResponse, name="get_view_form")
async def get_view_form_content(renderer: ViewRenderer = Depends(get_view_form_renderer)):
    return await renderer.render_to_response()

@router.get("/form/edit/{model_name}/{item_id}", response_class=HTMLResponse, name="get_edit_form")
async def get_edit_form_content(renderer: ViewRenderer = Depends(get_edit_form_renderer)):
    return await renderer.render_to_response()

@router.get("/view/delete/{model_name}/{item_id}", response_class=HTMLResponse, name="get_delete_confirm")
async def get_delete_confirm_content(renderer: ViewRenderer = Depends(get_delete_confirm_renderer)):
    return await renderer.render_to_response()

@router.get("/form/create/{model_name}", response_class=HTMLResponse, name="get_create_form")
async def get_create_form_content(renderer: ViewRenderer = Depends(get_create_form_renderer)):
    return await renderer.render_to_response()

@router.get("/list/{model_name}", response_class=HTMLResponse, name="get_list_table")
async def get_list_table_content(renderer: ViewRenderer = Depends(get_list_table_renderer)):
    return await renderer.render_to_response()

@router.get("/list-rows/{model_name}", response_class=HTMLResponse, name="get_list_table_rows")
async def get_list_table_rows_content(renderer: ViewRenderer = Depends(get_list_table_rows_renderer)):
    return await renderer.render_to_response()

@router.get("/filter/{model_name}", response_class=HTMLResponse, name="get_filter_form", include_in_schema=False)
async def get_filter_form_content(renderer: ViewRenderer = Depends(get_filter_form_renderer)):
    return await renderer.render_to_response()

# --- РУЧКИ ОБРАБОТКИ ДАННЫХ ФОРМ (POST, PUT, DELETE item) ---
@router.post("/item/{model_name}", response_class=HTMLResponse, name="create_item")
async def create_item(
    request: Request, model_name: str = FastAPIPath(...),
    form_renderer: ViewRenderer = Depends(get_create_form_renderer),
):
    json_data: Dict[str, Any] = {}
    try: json_data = await request.json()
    except Exception:
        form_renderer.validation_errors = {"_form": ["Неверный формат JSON."]}
        target_schema_cls = form_renderer._get_schema_for_data_loading();
        form_renderer.item_data = target_schema_cls() if target_schema_cls else None
        return await form_renderer.render_to_response(status_code=422)
    try:
        await form_renderer.manager.create(json_data)
        response = Response(status_code=204, content=None)
        response.headers["HX-Trigger"] = f"closeModal, itemCreated_{model_name}, refreshData"
        return response
    except HTTPException as e:
        form_renderer.validation_errors = e.detail; target_schema_cls = form_renderer._get_schema_for_data_loading()
        try: instance_with_user_data = target_schema_cls.model_validate(json_data)
        except ValidationError: instance_with_user_data = target_schema_cls(); [setattr(instance_with_user_data, k, v) for k, v in json_data.items() if hasattr(instance_with_user_data, k)]
        form_renderer.item_data = instance_with_user_data
        return await form_renderer.render_to_response(status_code=e.status_code)
    except Exception as e_final:
        logger.exception(f"Error creating {model_name}: {e_final}"); form_renderer.validation_errors = {"_form": ["Внутренняя ошибка сервера при создании."]}
        target_schema_cls = form_renderer._get_schema_for_data_loading();
        try: instance_with_user_data = target_schema_cls.model_validate(json_data)
        except ValidationError: instance_with_user_data = target_schema_cls(); [setattr(instance_with_user_data, k, v) for k, v in json_data.items() if hasattr(instance_with_user_data, k)]
        form_renderer.item_data = instance_with_user_data
        return await form_renderer.render_to_response(status_code=422)

@router.put("/item/{model_name}/{item_id}", response_class=HTMLResponse, name="update_item")
async def update_item(
    request: Request, model_name: str = FastAPIPath(...), item_id: uuid.UUID = FastAPIPath(...),
    form_renderer: ViewRenderer = Depends(get_edit_form_renderer),
):
    json_data: Dict[str, Any] = {}
    try: json_data = await request.json()
    except Exception:
        if form_renderer.item_data is None: await form_renderer._load_data()
        form_renderer.validation_errors = {"_form": ["Неверный формат JSON."]}
        return await form_renderer.render_to_response(status_code=422)
    try:
        updated_item_sqlmodel = await form_renderer.manager.update(item_id, json_data)
        view_renderer = ViewRenderer(request, model_name, form_renderer.dam_factory, form_renderer.user, item_id, ComponentMode.VIEW_FORM)
        read_schema_cls = view_renderer.model_info.read_schema_cls
        view_renderer.item_data = read_schema_cls.model_validate(updated_item_sqlmodel)
        response = await view_renderer.render_to_response(status_code=200)
        response.headers["HX-Trigger"] = f"itemUpdated_{model_name}_{item_id}, closeModal, refreshData"
        return response
    except HTTPException as e:
        form_renderer.validation_errors = e.detail
        if form_renderer.item_data is None and e.status_code != 404: await form_renderer._load_data()
        target_schema_cls = form_renderer._get_schema_for_data_loading()
        try: instance_with_user_data = target_schema_cls.model_validate(json_data)
        except ValidationError:
            instance_with_user_data = target_schema_cls()
            if form_renderer.item_data: # Заполняем из оригинала, потом из json_data
                for field_name_original in target_schema_cls.model_fields.keys():
                    if hasattr(form_renderer.item_data, field_name_original) and hasattr(instance_with_user_data, field_name_original):
                        setattr(instance_with_user_data, field_name_original, getattr(form_renderer.item_data, field_name_original))
            for key, value in json_data.items():
                if hasattr(instance_with_user_data, key): setattr(instance_with_user_data, key, value)
        form_renderer.item_data = instance_with_user_data
        return await form_renderer.render_to_response(status_code=e.status_code)
    except Exception as e_final:
        logger.exception(f"Unexpected error updating {model_name}/{item_id}: {e_final}")
        if form_renderer.item_data is None: await form_renderer._load_data()
        form_renderer.validation_errors = {"_form": ["Внутренняя ошибка сервера при обновлении."]}
        target_schema_cls = form_renderer._get_schema_for_data_loading()
        try: instance_with_user_data = target_schema_cls.model_validate(json_data)
        except ValidationError:
            instance_with_user_data = target_schema_cls()
            if form_renderer.item_data:
                for field_name_original in target_schema_cls.model_fields.keys():
                    if hasattr(form_renderer.item_data, field_name_original) and hasattr(instance_with_user_data, field_name_original):
                        setattr(instance_with_user_data, field_name_original, getattr(form_renderer.item_data, field_name_original))
            for key, value in json_data.items():
                if hasattr(instance_with_user_data, key): setattr(instance_with_user_data, key, value)
        form_renderer.item_data = instance_with_user_data
        return await form_renderer.render_to_response(status_code=422)

@router.delete("/item/{model_name}/{item_id}", response_class=Response, name="delete_item")
async def delete_item(renderer: ViewRenderer = Depends(get_delete_confirm_renderer)):
    logger.info(f"Attempting to delete {renderer.model_name}/{renderer.item_id}")
    if renderer.item_id is None: raise HTTPException(status_code=400, detail="Item ID is required for deletion.")
    try:
        success = await renderer.manager.delete(renderer.item_id)
        if success:
            response = Response(status_code=204); response.headers["HX-Trigger"] = f"itemDeleted_{renderer.model_name}_{renderer.item_id}, closeModal, refreshData"
            return response
        else: raise HTTPException(status_code=500, detail="Delete operation failed unexpectedly.")
    except HTTPException as e: raise e
    except Exception as e_final: logger.exception(f"Error deleting {renderer.model_name}/{renderer.item_id}: {e_final}"); raise HTTPException(status_code=500, detail="Internal server error during deletion.")

# Ручка для опций select (без изменений)
@router.get("/select-options/{model_name}", name="get_select_options")
async def get_select_options(request: Request, model_name: str = FastAPIPath(...), q: Optional[str] = Query(None), id: Optional[str] = Query(None), dam_factory: DataAccessManagerFactory = Depends(get_dam_factory)):
    manager = dam_factory.get_manager(model_name, request=request); filters = {}; options_limit = 20
    if id:
        try:
            item_sqlmodel = await manager.get(uuid.UUID(id))
            if item_sqlmodel:
                read_schema_cls = manager.read_schema_cls; item_readschema = read_schema_cls.model_validate(item_sqlmodel)
                label = next((str(getattr(item_readschema, fld, "")) for fld in ["name", "title", "email"] if hasattr(item_readschema, fld) and getattr(item_readschema, fld)), str(item_readschema.id))
                from fastapi.responses import JSONResponse
                return JSONResponse(content=[{"value": str(item_readschema.id), "label": label, "id": str(item_readschema.id)}])
            return JSONResponse(content=[])
        except Exception as e: logger.error(f"Error in get_select_options by ID: {e}"); raise HTTPException(status_code=500)
    elif q: filters["search"] = q
    try:
        paginated_result_from_dam = await manager.list(limit=options_limit, filters=filters)
        items_sqlmodel_list = paginated_result_from_dam.get("items", [])
        read_schema_cls = manager.read_schema_cls; options_list = []
        for item_sqlmodel in items_sqlmodel_list:
            item_readschema = read_schema_cls.model_validate(item_sqlmodel)
            item_id_val = getattr(item_readschema, "id", None)
            label = next((str(getattr(item_readschema, fld, "")) for fld in ["name", "title", "email"] if hasattr(item_readschema, fld) and getattr(item_readschema, fld)), str(item_id_val) if item_id_val else "N/A")
            if item_id_val: options_list.append({"value": str(item_id_val), "label": label, "id": str(item_id_val)})
        from fastapi.responses import JSONResponse
        return JSONResponse(content=options_list)
    except Exception as e: logger.error(f"Error in get_select_options by query: {e}"); raise HTTPException(status_code=500)


# --- НОВЫЕ РУЧКИ ДЛЯ ФРАГМЕНТОВ ПОЛЕЙ (ДЛЯ "CLICK-TO-EDIT") ---

@router.get(
    # Путь теперь не включает состояние (view/edit)
    "/field-fragment/{parent_mode}/{model_name}/{item_id}/{field_name}",
    response_class=HTMLResponse,
    name="get_field_fragment" # Новое общее имя
)
async def get_field_fragment(
    request: Request,
    parent_mode: str = FastAPIPath(...),
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    field_name: str = FastAPIPath(...),
    # ---query-параметр для желаемого состояния поля---
    field_state_str: str = Query(FieldState.VIEW.value, alias="field_state"),
    # ---------------------------------------------------------
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
):
    try:
        parent_mode = ComponentMode(parent_mode)
    except ValueError:
        # Определяем fallback в зависимости от того, для чего чаще будет использоваться
        # Если чаще для таблиц, то TABLE_CELL, если для форм просмотра - VIEW_FORM
        parent_mode = ComponentMode.TABLE_CELL
        logger.warning(f"Invalid parent_mode '{parent_mode}' in get_field_fragment. Defaulting to {parent_mode.value}.")

    try:
        target_field_state = FieldState(field_state_str)
    except ValueError:
        logger.warning(f"Invalid field_state '{field_state_str}' in get_field_fragment. Defaulting to VIEW.")
        target_field_state = FieldState.VIEW

    # ViewRenderer инициализируется с item_id и parent_mode.
    # field_to_focus важен, если target_field_state == EDIT и parent_mode == TABLE_CELL,
    # чтобы ViewRenderer._prepare_sdk_fields правильно установил current_sdk_field_state для SDKField.
    # Если target_field_state == VIEW, то field_to_focus не так важен для логики состояния,
    # но может использоваться для других целей, если они есть.
    renderer = ViewRenderer(
        request, model_name, dam_factory, user, item_id,
        component_mode=parent_mode,
        field_to_focus=field_name if target_field_state == FieldState.EDIT else None # Фокус только если переходим в EDIT
    )
    return await renderer.render_field_fragment_response(field_name, target_field_state)


@router.put(
    # parent_mode_str уже в пути
    "/inline-update-field/{parent_mode_str}/{model_name}/{item_id}/{field_name}",
    response_class=HTMLResponse,
    name="update_inline_field"
)
@router.put(
    "/inline-update-field/{parent_mode}/{model_name}/{item_id}/{field_name}",
    response_class=HTMLResponse,
    name="update_inline_field"
)
async def update_inline_field_endpoint(
    request: Request,
    parent_mode: str = FastAPIPath(...),
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    field_name: str = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
):
    json_data, raw_value_from_json = {}, None
    try:
        parent_mode_for_template_context = ComponentMode(parent_mode)
    except ValueError:
        parent_mode_for_template_context = ComponentMode.TABLE_CELL

    renderer_component_mode_for_error = parent_mode_for_template_context
    if parent_mode_for_template_context == ComponentMode.LIST_TABLE_ROWS_FRAGMENT:
        renderer_component_mode_for_error = ComponentMode.TABLE_CELL

    error_edit_renderer = ViewRenderer(request, model_name, dam_factory, user, item_id, renderer_component_mode_for_error, field_to_focus=field_name)
    if error_edit_renderer.item_data is None: await error_edit_renderer._load_data()

    try:
        json_data = await request.json()
        if field_name not in json_data:
            error_edit_renderer.validation_errors = {field_name: [f"Поле '{field_name}' отсутствует в запросе."]}
            if error_edit_renderer.item_data and hasattr(error_edit_renderer.item_data, field_name) and raw_value_from_json is not None:
                 setattr(error_edit_renderer.item_data, field_name, raw_value_from_json)
            return await error_edit_renderer.render_field_fragment_response(field_name, FieldState.EDIT, status_code=400)
        raw_value_from_json = json_data[field_name]
    except Exception:
        error_edit_renderer.validation_errors = {field_name: ["Неверный формат JSON."]}
        return await error_edit_renderer.render_field_fragment_response(field_name, FieldState.EDIT, status_code=400)

    manager = dam_factory.get_manager(model_name, request=request)
    try:
        # ... (валидация значения как была) ...
        schema_for_validation = manager.update_schema_cls or manager.read_schema_cls
        if not schema_for_validation or field_name not in schema_for_validation.model_fields:
            error_edit_renderer.validation_errors = {field_name: [f"Неизвестное поле: {field_name}"]}
            if error_edit_renderer.item_data and hasattr(error_edit_renderer.item_data, field_name): setattr(error_edit_renderer.item_data, field_name, raw_value_from_json)
            return await error_edit_renderer.render_field_fragment_response(field_name, FieldState.EDIT, status_code=400)

        field_info_obj = schema_for_validation.model_fields[field_name]; annotation = field_info_obj.annotation
        validated_value = None
        try:
            current_value_for_validation = raw_value_from_json
            if annotation == Dict[str, Any] and isinstance(raw_value_from_json, str):
                import json
                try: current_value_for_validation = json.loads(raw_value_from_json)
                except json.JSONDecodeError: raise ValidationError.from_exception_data(title=field_name, line_errors=[{'type': 'json_invalid', 'loc': (field_name,), 'msg': 'Invalid JSON string', 'input': raw_value_from_json}])
            elif (annotation == List[str] or annotation == Optional[List[str]]) and isinstance(raw_value_from_json, str) and field_info_obj.json_schema_extra and field_info_obj.json_schema_extra.get("input_widget") == "textarea_lines":
                current_value_for_validation = [line.strip() for line in raw_value_from_json.splitlines() if line.strip()]

            ValidatorModel = create_model("FieldValidator", **{field_name: (annotation, ...)})
            validated_field_data = ValidatorModel.model_validate({field_name: current_value_for_validation})
            validated_value = getattr(validated_field_data, field_name)
        except ValidationError as ve:
            error_messages = [e_detail.get("msg", "Invalid value.") for e_detail in ve.errors()]
            error_edit_renderer.validation_errors = {field_name: error_messages}
            if error_edit_renderer.item_data and hasattr(error_edit_renderer.item_data, field_name): setattr(error_edit_renderer.item_data, field_name, raw_value_from_json)
            return await error_edit_renderer.render_field_fragment_response(field_name, FieldState.EDIT, status_code=422)

        updated_item_sqlmodel = await manager.update(item_id, {field_name: validated_value})

        # При успехе, renderer для success_view должен использовать тот же parent_mode,
        # чтобы _field_layout_wrapper отрендерил его правильно для контекста (например, таблицы)
        success_view_renderer = ViewRenderer(request, model_name, dam_factory, user, item_id, parent_mode_for_template_context, field_to_focus=field_name)
        read_schema_cls = success_view_renderer.model_info.read_schema_cls
        success_view_renderer.item_data = read_schema_cls.model_validate(updated_item_sqlmodel)
        return await success_view_renderer.render_field_fragment_response(field_name, FieldState.VIEW)
    except HTTPException as e:
        error_edit_renderer.validation_errors = {field_name: [str(e.detail)]}
        if error_edit_renderer.item_data and hasattr(error_edit_renderer.item_data, field_name): setattr(error_edit_renderer.item_data, field_name, raw_value_from_json)
        return await error_edit_renderer.render_field_fragment_response(field_name, FieldState.EDIT, status_code=e.status_code)
    except Exception as e_final:
        logger.exception(f"Unexpected error during inline update of {model_name}.{field_name}: {e_final}")
        error_edit_renderer.validation_errors = {field_name: ["Ошибка сервера при обновлении."]}
        if error_edit_renderer.item_data and hasattr(error_edit_renderer.item_data, field_name): setattr(error_edit_renderer.item_data, field_name, raw_value_from_json)
        return await error_edit_renderer.render_field_fragment_response(field_name, FieldState.EDIT, status_code=500)