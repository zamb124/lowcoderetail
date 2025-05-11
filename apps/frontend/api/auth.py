# apps/frontend/app/api/auth.py
import logging
import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse  # Для ошибок в proxy_login
from starlette import status
from starlette.exceptions import HTTPException

from core_sdk.schemas.token import Token
from data_access import (
    get_global_http_client,
)  # Используем get_global_http_client из SDK
from ..config import settings  # Настройки текущего сервиса frontend

logger = logging.getLogger("frontend.api.auth")

router = APIRouter(prefix="/auth", tags=["Authentication & Authorization"])


@router.post("/login", response_model=Token, name="proxy_login")
async def proxy_login_for_access_token(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    http_client: httpx.AsyncClient = Depends(get_global_http_client),
):
    logger.info(f"BFF login proxy attempt for user: {form_data.username}")
    if not http_client:
        logger.error("BFF Login Proxy: Global HTTP client not available.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service connector unavailable.",
        )

    # API_V1_STR для Core сервиса берется из его настроек, предполагаем, что он там есть
    # Если в settings.CORE_SERVICE_URL уже есть /api/v1, то settings.API_V1_STR_CORE должен быть ""
    # Лучше, чтобы CORE_SERVICE_URL был базовым, а API_V1_STR добавлялся явно.
    # Предположим, что в settings есть CORE_API_V1_STR
    core_api_prefix = getattr(
        settings, "CORE_API_V1_STR", "/api/v1"
    )  # Фоллбэк на /api/v1
    core_login_url = f"{settings.CORE_SERVICE_URL}/auth/login"
    logger.debug(f"Proxying login request to: {core_login_url}")

    try:
        core_response = await http_client.post(
            core_login_url,
            data={"username": form_data.username, "password": form_data.password},
        )
        core_response.raise_for_status()
        token_data = core_response.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        if not access_token:
            logger.error(
                "BFF Login Proxy: Core service did not return an access_token."
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve token from authentication service.",
            )

        logger.info(
            f"BFF Login Proxy: Successfully received tokens for user {form_data.username}."
        )

        access_max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        response.set_cookie(
            key="Authorization",
            value=f"Bearer {access_token}",
            max_age=access_max_age,
            expires=access_max_age,
            path="/",
            httponly=True,
            samesite="lax",
            secure=settings.ENV != "dev",
        )
        logger.debug(f"Access token cookie set (max_age={access_max_age}s).")

        if refresh_token:
            refresh_max_age = (
                settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60
            )  # Предполагаем, что есть такая настройка
            response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                max_age=refresh_max_age,
                expires=refresh_max_age,
                path=f"{router.prefix}/refresh",
                httponly=True,
                samesite="lax",
                secure=settings.ENV != "dev",  # Используем префикс роутера
            )
            logger.debug(f"Refresh token cookie set (max_age={refresh_max_age}s).")

        response.headers["HX-Redirect"] = "/"
        return token_data

    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        try:
            error_detail = e.response.json().get("detail", "Authentication failed")
        except Exception:
            error_detail = e.response.text or "Authentication failed"
        logger.warning(
            f"BFF Login Proxy: Core service returned error {status_code} for user {form_data.username}. Detail: {error_detail}"
        )
        return HTMLResponse(
            content=f'<div class="alert alert-danger mt-2">{error_detail}</div>',
            status_code=status_code,
        )
    except httpx.RequestError as e:
        logger.error(
            f"BFF Login Proxy: Network error connecting to Core service at {core_login_url}: {e}",
            exc_info=True,
        )
        return HTMLResponse(
            content='<div class="alert alert-danger mt-2">Ошибка подключения к сервису аутентификации.</div>',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except Exception as e:
        logger.exception(
            f"BFF Login Proxy: Unexpected error during login for user {form_data.username}."
        )
        return HTMLResponse(
            content='<div class="alert alert-danger mt-2">Внутренняя ошибка сервера.</div>',
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
    name="handle_logout",
)
async def handle_logout(response: Response):
    logger.info("Processing logout request.")
    response.delete_cookie(key="Authorization", path="/", httponly=True, samesite="lax")
    response.delete_cookie(
        key="refresh_token",
        path=f"{router.prefix}/refresh",
        httponly=True,
        samesite="lax",
    )
    response.headers["HX-Redirect"] = "/login"
    return Response(status_code=status.HTTP_200_OK)


# Можно добавить эндпоинт /auth/refresh, если BFF будет сам обновлять токены
# @router.post("/refresh", ...)
# async def refresh_token(...): ...
