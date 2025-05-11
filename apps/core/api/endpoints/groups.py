# core/app/api/endpoints/groups.py
import logging
from uuid import UUID

from fastapi import (
    Depends,
    HTTPException,
    Body,
)  # APIRouter и Body не нужны здесь напрямую
# sqlalchemy.orm.selectinload не используется

from core_sdk.crud.factory import CRUDRouterFactory
from core_sdk.data_access import (
    DataAccessManagerFactory,
    get_dam_factory,
    BaseDataAccessManager,
)
from core_sdk.dependencies.auth import get_current_user

from ... import schemas  # Нужны схемы для response_model
# UserDataAccessManager не используется напрямую в этом файле

logger = logging.getLogger(__name__)  # Имя будет app.api.endpoints.groups

group_factory = CRUDRouterFactory(
    model_name="Group",
    prefix="/groups",
    tags=["Groups"],  # Добавляем тег
    get_deps=[Depends(get_current_user)],
    list_deps=[Depends(get_current_user)],
    create_deps=[Depends(get_current_user)],
    update_deps=[Depends(get_current_user)],
    delete_deps=[Depends(get_current_user)],
)


@group_factory.router.post(
    "/{group_id}/permissions",
    response_model=schemas.group.GroupRead,  # Возвращаем базовую инфу
    summary="Assign Permission Codename to Group",
    dependencies=[Depends(get_current_user)],
)
async def assign_permission_codename_to_group(
    group_id: UUID,
    permission_codename: str = Body(
        ..., embed=True, description="Коднайм права для добавления."
    ),
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
):
    """Назначает право доступа (по коднайму) группе."""
    logger.info(f"Assigning permission '{permission_codename}' to group {group_id}")
    group_manager: BaseDataAccessManager = dam_factory.get_manager("Group")
    group = await group_manager.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # TODO: Валидация permission_codename (опционально)
    # Можно проверить, что такой коднайм существует в каком-либо Enum из SDK/приложения

    if permission_codename not in group.permissions:
        # Используем update базового менеджера для добавления элемента в массив
        # Это может потребовать кастомной логики в DAM или прямого SQL,
        # так как простой setattr(group, 'permissions', ...) перезапишет массив.
        # Простой, но не атомарный вариант:
        current_perms = list(group.permissions)  # Копируем текущий список
        current_perms.append(permission_codename)
        try:
            # Обновляем поле permissions целиком
            updated_group = await group_manager.update(
                group_id, {"permissions": current_perms}
            )
            logger.info(
                f"Permission '{permission_codename}' assigned to group {group_id}."
            )
            return updated_group
        except Exception:
            logger.exception(
                f"Failed to assign permission '{permission_codename}' to group {group_id}"
            )
            raise HTTPException(status_code=500, detail="Could not assign permission.")
    else:
        logger.info(
            f"Permission '{permission_codename}' already assigned to group {group_id}."
        )
        return group  # Возвращаем без изменений


@group_factory.router.delete(
    "/{group_id}/permissions/{permission_codename}",
    response_model=schemas.group.GroupRead,
    summary="Revoke Permission Codename from Group",
    dependencies=[Depends(get_current_user)],
)
async def revoke_permission_codename_from_group(
    group_id: UUID,
    permission_codename: str,  # Получаем из пути
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
):
    """Отзывает право доступа (по коднайму) у группы."""
    logger.info(f"Revoking permission '{permission_codename}' from group {group_id}")
    group_manager: BaseDataAccessManager = dam_factory.get_manager("Group")
    group = await group_manager.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    if permission_codename in group.permissions:
        current_perms = list(group.permissions)
        current_perms.remove(permission_codename)
        try:
            updated_group = await group_manager.update(
                group_id, {"permissions": current_perms}
            )
            logger.info(
                f"Permission '{permission_codename}' revoked from group {group_id}."
            )
            return updated_group
        except Exception:
            logger.exception(
                f"Failed to revoke permission '{permission_codename}' from group {group_id}"
            )
            raise HTTPException(status_code=500, detail="Could not revoke permission.")
    else:
        logger.info(
            f"Permission '{permission_codename}' was not assigned to group {group_id}."
        )
        return group
