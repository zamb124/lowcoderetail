# core_sdk/schemas/base.py
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field


class BaseSchema(BaseModel):
    """
    Базовая Pydantic схема, зеркалирующая общие поля из BaseModelWithMeta.
    Предназначена для наследования схемами чтения (Read) и, возможно, другими схемами.
    """
    id: Optional[uuid.UUID] = Field(
        default=None,
        description="Уникальный идентификатор записи (UUID)"
    )

    vars: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Дополнительные данные в формате JSON"
    )

    created_at: Optional[datetime] = Field(
        default=None,
        description="Дата и время создания записи (UTC)"
    )

    updated_at: Optional[datetime] = Field(
        default=None,
        description="Дата и время последнего обновления записи (UTC)"
    )

    company_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Идентификатор компании, к которой относится запись",
        rel='company'
    )

    lsn: Optional[int] = Field(
        default=None,
        description="Последовательный номер записи (LSN)"
    )