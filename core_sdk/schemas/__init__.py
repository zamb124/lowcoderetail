# core_sdk/schemas/__init__.py

from .base import BaseSchema # <--- ДОБАВИТЬ
from . import token
from . import user
from . import i18n
from .pagination import PaginatedResponse # <--- ДОБАВИТЬ, если еще не там
from .auth_user import AuthenticatedUser # <--- ДОБАВИТЬ, если еще не там

__all__ = [
    "BaseSchema",
    "token",
    "user",
    "i18n",
    "PaginatedResponse",
    "AuthenticatedUser",
]