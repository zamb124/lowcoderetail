# core/app/api/deps.py
from typing import AsyncGenerator, Optional
from uuid import UUID # <--- Добавляем импорт UUID

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
# Убираем AsyncSession, т.к. DAM его получит сам
# from sqlalchemy.ext.asyncio import AsyncSession

# Импорты из SDK
# Убираем get_session
# from core_sdk.db.session import get_session
from core_sdk.security import verify_token
from core_sdk.schemas.token import TokenPayload
from core_sdk.data_access import get_dam_factory
from core_sdk.data_access import DataAccessManagerFactory
from ..data_access.user_manager import UserDataAccessManager
# --- ИМПОРТИРУЕМ DAM ---


# Локальные импорты
# Убираем импорт всего пакета models/schemas, если нужен только User
# from .. import models, schemas
from ..models.user import User as UserModel # Импортируем модель User явно
from ..config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

async def get_user_manager(
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory)
) -> UserDataAccessManager:
    """Dependency to get an instance of UserDataAccessManager."""
    try:
        # Получаем конкретный менеджер из фабрики
        manager = dam_factory.get_manager("User")
        # Проверяем тип на всякий случай (хотя фабрика должна вернуть правильный)
        if not isinstance(manager, UserDataAccessManager):
             raise TypeError(f"Expected UserDataAccessManager, but got {type(manager)}")
        return manager
    except Exception as e:
        # Обработка ошибок получения менеджера (напр., не зарегистрирован)
        print(f"Error getting UserDataAccessManager: {e}")
        raise HTTPException(status_code=500, detail="Internal server error: Could not get user data manager.")
# ---------------------------------------------------------

# --- Используем НОВУЮ зависимость в get_current_user ---
async def get_current_user(
    # --- Зависим от get_user_manager ---
    user_manager: UserDataAccessManager = Depends(get_user_manager),
    # ----------------------------------
    token: str = Depends(oauth2_scheme)
) -> UserModel:
    """
    Verifies the JWT token and retrieves the user using the UserDataAccessManager.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Шаг 1: Верификация токена
        payload = verify_token(token=token, secret_key=settings.SECRET_KEY, algorithm=settings.ALGORITHM, credentials_exception=credentials_exception)
        token_data = TokenPayload.model_validate(payload)
    # ... (обработка ошибок токена) ...
    except (JWTError, ValidationError) as e: print(f"Token validation error: {e}"); raise credentials_exception
    except Exception as e: print(f"Unexpected error during token verification: {e}"); raise credentials_exception

    # Шаг 2: Проверка user_id
    if token_data.user_id is None: print("Token validation error: user_id missing."); raise credentials_exception

    # --- Шаг 3: Получение пользователя через УЖЕ ПОЛУЧЕННЫЙ user_manager ---
    try:
        user_uuid = UUID(str(token_data.user_id))
    except ValueError: print(f"Invalid user_id format: '{token_data.user_id}'."); raise credentials_exception

    # --- Вызываем метод get менеджера ---
    user = await user_manager.get(user_uuid) # Используем прямой вызов
    # ------------------------------------

    # Шаг 4: Проверка, найден ли пользователь
    if user is None: print(f"User not found for ID: {user_uuid}"); raise credentials_exception
    if not isinstance(user, UserModel): print(f"DAM returned unexpected type {type(user)}"); raise credentials_exception

    return user

# --- Функции get_current_active_user и get_current_active_superuser ---
# Остаются БЕЗ ИЗМЕНЕНИЙ, так как они зависят от get_current_user,
# которая теперь возвращает правильный объект UserModel.

async def get_current_active_user(
    current_user: UserModel = Depends(get_current_user),
) -> UserModel:
    """
    Зависимость для получения текущего *активного* пользователя.
    """
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_active_superuser(
    current_user: UserModel = Depends(get_current_active_user),
) -> UserModel:
    """
    Зависимость для получения текущего *активного суперпользователя*.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user

# TODO: Добавить зависимости для проверки специфичных прав доступа (permissions)
# def require_permission(permission_name: str): ...