# apps/core/data_access/user_manager.py
import logging
from typing import Optional, Any, Dict
from uuid import UUID
import datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select as sqlmodel_select, func, SQLModel # SQLModel для DM_SQLModelType

from core_sdk.data_access.local_manager import LocalDataAccessManager, DM_SQLModelType # Используем DM_SQLModelType
from core_sdk.security import get_password_hash, verify_password
from core_sdk.exceptions import CoreSDKError

from apps.core import models as core_models
from apps.core import schemas as core_schemas

logger = logging.getLogger("app.data_access.user_manager")

# UserDataAccessManager работает с core_models.user.User как с основным типом (DM_SQLModelType)
# и использует core_schemas.user.UserRead как схему для чтения (DM_ReadSchemaType)
class UserDataAccessManager(
    LocalDataAccessManager[
        core_models.user.User, # DM_SQLModelType
        core_schemas.user.UserCreate,
        core_schemas.user.UserUpdate,
        core_schemas.user.UserRead # DM_ReadSchemaType
    ]
):
    # model_cls, create_schema_cls, update_schema_cls, read_schema_cls
    # будут установлены в super().__init__ на основе того, что передано
    # из ModelRegistry через DataAccessManagerFactory.
    # Явное определение здесь не обязательно, если регистрация в ModelRegistry верна.

    async def _prepare_for_create(
            self, validated_data: core_schemas.user.UserCreate
    ) -> core_models.user.User: # Возвращает SQLModel (core_models.user.User)
        logger.debug(f"UserDataAccessManager: Preparing user for creation with email {validated_data.email}.")
        if not validated_data.password:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Password is required for user creation.")
        try:
            hashed_password = get_password_hash(validated_data.password)
        except RuntimeError as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process password.") from e

        user_data_dict = validated_data.model_dump(exclude={"password"})
        try:
            # self.model_cls здесь это core_models.user.User (DM_SQLModelType)
            db_user = self.model_cls(**user_data_dict, hashed_password=hashed_password)
            return db_user
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error preparing user data: {e}")

    async def _prepare_for_update(
            self, db_item: core_models.user.User, update_payload: Dict[str, Any]
    ) -> tuple[core_models.user.User, bool]:
        logger.debug(f"UserDataAccessManager: Preparing update for user {db_item.email} (ID: {db_item.id}).")
        new_password = update_payload.pop("password", None)

        db_item_prepared, updated = await super()._prepare_for_update(db_item, update_payload)

        if new_password:
            logger.info(f"UserDataAccessManager: New password provided for user {db_item_prepared.email}. Hashing and updating.")
            try:
                db_item_prepared.hashed_password = get_password_hash(new_password) # type: ignore
                updated = True
            except RuntimeError as e:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process new password during update.") from e
        return db_item_prepared, updated

    async def get_by_email(self, email: str) -> Optional[core_models.user.User]: # Возвращает SQLModel
        logger.info(f"UserDataAccessManager: Getting user by email '{email}'.")
        email_lower = email.lower()
        try:
            # self.list вернет Dict с items: List[core_models.user.User]
            results_dict = await self.list(filters={"email": email_lower}, limit=1)
            items = results_dict.get("items", [])
            if items: return items[0] # Это уже core_models.user.User
            return None
        except Exception:
            logger.exception(f"UserDataAccessManager: Error fetching user by email '{email}'.")
            return None

    async def authenticate(self, email: str, password: str) -> Optional[core_models.user.User]:
        logger.info(f"UserDataAccessManager: Authenticating user {email}.")
        # self.model_cls здесь это core_models.user.User
        stmt = sqlmodel_select(self.model_cls).where(func.lower(self.model_cls.email) == email.lower()) # type: ignore
        db_user = (await self.session.execute(stmt)).scalar_one_or_none()

        if not db_user: return None
        if not verify_password(password, db_user.hashed_password): return None # type: ignore
        return db_user

    async def update_last_login(self, user: core_models.user.User) -> None:
        # ... (без изменений) ...
        if hasattr(user, "last_login"):
            user.last_login = datetime.datetime.now(datetime.timezone.utc) # type: ignore
            self.session.add(user)
            try:
                await self.session.commit()
                await self.session.refresh(user, attribute_names=["last_login"])
            except Exception: logger.exception(f"Error committing last_login update for user {user.email}.")
        else: logger.warning(f"User model does not have 'last_login' attribute.")

    async def assign_to_group(self, user_id: UUID, group_id: UUID) -> core_models.user.User: # Возвращает SQLModel
        logger.info(f"UserDataAccessManager: Assigning user {user_id} to group {group_id}.")

        user_db_item = await self.session.get(self.model_cls, user_id) # self.model_cls это core_models.user.User
        if not user_db_item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        group_db_item = await self.session.get(core_models.group.Group, group_id)
        if not group_db_item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

        if group_db_item not in user_db_item.groups: # type: ignore
            user_db_item.groups.append(group_db_item) # type: ignore
            self.session.add(user_db_item)
            try:
                await self.session.commit()
                await self.session.refresh(user_db_item, attribute_names=["groups"])
            except IntegrityError:
                await self.session.rollback()
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Failed to assign user to group due to a data conflict.")
            except Exception:
                await self.session.rollback()
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not assign user to group due to a database error.")

        return user_db_item # Возвращаем SQLModel объект