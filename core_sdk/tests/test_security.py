# core_sdk/tests/test_security.py
import pytest
from datetime import datetime, timedelta, timezone
import uuid # Для user_id в токенах
from typing import Dict, Any

from jose import jwt, JWTError # Для проверки типов ошибок JWT
from passlib.exc import InvalidHashError # Для проверки ошибок passlib

from core_sdk.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    verify_token,
    ALGORITHM # Используем дефолтный алгоритм из модуля
)

# --- Тестовые данные ---
TEST_PASSWORD = "strongpassword123"
TEST_SECRET_KEY = "a-very-secret-key-for-testing-jwt-tokens"
SHORT_EXPIRES_DELTA = timedelta(minutes=5)
LONG_EXPIRES_DELTA = timedelta(days=1)

# --- Тесты для Password Hashing ---

def test_get_password_hash_generates_valid_hash():
    hashed_password = get_password_hash(TEST_PASSWORD)
    assert hashed_password is not None
    assert isinstance(hashed_password, str)
    assert len(hashed_password) > len(TEST_PASSWORD) # Хеш должен быть длиннее
    # Проверяем, что это не сам пароль
    assert hashed_password != TEST_PASSWORD

def test_verify_password_correct():
    hashed_password = get_password_hash(TEST_PASSWORD)
    assert verify_password(TEST_PASSWORD, hashed_password) is True

def test_verify_password_incorrect():
    hashed_password = get_password_hash(TEST_PASSWORD)
    assert verify_password("wrongpassword", hashed_password) is False

def test_verify_password_empty_plain():
    hashed_password = get_password_hash(TEST_PASSWORD)
    assert verify_password("", hashed_password) is False

def test_verify_password_empty_hashed():
    assert verify_password(TEST_PASSWORD, "") is False

def test_verify_password_both_empty():
    assert verify_password("", "") is False

def test_verify_password_invalid_hash_format():
    # Passlib's verify может вернуть False или выбросить ошибку в зависимости от формата
    # Наша функция verify_password ловит ValueError и возвращает False
    assert verify_password(TEST_PASSWORD, "not_a_valid_bcrypt_hash") is False

def test_get_password_hash_empty_password(caplog):
    get_password_hash("")
    assert "Attempting to hash an empty password." in caplog.text

# --- Тесты для JWT Token Handling ---

@pytest.fixture
def sample_token_data() -> Dict[str, Any]:
    return {"sub": "testuser@example.com", "user_id": str(uuid.uuid4())}

