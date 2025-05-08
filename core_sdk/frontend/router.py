# core_sdk/frontend/router.py
import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Request, HTTPException, Path, Query, Form
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError, create_model

from data_access import DataAccessManagerFactory, get_dam_factory
from .dependencies import get_view_renderer
from .field import SDKField
from .renderer import ViewRenderer, RenderContext # Импортируем RenderContext
from .templating import templates, get_templates
from .types import RenderMode
from .config import STATIC_URL_PATH # Для app.js

logger = logging.getLogger("core_sdk.frontend.router")

router = APIRouter()

# --- Эндпоинты для рендеринга ---

async def _render_response(request: Request, context: RenderContext, template_name: Optional[str] = None) -> HTMLResponse:
    """Хелпер для рендеринга ответа."""
    if template_name is None:
        # Определяем шаблон по умолчанию на основе режима
        template_map = {
            RenderMode.VIEW: "components/view.html",
            RenderMode.EDIT: "components/form.html",
            RenderMode.CREATE: "components/form.html",
            RenderMode.LIST: "components/table.html",
        }
        template_name = template_map.get(context.mode, "components/view.html") # Фоллбэк

    return templates.TemplateResponse(
        template_name,
        {"request": request, "ctx": context}
    )

@router.get("/view/{model_name}/{item_id}", response_class=HTMLResponse)
async def get_view(
    request: Request,
    model_name: str = Path(...),
    item_id: UUID = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...), item_id=Path(...): get_view_renderer(request, model_name, item_id, RenderMode.VIEW))
):
    """Отдает HTML представление объекта."""
    try:
        context = await renderer.get_render_context()
        return await _render_response(request, context)
    except Exception as e: # Ловим ошибки рендеринга (включая 404)
        logger.error(f"Error rendering view for {model_name}/{item_id}: {e}", exc_info=True)
        # TODO: Отдавать HTML с ошибкой
        raise HTTPException(status_code=getattr(e, 'status_code', 500), detail=str(e))


@router.get("/form/{model_name}/{item_id}", response_class=HTMLResponse)
async def get_edit_form(
    request: Request,
    model_name: str = Path(...),
    item_id: UUID = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...), item_id=Path(...): get_view_renderer(request, model_name, item_id, RenderMode.EDIT))
):
    """Отдает HTML форму редактирования."""
    try:
        context = await renderer.get_render_context()
        # Устанавливаем target для HTMX = ID самого компонента
        context.extra["hx_target"] = f"#{context.html_id}"
        return await _render_response(request, context)
    except Exception as e:
        logger.error(f"Error rendering edit form for {model_name}/{item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=getattr(e, 'status_code', 500), detail=str(e))

@router.get("/form/{model_name}", response_class=HTMLResponse)
async def get_create_form(
    request: Request,
    model_name: str = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...): get_view_renderer(request, model_name, None, RenderMode.CREATE))
):
    """Отдает HTML форму создания."""
    try:
        context = await renderer.get_render_context()
        context.extra["hx_target"] = f"#{context.html_id}" # Пример
        return await _render_response(request, context)
    except Exception as e:
        logger.error(f"Error rendering create form for {model_name}: {e}", exc_info=True)
        raise HTTPException(status_code=getattr(e, 'status_code', 500), detail=str(e))

@router.get("/list/{model_name}", response_class=HTMLResponse)
async def get_list_view(
    request: Request,
    model_name: str = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...): get_view_renderer(request, model_name, None, RenderMode.LIST))
):
    """Отдает HTML представление списка/таблицы."""
    try:
        context = await renderer.get_render_context()
        return await _render_response(request, context)
    except Exception as e:
        logger.error(f"Error rendering list for {model_name}: {e}", exc_info=True)
        raise HTTPException(status_code=getattr(e, 'status_code', 500), detail=str(e))


# --- Эндпоинты для обработки данных форм ---

