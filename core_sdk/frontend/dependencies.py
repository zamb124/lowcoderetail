# core_sdk/frontend/dependencies.py
from typing import Optional
from fastapi import (
    Request,
    Depends,
    Path as FastAPIPath,
)  # Используем FastAPIPath во избежание конфликта
import uuid

from core_sdk.data_access import get_dam_factory, DataAccessManagerFactory
from core_sdk.frontend.renderer import ViewRenderer  # Убедитесь, что импорт корректен
from core_sdk.frontend.types import RenderMode
from core_sdk.schemas.auth_user import AuthenticatedUser  # Для user
from core_sdk.dependencies.auth import get_optional_current_user  # Для user


# Общая зависимость для ViewRenderer
async def get_renderer(
    request: Request,
    model_name: str,  # Будет браться из Path в конкретных ручках
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    item_id: Optional[uuid.UUID] = None,  # Будет браться из Path или None
    mode: RenderMode = RenderMode.VIEW,  # Режим по умолчанию, будет переопределяться
    field_to_focus: Optional[str] = None,  # Для inline editing
) -> ViewRenderer:
    return ViewRenderer(
        request=request,
        model_name=model_name,
        dam_factory=dam_factory,
        user=user,
        item_id=item_id,
        mode=mode,
        query_params=dict(request.query_params),
        field_to_focus=field_to_focus,
    )


# Специализированные зависимости для каждого режима, чтобы было чище в ручках
async def get_view_mode_renderer(
    request: Request,
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, item_id, RenderMode.VIEW
    )

async def get_delete_mode_renderer(
    request: Request,
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, item_id, RenderMode.DELETE
    )


async def get_edit_form_renderer(
    request: Request,
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, item_id, RenderMode.EDIT
    )


async def get_create_form_renderer(
    request: Request,
    model_name: str = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, None, RenderMode.CREATE
    )


async def get_list_mode_renderer(
    request: Request,
    model_name: str = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, None, RenderMode.LIST
    )


async def get_list_rows_renderer(
    request: Request,
    model_name: str = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, None, RenderMode.LIST_ROWS
    )


async def get_table_cell_renderer(
    request: Request,
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    field_name: str = FastAPIPath(...),  # Добавляем field_name
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request,
        model_name,
        dam_factory,
        user,
        item_id,
        RenderMode.TABLE_CELL,
        field_to_focus=field_name,
    )


async def get_inline_edit_field_renderer(
    request: Request,
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    field_name: str = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    # Для формы редактирования поля используем режим EDIT, но фокусируемся на конкретном поле
    return await get_renderer(
        request,
        model_name,
        dam_factory,
        user,
        item_id,
        RenderMode.EDIT,
        field_to_focus=field_name,
    )


async def get_filter_form_renderer(  # Новая специализированная зависимость
    request: Request,
    model_name: str = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, None, RenderMode.FILTER_FORM
    )
