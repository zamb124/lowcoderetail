# core/app/permissions_init.py
import logging

from fastapi import HTTPException, status # Добавляем status

# --- SDK Imports ---
from core_sdk.constants.permissions import get_all_base_permissions
from core_sdk.registry import ModelRegistry
from core_sdk.exceptions import CoreSDKError # Используем CoreSDKError для ошибок DAM/Registry
from core_sdk.data_access import DataAccessManagerFactory, BaseDataAccessManager

# --- Локальные импорты ---
# Модели и схемы Permission здесь не нужны, т.к. работаем через DAM
# AsyncSession и async_sessionmaker не нужны, т.к. сессия управляется через managed_session/DAM

logger = logging.getLogger("app.permissions_init") # Логгер для этого модуля

async def ensure_base_permissions():
    """
    Проверяет наличие базовых прав доступа в базе данных и создает недостающие.
    Использует DataAccessManager для взаимодействия с БД.
    Предполагается, что эта функция вызывается внутри контекста `managed_session`.
    """
    logger.info("Ensuring base permissions exist...")

    try:
        # Создаем фабрику DAM. Сессия будет получена менеджером через get_current_session().
        dam_factory = DataAccessManagerFactory(registry=ModelRegistry)
        # Получаем менеджер для Permission
        permission_manager: BaseDataAccessManager = dam_factory.get_manager("Permission")
    except CoreSDKError as e:
        logger.critical(f"Failed to get Permission manager: {e}", exc_info=True)
        # Если менеджер не получить, инициализация прав невозможна
        raise RuntimeError("Cannot initialize permissions: failed to get Permission manager.") from e

    try:
        base_permissions_data = get_all_base_permissions()
        if not base_permissions_data:
            logger.warning("No base permissions defined in core_sdk.constants.permissions.get_all_base_permissions().")
            return

        created_count = 0
        checked_count = 0
        skipped_count = 0
        error_count = 0

        logger.info(f"Checking/creating {len(base_permissions_data)} base permissions...")
        for codename, name in base_permissions_data:
            checked_count += 1
            try:
                # Ищем право по codename через менеджер
                # Метод list менеджера возвращает словарь с ключом 'items'
                existing_result = await permission_manager.list(filters={"codename": codename}, limit=1)
                existing_items = existing_result.get("items", [])

                if not existing_items:
                    logger.info(f"  Permission '{codename}' not found, attempting to create...")
                    perm_data = {
                        "codename": codename,
                        "name": name,
                        "description": f"Allows to {name.lower()}" # Генерируем простое описание
                        # company_id не указываем, чтобы создать глобальное право (если модель позволяет)
                    }
                    # Вызываем create менеджера
                    await permission_manager.create(perm_data)
                    logger.info(f"    Successfully created permission: {codename}")
                    created_count += 1
                else:
                    logger.debug(f"  Permission '{codename}' already exists. Skipping.")
                    skipped_count += 1
            except HTTPException as e:
                 # Ловим HTTP ошибки, которые может выбросить DAM (например, 409 Conflict)
                 if e.status_code == status.HTTP_409_CONFLICT:
                     logger.warning(f"    Permission '{codename}' likely already exists (Conflict/409 from DAM). Skipping.")
                     skipped_count += 1
                 else:
                     logger.error(f"    HTTP ERROR creating/checking permission '{codename}': Status={e.status_code}, Detail={e.detail}")
                     error_count += 1
            except CoreSDKError as e: # Ловим другие ошибки SDK/DAM
                 logger.error(f"    SDK ERROR checking/processing permission '{codename}': {e}", exc_info=True)
                 error_count += 1
            except Exception as e:
                 # Ловим непредвиденные ошибки
                 logger.exception(f"  UNEXPECTED ERROR checking/processing permission '{codename}'.")
                 error_count += 1

        # Итоговая статистика
        log_message = (
            f"Finished ensuring base permissions. "
            f"Checked: {checked_count}, Created: {created_count}, "
            f"Skipped (already exist): {skipped_count}, Errors: {error_count}"
        )
        if error_count > 0:
            logger.error(log_message)
            # Решите, должна ли ошибка при создании прав останавливать приложение
            # raise RuntimeError(f"Failed to ensure all base permissions ({error_count} errors).")
        elif created_count == 0 and skipped_count == checked_count and checked_count > 0:
             logger.info("All base permissions already existed.")
        else:
             logger.info(log_message)

    except Exception as e:
         # Ошибка на уровне получения данных или цикла
         logger.critical("Critical error during base permissions processing loop.", exc_info=True)
         raise RuntimeError("Failed to process base permissions.") from e