# core_sdk/frontend/router.py
import logging
import uuid # Добавил импорт uuid
from typing import Optional, Any, Dict, List # Добавил List
from fastapi import APIRouter, Depends, Request, HTTPException, Path, Query, Form
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ValidationError, create_model # Добавил BaseModel, ValidationError, create_model

from core_sdk.data_access import DataAccessManagerFactory, get_dam_factory
from core_sdk.frontend.dependencies import get_view_renderer # Используем зависимость для рендерера
from core_sdk.frontend.field import SDKField # Для inline editing
from core_sdk.frontend.renderer import ViewRenderer, RenderContext, RenderMode # Импортируем RenderContext и RenderMode
from core_sdk.frontend.templating import get_templates # Используем get_templates
from core_sdk.frontend.config import STATIC_URL_PATH # Для app.js (если используется в шаблонах)
from core_sdk.registry import ModelRegistry # Для получения информации о фильтре
from core_sdk.filters.base import DefaultFilter # Базовый фильтр по умолчанию
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter # Для проверки типа фильтра

from dependencies.auth import get_optional_current_user
from frontend.utils import get_base_type
from schemas.auth_user import AuthenticatedUser

logger = logging.getLogger("core_sdk.frontend.router")

router = APIRouter(
    prefix="/sdk", # Стандартный префикс для UI роутов SDK
    tags=["SDK UI Components"],
    # dependencies=[Depends(get_current_user)] # Можно добавить общую зависимость аутентификации
)

# --- Хелпер для рендеринга ответа ---
async def _render_response(request: Request, context: RenderContext, template_name: Optional[str] = None) -> HTMLResponse:
    templates = get_templates()
    if template_name is None:
        template_map = {
            RenderMode.VIEW: "components/view.html",
            RenderMode.EDIT: "components/form.html",
            RenderMode.CREATE: "components/form.html",
            RenderMode.LIST: "components/table.html",
            RenderMode.TABLE_CELL: context.fields[0].template_path if context.fields else "fields/text_table.html", # Пример для ячейки
        }
        template_name = template_map.get(context.mode, "components/view.html")

    # Для TABLE_CELL контекст должен быть field_ctx, а не ctx
    if context.mode == RenderMode.TABLE_CELL:
        render_data = {"request": request, "field_ctx": context.fields[0] if context.fields else None, "item": context.item, "model_name": context.model_name}
    else:
        render_data = {"request": request, "ctx": context}

    return templates.TemplateResponse(template_name, render_data)


# --- Эндпоинты для рендеринга ---

@router.get("/view/{model_name}/{item_id}", response_class=HTMLResponse, name="get_view")
async def get_view(
    request: Request,
    model_name: str = Path(...),
    item_id: uuid.UUID = Path(...),
    # Используем get_view_renderer с указанием режима
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...), item_id=Path(...): get_view_renderer(request, model_name, item_id, RenderMode.VIEW))
):
    """Отдает HTML представление объекта."""
    try:
        context = await renderer.get_render_context()
        return await _render_response(request, context)
    except HTTPException as e: # Пробрасываем HTTPException (например, 404)
        raise e
    except Exception as e:
        logger.error(f"Error rendering view for {model_name}/{item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/form/{model_name}/{item_id}", response_class=HTMLResponse, name="get_edit_form")
