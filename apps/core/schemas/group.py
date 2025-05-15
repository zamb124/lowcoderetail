# apps/core/schemas/group.py
import logging
import uuid
from typing import Optional, List

from pydantic import Field, BaseModel

from core_sdk.schemas.base import BaseSchema
from core_sdk.schemas.user import UserRead

logger = logging.getLogger("app.schemas.group")

class GroupBase(BaseSchema):
    name: str = Field(
        max_length=100,
        description="Название группы.",
    )
    description: Optional[str] = Field(
        default=None, max_length=255, description="Описание группы."
    )
    permissions: List[str] = Field(
        default_factory=list,
        description="Список коднаймов прав доступа.",
    )
    # company_id наследуется из BaseSchema как Optional[uuid.UUID]

class GroupCreate(GroupBase):
    id: Optional[uuid.UUID] = Field(default=None) # Явное переопределение для гарантии
    company_id: uuid.UUID # Делаем обязательным для создания группы

class GroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=255)
    permissions: Optional[List[str]] = Field(default=None)

class GroupRead(GroupBase):
     pass

class GroupReadWithDetails(GroupRead):
    users: List[UserRead] = Field(default_factory=list)

logger.debug(
    "Group schemas defined: GroupBase, GroupCreate, GroupUpdate, GroupRead, GroupReadWithDetails"
)