@router.post("/item/{model_name}", response_class=HTMLResponse)
async def create_item(
    request: Request,
    model_name: str = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...): get_view_renderer(request, model_name, None, RenderMode.CREATE)),
    # Используем Form(...) для получения всех данных формы
    # form_data: dict = Depends(lambda request: request.form()) # Не работает напрямую с Depends
):
    """Создает новый объект."""
    form_data_raw = await request.form()
    form_data = dict(form_data_raw)
    logger.debug(f"Received create data for {model_name}: {form_data}")
    try:
        # Валидация и создание через DAM
        new_item = await renderer.manager.create(form_data)
        # После создания редиректим на страницу просмотра созданного объекта
        # или возвращаем HTML обновленного списка/созданного элемента
        view_renderer = ViewRenderer(request, model_name, renderer.dam_factory, new_item.id, RenderMode.VIEW)
        context = await view_renderer.get_render_context()
        response = await _render_response(request, context)
        # Добавляем заголовок для HTMX для редиректа на стороне клиента (опционально)
        # response.headers["HX-Redirect"] = f"/some/path/to/view/{new_item.id}"
        # Или для обновления URL в браузере
        response.headers["HX-Push-Url"] = f"/some/path/to/view/{new_item.id}" # Заменить на реальный URL
        return response
    except HTTPException as e: # Ошибки валидации (422) или конфликта (409) из DAM
         logger.warning(f"HTTPException during create {model_name}: {e.status_code} - {e.detail}")
         # Возвращаем форму создания снова, но с ошибками
         context = await renderer.get_render_context()
         context.errors = e.detail if isinstance(e.detail, dict) else {"_form": [str(e.detail)]}
         response = await _render_response(request, context)
         response.status_code = e.status_code # Возвращаем исходный код ошибки
         return response
    except Exception as e:
        logger.exception(f"Error creating {model_name}")
        # Возвращаем форму создания с общей ошибкой
        context = await renderer.get_render_context()
        context.errors = {"_form": ["An unexpected error occurred during creation."]}
        response = await _render_response(request, context)
        response.status_code = 500
        return response


@router.put("/item/{model_name}/{item_id}", response_class=HTMLResponse)
async def update_item(
    request: Request,
    model_name: str = Path(...),
    item_id: UUID = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...), item_id=Path(...): get_view_renderer(request, model_name, item_id, RenderMode.EDIT)),
):
    """Обновляет существующий объект."""
    form_data_raw = await request.form()
    form_data = dict(form_data_raw)
    logger.debug(f"Received update data for {model_name}/{item_id}: {form_data}")
    try:
        # Валидация и обновление через DAM
        updated_item = await renderer.manager.update(item_id, form_data)
        # После обновления возвращаем режим просмотра
        view_renderer = ViewRenderer(request, model_name, renderer.dam_factory, item_id, RenderMode.VIEW)
        view_renderer.item = updated_item # Используем уже загруженный объект
        context = await view_renderer.get_render_context()
        # Важно: Убедимся, что hx-target в форме указывает на правильный элемент для замены
        return await _render_response(request, context) # Шаблон view заменит форму
    except HTTPException as e: # 404, 422
         logger.warning(f"HTTPException during update {model_name}/{item_id}: {e.status_code} - {e.detail}")
         # Возвращаем форму редактирования с ошибками
         context = await renderer.get_render_context() # Получаем контекст формы
         context.errors = e.detail if isinstance(e.detail, dict) else {"_form": [str(e.detail)]}
         response = await _render_response(request, context) # Рендерим форму
         response.status_code = e.status_code
         return response
    except Exception as e:
        logger.exception(f"Error updating {model_name}/{item_id}")
        # Возвращаем форму редактирования с общей ошибкой
        context = await renderer.get_render_context()
        context.errors = {"_form": ["An unexpected error occurred during update."]}
        response = await _render_response(request, context)
        response.status_code = 500
        return response


@router.delete("/item/{model_name}/{item_id}", response_class=Response)
async def delete_item(
    request: Request,
    model_name: str = Path(...),
    item_id: UUID = Path(...),
    renderer: ViewRenderer = Depends(lambda request, model_name=Path(...), item_id=Path(...): get_view_renderer(request, model_name, item_id, RenderMode.VIEW)),
):
    """Удаляет объект."""
    logger.info(f"Attempting to delete {model_name}/{item_id}")
    try:
        success = await renderer.manager.delete(item_id)
        if success:
            # Возвращаем пустой ответ 200 OK, HTMX удалит элемент, если есть hx-target="closest tr" и т.п.
            # Или можно вернуть специальный заголовок HX-Trigger для обновления списка
            response = Response(status_code=200)
            # response.headers["HX-Trigger"] = json.dumps({"event": "itemDeleted", "model": model_name})
            return response
        else:
            # Этого не должно происходить, если DAM выбрасывает 404
             raise HTTPException(status_code=500, detail="Delete operation failed unexpectedly.")
    except HTTPException as e: # 404
        logger.warning(f"HTTPException during delete {model_name}/{item_id}: {e.status_code} - {e.detail}")
        raise e # Пробрасываем 404
    except Exception as e:
        logger.exception(f"Error deleting {model_name}/{item_id}")
        raise HTTPException(status_code=500, detail="Internal server error during deletion.")