async def get_edit_form(
    request: Request,
    model_name: str = Path(...),
    item_id: uuid.UUID = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...), item_id=Path(...): get_view_renderer(request, model_name, item_id, RenderMode.EDIT))
):
    """Отдает HTML форму редактирования."""
    try:
        context = await renderer.get_render_context()
        context.extra["hx_target"] = f"#{context.html_id}" # Цель для HTMX - сама форма
        return await _render_response(request, context)
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error rendering edit form for {model_name}/{item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/form/{model_name}", response_class=HTMLResponse, name="get_create_form")
async def get_create_form(
    request: Request,
    model_name: str = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...): get_view_renderer(request, model_name, None, RenderMode.CREATE))
):
    """Отдает HTML форму создания."""
    try:
        context = await renderer.get_render_context()
        # Цель для HTMX может быть плейсхолдером модального окна или другой областью
        context.extra["hx_target"] = "#modal-placeholder" # Пример для модалки
        return await _render_response(request, context)
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error rendering create form for {model_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# --- ИЗМЕНЕННЫЙ ЭНДПОИНТ ДЛЯ СПИСКА ---
@router.get("/list/{model_name}", response_class=HTMLResponse, name="get_list_view", tags=['SDK'])
async def get_list_view(
    request: Request,
    model_name: str = Path(...),
    # Фильтры будут автоматически инжектированы FastAPI на основе аннотации типа
    # Мы определим класс фильтра динамически ниже
    # filter_params: Dict[str, Any] = Depends(get_filter_params), # Альтернативный способ получения всех query params
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    # Для списка аутентификация может быть опциональной или с другими правами
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)
):
    """Отдает HTML представление списка/таблицы с поддержкой фильтрации и пагинации."""
    try:
        model_info = ModelRegistry.get_model_info(model_name)
        filter_cls = model_info.filter_cls

        if not filter_cls or not issubclass(filter_cls, BaseSQLAlchemyFilter):
            logger.debug(f"No valid custom filter for {model_name}, using dynamic DefaultFilter.")
            # Создаем DefaultFilter с Constants динамически
            manager = dam_factory.get_manager(model_name) # Нужен для получения self.model
            search_fields = [
                name for name, field_info in manager.model.model_fields.items()
                if field_info.annotation is str or field_info.annotation is Optional[str]
            ]
            class RuntimeConstants(DefaultFilter.Constants):
                model = manager.model
                search_model_fields = search_fields
            filter_cls = create_model(
                f"{model_name}RuntimeListFilter",
                __base__=DefaultFilter,
                Constants=(RuntimeConstants, ...)
            )
            try: filter_cls.model_rebuild(force=True)
            except Exception: pass

        # Создаем экземпляр фильтра из query параметров
        # FastAPI сделает это автоматически, если filter_cls указан как зависимость
        # Но так как мы определяем его динамически, нужно сделать это вручную или создать зависимость "на лету"

        # Простой способ: передать все query_params в renderer,
        # а ViewRenderer уже передаст их в DAM.list как словарь.
        # DAM.list должен уметь принимать словарь фильтров.
        query_params_dict = dict(request.query_params)

        renderer = ViewRenderer(
            request=request,
            model_name=model_name,
            dam_factory=dam_factory,
            mode=RenderMode.LIST,
            query_params=query_params_dict # Передаем все query параметры
        )
        context = await renderer.get_render_context()
        return await _render_response(request, context)
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error rendering list for {model_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --- Эндпоинты для обработки данных форм ---

@router.post("/item/{model_name}", response_class=HTMLResponse, name="create_item")
async def create_item(
    request: Request,
    model_name: str = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...): get_view_renderer(request, model_name, None, RenderMode.CREATE)),
):
    form_data_raw = await request.form()
    form_data = dict(form_data_raw)
    logger.debug(f"Received create data for {model_name}: {form_data}")
    try:
        new_item = await renderer.manager.create(form_data)
        # После создания редиректим на страницу просмотра или возвращаем обновленный компонент
        view_renderer = ViewRenderer(request, model_name, renderer.dam_factory, new_item.id, RenderMode.VIEW)
        context = await view_renderer.get_render_context()
        response = await _render_response(request, context) # Рендерим view созданного элемента
        # Говорим HTMX обновить URL в браузере
        # Путь к просмотру обычно /ui/view/{model_name}/{item_id}
        response.headers["HX-Push-Url"] = str(request.url_for('get_view', model_name=model_name, item_id=new_item.id))
        # Закрываем модалку, если форма была в ней (через событие)
        response.headers["HX-Trigger"] = "closeModal" # Слушаем это событие в JS для закрытия модалки
        return response
    except HTTPException as e:
         logger.warning(f"HTTPException during create {model_name}: {e.status_code} - {e.detail}")
         context = await renderer.get_render_context() # Контекст формы создания
         context.errors = e.detail if isinstance(e.detail, list) and e.detail and isinstance(e.detail[0], dict) else {"_form": [str(e.detail)]}
         context.item = BaseModel(**form_data) # Передаем введенные данные обратно в форму
         response = await _render_response(request, context)
         response.status_code = e.status_code
         return response
    except Exception as e:
        logger.exception(f"Error creating {model_name}")
        context = await renderer.get_render_context()
        context.errors = {"_form": ["An unexpected error occurred during creation."]}
        context.item = BaseModel(**form_data)
        response = await _render_response(request, context)
        response.status_code = 500
        return response


