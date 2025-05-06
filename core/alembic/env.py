# alembic/env.py
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine # Пример для async

from alembic import context

# --- ДОБАВЬТЕ ЭТОТ БЛОК ---
# Добавляем корень проекта в sys.path, чтобы Alembic мог найти core_sdk и core.app
# Предполагаем, что alembic.ini находится в корне проекта,
# а env.py - в директории alembic внутри корня.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# ---------------------------
print(sys.path)
# --- Теперь импорты ваших модулей должны работать ---
from core.app.models import *
from core_sdk.db.base_model import BaseModelWithMeta # <-- Ваш импорт
# from core.config import settings # Пример, если нужен доступ к настройкам
# ----------------------------------------------------


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = BaseModelWithMeta.metadata # <--- Ваши метаданные

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

# --- Получаем URL БД из alembic.ini ---
# Убедитесь, что sqlalchemy.url задан в alembic.ini
db_url = config.get_main_option("sqlalchemy.url")
if not db_url:
    # Можно попытаться загрузить из настроек приложения, если alembic.ini пуст
    # try:
    #     from core.config import settings
    #     db_url = str(settings.DATABASE_URL)
    #     config.set_main_option("sqlalchemy.url", db_url) # Устанавливаем для использования ниже
    # except ImportError:
    raise ValueError("Database URL not configured in alembic.ini (sqlalchemy.url)")
# ---------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.
    # ... (стандартный код offline режима) ...
    """
    url = db_url # Используем полученный URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """Helper function to run migrations."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations online in async mode."""
    # Убедитесь, что ваш db_url подходит для asyncpg
    connectable = AsyncEngine(
        engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
            future=True, # Используйте future=True для SQLAlchemy 1.4+
        )
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    import asyncio
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()