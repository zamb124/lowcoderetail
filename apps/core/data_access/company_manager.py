# core/app/data_access/company_manager.py
import logging
from typing import Optional, List, Any, Dict, Union
from uuid import UUID

from fastapi import HTTPException, status  # Добавляем status для кодов ошибок

# Импортируем базовый менеджер и нужные типы из SDK
from core_sdk.data_access.base_manager import (
    BaseDataAccessManager,
    CreateSchemaType,
    ModelType,
)
from core_sdk.exceptions import CoreSDKError  # Для обработки ошибок базового менеджера

# Локальные импорты приложения
from .. import models  # Нужны модели для type hinting и операций
from .. import schemas  # Нужны схемы для type hinting
from ..schemas.company import CompanyRead  # Конкретная схема для возвращаемого типа

# AsyncSession не используется напрямую
# settings не используется напрямую

logger = logging.getLogger(__name__)  # Имя будет app.data_access.company_manager


class CompanyDataAccessManager(
    BaseDataAccessManager[
        models.company.Company,
        schemas.company.CompanyCreate,
        schemas.company.CompanyUpdate,
    ]
):
    """
    Менеджер доступа к данным (DAM) для модели Company.
    Предоставляет CRUD операции и специфичные для компании методы.
    Наследует базовую CRUD логику от BaseDataAccessManager.
    """

    # Явно определяем модель и схемы для ясности и проверки типов
    model = models.company.Company
    create_schema = schemas.company.CompanyCreate
    update_schema = schemas.company.CompanyUpdate

    # --- Переопределение хуков базового менеджера (Примеры) ---
    # В данном случае стандартное поведение подходит, поэтому методы закомментированы.
    # async def _prepare_for_create(self, validated_data: schemas.company.CompanyCreate) -> models.company.Company:
    #     logger.debug(f"Company DAM: Custom prepare for create for company name: {validated_data.name}")
    #     # Здесь может быть специфичная логика перед созданием компании
    #     db_item = await super()._prepare_for_create(validated_data)
    #     # Например, установка дополнительных полей
    #     return db_item

    # async def _prepare_for_update(self, db_item: models.company.Company, update_payload: Dict[str, Any]) -> tuple[models.company.Company, bool]:
    #     logger.debug(f"Company DAM: Custom prepare for update for company ID: {db_item.id}")
    #     # Здесь может быть специфичная логика перед обновлением компании
    #     db_item, updated = await super()._prepare_for_update(db_item, update_payload)
    #     # ...
    #     return db_item, updated

    # --- Кастомные методы, специфичные для Company ---

    async def get_by_name(self, name: str) -> Optional[models.company.Company]:
        """
        Находит компанию по ее точному имени.

        :param name: Точное имя компании для поиска.
        :return: Объект Company или None, если компания не найдена.
        """
        logger.info(f"Company DAM: Getting company by exact name '{name}'.")
        try:
            # Используем базовый метод list с фильтром по точному совпадению имени
            results_dict = await self.list(filters={"name": name}, limit=1)
            items = results_dict.get("items", [])
            if items:
                logger.debug(f"Company with name '{name}' found with ID: {items[0].id}")
                return items[0]
            else:
                logger.debug(f"Company with name '{name}' not found.")
                return None
        except Exception as e:
            logger.exception(f"Company DAM: Error fetching company by name '{name}'.")
            # Не пробрасываем ошибку дальше, возвращаем None или можно выбросить специфичное исключение
            return None

    async def get_company_users(
        self, company_id: UUID, limit: int = 50, cursor: Optional[int] = None
    ) -> List[models.user.User]:
        """
        Извлекает список пользователей, принадлежащих указанной компании.
        ВНИМАНИЕ: Текущая реализация не завершена и требует доработки.

        :param company_id: ID компании.
        :param limit: Максимальное количество пользователей для возврата.
        :param cursor: Курсор LSN для пагинации.
        :return: Список объектов User.
        :raises NotImplementedError: Указывает, что метод требует дальнейшей реализации.
        """
        logger.info(
            f"Company DAM: Getting users for company {company_id} (Limit: {limit}, Cursor: {cursor})."
        )
        company = await self.get(company_id)
        if not company:
            logger.warning(
                f"Company {company_id} not found when trying to get its users."
            )
            return []  # Возвращаем пустой список, если компания не найдена

        # TODO: Реализовать логику получения пользователей.
        # Варианты:
        # 1. Прямой запрос к БД с использованием self.session и модели User.
        #    Пример: `stmt = select(models.user.User).where(models.user.User.company_id == company_id)...`
        # 2. Использование UserDataAccessManager (потребует его получения через фабрику или инъекцию).
        #    Пример: `user_manager = self.dam_factory.get_manager("User"); await user_manager.list(filters={"company_id": company_id}, ...)`
        # 3. Использование связи `company.users` (если она правильно настроена и загружена).
        #    Пример: `await self.session.refresh(company, attribute_names=['users']); return company.users` (требует осторожности с производительностью).
        logger.error("get_company_users method is not implemented.")
        raise NotImplementedError(
            "Accessing users from Company DAM requires further implementation (direct query or User DAM dependency)"
        )

    async def activate_company(self, company_id: UUID) -> CompanyRead:
        """
        Активирует компанию (устанавливает флаг is_active = True).
        Если компания уже активна, возвращает ее текущее состояние.

        :param company_id: ID компании для активации.
        :return: Схема CompanyRead с обновленными данными компании.
        :raises HTTPException(404): Если компания не найдена.
        :raises HTTPException(500): При ошибке во время обновления.
        """
        logger.info(f"Company DAM: Activating company {company_id}.")
        company = await self.get(company_id)
        if not company:
            logger.warning(f"Company {company_id} not found for activation.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Company {company_id} not found",
            )

        if company.is_active:
            logger.info(
                f"Company DAM: Company {company_id} is already active. No action needed."
            )
            return CompanyRead.model_validate(company)  # Возвращаем текущие данные

        logger.debug(f"Company {company_id} is inactive, attempting to activate.")
        try:
            # Используем базовый метод update для изменения одного поля
            updated_company_model = await self.update(company_id, {"is_active": True})
            logger.info(f"Company {company_id} activated successfully.")
            # Преобразуем результат (модель SQLAlchemy/SQLModel) в схему Pydantic для возврата
            return CompanyRead.model_validate(updated_company_model)
        except HTTPException as e:  # Пробрасываем HTTP ошибки из self.update (например, 404 если гонка состояний)
            logger.error(
                f"Company DAM: HTTP error during activation of company {company_id}: Status={e.status_code}, Detail={e.detail}"
            )
            raise e
        except CoreSDKError as e:  # Ловим ошибки базового менеджера
            logger.exception(
                f"Company DAM: CoreSDKError activating company {company_id}."
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to activate company due to SDK error: {e}",
            )
        except Exception as e:
            logger.exception(
                f"Company DAM: Unexpected error activating company {company_id}."
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to activate company: {e}",
            )

    async def deactivate_company(self, company_id: UUID) -> models.company.Company:
        """
        Деактивирует компанию (устанавливает флаг is_active = False).

        :param company_id: ID компании для деактивации.
        :return: Обновленный объект модели Company.
        :raises HTTPException(404): Если компания не найдена.
        :raises HTTPException(500): При ошибке во время обновления.
        """
        logger.info(f"Company DAM: Deactivating company {company_id}.")
        # Метод update базового класса выбросит 404, если компания не найдена
        try:
            updated_company = await self.update(company_id, {"is_active": False})
            logger.info(f"Company {company_id} deactivated successfully.")
            return updated_company
        except HTTPException as e:
            logger.error(
                f"Company DAM: HTTP error during deactivation of company {company_id}: Status={e.status_code}, Detail={e.detail}"
            )
            raise e
        except CoreSDKError as e:
            logger.exception(
                f"Company DAM: CoreSDKError deactivating company {company_id}."
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to deactivate company due to SDK error: {e}",
            )
        except Exception as e:
            logger.exception(
                f"Company DAM: Unexpected error deactivating company {company_id}."
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to deactivate company: {e}",
            )

    async def create(self, data: Union[CreateSchemaType, Dict[str, Any]]) -> ModelType:
        """
        Создает новую компанию и устанавливает ее company_id равным ее собственному id.
        Переопределяет базовый метод create.

        :param data: Данные для создания компании (схема CompanyCreate или словарь).
        :return: Созданный объект модели Company.
        :raises HTTPException: При ошибках валидации, конфликтах или других ошибках БД.
        """
        logger.info("Company DAM: Creating new company.")
        # Вызываем базовый create, который обработает валидацию и _prepare_for_create
        new_company = await super().create(data)

        # Устанавливаем company_id = id после успешного создания и получения ID
        if new_company.id and new_company.company_id != new_company.id:
            logger.debug(
                f"Setting company_id={new_company.id} for newly created company {new_company.id}."
            )
            new_company.company_id = new_company.id
            self.session.add(
                new_company
            )  # Добавляем в сессию для сохранения изменения company_id
            try:
                await self.session.commit()
                await self.session.refresh(new_company)  # Обновляем объект из БД
                logger.info(
                    f"Successfully created company '{new_company.name}' with ID {new_company.id} and set company_id."
                )
            except Exception as e:
                # Откат произойдет в managed_session
                logger.exception(
                    f"Company DAM: Error committing company_id update for new company {new_company.id}."
                )
                # Можно либо вернуть компанию без обновленного company_id, либо выбросить ошибку
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to finalize company creation.",
                )
        elif not new_company.id:
            logger.error(
                "Company DAM: Company created via super().create() but has no ID. This should not happen."
            )
            # Это неожиданная ситуация, выбрасываем ошибку
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get ID for newly created company.",
            )
        else:
            # company_id уже был равен id (маловероятно при создании) или не изменился
            logger.debug(
                f"Company ID {new_company.id} already has matching company_id."
            )

        return new_company