# Тесты для create_access_token
def test_create_access_token_success(sample_token_data: Dict[str, Any]):
    token = create_access_token(
        data=sample_token_data,
        secret_key=TEST_SECRET_KEY,
        expires_delta=SHORT_EXPIRES_DELTA
    )
    assert isinstance(token, str)

    payload = jwt.decode(token, TEST_SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["sub"] == sample_token_data["sub"]
    assert payload["user_id"] == sample_token_data["user_id"]
    assert payload["type"] == "access"
    assert "exp" in payload
    # Проверяем, что exp примерно равен ожидаемому (с небольшой дельтой на время выполнения)
    expected_exp = datetime.now(timezone.utc) + SHORT_EXPIRES_DELTA
    assert abs((datetime.fromtimestamp(payload["exp"], tz=timezone.utc) - expected_exp).total_seconds()) < 5

def test_create_access_token_no_secret_key_raises_error(sample_token_data: Dict[str, Any]):
    with pytest.raises(ValueError, match="Secret key must be provided"):
        create_access_token(data=sample_token_data, secret_key="", expires_delta=SHORT_EXPIRES_DELTA)

# Тесты для create_refresh_token (аналогичны access_token, но с type="refresh")
def test_create_refresh_token_success(sample_token_data: Dict[str, Any]):
    # Для refresh токена data может быть проще, например, только user_id
    refresh_data = {"user_id": sample_token_data["user_id"]}
    token = create_refresh_token(
        data=refresh_data,
        secret_key=TEST_SECRET_KEY,
        expires_delta=LONG_EXPIRES_DELTA
    )
    assert isinstance(token, str)

    payload = jwt.decode(token, TEST_SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["user_id"] == refresh_data["user_id"]
    assert payload["type"] == "refresh"
    assert "exp" in payload
    expected_exp = datetime.now(timezone.utc) + LONG_EXPIRES_DELTA
    assert abs((datetime.fromtimestamp(payload["exp"], tz=timezone.utc) - expected_exp).total_seconds()) < 5

def test_create_refresh_token_no_secret_key_raises_error(sample_token_data: Dict[str, Any]):
    with pytest.raises(ValueError, match="Secret key must be provided"):
        create_refresh_token(data=sample_token_data, secret_key="", expires_delta=LONG_EXPIRES_DELTA)

# Тесты для verify_token
def test_verify_token_success(sample_token_data: Dict[str, Any]):
    token = create_access_token(
        data=sample_token_data,
        secret_key=TEST_SECRET_KEY,
        expires_delta=SHORT_EXPIRES_DELTA
    )
    payload = verify_token(token, TEST_SECRET_KEY)
    assert payload["sub"] == sample_token_data["sub"]
    assert payload["user_id"] == sample_token_data["user_id"]

def test_verify_token_expired_raises_error(sample_token_data: Dict[str, Any]):
    # Создаем токен, который уже просрочен
    expired_delta = timedelta(seconds=-300) # 5 минут назад
    token = create_access_token(
        data=sample_token_data,
        secret_key=TEST_SECRET_KEY,
        expires_delta=expired_delta
    )
    with pytest.raises(ValueError, match="Could not validate credentials"): # Ожидаем credentials_exception по умолчанию
        verify_token(token, TEST_SECRET_KEY)

def test_verify_token_invalid_signature_raises_error(sample_token_data: Dict[str, Any]):
    token = create_access_token(
        data=sample_token_data,
        secret_key=TEST_SECRET_KEY,
        expires_delta=SHORT_EXPIRES_DELTA
    )
    with pytest.raises(ValueError, match="Could not validate credentials"):
        verify_token(token, "wrong-secret-key")

def test_verify_token_malformed_raises_error():
    malformed_token = "this.is.not.a.valid.jwt"
    with pytest.raises(ValueError, match="Could not validate credentials"):
        verify_token(malformed_token, TEST_SECRET_KEY)

def test_verify_token_no_user_id_raises_error():
    # Создаем токен без user_id в data
    data_no_user_id = {"sub": "test@example.com"} # Нет user_id
    token = create_access_token(
        data=data_no_user_id,
        secret_key=TEST_SECRET_KEY,
        expires_delta=SHORT_EXPIRES_DELTA
    )
    with pytest.raises(ValueError, match="Could not validate credentials"):
        verify_token(token, TEST_SECRET_KEY)

def test_verify_token_no_secret_key_raises_value_error(sample_token_data: Dict[str, Any]):
    token = create_access_token(data=sample_token_data, secret_key=TEST_SECRET_KEY, expires_delta=SHORT_EXPIRES_DELTA)
    with pytest.raises(ValueError, match="Secret key must be provided to verify token"):
        verify_token(token, "")

def test_verify_token_empty_token_string_raises_error():
    with pytest.raises(ValueError, match="Could not validate credentials"):
        verify_token("", TEST_SECRET_KEY)

def test_verify_token_custom_credentials_exception(sample_token_data: Dict[str, Any]):
    class CustomAuthError(Exception): pass

    token = create_access_token(data=sample_token_data, secret_key=TEST_SECRET_KEY, expires_delta=timedelta(seconds=-1))
    with pytest.raises(CustomAuthError):
        verify_token(token, TEST_SECRET_KEY, credentials_exception=CustomAuthError("Custom message"))