from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, Literal

class TokenPayload(BaseModel):
    """
    Схема данных (claims), содержащихся внутри JWT токена.
    """
    sub: str | None = None # Subject (может быть email или другой идентификатор)
    user_id: UUID | None = None # Явный ID пользователя
    exp: datetime | None = None # Время истечения срока действия
    type: Optional[Literal['access', 'refresh']] = None # Тип токена

class Token(BaseModel):
    """
    Схема ответа API при успешной аутентификации или обновлении токена.
    """
    access_token: str
    refresh_token: Optional[str] = None # Refresh токен может не возвращаться всегда
    token_type: str = "bearer"