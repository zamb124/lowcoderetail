# core_sdk/security.py

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

# Используем абсолютные импорты в рамках SDK или внешних библиотек
from jose import jwt, JWTError
from passlib.context import CryptContext

# Получаем логгер для этого модуля
logger = logging.getLogger(__name__)

# --- Password Hashing ---
# Используем bcrypt как рекомендуемый алгоритм
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Проверяет, соответствует ли обычный пароль хешированному.

    :param plain_password: Пароль в открытом виде.
    :param hashed_password: Хешированный пароль для сравнения.
    :return: True, если пароли совпадают, иначе False.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except ValueError as e:
        # Ошибка может возникнуть, если хеш имеет неверный формат
        logger.error(f"Error verifying password (invalid hash format?): {e}")
        return False
    except Exception as e:
        # Другие неожиданные ошибки passlib
        logger.exception(f"Unexpected error verifying password: {e}")
        return False


def get_password_hash(password: str) -> str:
    """
    Возвращает хеш для заданного пароля.

    :param password: Пароль для хеширования.
    :return: Строка с хешем пароля.
    :raises RuntimeError: Если произошла ошибка при хешировании.
    """
    if not password:
        # Возможно, стоит выбрасывать ValueError, но пока оставим как есть,
        # т.к. пустой пароль технически можно хешировать.
        # Зависит от бизнес-логики - должен ли пароль быть непустым.
        logger.warning("Attempting to hash an empty password.")
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logger.exception("Error generating password hash.")
        # Перевыбрасываем, т.к. не можем вернуть валидный хеш
        raise RuntimeError("Failed to hash password") from e


# --- JWT Token Handling ---
ALGORITHM = "HS256"  # Алгоритм подписи по умолчанию


def create_access_token(
    *,
    data: Dict[str, Any],
    secret_key: str,
    algorithm: str = ALGORITHM,
    expires_delta: timedelta,
) -> str:
    """
    Создает JWT access токен.

    :param data: Данные (payload) для включения в токен (например, user_id, sub).
    :param secret_key: Секретный ключ для подписи токена.
    :param algorithm: Алгоритм подписи (по умолчанию HS256).
    :param expires_delta: Время жизни токена (объект timedelta).
    :return: Строка с JWT access токеном.
    :raises ValueError: Если не предоставлен secret_key.
    :raises RuntimeError: Если произошла ошибка при кодировании токена.
    """
    if not secret_key:
        logger.error("Cannot create access token: secret_key is missing.")
        raise ValueError("Secret key must be provided to create access token.")
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire, "type": "access"})  # Добавляем срок годности и тип
    try:
        encoded_jwt = jwt.encode(to_encode, secret_key, algorithm=algorithm)
        return encoded_jwt
    except Exception as e:
        logger.exception("Error encoding access token.")
        raise RuntimeError("Failed to create access token") from e


def create_refresh_token(
    *,
    data: Dict[str, Any],  # Обычно содержит только user_id или аналог
    secret_key: str,
    algorithm: str = ALGORITHM,
    expires_delta: timedelta,  # Обычно дольше, чем у access токена
) -> str:
    """
    Создает JWT refresh токен.

    :param data: Данные (payload) для включения в токен.
    :param secret_key: Секретный ключ для подписи токена.
    :param algorithm: Алгоритм подписи (по умолчанию HS256).
    :param expires_delta: Время жизни токена (объект timedelta).
    :return: Строка с JWT refresh токеном.
    :raises ValueError: Если не предоставлен secret_key.
    :raises RuntimeError: Если произошла ошибка при кодировании токена.
    """
    if not secret_key:
        logger.error("Cannot create refresh token: secret_key is missing.")
        raise ValueError("Secret key must be provided to create refresh token.")
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update(
        {"exp": expire, "type": "refresh"}
    )  # Добавляем срок годности и тип
    try:
        encoded_jwt = jwt.encode(to_encode, secret_key, algorithm=algorithm)
        return encoded_jwt
    except Exception as e:
        logger.exception("Error encoding refresh token.")
        raise RuntimeError("Failed to create refresh token") from e


def verify_token(
    token: str,
    secret_key: str,
    algorithm: str = ALGORITHM,
    # Используем стандартное исключение Python по умолчанию,
    # чтобы SDK не зависел от FastAPI напрямую.
    # Вызывающий код (например, зависимость FastAPI) может передать HTTPException.
    credentials_exception: Exception = ValueError("Could not validate credentials"),
) -> Dict[str, Any]:
    """
    Декодирует и валидирует JWT токен.

    :param token: Строка JWT токена.
    :param secret_key: Секретный ключ для проверки подписи.
    :param algorithm: Алгоритм подписи.
    :param credentials_exception: Исключение, которое будет выброшено при ошибке валидации.
    :return: Словарь с payload (claims) токена.
    :raises ValueError: Если не предоставлен secret_key.
    :raises credentials_exception: При любой ошибке валидации токена (формат, подпись, срок действия, отсутсвие user_id).
    """
    if not secret_key:
        logger.error("Cannot verify token: secret_key is missing.")
        # Это критическая ошибка конфигурации
        raise ValueError("Secret key must be provided to verify token.")
    if not token:
        logger.warning("Token verification attempt with empty token string.")
        raise credentials_exception  # Пустой токен невалиден

    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[algorithm],
            # Опции можно добавить, например, для проверки audience ('aud')
            # options={"verify_aud": False}
        )
        # Проверяем наличие обязательного поля 'user_id'
        user_id = payload.get("user_id")
        if user_id is None:
            logger.warning(
                "Token verification failed: 'user_id' claim missing in payload."
            )
            raise credentials_exception  # Отсутствие user_id - невалидный токен для системы

        # Можно добавить другие обязательные проверки payload здесь

        return payload
    except JWTError as e:
        # Ошибка валидации JWT (подпись, срок действия, формат и т.д.)
        logger.warning(f"Token verification failed due to JWTError: {e}")
        raise credentials_exception from e
    except Exception as e:
        # Ловим другие возможные ошибки при декодировании (неожиданные)
        logger.exception(f"Unexpected error during token verification: {e}")
        raise credentials_exception from e
