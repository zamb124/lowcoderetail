# core_sdk/frontend/dependencies.py
from typing import Optional
from fastapi import (
    Request,
    Depends,
    Path as FastAPIPath,
)
import uuid

from core_sdk.data_access import get_dam_factory, DataAccessManagerFactory
from core_sdk.frontend.renderer import ViewRenderer
# --- ИЗМЕНЕНИЕ: Импортируем ComponentMode ---
from core_sdk.frontend.types import ComponentMode
# -----------------------------------------
from core_sdk.schemas.auth_user import AuthenticatedUser
from core_sdk.dependencies.auth import get_optional_current_user


# Общая зависимость для ViewRenderer (без изменений, кроме типа mode)
async def get_renderer(
    request: Request,
    model_name: str,
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    item_id: Optional[uuid.UUID] = None,
    # --- ИЗМЕНЕНИЕ: mode теперь ComponentMode ---
    component_mode: ComponentMode = ComponentMode.VIEW_FORM,
    # -------------------------------------------
    field_to_focus: Optional[str] = None,
) -> ViewRenderer:
    return ViewRenderer(
        request=request,
        model_name=model_name,
        dam_factory=dam_factory,
        user=user,
        item_id=item_id,
        component_mode=component_mode, # Передаем component_mode
        query_params=dict(request.query_params),
        field_to_focus=field_to_focus,
    )


# Специализированные зависимости для каждого режима
async def get_view_form_renderer( # Переименовано из get_view_mode_renderer
    request: Request,
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, item_id, ComponentMode.VIEW_FORM
    )

async def get_delete_confirm_renderer( # Переименовано из get_delete_mode_renderer
    request: Request,
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, item_id, ComponentMode.DELETE_CONFIRM
    )

async def get_edit_form_renderer(
    request: Request,
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, item_id, ComponentMode.EDIT_FORM
    )

async def get_create_form_renderer(
    request: Request,
    model_name: str = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, None, ComponentMode.CREATE_FORM
    )

async def get_list_table_renderer( # Переименовано из get_list_mode_renderer
    request: Request,
    model_name: str = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, None, ComponentMode.LIST_TABLE
    )

async def get_list_table_rows_renderer( # Переименовано из get_list_rows_renderer
    request: Request,
    model_name: str = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, None, ComponentMode.LIST_TABLE_ROWS_FRAGMENT
    )

async def get_table_cell_renderer(
    request: Request,
    model_name: str = FastAPIPath(...),
    item_id: uuid.UUID = FastAPIPath(...),
    field_name: str = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request,
        model_name,
        dam_factory,
        user,
        item_id,
        ComponentMode.TABLE_CELL, # component_mode теперь TABLE_CELL
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
    # Для формы редактирования поля используем ComponentMode.TABLE_CELL,
    # так как это все еще рендеринг в контексте ячейки, но ViewRenderer
    # внутри _prepare_fields установит FieldState.EDIT для этого поля.
    return await get_renderer(
        request,
        model_name,
        dam_factory,
        user,
        item_id,
        ComponentMode.TABLE_CELL, # component_mode остается TABLE_CELL
        field_to_focus=field_name,
    )

async def get_filter_form_renderer(
    request: Request,
    model_name: str = FastAPIPath(...),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> ViewRenderer:
    return await get_renderer(
        request, model_name, dam_factory, user, None, ComponentMode.FILTER_FORM
    )