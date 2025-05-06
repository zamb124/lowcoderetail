# core/app/api/endpoints/groups.py
import logging
from typing import List # Optional не используется напрямую
from uuid import UUID

from fastapi import Depends, HTTPException, status # APIRouter и Body не нужны здесь напрямую
# sqlalchemy.orm.selectinload не используется

from core_sdk.crud.factory import CRUDRouterFactory
from core_sdk.data_access import DataAccessManagerFactory, get_dam_factory, BaseDataAccessManager
from core_sdk.exceptions import CoreSDKError # Для обработки ошибок DAM

from .. import deps # Используем app. для импорта из текущего приложения
from ... import models # Нужны модели для проверки связей
from ... import schemas # Нужны схемы для response_model
# UserDataAccessManager не используется напрямую в этом файле

logger = logging.getLogger(__name__) # Имя будет app.api.endpoints.groups

group_factory = CRUDRouterFactory(
    model_name="Group",
    prefix='/groups',
    tags=["Groups"], # Добавляем тег
    get_deps=[Depends(deps.get_current_active_superuser)],
    list_deps=[Depends(deps.get_current_active_superuser)],
    create_deps=[Depends(deps.get_current_active_superuser)],
    update_deps=[Depends(deps.get_current_active_superuser)],
    delete_deps=[Depends(deps.get_current_active_superuser)],
)