@router.put("/item/{model_name}/{item_id}", response_class=HTMLResponse, name="update_item")
async def update_item(
    request: Request,
    model_name: str = Path(...),
    item_id: uuid.UUID = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...), item_id=Path(...): get_view_renderer(request, model_name, item_id, RenderMode.EDIT)),
):
    form_data_raw = await request.form()
    form_data = dict(form_data_raw)
    logger.debug(f"Received update data for {model_name}/{item_id}: {form_data}")
    try:
        updated_item = await renderer.manager.update(item_id, form_data)
        view_renderer = ViewRenderer(request, model_name, renderer.dam_factory, item_id, RenderMode.VIEW)
        view_renderer.item = updated_item
        context = await view_renderer.get_render_context()
        response = await _render_response(request, context) # Рендерим view обновленного элемента
        # Закрываем модалку, если форма была в ней
        response.headers["HX-Trigger"] = "closeModal"
        return response
    except HTTPException as e:
         logger.warning(f"HTTPException during update {model_name}/{item_id}: {e.status_code} - {e.detail}")
         context = await renderer.get_render_context()
         context.errors = e.detail if isinstance(e.detail, list) and e.detail and isinstance(e.detail[0], dict) else {"_form": [str(e.detail)]}
         # Заполняем форму текущими значениями из БД + невалидными из form_data
         current_item_dict = renderer.item.model_dump() if renderer.item else {}
         current_item_dict.update(form_data) # Перезаписываем значениями из формы
         try:
             context.item = renderer._get_schema_for_mode()(**current_item_dict)
         except ValidationError: # Если даже так не валидно, берем что есть
             context.item = BaseModel(**current_item_dict)

         response = await _render_response(request, context)
         response.status_code = e.status_code
         return response
    except Exception as e:
        logger.exception(f"Error updating {model_name}/{item_id}")
        context = await renderer.get_render_context()
        context.errors = {"_form": ["An unexpected error occurred during update."]}
        response = await _render_response(request, context)
        response.status_code = 500
        return response


@router.delete("/item/{model_name}/{item_id}", response_class=Response, name="delete_item") # response_class=Response для 204
async def delete_item(
    request: Request, # request может быть не нужен, если нет зависимостей от него
    model_name: str = Path(...),
    item_id: uuid.UUID = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...), item_id=Path(...): get_view_renderer(request, model_name, item_id, RenderMode.VIEW)), # Нужен для доступа к менеджеру
):
    logger.info(f"Attempting to delete {model_name}/{item_id}")
    try:
        success = await renderer.manager.delete(item_id)
        if success:
            # Возвращаем пустой ответ 204 No Content
            # HTMX удалит элемент, если есть hx-target="closest tr" и hx-swap="outerHTML"
            # или hx-target="[ui_key='...']" hx-swap="delete"
            # Для закрытия модалки после удаления можно отправить событие
            response = Response(status_code=204)
            response.headers["HX-Trigger"] = "itemDeleted" # Событие для обновления списка или закрытия модалки
            return response
        else:
             # Этого не должно происходить, если DAM выбрасывает 404 или другую ошибку
             raise HTTPException(status_code=500, detail="Delete operation failed unexpectedly.")
    except HTTPException as e:
        logger.warning(f"HTTPException during delete {model_name}/{item_id}: {e.status_code} - {e.detail}")
        raise e
    except Exception as e:
        logger.exception(f"Error deleting {model_name}/{item_id}")
        raise HTTPException(status_code=500, detail="Internal server error during deletion.")

# --- Эндпоинт для динамических опций (для Choices.js) ---
@router.get("/select-options/{model_name}", name="get_select_options") # Убрал response_class=HTMLResponse
async def get_select_options(
    request: Request,
    model_name: str = Path(...),
    q: Optional[str] = Query(None, description="Search query"),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory)
):
    manager = dam_factory.get_manager(model_name)
    filters = {}
    if q:
        # Предполагаем, что у модели есть поле 'name' или 'title' для поиска
        # или что DefaultFilter настроен на поиск по нескольким полям
        filters["search"] = q

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
             if item_id:
                  options.append({"value": str(item_id), "label": label})
        from fastapi.responses import JSONResponse # Импорт здесь, чтобы не засорять начало файла
        return JSONResponse(content=options)
    except Exception as e:
        logger.exception(f"Error fetching select options for {model_name}")
        raise HTTPException(status_code=500, detail="Failed to load options")

