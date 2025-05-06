# core_sdk/db/session.py
import contextlib
import contextvars
import logging
from typing import AsyncGenerator, Optional, Dict, Any # Добавил Dict, Any для engine_options

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel # SQLModel используется для create_db_and_tables
# fastapi.Request, fastapi.Depends, fastapi.HTTPException не используются в этом файле напрямую.
# Они могут быть нужны для get_session_dependency, но сама зависимость определена здесь.
# Если get_session_dependency не используется вовне SDK напрямую, их можно убрать.
# Пока оставим, так как get_session_dependency экспортируется.
from fastapi import Depends # Depends используется в get_session_dependency

logger = logging.getLogger(__name__) # Имя будет core_sdk.db.session

_db_engine: Optional[AsyncEngine] = None
_db_session_maker: Optional[async_sessionmaker[AsyncSession]] = None

_current_session: contextvars.ContextVar[Optional[AsyncSession]] = contextvars.ContextVar(
    "current_session",
    default=None
)

def init_db(
        database_url: str,
        engine_options: Optional[Dict[str, Any]] = None, # Уточнил тип engine_options
        echo: bool = False
):
    """
    Инициализирует глобальный асинхронный движок SQLAlchemy и фабрику сессий.
    Эта функция должна вызываться один раз при старте приложения или воркера,
    использующего данный SDK для доступа к базе данных.

    :param database_url: Строка подключения к базе данных (например, "postgresql+asyncpg://user:pass@host:port/db").
    :param engine_options: Словарь дополнительных опций для `create_async_engine` (например, `pool_size`, `max_overflow`).
    :param echo: Если True, SQLAlchemy будет логировать все SQL-запросы. Полезно для отладки.
    :raises RuntimeError: Если инициализация базы данных не удалась.
    """
    global _db_engine, _db_session_maker
    if _db_engine:
        logger.warning("Database engine and session maker already initialized. Skipping re-initialization.")
        return

    logger.info(f"Initializing database engine and session maker for URL: {database_url[:database_url.find('@') + 1]}********") # Логируем URL без пароля
    options = engine_options or {}
    try:
        _db_engine = create_async_engine(database_url, echo=echo, future=True, **options)
        _db_session_maker = async_sessionmaker(
            bind=_db_engine,
            class_=AsyncSession,
            expire_on_commit=False # Важно для асинхронного кода и работы с объектами после коммита
        )
        logger.info("Database engine and session maker initialized successfully.")
    except Exception as e:
        logger.critical("Failed to initialize database engine or session maker.", exc_info=True)
        raise RuntimeError("Failed to initialize database infrastructure") from e

async def close_db():
    """
    Корректно закрывает (disposes) глобальный движок SQLAlchemy.
    Должна вызываться при завершении работы приложения или воркера.
    """
    global _db_engine, _db_session_maker
    if _db_engine:
        logger.info("Disposing database engine...")
        try:
            await _db_engine.dispose()
            logger.info("Database engine disposed successfully.")
        except Exception as e:
            logger.error("Error during database engine disposal.", exc_info=True)
        finally: # Гарантированно сбрасываем глобальные переменные
            _db_engine = None
            _db_session_maker = None
    else:
        logger.info("Database engine was not initialized or already disposed. No action taken.")