# --- Эндпоинт для динамических опций (например, для Choices.js) ---
@router.get("/select-options/{model_name}", response_class=HTMLResponse)
async def get_select_options(
    request: Request,
    model_name: str = Path(...),
    q: Optional[str] = Query(None, description="Search query"),
    # Дополнительные фильтры можно передавать через query params
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory)
):
    """Возвращает опции для select/relation полей (для Choices.js или аналогов)."""
    manager = dam_factory.get_manager(model_name)
    filters = {}
    if q:
        filters["search"] = q # Используем стандартный поиск DAM, если он настроен
        # Или фильтруем по конкретным полям: filters["name__like"] = q

    try:
        # Загружаем список (нужна пагинация?)
        results_dict = await manager.list(limit=50, filters=filters) # Лимит для выпадающего списка
        items = results_dict.get("items", [])

        # Формируем ответ в формате, ожидаемом Choices.js или другим компонентом
        # Пример для Choices.js: список словарей {'value': 'id', 'label': 'display_name'}
        options = []
        for item in items:
             item_id = getattr(item, 'id', None)
             label = getattr(item, 'title', None) or \
                     getattr(item, 'name', None) or \
                     getattr(item, 'email', None) or \
                     str(item_id)
             if item_id:
                  options.append({"value": str(item_id), "label": label})

        # Отдаем JSON (или HTML с <option>, если так настроен HTMX)
        from fastapi.responses import JSONResponse
        return JSONResponse(content=options)

    except Exception as e:
        logger.exception(f"Error fetching select options for {model_name}")
        raise HTTPException(status_code=500, detail="Failed to load options")

