# apps/frontend/app/main.py
import logging
import os
import json
from typing import Optional

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Depends, APIRouter
# --- ИЗМЕНЕНИЕ: Добавляем HTMLResponse ---
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from starlette import status
from starlette.exceptions import HTTPException
# ----------------------------------------
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles

# --- SDK Imports ---
from core_sdk.app_setup import create_app_with_sdk_setup
from core_sdk.config import BaseAppSettings
from core_sdk.dependencies.auth import get_current_user, get_optional_current_user
from core_sdk.schemas.auth_user import AuthenticatedUser
from core_sdk.registry import ModelRegistry
# Используем get_templates для получения инициализированного объекта
# --- ИЗМЕНЕНИЕ: Импортируем sdk_crud_router как sdk_crud_router ---
from core_sdk.frontend import mount_static_files, initialize_templates, get_templates, frontend_router as sdk_crud_router
# --------------------------------------------------------------------
from core_sdk.schemas.token import Token
from data_access import get_global_http_client # Оставляем, если proxy_login нужен

# --- Frontend Service Imports ---
from .config import settings
from . import registry_config # noqa F401
from .ws_manager import manager as ws_manager # Оставляем, если WS нужен

# --- Настройка логгирования ---
logging.basicConfig(level=settings.LOGGING_LEVEL.upper())
logger = logging.getLogger("frontend.app.main")

# --- Проверка конфигурации ModelRegistry ---
if not ModelRegistry.is_configured():
    logger.critical("ModelRegistry was not configured!")
    # exit(1) # Можно раскомментировать, если это критично

logger.info("--- Starting Frontend Service Application Setup ---")

SERVICE_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
SERVICE_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

try:
    # Передаем директорию шаблонов сервиса для инициализации
    initialize_templates(SERVICE_TEMPLATE_DIR)
except Exception as e:
    logger.critical(f"Failed to initialize templates: {e}", exc_info=True)
    exit(1)

# Убираем TemplatesStateMiddleware, т.к. get_templates() используется напрямую
# class TemplatesStateMiddleware(BaseHTTPMiddleware): ...

# --- Роутер для UI фрагментов (Header, Sidebar, Footer, Dashboard) ---
ui_fragment_router = APIRouter(tags=["UI Fragments"])

@ui_fragment_router.get("/header", response_class=HTMLResponse, include_in_schema=False, name="get_header_fragment")
async def get_header_fragment(request: Request, user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)):
    templates = get_templates()
    context = {
        "request": request, "user": user, "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH
    }
    # Используем новый шаблон
    return templates.TemplateResponse("components/_header.html", context)

@ui_fragment_router.get("/sidebar", response_class=HTMLResponse, include_in_schema=False, name="get_sidebar_fragment")
async def get_sidebar_fragment(request: Request, user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)):
    templates = get_templates()
    context = {
        "request": request, "user": user, "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH
    }
     # Используем новый шаблон
    return  templates.TemplateResponse("components/_sidebar.html", context)

@ui_fragment_router.get("/footer", response_class=HTMLResponse, include_in_schema=False, name="get_footer_fragment")
async def get_footer_fragment(request: Request):
    templates = get_templates()
    context = {
        "request": request, "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH
    }
    # Используем новый шаблон
    return  templates.TemplateResponse("components/_footer.html", context)