@group_factory.router.get(
    "/{group_id}/details",
    response_model=schemas.group.GroupReadWithDetails,
    summary="Get Group Details",
    description="Получает детальную информацию о группе, включая список связанных пользователей и прав доступа.",
    dependencies=[Depends(deps.get_current_active_superuser)]
)
async def read_group_details(
        group_id: UUID,
        dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
):
    logger.info(f"Fetching details for group ID: {group_id}")
    try:
        group_manager: BaseDataAccessManager = dam_factory.get_manager("Group")
    except CoreSDKError as e:
        logger.critical(f"Failed to get Group DAM for details: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service unavailable.")

    group = await group_manager.get(group_id)
    if not group:
        logger.warning(f"Group with ID {group_id} not found for details.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    try:
        if hasattr(group_manager, 'session') and group_manager.session:
            logger.debug(f"Loading relations 'users' and 'permissions' for group {group_id} via session refresh.")
            # Явно загружаем связи. SQLModel должен автоматически обработать их при сериализации.
            await group_manager.session.refresh(group, attribute_names=['users', 'permissions'])
            logger.debug(f"Relations loaded for group {group_id}.")
            return group # Pydantic/FastAPI преобразует в GroupReadWithDetails
        else:
            logger.warning(f"Cannot load relations for group {group_id}: session not available in manager. Returning group without details.")
            # Возвращаем базовые данные, списки users/permissions будут пустыми по умолчанию в схеме
            return schemas.group.GroupReadWithDetails.model_validate(group) # Явное преобразование
    except Exception as e:
        logger.exception(f"Error refreshing group relations for group {group_id}.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error loading group details")

@group_factory.router.post(
    "/{group_id}/assign_permission/{permission_id}",
    response_model=schemas.group.GroupRead,
    summary="Assign Permission to Group",
    description="Назначает указанное право доступа (permission) указанной группе.",
    tags=["Groups", "Permissions"], # Уточняем теги
    dependencies=[Depends(deps.get_current_active_superuser)]
)
async def assign_permission_to_group(
        group_id: UUID,
        permission_id: UUID,
        dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
):
    logger.info(f"Attempting to assign permission {permission_id} to group {group_id}.")
    try:
        group_manager: BaseDataAccessManager = dam_factory.get_manager("Group")
        permission_manager: BaseDataAccessManager = dam_factory.get_manager("Permission")
    except CoreSDKError as e:
        logger.critical(f"Failed to get DAM for group/permission assignment: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service unavailable.")

    group = await group_manager.get(group_id)
    if not group:
        logger.warning(f"Group {group_id} not found for permission assignment.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    permission = await permission_manager.get(permission_id)
    if not permission:
        logger.warning(f"Permission {permission_id} not found for assignment to group {group_id}.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")

    # Проверяем, что у группы есть атрибут permissions и он является списком
    if not hasattr(group, 'permissions') or not isinstance(group.permissions, list):
        logger.error(f"Group model {type(group)} for ID {group_id} does not have a valid 'permissions' list attribute. Refreshing relations.")
        # Попытка загрузить связи, если они не были загружены
        try:
            await group_manager.session.refresh(group, attribute_names=['permissions'])
            if not hasattr(group, 'permissions') or not isinstance(group.permissions, list):
                raise AttributeError("Permissions attribute still invalid after refresh.")
        except Exception as e_refresh:
            logger.exception(f"Failed to refresh permissions for group {group_id} during assignment.")
            raise HTTPException(status_code=500, detail="Could not process group permissions.")


    if permission not in group.permissions: # Сравнение объектов моделей
        group.permissions.append(permission)
        group_manager.session.add(group) # Добавляем группу в сессию для сохранения связи
        try:
            await group_manager.session.commit()
            await group_manager.session.refresh(group) # Обновляем группу, чтобы получить актуальное состояние
            logger.info(f"Permission {permission.id} ('{permission.codename}') assigned to group {group.id} ('{group.name}').")
        except Exception as e:
            await group_manager.session.rollback()
            logger.exception(f"Error committing permission assignment for group {group.id}.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not assign permission due to a database error.")
    else:
        logger.info(f"Permission {permission.id} ('{permission.codename}') already assigned to group {group.id} ('{group.name}'). No action taken.")
    return group

@group_factory.router.delete(
    "/{group_id}/revoke_permission/{permission_id}",
    response_model=schemas.group.GroupRead,
    summary="Revoke Permission from Group",
    description="Отзывает указанное право доступа (permission) у указанной группы.",
    tags=["Groups", "Permissions"],
    dependencies=[Depends(deps.get_current_active_superuser)]
)
async def revoke_permission_from_group(
        group_id: UUID,
        permission_id: UUID,
        dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
):
    logger.info(f"Attempting to revoke permission {permission_id} from group {group_id}.")
    try:
        group_manager: BaseDataAccessManager = dam_factory.get_manager("Group")
        permission_manager: BaseDataAccessManager = dam_factory.get_manager("Permission")
    except CoreSDKError as e:
        logger.critical(f"Failed to get DAM for group/permission revocation: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service unavailable.")

    group = await group_manager.get(group_id)
    if not group:
        logger.warning(f"Group {group_id} not found for permission revocation.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    # Загружаем права, если они еще не загружены или не являются списком
    if not hasattr(group, 'permissions') or not isinstance(group.permissions, list):
        logger.debug(f"Permissions for group {group_id} not loaded or invalid type. Refreshing.")
        try:
            await group_manager.session.refresh(group, attribute_names=['permissions'])
            if not hasattr(group, 'permissions') or not isinstance(group.permissions, list):
                raise AttributeError("Permissions attribute still invalid after refresh.")
        except Exception as e_refresh:
            logger.exception(f"Failed to refresh permissions for group {group_id} during revocation.")
            raise HTTPException(status_code=500, detail="Could not process group permissions.")

    permission_to_revoke = None
    for p in group.permissions:
        if p.id == permission_id:
            permission_to_revoke = p
            break

    if permission_to_revoke:
        group.permissions.remove(permission_to_revoke)
        group_manager.session.add(group)
        try:
            await group_manager.session.commit()
            await group_manager.session.refresh(group)
            logger.info(f"Permission {permission_id} revoked from group {group.id} ('{group.name}').")
        except Exception as e:
            await group_manager.session.rollback()
            logger.exception(f"Error committing permission revocation for group {group.id}.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not revoke permission due to a database error.")
    else:
        logger.info(f"Permission {permission_id} was not assigned to group {group.id} ('{group.name}'). No action taken.")
    return group