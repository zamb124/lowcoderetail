# frontend/api/base.py (Пример)
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse
import uuid
from typing import Optional

from core_sdk.frontend.renderer import ViewRenderer # Наш рендерер из SDK
from core_sdk.data_access import get_dam_factory, DataAccessManagerFactory
from core_sdk.dependencies.auth import get_current_user # Защита
from core_sdk.schemas.auth_user import AuthenticatedUser

router = APIRouter()

@router.get("/view/{model_name}/{item_id}", response_class=HTMLResponse)
async def get_item_view(
    request: Request,
    model_name: str,
    item_id: uuid.UUID,
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: AuthenticatedUser = Depends(get_current_user) # Пример защиты
):
    """ Отдает HTML представление объекта для просмотра """
    try:
        renderer = ViewRenderer(model_name, dam_factory, item_id)
        context = await renderer.get_context(mode='view')
        # request.state.templates должен быть установлен middleware
        return request.state.templates.TemplateResponse(
            "components/item_view.html", # Шаблон для отображения объекта
            {"request": request, "ctx": context}
        )
    except ValueError as e: # Обработка "не найдено" из рендерера
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # Обработка других ошибок
        raise HTTPException(status_code=500, detail="Failed to render item view")

@router.get("/view/{model_name}/{item_id}/edit", response_class=HTMLResponse)
async def get_item_edit_form(
    request: Request,
    model_name: str,
    item_id: uuid.UUID,
    # hx_target: Optional[str] = Header(None), # Можно получать target из заголовков HTMX
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: AuthenticatedUser = Depends(get_current_user)
):
    """ Отдает HTML форму редактирования объекта """
    try:
        renderer = ViewRenderer(model_name, dam_factory, item_id)
        context = await renderer.get_context(mode='edit')
        # Может быть другой шаблон для формы
        return request.state.templates.TemplateResponse(
            "components/item_form.html",
            {"request": request, "ctx": context, "target_id": context.extra.get("html_id")}
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to render item form")

@router.put("/view/{model_name}/{item_id}", response_class=HTMLResponse)
async def update_item(
    request: Request,
    model_name: str,
    item_id: uuid.UUID,
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: AuthenticatedUser = Depends(get_current_user)
):
    """ Обрабатывает PUT запрос от формы редактирования HTMX """
    form_data = await request.form()
    update_data = dict(form_data) # Преобразуем в dict
    renderer = ViewRenderer(model_name, dam_factory, item_id)
    manager = renderer.manager

    try:
        # Используем DAM для обновления
        updated_item = await manager.update(item_id, update_data)
        # После успешного обновления отдаем обновленный вид объекта (view mode)
        renderer.item_data = updated_item # Обновляем данные в рендерере
        context = await renderer.get_context(mode='view')
        return request.state.templates.TemplateResponse(
            "components/item_view.html", # Тот же шаблон, что и для GET /view/...
             {"request": request, "ctx": context}
        )
    except HTTPException as e: # Пробрасываем ошибки валидации (422) или 404 из DAM
        raise e
    except Exception as e:
         # Можно вернуть HTML с сообщением об ошибке
         raise HTTPException(status_code=500, detail="Failed to update item")

# Добавьте эндпоинты для list (с пагинацией), create, delete