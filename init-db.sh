#!/bin/bash
set -e # Остановить выполнение при ошибке

# Переменные из .env файлов ваших сервисов (здесь для примера, замените на реальные)
# Вы можете либо жестко задать их здесь, либо передать через environment в docker-compose.yml для db сервиса
CORE_DB_USER=${CORE_DB_USER:-core_user}
CORE_DB_PASSWORD=${CORE_DB_PASSWORD:-your_strong_password_core}
CORE_DB_NAME=${CORE_DB_NAME:-core_db}

WMS_DB_USER=${WMS_DB_USER:-wms_user}
WMS_DB_PASSWORD=${WMS_DB_PASSWORD:-your_strong_password_wms}
WMS_DB_NAME=${WMS_DB_NAME:-wms_db}

# Используем переменные окружения POSTGRES_USER и POSTGRES_DB, заданные в docker-compose.yml
# для подключения к psql
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Создание пользователя и БД для Core сервиса
    CREATE USER $CORE_DB_USER WITH PASSWORD '$CORE_DB_PASSWORD';
    CREATE DATABASE $CORE_DB_NAME;
    GRANT ALL PRIVILEGES ON DATABASE $CORE_DB_NAME TO $CORE_DB_USER;

    -- Создание пользователя и БД для WMS сервиса
    CREATE USER $WMS_DB_USER WITH PASSWORD '$WMS_DB_PASSWORD';
    CREATE DATABASE $WMS_DB_NAME;
    GRANT ALL PRIVILEGES ON DATABASE $WMS_DB_NAME TO $WMS_DB_USER;

    -- Можно добавить расширения, если нужно (например, для UUID)
    -- \c $CORE_DB_NAME; -- Подключиться к созданной БД
    -- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    -- \c $WMS_DB_NAME;
    -- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

EOSQL

echo "Databases and users created successfully!"