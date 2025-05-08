# core/app/api/endpoints/users.py
import logging
from typing import List, Optional # List, Optional могут быть нужны для кастомных эндпоинтов
from uuid import UUID

from fastapi import Depends, HTTPException, status # APIRouter не нужен здесь напрямую
from sqlalchemy.ext.asyncio import AsyncSession

from core_sdk.crud.factory import CRUDRouterFactory
from core_sdk.db.session import get_current_session # Переименовали get_session на get_current_session
from core_sdk.data_access import DataAccessManagerFactory, get_dam_factory # Для кастомных эндпоинтов
from core_sdk.exceptions import CoreSDKError
from core_sdk.dependencies.auth import get_current_user, get_current_superuser, require_permission
from core_sdk.schemas.auth_user import AuthenticatedUser
from ...data_access.user_manager import UserDataAccessManager
from ... import schemas
# Локальный CRUD не используется, если все через DAM
# from app import crud

logger = logging.getLogger(__name__) # Имя будет app.api.endpoints.users

user_factory = CRUDRouterFactory(
    model_name='User', # Имя модели, как зарегистрировано в ModelRegistry
    prefix='/users',
    tags=["Users"], # Добавляем тег
    create_deps=[Depends(get_current_superuser)],
    # Для update и get проверка прав может быть более сложной (например, пользователь может менять себя)
    # Это можно реализовать в кастомном эндпоинте или через более сложную зависимость.
    # Пока оставляем базовые проверки.
    update_deps=[Depends(get_current_superuser)],
    delete_deps=[Depends(get_current_superuser)],
    list_deps=[Depends(get_current_superuser)],
    get_deps=[Depends(get_current_superuser)],
)

@user_factory.router.get(
    "/funcs/me",
    response_model=AuthenticatedUser, # Используем схему из модуля
    summary="Get Current User",
    description="Получает информацию о текущем аутентифицированном пользователе.",
    dependencies=[Depends(require_permission('me'))],
    tags=["Users"] # Уточняем тег, если нужно отделить от CRUD
)
async def read_users_me(
        current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Возвращает данные текущего активного пользователя.
    """
    logger.info(f"Request for current user data by user ID: {current_user.id}")
    return current_user

@user_factory.router.post(
    "/{user_id}/assign_group/{group_id}",
    response_model=schemas.user.UserReadWithGroups, # Возвращаем пользователя с группами
    summary="Assign User to Group",
    description="Назначает указанного пользователя в указанную группу.",
    tags=["Users", "Groups"],
    dependencies=[Depends(require_permission('assign_user_to_group'))], # Проверка прав доступа
)
async def assign_user_to_group_endpoint( # Переименовал для ясности
    user_id: UUID,
    group_id: UUID,
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
    # current_user: AuthenticatedUser = Depends(get_current_active_superuser) # Защита через require_permission
):
    """
    Назначает пользователя в группу, используя UserDataAccessManager.
    """
    logger.info(f"API: Attempting to assign user {user_id} to group {group_id}.")
    try:
        user_manager: UserDataAccessManager = dam_factory.get_manager("User")
        # Вызываем новый метод менеджера
        updated_user_model = await user_manager.assign_to_group(user_id=user_id, group_id=group_id)
        # Преобразуем модель User из БД в схему UserReadWithGroups перед возвратом
        return schemas.user.UserReadWithGroups.model_validate(updated_user_model)
    except HTTPException: # Пробрасываем HTTPException из DAM (404, 500, 409)
        raise
    except CoreSDKError as e: # Ловим другие ошибки SDK
        logger.error(f"API: SDK error during user-group assignment: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process user-group assignment.")
    except Exception as e:
        logger.exception(f"API: Unexpected error assigning user {user_id} to group {group_id}.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred.")

# Аналогично можно добавить эндпоинт для отвязки пользователя от группы
# @user_factory.router.delete("/{user_id}/revoke_group/{group_id}", ...)