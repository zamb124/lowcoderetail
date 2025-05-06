# core_sdk/db/base_model.py
import uuid
from datetime import datetime # timezone не используется напрямую, но datetime может быть timezone-aware
from typing import Any, Dict, Optional # List не используется в этом файле

from sqlalchemy import BigInteger, DateTime, func, Column
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
# declared_attr не используется в текущей реализации lsn
from sqlalchemy.schema import Identity
from sqlalchemy.sql import text # text используется для server_default

from sqlmodel import Field, SQLModel # Relationship не используется в этом базовом классе

class BaseModelWithMeta(SQLModel):
    """
    Базовая модель SQLModel с общими полями метаданных, такими как id,
    даты создания/обновления, lsn для отслеживания изменений и поле `vars` для
    хранения произвольных JSONB данных.
    Предназначена для наследования всеми моделями таблиц в сервисах.
    """

    id: Optional[uuid.UUID] = Field(
        default=None, # Значение будет установлено БД или при создании объекта
        primary_key=True,
        index=True,
        nullable=False, # БД не позволит NULL из-за server_default и primary_key
        sa_type=PG_UUID(as_uuid=True), # Явное указание типа колонки SQLAlchemy
        sa_column_kwargs={ # Дополнительные аргументы для SQLAlchemy Column
            "server_default": text("gen_random_uuid()"), # Генерация UUID на стороне БД
            "unique": True,
            "comment": "Уникальный идентификатор записи (UUID, генерируется базой данных)"
        },
        description="Уникальный идентификатор записи (UUID)"
    )

    vars: Optional[Dict[str, Any]] = Field(
        default_factory=dict, # Используем default_factory для изменяемых типов (словари, списки)
        sa_type=JSONB, # Тип колонки JSONB для PostgreSQL
        nullable=True, # Поле может быть NULL в БД
        sa_column_kwargs={
             "server_default": text("'{}'::jsonb"), # Значение по умолчанию в БД - пустой JSONB объект
             "comment": "Поле для хранения произвольных данных в формате JSONB"
        },
        description="Дополнительные данные в формате JSONB"
    )

    created_at: Optional[datetime] = Field(
        default=None, # Значение будет установлено БД
        nullable=False, # Поле не может быть NULL
        sa_type=DateTime(timezone=True), # Тип DateTime с информацией о временной зоне
        sa_column_kwargs={
            "server_default": func.now(), # Текущее время на стороне БД при создании записи
            "comment": "Дата и время создания записи (UTC)"
        },
        description="Дата и время создания записи (UTC)"
    )

    updated_at: Optional[datetime] = Field(
        default=None, # Значение будет установлено БД
        nullable=False, # Поле не может быть NULL
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={
            "server_default": func.now(), # Текущее время на стороне БД при создании
            "onupdate": func.now(),       # Текущее время на стороне БД при обновлении
            "comment": "Дата и время последнего обновления записи (UTC)"
        },
        description="Дата и время последнего обновления записи (UTC)"
    )

    company_id: Optional[uuid.UUID] = Field(
        # ForeignKey должен определяться в дочерних моделях, если он нужен.
        # Здесь это просто поле UUID для хранения ID компании.
        default=None, # Явно указываем, что может быть None
        index=True,
        nullable=False, # В исходном коде было False, оставляем так. Если нужно разрешить NULL, измените на True.
        sa_type=PG_UUID(as_uuid=True),
        description="Идентификатор компании, к которой относится запись"
    )

    # lsn: Log Sequence Number - для отслеживания порядка изменений, генерируется БД.
    # Оставляем исходную логику с __init_subclass__ для lsn.
    lsn: Optional[int] = None  # Только аннотация типа, реальное поле создается в __init_subclass__

    @classmethod
    def __init_subclass__(cls, **kwargs: Any) -> None:
        """
        SQLModel hook, вызываемый при наследовании от этого класса.
        Используется для динамического добавления колонки `lsn` с `Identity`
        к каждой конкретной таблице-наследнику. Это гарантирует, что каждая
        таблица будет иметь свою собственную последовательность LSN.
        """
        super().__init_subclass__(**kwargs)
        # Добавляем колонку lsn только для реальных таблиц-наследников,
        # а не для самого BaseModelWithMeta.
        if cls.__name__ != 'BaseModelWithMeta':
            # Создаем новый объект Column для lsn для каждого подкласса,
            # чтобы Identity(always=True) создавал отдельную последовательность для каждой таблицы.
            lsn_column = Column(
                "lsn",
                BigInteger,
                Identity(always=True), # always=True означает, что значение всегда генерируется БД
                unique=True,
                nullable=False,
                index=True,
                comment="Последовательный номер записи (LSN) в таблице, генерируется БД"
            )
            # Используем Field для интеграции с Pydantic/SQLModel, передавая sa_column
            lsn_field = Field(
                default=None, # Pydantic не должен пытаться установить это значение
                sa_column=lsn_column,
                description="Последовательный номер записи (LSN), генерируемый базой данных для отслеживания порядка"
            )
            # Устанавливаем поле в классе
            setattr(cls, 'lsn', lsn_field)
            # cls.model_rebuild() здесь может быть не нужен, если SQLModel сам подхватывает
            # изменения при инициализации класса. Если возникают проблемы с распознаванием поля,
            # можно раскомментировать.
            # cls.model_rebuild(force=True)
