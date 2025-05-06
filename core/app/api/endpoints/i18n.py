# core/app/api/endpoints/i18n.py
import logging
from typing import List

from fastapi import APIRouter # Depends не используется здесь
from starlette.exceptions import HTTPException

# Прямые импорты из SDK
from core_sdk.services import i18n_service
from core_sdk.schemas import i18n as i18n_schemas # Используем псевдоним для ясности

logger = logging.getLogger(__name__) # Имя будет app.api.endpoints.i18n

router = APIRouter(prefix="/i18n", tags=["I18n"]) # Префикс и тег здесь

@router.get(
    "/languages",
    response_model=List[i18n_schemas.Language],
    summary="Get List of Supported Languages",
    description="Возвращает список поддерживаемых языков с их ISO 639-1 кодами и названиями на английском языке."
)
async def read_languages():
    """
    Извлекает список доступных языков.
    """
    logger.info("Request received for list of languages.")
    try:
        languages = await i18n_service.get_languages()
        logger.debug(f"Returning {len(languages)} languages.")
        return languages
    except Exception as e:
        logger.exception("Error retrieving languages from i18n_service.")
        # В данном случае, если сервис i18n недоступен, это может быть 503
        raise HTTPException(status_code=503, detail="Language service is currently unavailable.")


@router.get(
    "/countries",
    response_model=List[i18n_schemas.Country],
    summary="Get List of Countries",
    description="Возвращает список стран с их ISO 3166-1 alpha-2 кодами и официальными названиями."
)
async def read_countries():
    """
    Извлекает список доступных стран.
    """
    logger.info("Request received for list of countries.")
    try:
        countries = await i18n_service.get_countries()
        logger.debug(f"Returning {len(countries)} countries.")
        return countries
    except Exception as e:
        logger.exception("Error retrieving countries from i18n_service.")
        raise HTTPException(status_code=503, detail="Country service is currently unavailable.")

@router.get(
    "/currencies",
    response_model=List[i18n_schemas.Currency],
    summary="Get List of Currencies",
    description="Возвращает список валют с их ISO 4217 кодами и названиями на английском языке."
)
async def read_currencies():
    """
    Извлекает список доступных валют.
    """
    logger.info("Request received for list of currencies.")
    try:
        currencies = await i18n_service.get_currencies()
        logger.debug(f"Returning {len(currencies)} currencies.")
        return currencies
    except Exception as e:
        logger.exception("Error retrieving currencies from i18n_service.")
        raise HTTPException(status_code=503, detail="Currency service is currently unavailable.")