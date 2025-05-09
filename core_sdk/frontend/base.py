# core_sdk/frontend/base.py
import logging
import uuid
from typing import Optional, Any, Dict, List
from fastapi import APIRouter, Depends, Request, HTTPException, Path as FastAPIPath, Query, Form
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ValidationError, create_model, Field as PydanticField, RootModel

# DataAccessManagerFactory из get_dam_factory используется в зависимостях рендерера,
# но не нужен напрямую в сигнатурах этих конкретных ручек create/update.
from core_sdk.data_access import get_dam_factory
# Используем новые специализированные зависимости
from core_sdk.frontend.dependencies import (
    get_view_mode_renderer, get_edit_form_renderer, get_create_form_renderer,
    get_list_mode_renderer, get_list_rows_renderer,
    get_table_cell_renderer, get_inline_edit_field_renderer, get_filter_form_renderer
)
from core_sdk.frontend.renderer import ViewRenderer, RenderMode # RenderMode нужен для создания нового ViewRenderer
from core_sdk.registry import ModelRegistry
from core_sdk.filters.base import DefaultFilter
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter

from data_access import DataAccessManagerFactory
from dependencies.auth import get_optional_current_user
from exceptions import ConfigurationError
from frontend.utils import get_base_type # Оставим, если используется в update_inline_field
from core_sdk.schemas.auth_user import AuthenticatedUser # Для user в update_inline_field

logger = logging.getLogger("core_sdk.frontend.router")

router = APIRouter(
    prefix="/sdk",
    tags=["SDK UI Components"],
)
logger_titles = logging.getLogger("core_sdk.frontend.titles") # Отдельный логгер
# ... (остальные GET ручки остаются без изменений) ...
# Pydantic модель для тела запроса
class ResolveTitlesRequest(BaseModel):
    model_name: str
    ids: List[uuid.UUID] # Принимаем список UUID

# Pydantic модель для ответа (хотя FastAPI может сериализовать dict)
class ResolvedTitle(BaseModel):
    id: uuid.UUID
    title: str

class ResolveTitlesResponse(BaseModel): # Ответ - словарь id: title
    root: Dict[uuid.UUID, str]

@router.post("/resolve-titles", response_model=ResolveTitlesResponse, name="resolve_titles")
async def resolve_titles_endpoint(
        request: Request, # Для доступа к request в DAM, если нужно
        payload: ResolveTitlesRequest, # Используем Pydantic модель для тела
        dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
        
):
    """
    Принимает имя модели и список ID, возвращает словарь {id: title}.
    """
    model_name = payload.model_name
    ids_to_resolve = payload.ids

    if not ids_to_resolve:
        return ResolveTitlesResponse(root={})

    logger_titles.debug(f"Resolving titles for model '{model_name}', IDs: {ids_to_resolve}")

    try:
        manager = dam_factory.get_manager(model_name, request=request)
    except ConfigurationError as e:
        logger_titles.error(f"Cannot resolve titles: Model '{model_name}' not found in registry. Error: {e}")
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not configured for title resolution.")

    resolved_titles: Dict[uuid.UUID, str] = {}

    # Поля, которые будем проверять для "title" в порядке приоритета
    title_field_candidates = ['title', 'name', 'email', 'display_name', 'label', 'username']

    # Оптимизация: получить все объекты одним запросом, если это возможно
    # Используем фильтр id__in, если он есть в DefaultFilter или кастомном фильтре
    # Это более эффективно, чем делать manager.get() для каждого ID в цикле.


    items_map: Dict[uuid.UUID, Any] = {}

    try:
        # Преобразуем UUID в строки для фильтра, если он ожидает строки
        # (зависит от реализации фильтра, но обычно FastAPI-Filter справляется с UUID)
        list_result = await manager.list(filters={"id__in": ids_to_resolve}, limit=len(ids_to_resolve) + 10) # +10 на всякий случай
        for item in list_result.get("items", []):
            if hasattr(item, 'id'):
                items_map[item.id] = item
    except Exception as e:
        logger_titles.error(f"Error fetching items by id__in for {model_name}: {e}. Falling back to individual gets.")
        # При ошибке или если id__in не сработал, переходим к индивидуальным запросам
        items_map = {} # Очищаем, чтобы не было частичных результатов

    # Если id__in не сработал или не доступен, или вернул не все, получаем по одному
    for item_id in ids_to_resolve:
        if item_id in items_map: # Уже получили через list
            item = items_map[item_id]
        else: # Получаем индивидуально
            try:
                item = await manager.get(item_id)
            except Exception as e:
                logger_titles.warning(f"Error fetching item {item_id} for model {model_name} during title resolution: {e}")
                item = None

        if item:
            item_title = None
            for field_name in title_field_candidates:
                if hasattr(item, field_name) and getattr(item, field_name):
                    item_title = str(getattr(item, field_name))
                    break
            if item_title is None: # Фоллбэк на ID, если подходящее поле не найдено
                item_title = f"{model_name} {str(item_id)[:8]}..."
            resolved_titles[item_id] = item_title
        else:
            resolved_titles[item_id] = f"ID: {str(item_id)[:8]} (не найден)"

    logger_titles.debug(f"Resolved titles for '{model_name}': {resolved_titles}")
    return ResolveTitlesResponse(root=resolved_titles)