# Добавляем в ui_fragment_router или sdk_crud_router
@router.get("/edit-field/{model_name}/{item_id}/{field_name}", response_class=HTMLResponse, name="get_inline_edit_field")
async def get_inline_edit_field(
    request: Request,
    model_name: str = Path(...),
    item_id: UUID = Path(...),
    field_name: str = Path(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    # user: AuthenticatedUser = Depends(get_current_user) # Добавить проверку прав на редактирование
):
    templates = get_templates()
    try:
        # Используем ViewRenderer для получения данных и информации о полях
        # Передаем режим EDIT, чтобы получить нужную схему и настройки readonly/required
        renderer = ViewRenderer(request, model_name, dam_factory, item_id, RenderMode.EDIT)
        # Загружаем данные объекта
        item = await renderer.manager.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Объект не найден")
        renderer.item = item # Устанавливаем загруженный объект

        # Находим нужный SDKField
        schema = renderer._get_schema_for_mode()
        if field_name not in schema.model_fields:
             raise HTTPException(status_code=404, detail=f"Поле '{field_name}' не найдено")

        field_info = schema.model_fields[field_name]
        value = getattr(item, field_name, None)

        # Создаем SDKField для конкретного поля в режиме EDIT
        sdk_field = SDKField(field_name, field_info, value, renderer, RenderMode.EDIT)
        field_ctx = await sdk_field.get_render_context()

        # Проверяем, можно ли редактировать это поле
        if field_ctx.is_readonly or not field_ctx.extra.get('editable', True):
             logger.warning(f"Attempt to edit read-only field '{field_name}' for {model_name}/{item_id}")
             # Если поле нельзя редактировать, возвращаем view-представление обратно
             sdk_field_view = SDKField(field_name, field_info, value, renderer, RenderMode.TABLE_CELL) # Используем TABLE_CELL
             field_ctx_view = await sdk_field_view.get_render_context()
             return await templates.TemplateResponse(field_ctx_view.template_path, {"request": request, "field_ctx": field_ctx_view})

        # Рендерим шаблон ИНЛАЙН-РЕДАКТИРОВАНИЯ поля
        # Используем специальный шаблон или адаптированный _input.html
        return await templates.TemplateResponse("fields/_inline_input_wrapper.html", {
            "request": request,
            "field_ctx": field_ctx,
            "item_id": item_id,
            "model_name": model_name
        })

    except HTTPException as e:
        # Возвращаем сообщение об ошибке, которое HTMX вставит в ячейку
        return HTMLResponse(f'<div class="text-danger p-2">Ошибка: {e.detail}</div>', status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Ошибка при получении формы для inline-редактирования {model_name}.{field_name}")
        return HTMLResponse('<div class="text-danger p-2">Внутренняя ошибка сервера</div>', status_code=500)

@router.put("/edit-field/{model_name}/{item_id}/{field_name}", response_class=HTMLResponse, name="update_inline_field")
async def update_inline_field(
    request: Request,
    model_name: str = Path(...),
    item_id: UUID = Path(...),
    field_name: str = Path(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    # user: AuthenticatedUser = Depends(get_current_user) # Проверка прав
):
    templates = get_templates()
    form_data = await request.form()
    # form() возвращает MultiDict, извлекаем значение поля
    # Имя поля соответствует field_ctx.html_name, которое равно field_name в простом случае
    raw_value = form_data.get(field_name)

    manager = dam_factory.get_manager(model_name)
    try:
        # --- Получаем информацию о поле из схемы обновления или модели ---
        update_schema = manager.update_schema or manager.model
        if field_name not in update_schema.model_fields:
             raise HTTPException(status_code=400, detail=f"Неизвестное поле: {field_name}")

        field_info = update_schema.model_fields[field_name]
        annotation = field_info.annotation
        base_annotation = get_base_type(annotation) # Получаем базовый тип (убираем Optional)

        # --- Обработка чекбокса ---
        # Checkbox присылает значение только если отмечен. Если не отмечен, приходит только hidden input.
        # Мы добавили hidden input с value="false" перед чекбоксом.
        if base_annotation is bool:
            # Если поле пришло и оно 'true' (или любое другое значение, кроме 'false') - считаем True
            # Если поле пришло и оно 'false' (от hidden input) - считаем False
            # Если поле НЕ пришло (чекбокс не был отмечен) - считаем False (т.к. hidden input не будет) - ОШИБКА ЛОГИКИ!
            # Правильно: Если пришло значение от чекбокса (обычно 'true' или 'on'), то True.
            # Если пришло только значение от hidden ('false'), то False.
            # Если НЕ пришло значение от чекбокса, но пришло от hidden ('false'), то False.
            # Если НЕ пришло ни то, ни другое (не должно быть при нашей разметке), то False.
            # Проще: если значение от чекбокса есть в form_data, то True, иначе False.
            # Hidden input нужен только для случая, когда чекбокс *был* отмечен, а потом его сняли и отправили форму НЕ через htmx.
            # Для htmx PUT/POST, если чекбокс не отмечен, он просто не придет.
            # Поэтому проверяем наличие ключа в form_data.
            new_value = field_name in form_data
            logger.debug(f"Checkbox '{field_name}' value interpreted as: {new_value}")
        else:
            new_value = raw_value # Для остальных типов берем как есть

        # --- Валидация и преобразование типа ---
        try:
            # Пытаемся валидировать значение с помощью Pydantic
            ValidatorModel = create_model('FieldValidator', **{field_name: (annotation, ...)})
            validated_field_data = ValidatorModel.model_validate({field_name: new_value})
            validated_value = getattr(validated_field_data, field_name)
            logger.debug(f"Validated value for '{field_name}': {validated_value} (type: {type(validated_value)})")
        except ValidationError as ve:
             logger.warning(f"Inline update validation error for {model_name}.{field_name}: {ve.errors()}")
             # Возвращаем форму редактирования С ОШИБКОЙ
             item = await manager.get(item_id) # Получаем текущий объект
             renderer = ViewRenderer(request, model_name, dam_factory, item_id, RenderMode.EDIT)
             renderer.item = item
             schema = renderer._get_schema_for_mode()
             field_info_orig = schema.model_fields[field_name]
             # Создаем SDKField с НЕвалидным значением и ошибками
             sdk_field = SDKField(field_name, field_info_orig, new_value, renderer, RenderMode.EDIT)
             field_ctx = await sdk_field.get_render_context()
             field_ctx.errors = [e['msg'] for e in ve.errors()] # Добавляем ошибки

             # Отправляем обратно форму редактирования с ошибкой
             # Важно: статус 422 (Unprocessable Entity)
             response = await templates.TemplateResponse("fields/_inline_input_wrapper.html", {
                 "request": request, "field_ctx": field_ctx, "item_id": item_id, "model_name": model_name
             }, status_code=422)
             # Говорим HTMX не заменять элемент при ошибке 422 (опционально, но полезно)
             response.headers["HX-Reswap"] = "none"
             return response
        except Exception as e:
            logger.exception(f"Error during inline field validation/type conversion for {model_name}.{field_name}.")
            raise HTTPException(status_code=400, detail="Неверный формат данных")

        # --- Обновление через DAM ---
        update_data = {field_name: validated_value}
        updated_item = await manager.update(item_id, update_data)

        # --- Возвращаем обновленное view-представление для ячейки ---
        # Получаем view-контекст для обновленного поля
        renderer_view = ViewRenderer(request, model_name, dam_factory, item_id, RenderMode.TABLE_CELL) # Используем режим TABLE_CELL
        renderer_view.item = updated_item # Используем обновленный объект
        schema_view = renderer_view._get_schema_for_mode()
        field_info_view = schema_view.model_fields[field_name]
        value_view = getattr(updated_item, field_name, None)
        sdk_field_view = SDKField(field_name, field_info_view, value_view, renderer_view, RenderMode.TABLE_CELL)
        field_ctx_view = await sdk_field_view.get_render_context()

        # Рендерим шаблон ячейки (_table_cell.html)
        return await templates.TemplateResponse(field_ctx_view.template_path, {"request": request, "field_ctx": field_ctx_view})

    except HTTPException as e:
        # Пробрасываем 404 или другие ошибки из manager.update
        logger.warning(f"HTTPException during inline update for {model_name}.{field_name}: {e.status_code} {e.detail}")
        # Возвращаем просто текст ошибки, HTMX вставит его в ячейку
        return HTMLResponse(f'<div class="text-danger p-2">Ошибка {e.status_code}: {e.detail}</div>', status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Ошибка при inline-обновлении {model_name}.{field_name}")
        return HTMLResponse('<div class="text-danger p-2">Ошибка сервера</div>', status_code=500)

    except HTTPException as e:
        # Пробрасываем 404 или другие ошибки из manager.update
        # Возвращаем view-представление с сообщением об ошибке? Или просто текст ошибки?
        logger.warning(f"HTTPException during inline update: {e.status_code} {e.detail}")
        # Возвращаем просто текст ошибки, HTMX вставит его в ячейку
        return HTMLResponse(f'<div class="text-danger p-2">Ошибка {e.status_code}: {e.detail}</div>', status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Ошибка при inline-обновлении {model_name}.{field_name}")
        return HTMLResponse('<div class="text-danger p-2">Ошибка сервера</div>', status_code=500)

@router.get("/view-field/{model_name}/{item_id}/{field_name}", response_class=HTMLResponse, name="get_table_cell_view")
async def get_table_cell_view(
    request: Request,
    model_name: str = Path(...),
    item_id: UUID = Path(...),
    field_name: str = Path(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    # user: AuthenticatedUser = Depends(get_current_user) # Проверка прав на просмотр
):
    """ Возвращает HTML для одной ячейки таблицы (режим просмотра). Используется для отмены inline-редактирования. """
    templates = get_templates()
    try:
        # Используем ViewRenderer для получения данных и информации о полях
        # Используем режим TABLE_CELL для получения компактного представления
        renderer = ViewRenderer(request, model_name, dam_factory, item_id, RenderMode.TABLE_CELL)
        item = await renderer.manager.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Объект не найден")
        renderer.item = item

        schema = renderer._get_schema_for_mode() # Должен вернуть read_schema или model_cls
        if field_name not in schema.model_fields:
             raise HTTPException(status_code=404, detail=f"Поле '{field_name}' не найдено")

        field_info = schema.model_fields[field_name]
        value = getattr(item, field_name, None)

        # Создаем SDKField для конкретного поля в режиме TABLE_CELL
        sdk_field = SDKField(field_name, field_info, value, renderer, RenderMode.TABLE_CELL)
        field_ctx = await sdk_field.get_render_context()

        # Рендерим шаблон ячейки (_table.html или специфичный _table_cell.html)
        return await templates.TemplateResponse(field_ctx.template_path, {"request": request, "field_ctx": field_ctx})

    except HTTPException as e:
        return HTMLResponse(f'<div class="text-danger p-2">Ошибка: {e.detail}</div>', status_code=e.status_code)
    except Exception as e:
        logger.exception(f"Ошибка при получении view для ячейки {model_name}.{field_name}")
        return HTMLResponse('<div class="text-danger p-2">Ошибка сервера</div>', status_code=500)
# --- Эндпоинт для основного JS файла ---
# Этот эндпоинт будет в *приложении*, использующем SDK, а не в самом SDK.
# Но SDK предоставляет путь к файлу.
# Пример, как это могло бы выглядеть в frontend/app/main.py:
# from fastapi.responses import FileResponse
# from core_sdk.frontend.config import STATIC_DIR
# import os
#
# @app.get("/static/app.js")
# async def get_main_js():
#     js_path = os.path.join(STATIC_DIR, "js", "app.js")
#     if os.path.exists(js_path):
#         return FileResponse(js_path, media_type="application/javascript")
#     else:
#         raise HTTPException(status_code=404, detail="app.js not found")