# core/app/data_access/user_manager.py
import logging
from typing import Optional, Any, Dict
from uuid import UUID
import datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

# --- ИЗМЕНЕНИЕ ИМПОРТА ---
from core_sdk.data_access.local_manager import LocalDataAccessManager # Наследуемся от Local
# --------------------------
from core_sdk.security import get_password_hash, verify_password
from core_sdk.exceptions import CoreSDKError

from .. import models
from .. import schemas

logger = logging.getLogger("app.data_access.user_manager") # Изменил имя логгера

class UserDataAccessManager(
    LocalDataAccessManager[ # Используем LocalDataAccessManager в Generic
        schemas.user.UserRead, # ModelType_co - это ReadSchema
        schemas.user.UserCreate,
        schemas.user.UserUpdate
    ]
):
    # db_model_cls и read_schema_cls будут установлены фабрикой на основе ModelRegistry
    # или можно их явно определить здесь, если менеджер не будет регистрироваться через ModelRegistry

    # --- Переопределение хуков (если они были для BaseDataAccessManager, теперь для LocalDataAccessManager) ---
    async def _prepare_for_create(
        self, validated_data: schemas.user.UserCreate
    ) -> models.user.User: # Возвращает SQLModel объект для сохранения в БД
        logger.debug(f"UserDataAccessManager: Preparing user for creation with email {validated_data.email}.")
        if not validated_data.password:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Password is required for user creation.")
        try:
            hashed_password = get_password_hash(validated_data.password)
        except RuntimeError as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process password.") from e

        user_data_dict = validated_data.model_dump(exclude={"password"})
        try:
            # self.db_model_cls здесь должен быть models.user.User
            db_user = self.db_model_cls(**user_data_dict, hashed_password=hashed_password) # type: ignore
            return db_user # type: ignore
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error preparing user data: {e}")

    async def _prepare_for_update(
        self, db_item: models.user.User, update_payload: Dict[str, Any] # Принимает SQLModel
    ) -> tuple[models.user.User, bool]: # Возвращает SQLModel
        logger.debug(f"UserDataAccessManager: Preparing update for user {db_item.email} (ID: {db_item.id}).")
        new_password = update_payload.pop("password", None)
        # Вызываем super()._prepare_for_update() от LocalDataAccessManager
        db_item_prepared, updated = await super()._prepare_for_update(db_item, update_payload)

        if new_password:
            logger.info(f"UserDataAccessManager: New password provided for user {db_item_prepared.email}. Hashing and updating.")
            try:
                db_item_prepared.hashed_password = get_password_hash(new_password)
                updated = True
            except RuntimeError as e:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process new password during update.") from e
        return db_item_prepared, updated

    # --- Кастомные методы (остаются без изменений в логике, но типизация self.get и т.д. теперь от LocalManager) ---
    async def get_by_email(self, email: str) -> Optional[schemas.user.UserRead]: # Возвращает ReadSchema
        logger.info(f"UserDataAccessManager: Getting user by email '{email}'.")
        email_lower = email.lower()
        try:
            # self.list вернет Dict[str, Any] с items: List[schemas.user.UserRead]
            results_dict = await self.list(filters={"email": email_lower}, limit=1)
            items = results_dict.get("items", [])
            if items: return items[0]
            return None
        except Exception:
            logger.exception(f"UserDataAccessManager: Error fetching user by email '{email}'.")
            return None

    async def authenticate(self, email: str, password: str) -> Optional[models.user.User]: # Возвращает SQLModel для проверки пароля
        logger.info(f"UserDataAccessManager: Authenticating user {email}.")
        # Для authenticate нам нужен объект из БД, чтобы получить hashed_password
        # Поэтому используем self.session.execute напрямую или создаем метод _get_db_item_by_email
        stmt = sqlmodel_select(self.db_model_cls).where(func.lower(self.db_model_cls.email) == email.lower()) # type: ignore
        db_user = (await self.session.execute(stmt)).scalar_one_or_none()

        if not db_user: return None
        if not verify_password(password, db_user.hashed_password): return None
        return db_user # Возвращаем объект БД

    async def update_last_login(self, user: models.user.User) -> None:
        # ... (без изменений) ...
        if hasattr(user, "last_login"):
            user.last_login = datetime.datetime.now(datetime.timezone.utc) # type: ignore
            self.session.add(user)
            try:
                await self.session.commit()
                await self.session.refresh(user, attribute_names=["last_login"])
            except Exception:
                logger.exception(f"Error committing last_login update for user {user.email}.")
        else:
            logger.warning(f"User model does not have 'last_login' attribute.")


    async def assign_to_group(self, user_id: UUID, group_id: UUID) -> schemas.user.UserRead: # Возвращает ReadSchema
        logger.info(f"UserDataAccessManager: Assigning user {user_id} to group {group_id}.")
        # Получаем пользователя из БД
        user_db_item = await self.session.get(self.db_model_cls, user_id)
        if not user_db_item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        group_db_item = await self.session.get(models.group.Group, group_id)
        if not group_db_item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

        # SQLAlchemy должна сама загрузить user_db_item.groups при первом доступе
        if group_db_item not in user_db_item.groups: # type: ignore
            user_db_item.groups.append(group_db_item) # type: ignore
            self.session.add(user_db_item)
            try:
                await self.session.commit()
                await self.session.refresh(user_db_item, attribute_names=["groups"]) # Обновляем SQLModel объект
            except IntegrityError:
                await self.session.rollback()
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Failed to assign user to group due to a data conflict.")
            except Exception:
                await self.session.rollback()
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not assign user to group due to a database error.")
        # Возвращаем UserRead схему
        return schemas.user.UserRead.model_validate(user_db_item)