# core_sdk/data_access/common.py
import contextlib
import httpx
import logging
from typing import Optional
from starlette.requests import Request
# fastapi.Depends не используется напрямую в этом файле, но может быть нужен вызывающему коду.
# Если он здесь не нужен, его можно убрать. Пока оставим, т.к. get_dam_factory его использует.
from fastapi import Depends

logger = logging.getLogger(__name__) # Имя будет core_sdk.data_access.common

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
            logger.debug(f"Invalid Authorization header format: '{auth_header[:30]}...'")
    else:
        logger.debug("No Authorization header found in request.")
    return None

_global_http_client: Optional[httpx.AsyncClient] = None

@contextlib.asynccontextmanager
async def global_http_client_lifespan():
    """
    Manages the lifecycle of a global httpx.AsyncClient instance.
    Intended to be used as a lifespan context manager in a FastAPI application.
    """
    global _global_http_client
    if _global_http_client is None:
        logger.info("SDK: Initializing global HTTP client...")
        timeouts = httpx.Timeout(10.0, connect=5.0, read=10.0, write=10.0)
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        try:
            _global_http_client = httpx.AsyncClient(timeout=timeouts, limits=limits)
            logger.info("SDK: Global HTTP client initialized successfully.")
        except Exception as e:
            logger.critical("SDK: Failed to initialize global HTTP client.", exc_info=True)
            # Если клиент не удалось создать, это критично для удаленных DAM.
            # Приложение может решить не стартовать или работать в ограниченном режиме.
            # Здесь мы просто логируем и позволяем приложению решить.
            # raise ConfigurationError("Failed to initialize global HTTP client") from e # Раскомментировать, если это должно останавливать запуск
    else:
        logger.info("SDK: Global HTTP client already initialized. Skipping re-initialization.")

    try:
        yield
    finally:
        client_to_close = _global_http_client
        _global_http_client = None # Сбрасываем ссылку перед закрытием
        if client_to_close:
            logger.info("SDK: Closing global HTTP client...")
            try:
                await client_to_close.aclose()
                logger.info("SDK: Global HTTP client closed successfully.")
            except Exception as e:
                logger.error("SDK: Error closing global HTTP client.", exc_info=True)
        else:
            logger.info("SDK: No global HTTP client instance was active to close.")

def get_global_http_client() -> Optional[httpx.AsyncClient]:
    """
    Returns the global httpx.AsyncClient instance.
    Returns None if the client has not been initialized or has been closed.
    """
    if _global_http_client is None:
        logger.warning("SDK: Attempted to get global HTTP client, but it's not initialized or already closed.")
    return _global_http_client