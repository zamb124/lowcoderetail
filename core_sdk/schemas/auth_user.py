# core_sdk/schemas/auth_user.py
import uuid
from typing import List, Optional
from pydantic import BaseModel, Field, EmailStr


class AuthenticatedUser(BaseModel):
    """
    Представление аутентифицированного пользователя,
    извлекаемое из JWT токена.
    """

    id: uuid.UUID = Field(description="ID пользователя.")
    company_id: Optional[uuid.UUID] = Field(
        None, description="ID компании пользователя (если есть)."
    )
    email: Optional[EmailStr] = Field(
        None, description="Email пользователя (опционально, для удобства)."
    )
    is_active: bool = Field(True, description="Статус активности пользователя.")
    is_superuser: bool = Field(
        False, description="Является ли пользователь суперюзером."
    )
    permissions: List[str] = Field(
        default=[], description="Список коднаймов прав доступа пользователя."
    )

    # Можно добавить хелпер для проверки прав
    def has_permission(self, required_permission: str) -> bool:
        """Проверяет, есть ли у пользователя указанное право."""
        # Суперпользователь имеет все права
        if self.is_superuser:
            return True
        return required_permission in self.permissions
