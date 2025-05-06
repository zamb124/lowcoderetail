# core/app/api/endpoints/companies.py
import logging
from typing import Optional # List не используется напрямую
from uuid import UUID

from fastapi import Depends, HTTPException, status # APIRouter импортируется фабрикой
# taskiq.TaskiqError не используется, TaskiqResult используется для type hinting
from taskiq import TaskiqResult # Оставляем для type hinting

from core_sdk.crud.factory import CRUDRouterFactory
from core_sdk.data_access import DataAccessManagerFactory, get_dam_factory
from core_sdk.exceptions import CoreSDKError # Для обработки ошибок брокера

from .. import deps # Используем app. для импорта из текущего приложения
# models и schemas не используются напрямую, т.к. фабрика работает с именами
from ...data_access.company_manager import CompanyDataAccessManager # Для type hinting
from ...schemas.company import CompanyRead # Для response_model

logger = logging.getLogger(__name__) # Имя будет app.api.endpoints.companies

company_factory = CRUDRouterFactory(
    model_name="Company",
    prefix='/companies',
    tags=["Companies"], # Добавляем тег для группировки
    get_deps=[Depends(deps.get_current_active_superuser)],
    list_deps=[Depends(deps.get_current_active_superuser)],
    create_deps=[Depends(deps.get_current_active_superuser)],
    update_deps=[Depends(deps.get_current_active_superuser)],
    delete_deps=[Depends(deps.get_current_active_superuser)],
)

@company_factory.router.post(
    "/{company_id}/activate-wait",
    response_model=CompanyRead,
    summary="Activate Company and Wait for Result",
    description=(
            "Асинхронно активирует компанию через брокер задач и ожидает результат выполнения. "
            "Этот эндпоинт блокирует ответ до тех пор, пока задача не будет выполнена или не истечет таймаут. "
            "Используйте с осторожностью для задач, которые гарантированно выполняются быстро."
    ),
    dependencies=[Depends(deps.get_current_active_superuser)]
)
async def activate_company_and_wait(
        company_id: UUID,
        dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
        wait_timeout: int = 10 # Таймаут ожидания в секундах
):
    """
    Активирует компанию и ожидает результат от фоновой задачи.
    """
    logger.info(f"API: Received request to activate company {company_id} and wait (timeout: {wait_timeout}s)")
    try:
        company_manager: CompanyDataAccessManager = dam_factory.get_manager("Company")
    except CoreSDKError as e:
        logger.critical(f"Failed to get CompanyDataAccessManager for company activation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is temporarily unavailable.",
        )

    try:
        # Вызываем метод activate_company через прокси брокера
        # BrokerTaskProxy.__getattr__ вернет обертку task_kicker_and_waiter
        # которая принимает _broker_timeout
        activated_company_data = await company_manager.broker.activate_company(company_id, _broker_timeout=wait_timeout)

        # BrokerTaskProxy должен вернуть десериализованный результат или выбросить исключение
        if activated_company_data is None: # Если воркер вернул None (маловероятно для activate)
            logger.error(f"Company activation task for {company_id} returned None unexpectedly.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Company activation failed.")

        # Предполагаем, что activate_company возвращает объект, который можно валидировать в CompanyRead
        # или уже является им. BrokerTaskProxy._deserialize_broker_result должен это сделать.
        return activated_company_data # FastAPI сам валидирует по response_model=CompanyRead
    except CoreSDKError as e: # Ловим другие ошибки SDK (например, ошибка воркера)
        logger.error(f"Error during company {company_id} activation via broker: {e}", exc_info=True)
        # Детали ошибки воркера могут быть чувствительными, возвращаем общее сообщение
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to activate company: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error during company {company_id} activation.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred.")