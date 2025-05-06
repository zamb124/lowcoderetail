# core/app/middleware.py (Новый файл или добавить в существующий)
import logging
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# Импортируем наш менеджер контекста сессии
from core_sdk.db.session import managed_session

logger = logging.getLogger(__name__)

class DBSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Оборачиваем весь вызов следующего обработчика (call_next)
        # в наш контекстный менеджер сессии
        async with managed_session():
            logger.debug(f"DBSessionMiddleware: Entered managed_session for {request.method} {request.url.path}")
            try:
                response = await call_next(request)
            except Exception as e:
                 # Логируем ошибку перед тем, как она пойдет дальше
                 logger.exception(f"DBSessionMiddleware: Exception during request processing within managed_session for {request.method} {request.url.path}")
                 raise e # Перевыбрасываем ошибку для стандартной обработки FastAPI
            finally:
                 logger.debug(f"DBSessionMiddleware: Exiting managed_session for {request.method} {request.url.path}")
        return response
