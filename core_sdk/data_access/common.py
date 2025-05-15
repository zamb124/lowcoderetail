# core_sdk/data_access/common.py
import contextlib
import httpx
import logging
from typing import Optional
from starlette.requests import Request

# fastapi.Depends не используется напрямую в этом файле, но может быть нужен вызывающему коду.
# Если он здесь не нужен, его можно убрать. Пока оставим, т.к. get_dam_factory его использует.
from fastapi import FastAPI


logger = logging.getLogger(__name__)  # Имя будет core_sdk.data_access.common


async def get_optional_token(request: Request) -> Optional[str]:
    """
    FastAPI dependency to extract the optional Bearer token from the Authorization header.
    Returns None if the header is missing or not a Bearer token.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            logger.debug("Bearer token found in Authorization header.")
            return parts[1]
        else:
            logger.debug(
                f"Invalid Authorization header format: '{auth_header[:30]}...'"
            )
    else:
        logger.debug("No Authorization header found in request.")
    return None


_global_http_client: Optional[httpx.AsyncClient] = None


@contextlib.asynccontextmanager
async def app_http_client_lifespan(app: FastAPI):  # Принимает app
    """
    Manages the lifecycle of an httpx.AsyncClient instance stored in app.state.
    Intended to be used as part of a FastAPI lifespan context manager.
    """
    logger.info("SDK: Initializing HTTP client in app.state...")
    timeouts = httpx.Timeout(10.0, connect=5.0, read=10.0, write=10.0)
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    client = None  # Локальная переменная
    try:
        client = httpx.AsyncClient(timeout=timeouts, limits=limits)
        app.state.http_client = client  # Сохраняем в app.state
        logger.info("SDK: HTTP client initialized successfully in app.state.")
        yield  # Приложение работает
    except Exception as e:
        logger.critical("SDK: Failed to initialize HTTP client.", exc_info=True)
        # Можно выбросить ошибку, чтобы остановить старт, если клиент критичен
        raise RuntimeError("Failed to initialize HTTP client") from e
    finally:
        if client:  # Используем локальную переменную client
            logger.info("SDK: Closing HTTP client from app.state...")
            await client.aclose()
            app.state.http_client = None  # Очищаем состояние
            logger.info("SDK: HTTP client closed successfully.")
        else:
            app.state.http_client = None  # На всякий случай очищаем
            logger.info(
                "SDK: No HTTP client instance was active in app.state to close."
            )


async def get_http_client_from_state(request: Request) -> Optional[httpx.AsyncClient]:
    """
    FastAPI dependency to get the httpx.AsyncClient from app.state.
    """
    client = getattr(request.app.state, "http_client", None)
    if client is None:
        logger.warning("SDK Dependency: HTTP client not found in app.state.")
    return client


async def get_global_http_client(request: Request) -> Optional[httpx.AsyncClient]:
    """
    Returns the global httpx.AsyncClient instance.
    This function is not intended to be used directly in FastAPI routes.
    """
    return await get_http_client_from_state(request)
