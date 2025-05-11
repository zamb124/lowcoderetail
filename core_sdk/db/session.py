# core_sdk/db/session.py
import contextlib
import contextvars
import logging
from typing import AsyncGenerator, Optional, Dict, Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool, NullPool  # Импортируем типы пулов для проверки
from sqlmodel import SQLModel
from fastapi import Depends

logger = logging.getLogger(__name__)

_db_engine: Optional[AsyncEngine] = None
_db_session_maker: Optional[async_sessionmaker[AsyncSession]] = None

_current_session: contextvars.ContextVar[Optional[AsyncSession]] = (
    contextvars.ContextVar("current_session", default=None)
)


def init_db(
    database_url: str,
    engine_options: Optional[Dict[str, Any]] = None,
    echo: bool = False,
):
    global _db_engine, _db_session_maker
    if _db_engine:
        logger.warning(
            "Database engine and session maker already initialized. Skipping re-initialization."
        )
        return

    logger.info(
        f"Initializing database engine and session maker for URL: {database_url[: database_url.find('@') + 1]}********"
    )

    options_to_pass = (
        engine_options.copy() if engine_options else {}
    )  # Копируем, чтобы не изменять оригинал

    # Проверяем, указан ли poolclass, который не использует pool_size/max_overflow
    pool_class_in_options = options_to_pass.get("poolclass")
    if pool_class_in_options and pool_class_in_options in [StaticPool, NullPool]:
        # Удаляем параметры, несовместимые с этими пулами
        options_to_pass.pop("pool_size", None)
        options_to_pass.pop("max_overflow", None)
        logger.debug(
            f"Using specified poolclass {pool_class_in_options.__name__}. "
            f"Removed pool_size/max_overflow from engine options if they were present."
        )

    try:
        _db_engine = create_async_engine(
            database_url, echo=echo, future=True, **options_to_pass
        )  # Передаем отфильтрованные options
        _db_session_maker = async_sessionmaker(
            bind=_db_engine, class_=AsyncSession, expire_on_commit=False
        )
        logger.info("Database engine and session maker initialized successfully.")
    except Exception as e:
        logger.critical(
            "Failed to initialize database engine or session maker.", exc_info=True
        )
        raise RuntimeError("Failed to initialize database infrastructure") from e


async def close_db():
    global _db_engine, _db_session_maker
    if _db_engine:
        logger.info("Disposing database engine...")
        try:
            await _db_engine.dispose()
            logger.info("Database engine disposed successfully.")
        except Exception as e:
            logger.error("Error during database engine disposal.", exc_info=True)
        finally:
            _db_engine = None
            _db_session_maker = None
    else:
        logger.info(
            "Database engine was not initialized or already disposed. No action taken."
        )


@contextlib.asynccontextmanager
async def managed_session() -> AsyncGenerator[AsyncSession, None]:
    if _db_session_maker is None:
        logger.error(
            "Session maker not initialized. Call init_db() first to configure database access."
        )
        raise RuntimeError("Session maker not initialized. Call init_db() first.")

    existing_session = _current_session.get()
    if existing_session is not None:
        logger.debug(
            f"managed_session: Reusing existing session {id(existing_session)} from contextvar."
        )
        yield existing_session
        return

    logger.debug("managed_session: Creating new session.")
    session = _db_session_maker()
    token = _current_session.set(session)
    session_id_for_log = id(session)
    logger.debug(
        f"managed_session: Set new session {session_id_for_log} in contextvar."
    )

    try:
        yield session
    except Exception:
        logger.exception(
            f"managed_session: Exception occurred within managed session {session_id_for_log}. Rolling back."
        )
        try:
            await session.rollback()
            logger.info(
                f"managed_session: Session {session_id_for_log} rolled back successfully."
            )
        except Exception as rb_exc:
            logger.error(
                f"managed_session: Critical error during rollback of session {session_id_for_log}.",
                exc_info=rb_exc,
            )
        raise
    finally:
        logger.debug(f"managed_session: Closing session {session_id_for_log}.")
        try:
            await session.close()
        except Exception as close_exc:
            logger.error(
                f"managed_session: Error closing session {session_id_for_log}.",
                exc_info=close_exc,
            )
        _current_session.reset(token)
        logger.debug(
            f"managed_session: Reset contextvar, session {session_id_for_log} is no longer current."
        )


def get_current_session() -> AsyncSession:
    session = _current_session.get()
    if session is None:
        logger.error(
            "Attempted to get current session, but no active session found in context."
        )
        raise RuntimeError(
            "No active session found in context. Ensure this code is called within an 'async with managed_session():' block."
        )
    logger.debug(
        f"get_current_session: Returning session {id(session)} from contextvar."
    )
    return session


async def get_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    logger.debug(
        "FastAPI dependency 'get_session_dependency' called, entering managed_session."
    )
    async with managed_session() as session:
        yield session
    logger.debug(
        "FastAPI dependency 'get_session_dependency' finished, managed_session exited."
    )


async def create_db_and_tables():
    global _db_engine
    if _db_engine is None:
        logger.error(
            "Database engine not initialized. Cannot create tables. Call init_db() first."
        )
        raise RuntimeError("Database engine not initialized. Call init_db() first.")

    logger.info("Attempting to create database tables based on SQLModel.metadata...")
    try:
        async with _db_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("Database tables checked/created successfully using global engine.")
    except Exception as e:
        logger.critical("Failed to create database tables.", exc_info=True)
