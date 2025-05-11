# core_sdk/middleware/auth.py
import logging
from typing import Optional, Any, List, Set  # Добавили Set
from fnmatch import fnmatch  # Для простого сопоставления с шаблоном

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
        allowed_paths: Optional[List[str]] = None,  # Список строк или шаблонов fnmatch
        api_prefix: str = "/api/v1",
    ):
        super().__init__(app)
        self.secret_key = secret_key
        self.algorithm = algorithm

        # Формируем стандартные разрешенные пути
        default_paths = {
            f"{api_prefix}/docs",
            f"{api_prefix}/openapi.json",
            f"{api_prefix}/redoc",
            f"{api_prefix}/docs/oauth2-redirect",
            f"{api_prefix}/auth/login",  # Предполагаем, что логин здесь
            f"{api_prefix}/auth/refresh",  # И обновление токена
            "/health",  # Health check обычно в корне
            # Добавляем стандартные пути для статики SDK и сервиса как ПРЕФИКСЫ
            "/sdk-static/",  # Важно: добавляем слэш для startswith
            "/static/",  # Важно: добавляем слэш для startswith
        }
        # Объединяем стандартные и пользовательские пути
        combined_allowed = default_paths.union(set(allowed_paths or []))

        # Разделяем на точные пути и префиксы/шаблоны для оптимизации
        self.allowed_exact_paths: Set[str] = set()
        self.allowed_prefixes: Set[str] = set()
        self.allowed_patterns: Set[str] = set()  # Для fnmatch, если нужно

        for path in combined_allowed:
            if "*" in path or "?" in path or "[" in path:
                # Считаем путем с шаблоном (wildcard)
                self.allowed_patterns.add(path)
            elif path.endswith("/"):
                # Считаем префиксом директории
                self.allowed_prefixes.add(path)
            else:
                # Считаем точным путем
                self.allowed_exact_paths.add(path)

        logger.debug(f"AuthMiddleware initialized.")
        logger.debug(f"  Allowed exact paths: {sorted(list(self.allowed_exact_paths))}")
        logger.debug(f"  Allowed prefixes: {sorted(list(self.allowed_prefixes))}")
        logger.debug(f"  Allowed patterns: {sorted(list(self.allowed_patterns))}")

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request.scope["user"] = None  # Устанавливаем user в None по умолчанию
        current_path = request.url.path

        # --- ИСПРАВЛЕННАЯ ЛОГИКА ПРОВЕРКИ ---
        is_allowed = False
        if current_path in self.allowed_exact_paths:
            is_allowed = True
        else:
            # Проверяем префиксы (для директорий статики и т.п.)
            for prefix in self.allowed_prefixes:
                if current_path.startswith(prefix):
                    is_allowed = True
                    break
            # Если не нашли по префиксу, проверяем шаблоны (если есть)
            if not is_allowed and self.allowed_patterns:
                for pattern in self.allowed_patterns:
                    if fnmatch(current_path, pattern):
                        is_allowed = True
                        break
        # --- КОНЕЦ ИСПРАВЛЕННОЙ ЛОГИКИ ---

        if is_allowed:
            logger.debug(
                f"AuthMiddleware: Skipping auth for allowed path: {current_path}"
            )
            # request.scope["user"] уже None
            return await call_next(request)

        # --- Остальная логика проверки токена (без изменений) ---
        authorization: str = request.headers.get(
            "Authorization"
        ) or request.cookies.get("Authorization")
        scheme, token = get_authorization_scheme_param(authorization)

        if not authorization or scheme.lower() != "bearer" or not token:
            logger.debug(
                f"AuthMiddleware: No valid Bearer token found for path: {current_path}"
            )
            # request.scope["user"] уже None
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
                credentials_exception=ValueError("Invalid token"),  # Внутренняя ошибка
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
                permissions=payload.get("perms", []),
            )
            request.scope["user"] = auth_user
            logger.debug(
                f"AuthMiddleware: User {auth_user.id} authenticated for path: {current_path}"
            )

        except Exception as e:
            logger.warning(
                f"AuthMiddleware: Token validation failed for path {current_path}. Error: {type(e).__name__}: {e}"
            )
            # request.scope["user"] уже None (или сбрасываем на всякий случай)
            request.scope["user"] = None
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Could not validate credentials"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        response = await call_next(request)
        return response