@ui_fragment_router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False, name="get_dashboard_content")
async def get_dashboard_content(request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    templates = get_templates()
    # Здесь можно получить реальные данные для дашборда
    dashboard_data = {"metric1": 123, "metric2": "abc"}
    context = {
        "request": request, "user": user, "data": dashboard_data, "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH
    }
    # Используем новый шаблон
    return templates.TemplateResponse("dashboard.html", context)
# --- Конец роутера для фрагментов ---

# --- Роутер для проксирования аутентификации (если нужен) ---
# Оставляем как есть, но убедимся, что login.html адаптирован
api_router = APIRouter(prefix="/auth", tags=["BFF API"])
@api_router.post("/login", response_model=Token, name="proxy_login")
async def proxy_login_for_access_token(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    http_client: httpx.AsyncClient = Depends(get_global_http_client)
):
    logger.info(f"BFF login proxy attempt for user: {form_data.username}")
    if not http_client:
        logger.error("BFF Login Proxy: Global HTTP client not available.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication service connector unavailable.")

    core_login_url = f"{str(settings.CORE_SERVICE_URL).rstrip('/')}{settings.API_V1_STR}/auth/login"
    logger.debug(f"Proxying login request to: {core_login_url}")

    try:
        core_response = await http_client.post(core_login_url, data={"username": form_data.username, "password": form_data.password})
        core_response.raise_for_status()
        token_data = core_response.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        if not access_token:
            logger.error("BFF Login Proxy: Core service did not return an access_token.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve token from authentication service.")

        logger.info(f"BFF Login Proxy: Successfully received tokens for user {form_data.username}.")

        access_max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        response.set_cookie(
            key="Authorization", value=f"Bearer {access_token}", max_age=access_max_age, expires=access_max_age,
            path="/", httponly=True, samesite="lax", secure=settings.ENV != "dev",
        )
        logger.debug(f"Access token cookie set (max_age={access_max_age}s).")

        if refresh_token:
            refresh_max_age = settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60
            response.set_cookie(
                key="refresh_token", value=refresh_token, max_age=refresh_max_age, expires=refresh_max_age,
                path="/auth/refresh", httponly=True, samesite="lax", secure=settings.ENV != "dev",
            )
            logger.debug(f"Refresh token cookie set (max_age={refresh_max_age}s).")

        # --- Ответ для HTMX ---
        response.headers["HX-Redirect"] = "/" # Редирект на главную после успешного логина
        return token_data

    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        try: error_detail = e.response.json().get("detail", "Authentication failed")
        except Exception: error_detail = e.response.text or "Authentication failed"
        logger.warning(f"BFF Login Proxy: Core service returned error {status_code} for user {form_data.username}. Detail: {error_detail}")
        # Возвращаем HTML с ошибкой для HTMX, чтобы он отобразился в #signin-response
        return HTMLResponse(content=f'<div class="alert alert-danger mt-2">{error_detail}</div>', status_code=status_code)
    except httpx.RequestError as e:
        logger.error(f"BFF Login Proxy: Network error connecting to Core service at {core_login_url}: {e}", exc_info=True)
        return HTMLResponse(content='<div class="alert alert-danger mt-2">Ошибка подключения к сервису аутентификации.</div>', status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception as e:
        logger.exception(f"BFF Login Proxy: Unexpected error during login for user {form_data.username}.")
        return HTMLResponse(content='<div class="alert alert-danger mt-2">Внутренняя ошибка сервера.</div>', status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
# --- Конец роутера API ---

# --- Собираем все роутеры ---
# sdk_crud_router содержит эндпоинты /view, /form, /list, /item из SDK
all_routers = [api_router, ui_fragment_router, sdk_crud_router]

# --- Создание приложения FastAPI ---
app = create_app_with_sdk_setup(
    settings=settings,
    api_routers=all_routers,
    enable_broker=False, # BFF обычно не нужен брокер
    rebuild_models=True, # Важно для ModelRegistry
    manage_http_client=True, # Управляем HTTP клиентом для проксирования
    enable_auth_middleware=True, # Включаем проверку токенов
    auth_allowed_paths=[ # Пути, доступные без токена
        settings.SDK_STATIC_URL_PATH + "/*", # Статика SDK (добавил *)
        "/static/*",                         # Статика сервиса (добавил *)
        "/favicon.ico",
        "/login",                            # Страница логина
        "/auth/login",                       # Эндпоинт обработки логина
        # Добавьте другие публичные пути, если они есть
    ],
    title=settings.PROJECT_NAME,
    description="Frontend BFF Service using Core SDK, HTMX and Datta Able.",
    version="0.1.0",
    include_health_check=True # Добавляем /health
)

# --- Монтирование статики ---
# Статика SDK (Datta Able)
mount_static_files(app)
# Статика сервиса (если есть)
if os.path.exists(SERVICE_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=SERVICE_STATIC_DIR), name="frontend_static")
    logger.info(f"Mounted service static files from '{SERVICE_STATIC_DIR}' at '/static'.")
else:
    logger.warning(f"Service static directory not found at '{SERVICE_STATIC_DIR}'.")

# --- WebSocket эндпоинт (если нужен) ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Ваш код для WebSocket...
    # Например, аутентификация и добавление в ConnectionManager
    # user = await get_current_user_from_ws_token(websocket) # Нужна функция для WS auth
    # if not user: return
    # await ws_manager.connect(websocket, str(user.id))
    # try:
    #     while True:
    #         data = await websocket.receive_text()
    #         # Обработка входящих сообщений WS
    # except WebSocketDisconnect:
    #     ws_manager.disconnect(websocket, str(user.id))
    pass

# --- Основные роуты страниц ---
@app.get("/", response_class=HTMLResponse, include_in_schema=False, name="read_root")
async def read_root(request: Request, user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)):
    if not user:
        # Редирект на страницу логина, если пользователь не аутентифицирован
        return RedirectResponse(url=request.url_for('login_page'), status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    templates = get_templates()
    context = {
        "request": request,
        "user": user,
        "title": "Панель управления",
        "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH,
        # "SERVICE_STATIC_URL": request.url_for('frontend_static', path='') # Если есть статика сервиса
    }
    # Рендерим новый index.html, который загрузит дашборд через HTMX
    return templates.TemplateResponse("index.html", context)

@app.get("/login", response_class=HTMLResponse, include_in_schema=False, name="login_page")
async def login_page(request: Request):
    logger.debug("Serving login page.")
    templates = get_templates()
    context = {
        "request": request,
        "title": "Вход",
        "SDK_STATIC_URL": settings.SDK_STATIC_URL_PATH,
        "login_post_url": request.url_for('proxy_login') # URL для POST запроса формы
    }
    # Рендерим новый login.html
    return templates.TemplateResponse("login.html", context)

# --- Эндпоинт для выхода ---
@app.post("/logout", status_code=status.HTTP_200_OK, include_in_schema=False, name="handle_logout")
async def handle_logout(response: Response):
    logger.info("Processing logout request.")
    # Удаляем куку авторизации
    response.delete_cookie(key="Authorization", path="/", httponly=True, samesite="lax")
    # Удаляем куку refresh токена, если она используется
    response.delete_cookie(key="refresh_token", path="/auth/refresh", httponly=True, samesite="lax")
    # Отправляем заголовок для редиректа через HTMX
    response.headers["HX-Redirect"] = "/login"
    # Возвращаем пустое тело или сообщение (HTMX его проигнорирует при редиректе)
    return Response(status_code=status.HTTP_200_OK)

logger.info("--- Frontend Service Application Setup Complete ---")

# --- Запуск Uvicorn (без изменений) ---
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = settings.FRONTEND_PORT
    log_level = settings.LOGGING_LEVEL.lower()
    workers = int(os.getenv("WEB_CONCURRENCY", "1"))

    logger.info(f"Starting Uvicorn for Frontend on {host}:{port} with {workers} worker(s)...")
    uvicorn.run(
        "frontend.app.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=(settings.ENV == "dev"),
        workers=workers
    )