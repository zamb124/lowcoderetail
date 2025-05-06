# core_sdk/middleware/auth.py
import logging
from typing import Optional, Any, List

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.status import HTTP_401_UNAUTHORIZED
from fastapi.security.utils import get_authorization_scheme_param

from core_sdk.security import verify_token
from core_sdk.schemas.auth_user import AuthenticatedUser
from core_sdk.schemas.token import TokenPayload

logger = logging.getLogger("core_sdk.middleware.auth")


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Any,
        secret_key: str,
        algorithm: str = "HS256",
        allowed_paths: Optional[List[str]] = None,
        api_prefix: str = "/api/v1", # Добавляем префикс для формирования путей
    ):
        super().__init__(app)
        self.secret_key = secret_key
        self.algorithm = algorithm

        # Формируем разрешенные пути с учетом префикса
        default_paths = {
            f"{api_prefix}/docs",
            f"{api_prefix}/openapi.json",
            f"{api_prefix}/redoc",
            f"{api_prefix}/docs/oauth2-redirect",
            f"{api_prefix}/auth/login",
            f"{api_prefix}/auth/refresh", # Добавляем, если нужно
            "/health", # Health обычно в корне
        }
        self.allowed_paths = default_paths.union(set(allowed_paths or []))
        logger.debug(f"AuthMiddleware initialized. Allowed paths: {sorted(list(self.allowed_paths))}")

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # --- ИЗМЕНЕНИЕ: Добавляем атрибут user со значением None по умолчанию ---
        # Это делается для того, чтобы атрибут существовал, даже если аутентификация не удалась
        # или не проводилась. Помогает избежать AttributeError в зависимостях.
        # --------------------------------------------------------------------
        request.scope["user"] = None
        current_path = request.url.path
        is_allowed = any(
            current_path == allowed_path or (allowed_path.endswith('/') and current_path.startswith(allowed_path))
            for allowed_path in self.allowed_paths
        )

        if is_allowed:
             logger.debug(f"AuthMiddleware: Skipping auth for allowed path: {current_path}")
             # Устанавливаем user в None для разрешенных путей, если он еще не None
             if getattr(request, 'user', 'NOT_SET') != None:
                 setattr(request, 'user', None)
             return await call_next(request)

        authorization: str = request.headers.get("Authorization")
        scheme, token = get_authorization_scheme_param(authorization)

        if not authorization or scheme.lower() != "bearer" or not token:
            logger.debug(f"AuthMiddleware: No valid Bearer token found for path: {current_path}")
            # Устанавливаем user в None перед возвратом ошибки
            request.scope["user"] = None
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Not authenticated"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            payload = verify_token(
                token=token,
                secret_key=self.secret_key,
                algorithm=self.algorithm,
                credentials_exception=ValueError("Invalid token")
            )
            token_data = TokenPayload.model_validate(payload)

            if token_data.user_id is None:
                raise ValueError("User ID missing in token payload")

            auth_user = AuthenticatedUser(
                id=token_data.user_id,
                company_id=payload.get("company_id"),
                email=token_data.sub,
                is_active=payload.get("is_active", True),
                is_superuser=payload.get("is_superuser", False),
                permissions=payload.get("perms", [])
            )
            # --- ИЗМЕНЕНИЕ: Устанавливаем request.user ---
            request.scope["user"] = auth_user
            # -------------------------------------------
            logger.debug(f"AuthMiddleware: User {auth_user.id} authenticated for path: {current_path}")

        except Exception as e:
            logger.warning(f"AuthMiddleware: Token validation failed for path {current_path}. Error: {type(e).__name__}: {e}")
            # Устанавливаем user в None перед возвратом ошибки
            setattr(request, 'user', None)
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Could not validate credentials"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        response = await call_next(request)
        return response