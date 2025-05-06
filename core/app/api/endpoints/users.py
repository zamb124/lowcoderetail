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

from .. import deps # Используем app. для импорта из текущего приложения
from ...models import user as user_model # Импортируем модуль user_model
from ...models import group as group_model # Импортируем модуль group_model
from ...schemas import user as user_schema # Импортируем модуль user_schema
# Локальный CRUD не используется, если все через DAM
# from app import crud

logger = logging.getLogger(__name__) # Имя будет app.api.endpoints.users

user_factory = CRUDRouterFactory(
    model_name='User', # Имя модели, как зарегистрировано в ModelRegistry
    prefix='/users',
    tags=["Users"], # Добавляем тег
    create_deps=[Depends(deps.get_current_active_superuser)],
    # Для update и get проверка прав может быть более сложной (например, пользователь может менять себя)
    # Это можно реализовать в кастомном эндпоинте или через более сложную зависимость.
    # Пока оставляем базовые проверки.
    update_deps=[Depends(deps.get_current_active_user)],
    delete_deps=[Depends(deps.get_current_active_superuser)],
    list_deps=[Depends(deps.get_current_active_superuser)],
    get_deps=[Depends(deps.get_current_active_user)],
)

@user_factory.router.get(
    "/funcs/me",
    response_model=user_schema.UserRead, # Используем схему из модуля
    summary="Get Current User",
    description="Получает информацию о текущем аутентифицированном пользователе.",
    tags=["Users"] # Уточняем тег, если нужно отделить от CRUD
)
async def read_users_me(
        current_user: user_model.User = Depends(deps.get_current_active_user),
):
    """
    Возвращает данные текущего активного пользователя.
    """
    logger.info(f"Request for current user data by user ID: {current_user.id}")
    return current_user

@user_factory.router.post(
    "/{user_id}/assign_group/{group_id}",
    response_model=user_schema.UserReadWithGroups, # Возвращаем пользователя с группами
    summary="Assign User to Group",
    description="Назначает указанного пользователя в указанную группу.",
    tags=["Users", "Groups"],
    dependencies=[Depends(deps.get_current_active_superuser)] # Только суперюзер может назначать группы
)
async def assign_user_to_group(
        user_id: UUID,
        group_id: UUID,
        dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
        # db_session: AsyncSession = Depends(get_current_session) # Сессия получается через DAM
):
    """
    Назначает пользователя в группу.
    Эта операция требует прямого взаимодействия с сессией для управления связями many-to-many.
    """
    logger.info(f"Attempting to assign user {user_id} to group {group_id}.")
    try:
        user_manager = dam_factory.get_manager("User")
        group_manager = dam_factory.get_manager("Group")
    except CoreSDKError as e:
        logger.critical(f"Failed to get DAM for user/group assignment: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service unavailable.")

    user: Optional[user_model.User] = await user_manager.get(user_id)
    if not user:
        logger.warning(f"User {user_id} not found for group assignment.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    group: Optional[group_model.Group] = await group_manager.get(group_id)
    if not group:
        logger.warning(f"Group {group_id} not found for assigning user {user_id}.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    # Проверка, что у пользователя есть атрибут groups и он является списком
    if not hasattr(user, 'groups') or not isinstance(user.groups, list):
        logger.error(f"User model {type(user)} for ID {user_id} does not have a valid 'groups' list attribute. Refreshing relations.")
        try:
            await user_manager.session.refresh(user, attribute_names=['groups'])
            if not hasattr(user, 'groups') or not isinstance(user.groups, list):
                raise AttributeError("Groups attribute still invalid after refresh.")
        except Exception as e_refresh:
            logger.exception(f"Failed to refresh groups for user {user_id} during assignment.")
            raise HTTPException(status_code=500, detail="Could not process user groups.")

    if group not in user.groups: # Сравнение объектов моделей
        user.groups.append(group)
        user_manager.session.add(user) # Добавляем пользователя в сессию для сохранения связи
        try:
            await user_manager.session.commit()
            await user_manager.session.refresh(user, attribute_names=['groups']) # Обновляем пользователя с его группами
            logger.info(f"User {user.id} ('{user.email}') assigned to group {group.id} ('{group.name}').")
        except Exception as e:
            await user_manager.session.rollback()
            logger.exception(f"Error committing user-group assignment for user {user.id}.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not assign user to group due to a database error.")
    else:
        logger.info(f"User {user.id} ('{user.email}') already in group {group.id} ('{group.name}'). No action taken.")

    # Возвращаем пользователя с обновленным списком групп
    return user_schema.UserReadWithGroups.model_validate(user)

# Аналогично можно добавить эндпоинт для отвязки пользователя от группы
# @user_factory.router.delete("/{user_id}/revoke_group/{group_id}", ...)