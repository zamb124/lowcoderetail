# apps/frontend/app/api/ui.py
import logging
from typing import Optional
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette import status

from core_sdk.dependencies.auth import get_current_user, get_optional_current_user
from core_sdk.schemas.auth_user import AuthenticatedUser
from core_sdk.frontend import get_templates
from ..config import settings # Настройки текущего сервиса frontend

logger = logging.getLogger("frontend.api.ui")

# Роутер для основных страниц UI и фрагментов
router = APIRouter(tags=["User Interface"])

# --- UI Фрагменты ---
@router.get("/ui/header", response_class=HTMLResponse, include_in_schema=False, name="get_header_fragment")
async def get_header_fragment(request: Request, user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)):
    templates = get_templates()
    context = {
        "request": request, "user": user, "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH
    }
    return templates.TemplateResponse("components/_header.html", context)

@router.get("/ui/sidebar", response_class=HTMLResponse, include_in_schema=False, name="get_sidebar_fragment")
async def get_sidebar_fragment(request: Request, user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)):
    templates = get_templates()
    context = {
        "request": request, "user": user, "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH
    }
    return templates.TemplateResponse("components/_sidebar.html", context)

@router.get("/ui/footer", response_class=HTMLResponse, include_in_schema=False, name="get_footer_fragment")
async def get_footer_fragment(request: Request):
    templates = get_templates()
    context = {
        "request": request, "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH
    }
    return templates.TemplateResponse("components/_footer.html", context)

@router.get("/ui/dashboard", response_class=HTMLResponse, include_in_schema=False, name="get_dashboard_content")
async def get_dashboard_content(request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    templates = get_templates()
    dashboard_data = {"metric1": 123, "metric2": "abc"} # Пример данных
    context = {
        "request": request, "user": user, "data": dashboard_data, "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH
    }
    return templates.TemplateResponse("dashboard.html", context)

# --- Основные страницы ---
@router.get("/", response_class=HTMLResponse, include_in_schema=False, name="read_root")
async def read_root(request: Request, user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)):
    if not user:
        return RedirectResponse(url=request.url_for('login_page'), status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    templates = get_templates()
    context = {
        "request": request,
        "user": user,
        "title": "Панель управления",
        "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH,
        #"SERVICE_STATIC_URL": request.url_for('frontend_static', path='') if 'frontend_static' in request.app.router.routes_by_name else None
    }
    return templates.TemplateResponse("index.html", context)

@router.get("/login", response_class=HTMLResponse, include_in_schema=False, name="login_page")
async def login_page(request: Request):
    logger.debug("Serving login page.")
    templates = get_templates()
    context = {
        "request": request,
        "title": "Вход",
        "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH,
        "login_post_url": request.url_for('proxy_login')
    }
    return templates.TemplateResponse("login.html", context)