@contextlib.asynccontextmanager
async def managed_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Асинхронный контекстный менеджер для управления сессиями SQLAlchemy.
    Обеспечивает создание сессии, ее доступность через `get_current_session()`,
    и автоматический откат транзакции при исключениях, а также закрытие сессии.
    Коммиты должны выполняться явно в коде, использующем сессию.
    Поддерживает вложенность: если сессия уже активна в текущем контексте,
    она будет использована повторно без создания новой.

    :raises RuntimeError: Если фабрика сессий (`_db_session_maker`) не была инициализирована вызовом `init_db()`.
    :yields AsyncSession: Активная сессия SQLAlchemy.
    """
    if _db_session_maker is None:
        logger.error("Session maker not initialized. Call init_db() first to configure database access.")
        raise RuntimeError("Session maker not initialized. Call init_db() first.")

    existing_session = _current_session.get()
    if existing_session is not None:
        logger.debug(f"managed_session: Reusing existing session {id(existing_session)} from contextvar.")
        yield existing_session
        return

    logger.debug("managed_session: Creating new session.")
    session = _db_session_maker()
    token = _current_session.set(session)
    session_id_for_log = id(session) # Сохраняем ID для логов в finally
    logger.debug(f"managed_session: Set new session {session_id_for_log} in contextvar.")

    try:
        # Транзакция начинается автоматически при первом запросе к БД
        # или может быть начата явно через await session.begin() если требуется.
        yield session
        # Коммит здесь не выполняется. Код, использующий сессию, должен явно вызывать session.commit().
        # Если коммит не был вызван, изменения не будут сохранены.
        # Это позволяет более гибко управлять транзакциями на уровне бизнес-логики (в DAM).
    except Exception:
        logger.exception(f"managed_session: Exception occurred within managed session {session_id_for_log}. Rolling back.")
        try:
            await session.rollback()
            logger.info(f"managed_session: Session {session_id_for_log} rolled back successfully.")
        except Exception as rb_exc:
            logger.error(f"managed_session: Critical error during rollback of session {session_id_for_log}.", exc_info=rb_exc)
        raise # Перевыбрасываем исходное исключение
    finally:
        logger.debug(f"managed_session: Closing session {session_id_for_log}.")
        try:
            await session.close()
        except Exception as close_exc:
            logger.error(f"managed_session: Error closing session {session_id_for_log}.", exc_info=close_exc)
        _current_session.reset(token)
        logger.debug(f"managed_session: Reset contextvar, session {session_id_for_log} is no longer current.")


def get_current_session() -> AsyncSession:
    """
    Возвращает текущую активную сессию SQLAlchemy из асинхронного контекста.
    Эта функция предназначена для использования внутри блока `async with managed_session():`.

    :raises RuntimeError: Если активная сессия не найдена в текущем контексте
                          (т.е. функция вызвана вне `managed_session`).
    :return AsyncSession: Активная сессия SQLAlchemy.
    """
    session = _current_session.get()
    if session is None:
        logger.error("Attempted to get current session, but no active session found in context.")
        raise RuntimeError(
            "No active session found in context. Ensure this code is called within an 'async with managed_session():' block."
        )
    logger.debug(f"get_current_session: Returning session {id(session)} from contextvar.")
    return session

async def get_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI зависимость для предоставления сессии SQLAlchemy в обработчиках запросов.
    Использует `managed_session` для управления жизненным циклом сессии.
    """
    logger.debug("FastAPI dependency 'get_session_dependency' called, entering managed_session.")
    async with managed_session() as session:
        yield session
    logger.debug("FastAPI dependency 'get_session_dependency' finished, managed_session exited.")

async def create_db_and_tables():
    """
    Создает все таблицы в базе данных, определенные в метаданных SQLModel.
    Использует глобальный движок SDK. Предназначено для инициализации
    или тестовых окружений. Не рекомендуется для продакшена без должного контроля.

    :raises RuntimeError: Если движок базы данных не был инициализирован вызовом `init_db()`.
    """
    global _db_engine
    if _db_engine is None:
        logger.error("Database engine not initialized. Cannot create tables. Call init_db() first.")
        raise RuntimeError("Database engine not initialized. Call init_db() first.")

    logger.info("Attempting to create database tables based on SQLModel.metadata...")
    try:
        async with _db_engine.begin() as conn:
            # SQLModel.metadata.create_all является синхронной операцией
            await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("Database tables checked/created successfully using global engine.")
    except Exception as e:
        logger.critical("Failed to create database tables.", exc_info=True)
        # Можно перевыбросить, если это критично для старта приложения
        # raise RuntimeError("Failed to create database tables") from e
