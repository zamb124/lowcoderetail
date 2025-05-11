# core/app/data_access/user_manager.py
import logging
from typing import Optional, Any, Dict
from uuid import UUID
import datetime  # Нужен для datetime.now()

from fastapi import HTTPException, status  # Добавляем status
from sqlalchemy.exc import IntegrityError

# Импортируем базовый менеджер и нужные типы из SDK
from core_sdk.data_access.base_manager import BaseDataAccessManager
from core_sdk.security import get_password_hash, verify_password
from core_sdk.exceptions import CoreSDKError  # Для обработки ошибок базового менеджера

# Локальные импорты приложения
from .. import models  # Нужны модели для type hinting и операций
from .. import schemas  # Нужны схемы для type hinting

# AsyncSession не используется напрямую

logger = logging.getLogger(__name__)  # Имя будет app.data_access.user_manager


class UserDataAccessManager(
    BaseDataAccessManager[
        models.user.User, schemas.user.UserCreate, schemas.user.UserUpdate
    ]
):
    """
    Менеджер доступа к данным (DAM) для модели User.
    Обрабатывает хеширование паролей при создании и обновлении,
    предоставляет метод аутентификации и другие специфичные для пользователя операции.
    """

    # Явно определяем модель и схемы для ясности и проверки типов
    model = models.user.User
    create_schema = schemas.user.UserCreate
    update_schema = schemas.user.UserUpdate

    # --- Переопределение хуков базового менеджера ---

    async def _prepare_for_create(
        self, validated_data: schemas.user.UserCreate
    ) -> models.user.User:
        """
        Хеширует пароль перед созданием экземпляра модели User.
        Переопределяет метод базового класса.

        :param validated_data: Валидированные данные из схемы UserCreate.
        :return: Экземпляр модели User, готовый к добавлению в сессию.
        :raises HTTPException(422): Если пароль отсутствует в validated_data.
        """
        logger.debug(
            f"UserDataAccessManager: Preparing user for creation with email {validated_data.email}."
        )
        if not validated_data.password:
            logger.error(
                "Password is required for user creation, but was not provided."
            )
            # Это ошибка валидации входных данных
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Password is required for user creation.",
            )

        try:
            hashed_password = get_password_hash(validated_data.password)
            logger.debug(
                f"Password hashed successfully for user {validated_data.email}."
            )
        except RuntimeError as e:  # Ловим ошибку хеширования из SDK
            logger.exception(
                f"Failed to hash password for user {validated_data.email}."
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to process password.",
            ) from e

        # Создаем словарь данных для модели User, исключая поле 'password' из схемы Create
        user_data_dict = validated_data.model_dump(exclude={"password"})
        # Создаем экземпляр модели User, добавляя хешированный пароль
        # Ошибки валидации модели (если есть) будут обработаны здесь
        try:
            db_user = self.model(**user_data_dict, hashed_password=hashed_password)
            logger.debug(f"User model instance created for {validated_data.email}.")
            return db_user
        except Exception as e:  # Ловим возможные ошибки инициализации модели
            logger.exception(
                f"Failed to create User model instance for email {validated_data.email}."
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error preparing user data: {e}",
            )

    async def _prepare_for_update(
        self,
        db_item: models.user.User,
        update_payload: Dict[str, Any],  # Словарь с полями для обновления
    ) -> tuple[models.user.User, bool]:
        """
        Хеширует пароль, если он включен в данные для обновления (`update_payload`).
        Применяет остальные обновления с помощью метода базового класса.
        Переопределяет метод базового класса.

        :param db_item: Существующий объект пользователя из БД.
        :param update_payload: Словарь с данными для обновления (уже провалидированный по UpdateSchema, если она есть).
        :return: Кортеж (обновленный объект User, флаг updated=True/False).
        :raises HTTPException(500): Если произошла ошибка при хешировании нового пароля.
        """
        logger.debug(
            f"UserDataAccessManager: Preparing update for user {db_item.email} (ID: {db_item.id})."
        )

        new_password = update_payload.pop(
            "password", None
        )  # Извлекаем пароль, если он есть

        # Вызываем базовый метод _prepare_for_update для применения остальных полей
        # Он вернет обновленный объект и флаг, были ли изменения *до* обработки пароля
        db_item, updated = await super()._prepare_for_update(db_item, update_payload)

        if new_password:
            logger.info(
                f"UserDataAccessManager: New password provided for user {db_item.email}. Hashing and updating."
            )
            try:
                db_item.hashed_password = get_password_hash(new_password)
                updated = True  # Считаем изменением, даже если другие поля не менялись
                logger.debug(f"Password updated successfully for user {db_item.email}.")
            except RuntimeError as e:
                logger.exception(
                    f"Failed to hash new password during update for user {db_item.email}."
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to process new password during update.",
                ) from e
        else:
            logger.debug(
                f"No new password provided for user {db_item.email}. Skipping password update."
            )

        # Базовый метод _prepare_for_update уже обновит updated_at, если updated=True
        return db_item, updated

    # --- Кастомные методы, специфичные для User ---

    async def get_by_email(self, email: str) -> Optional[models.user.User]:
        """
        Находит пользователя по его email адресу (регистронезависимый поиск).

        :param email: Email адрес для поиска.
        :return: Объект User или None, если пользователь не найден.
        """
        logger.info(f"UserDataAccessManager: Getting user by email '{email}'.")
        # Приводим email к нижнему регистру для регистронезависимого поиска
        email_lower = email.lower()
        try:
            # Используем базовый метод list с фильтром
            # Важно: Фильтр 'email' должен быть регистронезависимым на уровне БД или модели фильтра
            # Если используется стандартный DefaultFilter, он может быть регистрозависимым.
            # Для надежности лучше использовать ilike или func.lower.
            # Пример с func.lower (требует импорта func из sqlalchemy):
            # from sqlalchemy import func
            # results_dict = await self.list(filters={"func.lower(models.user.User.email)": email_lower}, limit=1)
            # Пока используем простой фильтр, предполагая, что email уникален и хранится в одном регистре,
            # или что сравнение в БД настроено как case-insensitive.
            results_dict = await self.list(
                filters={"email": email_lower}, limit=1
            )  # Используем email_lower
            items = results_dict.get("items", [])
            if items:
                logger.debug(f"User with email '{email}' found with ID: {items[0].id}")
                return items[0]
            else:
                logger.debug(f"User with email '{email}' not found.")
                return None
        except Exception:
            logger.exception(
                f"UserDataAccessManager: Error fetching user by email '{email}'."
            )
            return None

    async def authenticate(
        self, email: str, password: str
    ) -> Optional[models.user.User]:
        """
        Аутентифицирует пользователя по email и паролю.

        :param email: Email пользователя.
        :param password: Пароль пользователя в открытом виде.
        :return: Объект User, если аутентификация прошла успешно, иначе None.
        """
        logger.info(f"UserDataAccessManager: Authenticating user {email}.")
        user = await self.get_by_email(
            email
        )  # get_by_email уже логирует результат поиска

        if not user:
            # Сообщение об ошибке уже залогировано в get_by_email
            return None

        if not verify_password(password, user.hashed_password):
            logger.warning(
                f"Authentication failed: Incorrect password for user {email}."
            )
            return None

        # Проверка is_active не выполняется здесь, это ответственность вызывающего кода (например, эндпоинта /login)
        logger.info(f"Authentication successful for user {email} (ID: {user.id}).")
        return user

    async def update_last_login(self, user: models.user.User) -> None:
        """
        Обновляет время последнего входа для пользователя.
        Пример кастомного метода, не входящего в стандартный CRUD.

        :param user: Объект пользователя, для которого нужно обновить время входа.
        """
        # Этот метод предполагает, что у модели User есть поле `last_login: Optional[datetime]`
        if hasattr(user, "last_login"):
            logger.debug(f"Updating last_login for user {user.email} (ID: {user.id}).")
            # Используем UTC время
            user.last_login = datetime.datetime.now(datetime.timezone.utc)  # type: ignore
            self.session.add(user)  # Добавляем в сессию для сохранения
            try:
                await self.session.commit()
                # Обновляем только измененное поле, чтобы не перезаписывать другие возможные изменения
                await self.session.refresh(user, attribute_names=["last_login"])
                logger.info(f"Successfully updated last_login for user {user.email}.")
            except Exception:
                # Откат произойдет в managed_session
                logger.exception(
                    f"Error committing last_login update for user {user.email}."
                )
                # Можно перевыбросить ошибку, если это критично
                # raise CoreSDKError("Failed to update last login time") from e
        else:
            logger.warning(
                f"User model does not have 'last_login' attribute. Cannot update last login time for user {user.email}."
            )

    async def assign_to_group(self, user_id: UUID, group_id: UUID) -> models.user.User:
        """
        Назначает пользователя указанной группе.

        :param user_id: ID пользователя.
        :param group_id: ID группы.
        :return: Обновленный объект User с загруженными группами.
        :raises HTTPException(404): Если пользователь или группа не найдены.
        :raises HTTPException(500): При ошибках базы данных.
        """
        logger.info(
            f"UserDataAccessManager: Assigning user {user_id} to group {group_id}."
        )

        user = await self.get(
            user_id
        )  # Используем self.get() для получения пользователя
        if not user:
            logger.warning(f"User {user_id} not found for group assignment.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        try:
            group = await self.session.get(models.group.Group, group_id)
        except Exception:
            logger.exception(f"Error fetching group {group_id} during user assignment.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not retrieve group information.",
            )

        if not group:
            logger.warning(f"Group {group_id} not found for assigning user {user_id}.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
            )

        # Загрузка или проверка атрибута 'groups'
        # SQLAlchemy обычно лениво загружает связи, но для проверки 'in' лучше убедиться, что они загружены.
        # Если связь уже загружена (например, eager loading), refresh не обязателен.
        if not self.session.is_active:  # Проверка на случай, если сессия была закрыта
            logger.error("Session is not active before refreshing user groups.")
            raise CoreSDKError("Database session is not active.")

        try:
            # Проверяем, загружена ли уже коллекция. Если нет, SQLAlchemy попытается загрузить ее при доступе.
            # Явный refresh может быть избыточен, если нет специфичных требований к свежести данных.
            # await self.session.refresh(user, attribute_names=['groups'])
            pass  # SQLAlchemy должен сам загрузить user.groups при первом доступе
        except Exception:
            logger.exception(
                f"Failed to ensure user.groups collection is loaded for user {user_id}."
            )
            raise HTTPException(
                status_code=500, detail="Could not process user groups."
            )

        if group not in user.groups:
            user.groups.append(group)
            self.session.add(
                user
            )  # Добавляем пользователя в сессию для сохранения связи
            try:
                await self.session.commit()
                # После коммита обновляем пользователя, чтобы связи корректно отобразились
                await self.session.refresh(user, attribute_names=["groups"])
                logger.info(
                    f"User {user.id} ('{user.email}') successfully assigned to group {group.id} ('{group.name}')."
                )
            except IntegrityError:  # Ловим специфичные ошибки БД
                await self.session.rollback()
                logger.error(
                    f"Database integrity error assigning user {user.id} to group {group.id}.",
                    exc_info=True,
                )
                # Можно проанализировать e.orig для более детальной ошибки
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Failed to assign user to group due to a data conflict.",
                )
            except Exception:
                await self.session.rollback()
                logger.exception(
                    f"Error committing user-group assignment for user {user.id}."
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Could not assign user to group due to a database error.",
                )
        else:
            logger.info(
                f"User {user.id} ('{user.email}') already in group {group.id} ('{group.name}'). No action taken."
            )

        return user
