# Пример с Enum
from enum import Enum
from typing import List


class BasePermission(str, Enum):
    USERS_VIEW = "users:view"
    USERS_CREATE = "users:create"
    USERS_EDIT_OWN = "users:edit_own"  # Пример более гранулярного права
    COMPANIES_CREATE = "companies:create"
    COMPANIES_EDIT = "companies:edit"
    COMPANIES_DELETE = "companies:delete"  # Пример более гранулярного права
    # ... другие базовые права


# Функция для получения всех базовых коднаймов
def get_all_base_permission_codenames() -> List[str]:
    return [p.value for p in BasePermission]
