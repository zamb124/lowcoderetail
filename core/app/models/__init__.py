# core/app/models/__init__.py

from . import company
from . import user
from . import group

# Вариант 2: Ре-экспорт конкретных классов (тогда в deps.py нужно писать -> models.User)
# from .company import Company
# from .user import User # <--- Эта строка делает User доступным как models.User
# from .group import Group
# from .permission import Permission
# from .link_models import UserGroupLink, GroupPermissionLink