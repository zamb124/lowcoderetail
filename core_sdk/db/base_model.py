# core_sdk/db/base_model.py
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    func,
    Column,
    JSON,
)  # <--- ИЗМЕНЕНИЕ: JSON вместо JSONB
from sqlalchemy.schema import Identity
from sqlalchemy.sql import text

from sqlmodel import Field, SQLModel


class BaseModelWithMeta(SQLModel):
    id: Optional[uuid.UUID] = Field(
        default=None,
        primary_key=True,
        index=True,
        nullable=False,
        sa_column_kwargs={
            "server_default": text("gen_random_uuid()"),
            "unique": True,
            "comment": "Уникальный идентификатор записи (UUID, генерируется базой данных)",
        },
        description="Уникальный идентификатор записи (UUID)",
    )

    vars: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        sa_type=JSON,  # <--- ИЗМЕНЕНИЕ: JSONB на JSON
        nullable=True,
        sa_column_kwargs={
            "server_default": text("'{}'"),  # <--- ИЗМЕНЕНИЕ: убрано ::jsonb
            "comment": "Поле для хранения произвольных данных в формате JSON",  # <--- ИЗМЕНЕНИЕ: JSONB на JSON
        },
        description="Дополнительные данные в формате JSON",
    )

    created_at: Optional[datetime] = Field(
        default=None,
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={
            "server_default": func.now(),
            "comment": "Дата и время создания записи (UTC)",
        },
        description="Дата и время создания записи (UTC)",
    )

    updated_at: Optional[datetime] = Field(
        default=None,
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
            "comment": "Дата и время последнего обновления записи (UTC)",
        },
        description="Дата и время последнего обновления записи (UTC)",
    )

    company_id: Optional[uuid.UUID] = Field(
        default=None,
        index=True,
        nullable=False,
        # sa_type=PG_UUID(as_uuid=True) # PG_UUID здесь не нужен, SQLModel сам разберется с UUID для SQLite
        description="Идентификатор компании, к которой относится запись",
    )

    lsn: Optional[int] = None

    @classmethod
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__name__ != "BaseModelWithMeta":
            lsn_column = Column(
                "lsn",
                BigInteger,
                Identity(always=True),
                unique=True,
                nullable=False,
                index=True,
                comment="Последовательный номер записи (LSN) в таблице, генерируется БД",
            )
            lsn_field = Field(
                default=None,
                sa_column=lsn_column,
                description="Последовательный номер записи (LSN), генерируемый базой данных для отслеживания порядка",
            )
            setattr(cls, "lsn", lsn_field)
