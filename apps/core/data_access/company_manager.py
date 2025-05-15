# apps/core/data_access/company_manager.py
import logging
from typing import Optional, List, Any, Dict, Union
from uuid import UUID

from fastapi import HTTPException, status

from core_sdk.exceptions import CoreSDKError
from core_sdk.data_access.local_manager import LocalDataAccessManager, DM_SQLModelType

from apps.core import models as core_models
from apps.core import schemas as core_schemas

logger = logging.getLogger("app.data_access.company_manager")


class CompanyDataAccessManager(
    LocalDataAccessManager[
        core_models.company.Company, # DM_SQLModelType
        core_schemas.company.CompanyCreate,
        core_schemas.company.CompanyUpdate,
        core_schemas.company.CompanyRead # DM_ReadSchemaType
    ]
):
    # model_cls, create_schema_cls, update_schema_cls, read_schema_cls
    # будут установлены в super().__init__

    async def get_by_name(self, name: str) -> Optional[core_models.company.Company]: # Возвращает SQLModel
        logger.info(f"Company DAM: Getting company by exact name '{name}'.")
        try:
            results_dict = await self.list(filters={"name": name}, limit=1)
            items = results_dict.get("items", []) # items это List[core_models.company.Company]
            if items:
                logger.debug(f"Company with name '{name}' found with ID: {items[0].id}")
                return items[0]
            else:
                logger.debug(f"Company with name '{name}' not found.")
                return None
        except Exception:
            logger.exception(f"Company DAM: Error fetching company by name '{name}'.")
            return None

    async def get_company_users(
            self, company_id: UUID, limit: int = 50, cursor: Optional[int] = None
    ) -> List[core_models.user.User]: # Возвращает List[SQLModel]
        logger.info(f"Company DAM: Getting users for company {company_id} (Limit: {limit}, Cursor: {cursor}).")
        company = await self.get(company_id) # self.get() вернет core_models.company.Company
        if not company:
            logger.warning(f"Company {company_id} not found when trying to get its users.")
            return []
        logger.error("get_company_users method is not implemented.")
        raise NotImplementedError("Accessing users from Company DAM requires further implementation")

    async def activate_company(self, company_id: UUID) -> core_models.company.Company: # Возвращает SQLModel
        logger.info(f"Company DAM: Activating company {company_id}.")
        company_sqlmodel = await self.get(company_id) # self.get() вернет SQLModel
        if not company_sqlmodel:
            logger.warning(f"Company {company_id} not found for activation.")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Company {company_id} not found")

        if company_sqlmodel.is_active:
            logger.info(f"Company DAM: Company {company_id} is already active. No action needed.")
            return company_sqlmodel

        logger.debug(f"Company {company_id} is inactive, attempting to activate.")
        try:
            # self.update вернет SQLModel
            updated_company_sqlmodel = await self.update(company_id, {"is_active": True}) # type: ignore
            logger.info(f"Company {company_id} activated successfully.")
            return updated_company_sqlmodel
        except HTTPException as e:
            logger.error(f"Company DAM: HTTP error during activation of company {company_id}: Status={e.status_code}, Detail={e.detail}")
            raise e
        except CoreSDKError as e:
            logger.exception(f"Company DAM: CoreSDKError activating company {company_id}.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to activate company due to SDK error: {e}")
        except Exception as e:
            logger.exception(f"Company DAM: Unexpected error activating company {company_id}.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to activate company: {e}")

    async def deactivate_company(self, company_id: UUID) -> core_models.company.Company: # Возвращает SQLModel
        logger.info(f"Company DAM: Deactivating company {company_id}.")
        try:
            # self.update вернет SQLModel
            updated_company_sqlmodel = await self.update(company_id, {"is_active": False}) # type: ignore
            logger.info(f"Company {company_id} deactivated successfully.")
            return updated_company_sqlmodel
        # ... (обработка ошибок как была) ...
        except HTTPException as e:
            logger.error(f"Company DAM: HTTP error during deactivation of company {company_id}: Status={e.status_code}, Detail={e.detail}")
            raise e
        except CoreSDKError as e:
            logger.exception(f"Company DAM: CoreSDKError deactivating company {company_id}.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to deactivate company due to SDK error: {e}")
        except Exception as e:
            logger.exception(f"Company DAM: Unexpected error deactivating company {company_id}.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to deactivate company: {e}")


    async def create(self, data: Union[core_schemas.company.CompanyCreate, Dict[str, Any]]) -> core_models.company.Company: # Возвращает SQLModel
        logger.info("Company DAM: Creating new company.")
        # super().create вернет SQLModel (core_models.company.Company)
        created_company_sqlmodel = await super().create(data)

        if created_company_sqlmodel.id: # id должен быть у SQLModel
            if created_company_sqlmodel.company_id != created_company_sqlmodel.id:
                logger.debug(f"Setting company_id={created_company_sqlmodel.id} for newly created company {created_company_sqlmodel.id}.")
                created_company_sqlmodel.company_id = created_company_sqlmodel.id
                self.session.add(created_company_sqlmodel)
                try:
                    await self.session.commit()
                    await self.session.refresh(created_company_sqlmodel)
                    logger.info(f"Successfully updated company_id for company '{created_company_sqlmodel.name}' with ID {created_company_sqlmodel.id}.")
                except Exception as e_commit:
                    await self.session.rollback()
                    logger.exception(f"Company DAM: Error committing company_id update for new company {created_company_sqlmodel.id}.")
                    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to finalize company creation.") from e_commit
            else:
                logger.debug(f"Company ID {created_company_sqlmodel.id} already has matching company_id or no update needed.")
        else:
            logger.error("Company DAM: Company created via super().create() but has no ID. This should not happen.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get ID for newly created company.")

        return created_company_sqlmodel