# core_sdk/constants/permissions.py
from enum import Enum

class BasePermission(Enum):
    # Users
    USERS_VIEW = "users.view"
    USERS_CREATE = "users.create"
    USERS_EDIT = "users.edit"
    USERS_DELETE = "users.delete"
    USERS_MANAGE_GROUPS = "users.manage_groups" # Пример

    # Groups
    GROUPS_VIEW = "groups.view"
    GROUPS_CREATE = "groups.create"
    GROUPS_EDIT = "groups.edit"
    GROUPS_DELETE = "groups.delete"
    GROUPS_MANAGE_PERMISSIONS = "groups.manage_permissions" # Пример

    # Companies (возможно, только для супер-админов)
    COMPANIES_VIEW = "companies.view"
    COMPANIES_CREATE = "companies.create"
    COMPANIES_EDIT = "companies.edit"
    COMPANIES_DELETE = "companies.delete"

    # Другие базовые ресурсы Core
    # ...

    # Можно добавить метод для получения описания
    def get_description(self) -> str:
        # Логика для получения человекочитаемого описания
        descriptions = {
            BasePermission.USERS_VIEW: "View users list and details",
            BasePermission.USERS_CREATE: "Create new users",
            # ...
        }
        return descriptions.get(self, self.value) # Возвращаем значение (codename) по умолчанию

# Функция для получения всех базовых пермишенов для инициализации
def get_all_base_permissions() -> list[tuple[str, str]]:
    """Возвращает список кортежей (codename, name) для базовых прав."""
    return [(p.value, p.name.replace('_', ' ').title()) for p in BasePermission]

# Можно определить иерархию или категории, если нужно