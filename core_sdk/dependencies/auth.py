# core_sdk/dependencies/auth.py
import logging
from typing import Optional

from fastapi import Request, Depends, HTTPException, status

from core_sdk.schemas.auth_user import AuthenticatedUser

logger = logging.getLogger("core_sdk.dependencies.auth")

# --- Зависимость для получения AuthenticatedUser из request.user ---
def get_optional_current_user(request: Request) -> Optional[AuthenticatedUser]:
    """
    Возвращает объект AuthenticatedUser из request.user, если он был установлен
    AuthMiddleware, иначе None. Не вызывает ошибку, если пользователя нет.
    """
    # --- ИЗМЕНЕНИЕ: Читаем из request.user ---
    user = request.user
    # ---------------------------------------
    # Проверка типа остается полезной
    if user and not isinstance(user, AuthenticatedUser):
        logger.error(f"Invalid object type found in request.user: {type(user)}. Expected AuthenticatedUser or None.")
        # Возвращаем None, так как тип неверный
        return None
    return user

# --- Остальные зависимости (get_current_user, get_current_active_user, ...) ---
# --- НЕ ТРЕБУЮТ ИЗМЕНЕНИЙ, так как зависят от get_optional_current_user ---

def get_current_user(
    user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)
) -> AuthenticatedUser:
    """
    Возвращает объект AuthenticatedUser. Вызывает ошибку 401, если пользователь
    не аутентифицирован (AuthMiddleware не установила request.user или токен невалиден).
    """
    if user is None:
        logger.debug("get_current_user dependency: No authenticated user found in request.user.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def get_current_active_user(
    user: AuthenticatedUser = Depends(get_current_user)
) -> AuthenticatedUser:
    """
    Возвращает объект AuthenticatedUser, если пользователь аутентифицирован и активен.
    Вызывает ошибку 400, если пользователь неактивен.
    """
    if not user.is_active:
        logger.warning(f"Access denied for inactive user: {user.id}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
    return user

def get_current_superuser(
    user: AuthenticatedUser = Depends(get_current_active_user)
) -> AuthenticatedUser:
    """
    Возвращает объект AuthenticatedUser, если пользователь аутентифицирован,
    активен и является суперпользователем.
    Вызывает ошибку 403, если пользователь не суперюзер.
    """
    if not user.is_superuser:
        logger.warning(f"Access denied for non-superuser: {user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges"
        )
    return user

def require_permission(required_permission: str):
    """
    Фабрика зависимостей FastAPI, которая проверяет наличие у текущего
    пользователя необходимого права доступа.

    :param required_permission: Коднайм требуемого права доступа (строка).
    """
    async def _check_permission(
        user: AuthenticatedUser = Depends(get_current_active_user)
    ) -> AuthenticatedUser:
        logger.debug(f"Checking permission '{required_permission}' for user {user.id}")
        if not user.has_permission(required_permission):
            logger.warning(f"Permission '{required_permission}' denied for user {user.id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        logger.debug(f"Permission '{required_permission}' granted for user {user.id}")
        return user
    return _check_permission