# hash_my_password.py
import sys
from getpass import getpass # Для безопасного ввода пароля

# --- Убедитесь, что SDK доступен ---
# Добавляем корень проекта в PYTHONPATH, если скрипт запускается из корня
# import os
# project_root = os.path.dirname(os.path.abspath(__file__))
# sys.path.insert(0, project_root)
# ---------------------------------

try:
    # Импортируем функцию хеширования из вашего SDK
    from core_sdk.security import get_password_hash
except ImportError:
    print("Error: Could not import get_password_hash from core_sdk.security.")
    print("Make sure you run this script from the project root or adjust sys.path.")
    sys.exit(1)

print("Enter the password for the new user:")
# Используем getpass, чтобы пароль не отображался при вводе
password = getpass()

if not password:
    print("Password cannot be empty.")
    sys.exit(1)

# Генерируем хеш
hashed_password = get_password_hash(password)

print("\nGenerated Hashed Password:")
print("----------------------------")
print(hashed_password)
print("----------------------------")
print("Copy this hash and use it in the SQL INSERT statement for the 'users' table.")

"""
 INSERT INTO users (
    email,
    hashed_password,
    is_active,
    is_superuser,
    company_id,
    first_name,
    last_name
) VALUES (
    'admin1@example.com',  -- Замените на email вашего администратора
    '$2b$12$bbzSZy8MgOJkuVLhsZSDBeC0BtZRApF.Oan.QUWzvRe5F7VwZObYa', -- Вставьте сюда хеш
    TRUE,                 -- Пользователь активен
    TRUE,                 -- Сделать суперпользователем (ВАЖНО для первого админа)
    'UUID_КОМПАНИИ_ИЗ_ШАГА_1', -- Вставьте сюда UUID компании
    'Admin',              -- Опционально: Имя
    'User'                -- Опционально: Фамилия
);
 """