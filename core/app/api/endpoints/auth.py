# core/app/api/endpoints/auth.py
import logging
from datetime import timedelta
from typing import Any # Optional и List не используются напрямую в этом файле
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordRequestForm
# AsyncSession не импортируется напрямую

from core_sdk.security import create_access_token, create_refresh_token, verify_token # verify_password не используется здесь
from core_sdk.schemas.token import Token, TokenPayload
from core_sdk.data_access import DataAccessManagerFactory, get_dam_factory
from core_sdk.exceptions import CoreSDKError # Для обработки ошибок DAM

from ...config import settings # Используем app. для импорта из текущего приложения
from ...data_access.user_manager import UserDataAccessManager
from ...models.user import User as UserModel # Для проверки статуса пользователя

logger = logging.getLogger(__name__) # Имя будет app.api.endpoints.auth

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login", response_model=Token)
async def login_for_access_token(
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any: # Возвращаемый тип Any, так как Token это Pydantic модель, а FastAPI сам обработает
    """
    Аутентифицирует пользователя по email и паролю, возвращая JWT access и refresh токены.
    """
    logger.info(f"Login attempt for user: {form_data.username}")
    try:
        user_manager: UserDataAccessManager = dam_factory.get_manager("User")
    except CoreSDKError as e:
        logger.critical(f"Failed to get UserDataAccessManager during login: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable.",
        )

    user = await user_manager.authenticate(
        email=form_data.username, password=form_data.password
    )

    if not user:
        logger.warning(f"Authentication failed for user: {form_data.username}. Incorrect email or password.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        logger.warning(f"Authentication failed for user: {form_data.username}. User is inactive.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    logger.info(f"User {user.email} authenticated successfully. Generating tokens.")
    token_data = {"sub": user.email, "user_id": str(user.id)}

    try:
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data=token_data,
            secret_key=settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
            expires_delta=access_token_expires,
        )

        refresh_token_expires = timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
        refresh_token = create_refresh_token(
             data={"user_id": str(user.id)}, # Только user_id в refresh токене для безопасности
             secret_key=settings.SECRET_KEY,
             algorithm=settings.ALGORITHM,
             expires_delta=refresh_token_expires,
        )
    except Exception as e:
        logger.exception(f"Error creating tokens for user {user.email}.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create authentication tokens.",
        )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }

@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    refresh_token: str = Body(..., embed=True, description="Действующий refresh токен пользователя.")
):
    """
    Обновляет JWT access токен, используя предоставленный refresh токен.
    """
    logger.info("Attempting to refresh access token.")
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = verify_token(
            token=refresh_token,
            secret_key=settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
            credentials_exception=credentials_exception # Передаем исключение для verify_token
        )
        token_data = TokenPayload.model_validate(payload)

        if token_data.type != 'refresh':
             logger.warning(f"Invalid token type for refresh: {token_data.type}")
             raise credentials_exception
        if token_data.user_id is None:
            logger.warning("User ID not found in refresh token payload.")
            raise credentials_exception

        user_manager: UserDataAccessManager = dam_factory.get_manager("User")
        user_uuid = UUID(str(token_data.user_id)) # Преобразуем в UUID, если user_id строка
        user = await user_manager.get(user_uuid)

        if user is None or not user.is_active:
            logger.warning(f"User {user_uuid} not found or inactive during token refresh.")
            raise credentials_exception

        logger.info(f"Refresh token validated for user {user.email}. Generating new access token.")
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        new_token_data = {"sub": user.email, "user_id": str(user.id)}
        new_access_token = create_access_token(
            data=new_token_data,
            secret_key=settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
            expires_delta=access_token_expires,
        )

        return {
            "access_token": new_access_token,
            "refresh_token": refresh_token, # Возвращаем исходный refresh токен
            "token_type": "bearer",
        }
    except HTTPException: # Перебрасываем HTTPException, которые могли быть вызваны verify_token или логикой выше
        raise
    except CoreSDKError as e: # Ошибки получения DAM
        logger.critical(f"Failed to get UserDataAccessManager during token refresh: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable.",
        )
    except Exception as e:
        logger.exception("Unexpected error during token refresh.")
        # Не передаем детализацию исходной ошибки клиенту из соображений безопасности
        raise credentials_exception # Общее сообщение об ошибке валидации