@router.get("/view/{model_name}/{item_id}", response_class=HTMLResponse, name="get_view")
async def get_view(renderer: ViewRenderer = Depends(get_view_mode_renderer)):
    return await renderer.render_to_response()

@router.get("/form/{model_name}/{item_id}", response_class=HTMLResponse, name="get_edit_form")
async def get_edit_form(renderer: ViewRenderer = Depends(get_edit_form_renderer)):
    return await renderer.render_to_response()

@router.get("/form/{model_name}", response_class=HTMLResponse, name="get_create_form")
async def get_create_form(renderer: ViewRenderer = Depends(get_create_form_renderer)):
    return await renderer.render_to_response()

@router.get("/list/{model_name}", response_class=HTMLResponse, name="get_list_view")
async def get_list_view(renderer: ViewRenderer = Depends(get_list_mode_renderer)):
    return await renderer.render_to_response()


# --- Эндпоинты для обработки данных форм ---

@router.post("/item/{model_name}", response_class=HTMLResponse, name="create_item")
async def create_item(
    request: Request, # Нужен для form_data и создания нового renderer
    model_name: str = FastAPIPath(...),
    # Начальный renderer для формы создания
    form_renderer: ViewRenderer = Depends(get_create_form_renderer)
    # dam_factory больше не нужен здесь как отдельная зависимость
):
    form_data_raw = await request.form()
    form_data = dict(form_data_raw)
    logger.debug(f"Received create data for {model_name}: {form_data}")
    try:
        new_item = await form_renderer.manager.create(form_data)

        # После создания рендерим страницу просмотра нового элемента
        # Используем dam_factory и user из form_renderer
        view_renderer = ViewRenderer(
            request,
            model_name,
            form_renderer.dam_factory, # <--- ИЗМЕНЕНИЕ
            form_renderer.user,        # <--- ИЗМЕНЕНИЕ
            new_item.id,
            RenderMode.VIEW
        )
        response = await view_renderer.render_to_response()
        response.headers["HX-Push-Url"] = str(request.url_for('get_view', model_name=model_name, item_id=new_item.id))
        response.headers["HX-Trigger"] = "closeModal"
        return response
    except HTTPException as e:
        logger.warning(f"HTTPException during create {model_name}: {e.status_code} - {e.detail}")
        form_renderer.errors = e.detail
        try:
            form_renderer.item = form_renderer._get_schema_for_mode()(**form_data)
        except ValidationError:
            form_renderer.item = BaseModel(**form_data)

        return await form_renderer.render_to_response(status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Error creating {model_name}")
        form_renderer.errors = {"_form": ["An unexpected error occurred during creation."]}
        try:
            form_renderer.item = form_renderer._get_schema_for_mode()(**form_data)
        except ValidationError:
            form_renderer.item = BaseModel(**form_data)
        return await form_renderer.render_to_response(status_code=500)


@router.put("/item/{model_name}/{item_id}", response_class=HTMLResponse, name="update_item")
async def update_item(
    request: Request, # Нужен для form_data и создания нового renderer
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    # Начальный renderer для формы редактирования
    form_renderer: ViewRenderer = Depends(get_edit_form_renderer)
    # dam_factory больше не нужен здесь как отдельная зависимость
):
    form_data_raw = await request.form()
    form_data = dict(form_data_raw)
    logger.debug(f"Received update data for {model_name}/{item_id}: {form_data}")
    try:
        updated_item = await form_renderer.manager.update(item_id, form_data)

        # После обновления рендерим страницу просмотра обновленного элемента
        # Используем dam_factory и user из form_renderer
        view_renderer = ViewRenderer(
            request,
            model_name,
            form_renderer.dam_factory, # <--- ИЗМЕНЕНИЕ
            form_renderer.user,        # <--- ИЗМЕНЕНИЕ
            item_id,
            RenderMode.VIEW
        )
        view_renderer.item = updated_item # Устанавливаем обновленный элемент
        response = await view_renderer.render_to_response()
        response.headers["HX-Trigger"] = "closeModal"
        return response
    except HTTPException as e:
        logger.warning(f"HTTPException during update {model_name}/{item_id}: {e.status_code} - {e.detail}")
        form_renderer.errors = e.detail
        await form_renderer._load_data()
        current_item_dict = form_renderer.item.model_dump() if form_renderer.item else {}
        current_item_dict.update(form_data)
        try:
            form_renderer.item = form_renderer._get_schema_for_mode()(**current_item_dict)
        except ValidationError:
            form_renderer.item = BaseModel(**current_item_dict)
        return await form_renderer.render_to_response(status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Error updating {model_name}/{item_id}")
        form_renderer.errors = {"_form": ["An unexpected error occurred during update."]}
        await form_renderer._load_data()
        current_item_dict = form_renderer.item.model_dump() if form_renderer.item else {}
        current_item_dict.update(form_data)
        try:
            form_renderer.item = form_renderer._get_schema_for_mode()(**current_item_dict)
        except ValidationError:
            form_renderer.item = BaseModel(**current_item_dict)
        return await form_renderer.render_to_response(status_code=500)

@router.delete("/item/{model_name}/{item_id}", response_class=Response, name="delete_item")
async def delete_item(
    renderer: ViewRenderer = Depends(get_view_mode_renderer),
):
    logger.info(f"Attempting to delete {renderer.model_name}/{renderer.item_id}")
    try:
        success = await renderer.manager.delete(renderer.item_id)
        if success:
            response = Response(status_code=204)
            response.headers["HX-Trigger"] = "itemDeleted, closeModal"
            return response
        else:
             raise HTTPException(status_code=500, detail="Delete operation failed unexpectedly.")
    except HTTPException as e:
        logger.warning(f"HTTPException during delete {renderer.model_name}/{renderer.item_id}: {e.status_code} - {e.detail}")
        raise e
    except Exception as e:
        logger.exception(f"Error deleting {renderer.model_name}/{renderer.item_id}")
        raise HTTPException(status_code=500, detail="Internal server error during deletion.")

@router.get("/select-options/{model_name}", name="get_select_options")
async def get_select_options(
    request: Request,
    model_name: str = FastAPIPath(...),
    q: Optional[str] = Query(None, description="Search query"),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory) # dam_factory нужен здесь
):
    manager = dam_factory.get_manager(model_name, request=request)
    filters = {}
    if q: filters["search"] = q
    try:
        results_dict = await manager.list(limit=50, filters=filters)
        items = results_dict.get("items", [])
        options = []
        for item in items:
             item_id = getattr(item, 'id', None)
             label = getattr(item, 'title', None) or \
                     getattr(item, 'name', None) or \
                     getattr(item, 'email', None) or \
                     str(item_id)
             if item_id: options.append({"value": str(item_id), "label": label})
        from fastapi.responses import JSONResponse
        return JSONResponse(content=options)
    except Exception as e:
        logger.exception(f"Error fetching select options for {model_name}")
        raise HTTPException(status_code=500, detail="Failed to load options")

# --- Эндпоинты для Inline Editing ---
@router.get("/edit-field/{model_name}/{item_id}/{field_name}", response_class=HTMLResponse, name="get_inline_edit_field")
async def get_inline_edit_field(renderer: ViewRenderer = Depends(get_inline_edit_field_renderer)):
    try:
        return await renderer.render_field_to_response(renderer.field_to_focus)
    except HTTPException as e:
        return HTMLResponse(f'<div class="text-danger p-2">Ошибка: {e.detail}</div>', status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Ошибка при получении формы для inline-редактирования {renderer.model_name}.{renderer.field_to_focus}")
        return HTMLResponse('<div class="text-danger p-2">Внутренняя ошибка сервера</div>', status_code=500)


@router.put("/edit-field/{model_name}/{item_id}/{field_name}", response_class=HTMLResponse, name="update_inline_field")
async def update_inline_field(
    request: Request,
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    field_name: str = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory), # dam_factory нужен здесь
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)
):
    form_data = await request.form()
    raw_value = form_data.get(field_name)
    manager = dam_factory.get_manager(model_name, request=request)

    try:
        update_schema = manager.update_schema or manager.model
        if field_name not in update_schema.model_fields:
             raise HTTPException(status_code=400, detail=f"Неизвестное поле: {field_name}")

        field_info = update_schema.model_fields[field_name]
        annotation = field_info.annotation
        base_annotation = get_base_type(annotation)

        new_value = raw_value
        if base_annotation is bool: new_value = field_name in form_data

        try:
            ValidatorModel = create_model('FieldValidator', **{field_name: (annotation, ...)})
            validated_field_data = ValidatorModel.model_validate({field_name: new_value})
            validated_value = getattr(validated_field_data, field_name)
        except ValidationError as ve:
             logger.warning(f"Inline update validation error: {ve.errors()}")
             renderer = ViewRenderer(request, model_name, dam_factory, user, item_id, RenderMode.EDIT, field_to_focus=field_name)
             renderer.errors = {field_name: [e['msg'] for e in ve.errors()]}
             await renderer._load_data()
             response = await renderer.render_field_to_response(field_name, status_code=422)
             response.headers["HX-Reswap"] = "innerHTML"
             response.headers["HX-Retarget"] = f"#cell-{model_name}-{item_id}-{field_name}"
             return response

        updated_item = await manager.update(item_id, {field_name: validated_value})

        view_renderer = ViewRenderer(request, model_name, dam_factory, user, item_id, RenderMode.TABLE_CELL, field_to_focus=field_name)
        view_renderer.item = updated_item
        return await view_renderer.render_field_to_response(field_name)

    except HTTPException as e:
        return HTMLResponse(f'<div class="text-danger p-2">Ошибка {e.status_code}: {e.detail}</div>', status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Ошибка при inline-обновлении {model_name}.{field_name}")
        return HTMLResponse('<div class="text-danger p-2">Ошибка сервера</div>', status_code=500)


@router.get("/view-field/{model_name}/{item_id}/{field_name}", response_class=HTMLResponse, name="get_table_cell_view")
async def get_table_cell_view(renderer: ViewRenderer = Depends(get_table_cell_renderer)):
    try:
        return await renderer.render_field_to_response(renderer.field_to_focus)
    except HTTPException as e:
        return HTMLResponse(f'<div class="text-danger p-2">Ошибка: {e.detail}</div>', status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Ошибка при получении view для ячейки {renderer.model_name}.{renderer.field_to_focus}")
        return HTMLResponse('<div class="text-danger p-2">Ошибка сервера</div>', status_code=500)


@router.get("/list-rows/{model_name}", response_class=HTMLResponse, name="get_list_rows")
async def get_list_rows(renderer: ViewRenderer = Depends(get_list_rows_renderer)):
    try:
        render_context = await renderer.get_render_context()
        if not render_context.items and render_context.pagination and render_context.pagination.get("count", 0) == 0:
            return HTMLResponse(content="<!-- No more items -->", status_code=200)
        return await renderer.render_to_response()
    except HTTPException as e:
        logger.warning(f"HTTPException in get_list_rows for {renderer.model_name}: {e.status_code} - {e.detail}")
        return HTMLResponse(content=f"<!-- Error: {e.detail} -->", status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Error rendering list rows for {renderer.model_name}")
        return HTMLResponse(content="<!-- Server error -->", status_code=500)


@router.get("/filter/{model_name}", response_class=HTMLResponse, name="get_filter_form", include_in_schema=False)
async def get_filter_form(
        renderer: ViewRenderer = Depends(get_filter_form_renderer) # <--- ИСПОЛЬЗУЕМ НОВУЮ ЗАВИСИМОСТЬ
):
    """Отдает HTML-форму фильтра для указанной модели."""
    logger.debug(f"SDK Route: GET /filter/{renderer.model_name}")
    try:
        # Проверяем, есть ли вообще поля для фильтрации
        # (get_render_context загрузит self.item как экземпляр фильтра и подготовит self._fields)
        render_ctx = await renderer.get_render_context()
        if not render_ctx.fields:
            logger.warning(f"No fields available for filter form {renderer.model_name}. Returning empty.")
            return HTMLResponse(f"<!-- No filter fields available for {renderer.model_name} -->")

        return await renderer.render_to_response()
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.exception(f"Error rendering filter form for {renderer.model_name}")
        # Можно вернуть более информативное сообщение об ошибке или пустой ответ
        return HTMLResponse(f"<!-- Error rendering filter: {str(e)} -->", status_code=500)

@router.get("/confirm-delete/{model_name}/{item_id}", response_class=HTMLResponse, name="get_confirm_delete_modal")
async def get_confirm_delete_modal(
    request: Request,
    renderer: ViewRenderer = Depends(get_view_mode_renderer)
):
    from core_sdk.frontend.renderer import RenderContext # Локальный импорт
    from core_sdk.frontend.config import STATIC_URL_PATH # Локальный импорт
    modal_ctx = RenderContext(
        model_name=renderer.model_name,
        mode=RenderMode.VIEW,
        item_id=renderer.item_id,
        html_id=f"modal-delete-{renderer.model_name}-{renderer.item_id}",
        title="Confirm Delete"
    )
    context_dict = {
        "request": request,
        "user": renderer.user,
        "SDK_STATIC_URL": STATIC_URL_PATH,
        "url_for": request.url_for,
        "ctx": modal_ctx
    }
    return renderer.templates.TemplateResponse("components/_confirm_delete_modal.html", context_dict)

@router.delete("/item/{model_name}/{item_id}", response_class=Response, name="delete_item")
async def delete_item(
    renderer: ViewRenderer = Depends(get_view_mode_renderer), # Нужен для доступа к менеджеру
):
    logger.info(f"Attempting to delete {renderer.model_name}/{renderer.item_id}")
    try:
        success = await renderer.manager.delete(renderer.item_id)
        if success:
            response = Response(status_code=204)
            # Отправляем событие для закрытия модалки и обновления списка (если он слушает itemDeleted)
            response.headers["HX-Trigger"] = "itemDeleted, closeModal"
            return response
        else:
             # Этого не должно происходить, если DAM выбрасывает 404 или другую ошибку
             raise HTTPException(status_code=500, detail="Delete operation failed unexpectedly.")
    except HTTPException as e: # Пробрасываем ошибки из DAM (например, 404)
        logger.warning(f"HTTPException during delete {renderer.model_name}/{renderer.item_id}: {e.status_code} - {e.detail}")
        # Если удаление не удалось, модалка не должна закрываться автоматически через HX-Trigger ответа 204.
        # Вместо этого, можно вернуть ошибку, которую обработает htmx:responseError и покажет уведомление.
        # Модалка останется открытой, или пользователь закроет ее вручную.
        # Если хотим закрыть модалку и показать ошибку, можно вернуть HTML с ошибкой и скриптом закрытия,
        # но это усложняет. Проще оставить модалку открытой при ошибке.
        raise e # Перевыбрасываем ошибку, чтобы HTMX ее обработал
    except Exception as e:
        logger.exception(f"Error deleting {renderer.model_name}/{renderer.item_id}")
        raise HTTPException(status_code=500, detail="Internal server error during deletion.")