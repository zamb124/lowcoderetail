# apps/frontend/app/api/ui.py
import logging
from typing import Optional
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette import status

from core_sdk.dependencies.auth import get_current_user, get_optional_current_user
from core_sdk.schemas.auth_user import AuthenticatedUser
from core_sdk.frontend import get_templates
from ..config import settings  # Настройки текущего сервиса frontend

logger = logging.getLogger("frontend.api.ui")

# Роутер для основных страниц UI и фрагментов
router = APIRouter(tags=["User Interface"])


# --- UI Фрагменты ---
@router.get(
    "/ui/header",
    response_class=HTMLResponse,
    include_in_schema=False,
    name="get_header_fragment",
)
async def get_header_fragment(
    request: Request,
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
):
    templates = get_templates()
    context = {
        "request": request,
        "user": user,
        "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH,
    }
    return templates.TemplateResponse("components/_header.html", context)


@router.get(
    "/ui/sidebar",
    response_class=HTMLResponse,
    include_in_schema=False,
    name="get_sidebar_fragment",
)
async def get_sidebar_fragment(
    request: Request,
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
):
    templates = get_templates()
    context = {
        "request": request,
        "user": user,
        "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH,
    }
    return templates.TemplateResponse("components/_sidebar.html", context)


@router.get(
    "/ui/footer",
    response_class=HTMLResponse,
    include_in_schema=False,
    name="get_footer_fragment",
)
async def get_footer_fragment(request: Request):
    templates = get_templates()
    context = {"request": request, "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH}
    return templates.TemplateResponse("components/_footer.html", context)


@router.get(
    "/ui/dashboard",
    response_class=HTMLResponse,
    include_in_schema=False,
    name="get_dashboard_content",
)
async def get_dashboard_content(
    request: Request, user: AuthenticatedUser = Depends(get_current_user)
):
    templates = get_templates()
    dashboard_data = {"metric1": 123, "metric2": "abc"}  # Пример данных
    context = {
        "request": request,
        "user": user,
        "data": dashboard_data,
        "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH,
    }
    return templates.TemplateResponse("dashboard.html", context)


@router.get(
    "/{model_name_plural}/list-page",
    response_class=HTMLResponse,
    name="get_model_list_page",
)
async def get_model_list_page(
    request: Request,
    model_name_plural: str,  # Например, "users", "companies"
    user: Optional[AuthenticatedUser] = Depends(
        get_optional_current_user
    ),  # Или get_current_user
):
    """
    Отдает общую страницу-обертку для списка моделей,
    которая асинхронно загрузит фильтр и таблицу.
    """
    templates = get_templates()
    # Преобразуем множественное число из URL в единственное для ModelRegistry
    # Это простое предположение, может потребоваться более сложная логика или передача model_name напрямую
    model_name_singular = model_name_plural
    if model_name_plural.endswith("ies"):
        model_name_singular = model_name_plural[:-3] + "y"
    elif model_name_plural.endswith("s"):
        model_name_singular = model_name_plural[:-1]

    # Проверка прав доступа к списку этой модели (опционально)
    # if user and not user.has_permission(f"{model_name_singular.lower()}:list"):
    #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

    context = {
        "request": request,
        "user": user,
        "model_name": model_name_singular,  # Передаем имя модели для использования в hx-get
        "title": f"Список: {model_name_singular.capitalize()}",
        "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH,
    }
    return templates.TemplateResponse("list_page_wrapper.html", context)


# --- Основные страницы ---
@router.get("/", response_class=HTMLResponse, include_in_schema=False, name="read_root")
async def read_root(
    request: Request,
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
):
    if not user:
        return RedirectResponse(
            url=request.url_for("login_page"),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    templates = get_templates()
    context = {
        "request": request,
        "user": user,
        "title": "Панель управления",
        "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH,
        # "SERVICE_STATIC_URL": request.url_for('frontend_static', path='') if 'frontend_static' in request.app.router.routes_by_name else None
    }
    return templates.TemplateResponse("index.html", context)


@router.get(
    "/login", response_class=HTMLResponse, include_in_schema=False, name="login_page"
)
async def login_page(request: Request):
    logger.debug("Serving login page.")
    templates = get_templates()
    context = {
        "request": request,
        "title": "Вход",
        "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH,
        "login_post_url": request.url_for("proxy_login"),
    }
    return templates.TemplateResponse("login.html", context)
