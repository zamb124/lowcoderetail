# core_sdk/frontend/dependencies.py
from typing import Any, Optional
from fastapi import Request, Depends
import uuid

from core_sdk.data_access import get_dam_factory, DataAccessManagerFactory
from .renderer import ViewRenderer
from .types import RenderMode

async def get_view_renderer(
    request: Request,
    model_name: str,
    item_id: Optional[uuid.UUID] = None,
    mode: RenderMode = RenderMode.VIEW, # Режим можно получать из пути или query
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory)
) -> ViewRenderer:
    """
    FastAPI зависимость для получения настроенного экземпляра ViewRenderer.
    """
    # Извлекаем query параметры для пагинации/фильтрации
    query_params = dict(request.query_params)
    # Можно добавить извлечение parent_html_id и html_name_prefix из запроса, если нужно
    return ViewRenderer(
        request=request,
        model_name=model_name,
        dam_factory=dam_factory,
        item_id=item_id,
        mode=mode,
        query_params=query_params
    )