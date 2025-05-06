# core/app/api/endpoints/permissions.py
import logging # Добавляем logging
from fastapi import Depends # APIRouter, List, UUID не используются напрямую

from core_sdk.crud.factory import CRUDRouterFactory
# DataAccessManagerFactory, get_dam_factory, BaseDataAccessManager не используются напрямую
# если нет кастомных эндпоинтов для permissions.

from .. import deps # Используем app. для импорта из текущего приложения
# models, schemas не используются напрямую, если все через фабрику

logger = logging.getLogger(__name__) # Имя будет app.api.endpoints.permissions

# Права доступа обычно только читаются списком или по ID.
# Создание/изменение/удаление прав часто не доступны через общедоступное API,
# а управляются через миграции, административные интерфейсы или внутренние скрипты.
permission_factory = CRUDRouterFactory(
    model_name="Permission",
    prefix="/permissions",
    tags=["Permissions"], # Добавляем тег
    # Защищаем операции чтения (например, только суперюзер)
    get_deps=[Depends(deps.get_current_active_superuser)],
    list_deps=[Depends(deps.get_current_active_superuser)],
    # Явно отключаем CUD операции, если они не должны быть доступны через API
    create_deps=None, # Отключает POST /permissions/
    update_deps=None, # Отключает PUT /permissions/{id}
    delete_deps=None, # Отключает DELETE /permissions/{id}
)

logger.info(f"Permissions CRUD routes configured for model 'Permission' with read-only access for superusers.")
# Если CUD операции нужны, раскомментируйте и настройте зависимости:
# create_deps=[Depends(deps.get_current_active_superuser)],
# update_deps=[Depends(deps.get_current_active_superuser)],
# delete_deps=[Depends(deps.get_current_active_superuser)],