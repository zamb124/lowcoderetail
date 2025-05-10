# core_sdk/filters/base.py

import logging
from typing import Optional, List, Type
from uuid import UUID
from datetime import datetime

# Используем абсолютные импорты
from pydantic import Field
from fastapi_filter.contrib.sqlalchemy import Filter as BaseFilter # Переименовываем для ясности
from sqlmodel import SQLModel

# Получаем логгер для этого модуля
logger = logging.getLogger(__name__) # Имя будет core_sdk.filters

class DefaultFilter(BaseFilter):
    """
    Базовый фильтр, предоставляющий стандартные поля для пагинации,
    сортировки, поиска и фильтрации по общим полям моделей (ID, даты, company_id).

    Этот класс предназначен для наследования кастомными фильтрами в сервисах,
    чтобы обеспечить консистентный набор базовых возможностей фильтрации.
    Поля определены здесь для автоматической генерации документации OpenAPI
    и корректного парсинга запросов FastAPI.
    Фактическая логика фильтрации и сортировки выполняется методами `.filter()`
    и `.sort()` базового класса `fastapi_filter.contrib.sqlalchemy.Filter`.
    """
    # --- Стандартные поля фильтрации ---
    id__in: Optional[List[UUID]] = Field(
        default=None,
        title='Filter by ID list',
        description='Filter by a list of exact IDs.'
    )
    company_id: Optional[UUID] = Field(
        default=None,
        title='Filter by Company ID',
        description='Filter by a specific company ID.',
        rel='company' # Указываем связь с моделью Company
    )
    company_id__in: Optional[List[UUID]] = Field(
        default=None,
        title='Filter by Company ID list',
        description='Filter by a list of company IDs.',
        rel='company'
    )
    created_at__gte: Optional[datetime] = Field(
        default=None,
        title='Created at From',
        description='Filter by creation date (greater than or equal to).'
    )
    created_at__lt: Optional[datetime] = Field(
        default=None,
        title='Created at To',
        description='Filter by creation date (less than).'
    )
    updated_at__gte: Optional[datetime] = Field(
        default=None,
        title='Updated at From',
        description='Filter by update date (greater than or equal to).'
    )
    updated_at__lt: Optional[datetime] = Field(
        default=None,
        title='Updated at To',
        description='Filter by update date (less than).'
    )

    # --- Стандартные поля для сортировки и поиска ---
    order_by: Optional[List[str]] = Field(
        default=None,
        title="Order by fields",
        description="Fields to order by. Prefix with '-' for descending order (e.g., 'name,-created_at')."
    )
    search: Optional[str] = Field(
        default=None,
        title="Search term",
        description="Simple text search across designated text fields."
    )

    # --- Конфигурация для fastapi-filter ---
    # Этот вложенный класс должен быть определен в дочерних классах
    # или динамически добавлен CRUDRouterFactory при использовании этого
    # фильтра по умолчанию.
    class Constants(BaseFilter.Constants):
         model: Type[SQLModel]
         # search_model_fields: List[str] = [] # Определяется в дочернем классе или CRUDRouterFactory
         # ordering_field_name: str = "order_by" # Уже определено в BaseFilter.Constants

# Логгируем факт определения класса (для отладки импортов)
logger.debug(f"{__name__} loaded, DefaultFilter class defined.")