# --- Эндпоинты для Inline Editing ---
@router.get("/edit-field/{model_name}/{item_id}/{field_name}", response_class=HTMLResponse, name="get_inline_edit_field")
async def get_inline_edit_field(
    request: Request,
    model_name: str = Path(...),
    item_id: uuid.UUID = Path(...),
    field_name: str = Path(...),
    renderer: ViewRenderer = Depends(get_view_renderer)
):
    templates = get_templates()
    try:
        context = await renderer.get_render_context_for_field(field_name)
        if not context:
             raise HTTPException(status_code=404, detail=f"Поле '{field_name}' не найдено для рендеринга.")

        if context.is_readonly or not context.extra.get('editable', True):
             logger.warning(f"Attempt to edit read-only/non-editable field '{field_name}' for {model_name}/{item_id}")
             view_renderer = ViewRenderer(request, model_name, renderer.dam_factory, item_id, RenderMode.TABLE_CELL, field_to_focus=field_name)
             view_context = await view_renderer.get_render_context_for_field(field_name)
             return await _render_response(request, view_context) # Используем _render_response

        return templates.TemplateResponse("fields/_inline_input_wrapper.html", {
            "request": request,
            "field_ctx": context, # Передаем контекст одного поля
            "item_id": item_id,
            "model_name": model_name,
            "item": renderer.item # Передаем весь объект для доступа к другим полям, если нужно в шаблоне
        })
    except HTTPException as e:
        return HTMLResponse(f'<div class="text-danger p-2">Ошибка: {e.detail}</div>', status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Ошибка при получении формы для inline-редактирования {model_name}.{field_name}")
        return HTMLResponse('<div class="text-danger p-2">Внутренняя ошибка сервера</div>', status_code=500)

@router.put("/edit-field/{model_name}/{item_id}/{field_name}", response_class=HTMLResponse, name="update_inline_field")
async def update_inline_field(
    request: Request,
    model_name: str = Path(...),
    item_id: uuid.UUID = Path(...),
    field_name: str = Path(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
):
    templates = get_templates()
    form_data = await request.form()
    raw_value = form_data.get(field_name)

    manager = dam_factory.get_manager(model_name)
    try:
        update_schema = manager.update_schema or manager.model
        if field_name not in update_schema.model_fields:
             raise HTTPException(status_code=400, detail=f"Неизвестное поле: {field_name}")

        field_info = update_schema.model_fields[field_name]
        annotation = field_info.annotation
        base_annotation = get_base_type(annotation)

        new_value = raw_value
        if base_annotation is bool:
            new_value = field_name in form_data # True если ключ есть, False если нет (для чекбокса)

        try:
            ValidatorModel = create_model('FieldValidator', **{field_name: (annotation, ...)})
            validated_field_data = ValidatorModel.model_validate({field_name: new_value})
            validated_value = getattr(validated_field_data, field_name)
        except ValidationError as ve:
             logger.warning(f"Inline update validation error: {ve.errors()}")
             item = await manager.get(item_id)
             renderer = ViewRenderer(request, model_name, dam_factory, item_id, RenderMode.EDIT, field_to_focus=field_name)
             renderer.item = item
             field_ctx = await renderer.get_render_context_for_field(field_name)
             if field_ctx: field_ctx.errors = [e['msg'] for e in ve.errors()]
             response = await templates.TemplateResponse("fields/_inline_input_wrapper.html", {
                 "request": request, "field_ctx": field_ctx, "item_id": item_id, "model_name": model_name, "item": item
             }, status_code=422)
             response.headers["HX-Reswap"] = "none" # Говорим HTMX не заменять содержимое при ошибке
             return response

        updated_item = await manager.update(item_id, {field_name: validated_value})

        view_renderer = ViewRenderer(request, model_name, dam_factory, item_id, RenderMode.TABLE_CELL, field_to_focus=field_name)
        view_renderer.item = updated_item
        field_ctx_view = await view_renderer.get_render_context_for_field(field_name)
        # _render_response ожидает RenderContext, а не FieldRenderContext
        # Создадим временный RenderContext для ячейки
        temp_render_ctx = RenderContext(
            model_name=model_name,
            mode=RenderMode.TABLE_CELL,
            item_id=item_id,
            item=updated_item,
            fields=[field_ctx_view] if field_ctx_view else [],
            html_id=f"cell-{model_name}-{item_id}-{field_name}", # Примерный ID
            title=field_name
        )
        return await _render_response(request, temp_render_ctx)

    except HTTPException as e:
        return HTMLResponse(f'<div class="text-danger p-2">Ошибка {e.status_code}: {e.detail}</div>', status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Ошибка при inline-обновлении {model_name}.{field_name}")
        return HTMLResponse('<div class="text-danger p-2">Ошибка сервера</div>', status_code=500)

@router.get("/view-field/{model_name}/{item_id}/{field_name}", response_class=HTMLResponse, name="get_table_cell_view")
async def get_table_cell_view(
    request: Request,
    model_name: str = Path(...),
    item_id: uuid.UUID = Path(...),
    field_name: str = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...), item_id=Path(...), field_name=Path(...): get_view_renderer(request, model_name, item_id, RenderMode.TABLE_CELL, field_to_focus=field_name))
):
    try:
        context = await renderer.get_render_context_for_field(field_name)
        if not context:
            raise HTTPException(status_code=404, detail=f"Поле '{field_name}' не найдено.")
        # Создадим временный RenderContext для _render_response
        temp_render_ctx = RenderContext(
            model_name=model_name,
            mode=RenderMode.TABLE_CELL,
            item_id=item_id,
            item=renderer.item,
            fields=[context],
            html_id=f"cell-{model_name}-{item_id}-{field_name}",
            title=field_name
        )
        return await _render_response(request, temp_render_ctx)
    except HTTPException as e:
        return HTMLResponse(f'<div class="text-danger p-2">Ошибка: {e.detail}</div>', status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Ошибка при получении view для ячейки {model_name}.{field_name}")
        return HTMLResponse('<div class="text-danger p-2">Ошибка сервера</div>', status_code=500)