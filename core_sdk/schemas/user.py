import uuid
from typing import Optional
from sqlmodel import (
    SQLModel,
    Field,
)  # Используем SQLModel для консистентности, но без table=True
from pydantic import EmailStr


class UserRead(SQLModel):
    """
    Схема для чтения данных пользователя, безопасная для передачи между сервисами.
    Не содержит пароль или другие чувствительные данные, не предназначенные для внешнего мира.
    """

    id: uuid.UUID
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    company_id: uuid.UUID  # ID компании важен для многих сервисов
    lsn: int  # LSN может быть полезен для отслеживания изменений
    # Не включаем: hashed_password, created_at, updated_at (если не нужны явно), vars
    # Не включаем: Relationships (groups, etc.), если они не нужны всем сервисам
