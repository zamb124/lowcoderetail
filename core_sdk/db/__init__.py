# core_sdk/db/__init__.py
import uuid

# Импортируем нужные компоненты из base_model
from .base_model import BaseModelWithMeta, JSON, datetime, Optional, Dict, Any

# --- ИЗМЕНЕНИЕ: Импортируем CustomField вместо Field из base_model ---
# --------------------------------------------------------------------
# Импортируем компоненты из session
from .session import get_current_session, create_db_and_tables

UUID = uuid.UUID

__all__ = [
    "BaseModelWithMeta",
    "JSON",
    "datetime",
    "Optional",
    "Dict",
    "Any",
    "UUID",
    "get_current_session",
    "create_db_and_tables",
]
