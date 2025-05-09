#!/bin/bash
set -e # Остановить выполнение при ошибке

# Используем переменные окружения, переданные из docker-compose.yml
# Эти переменные должны быть определены в docker-compose.yml или в .env файле, который он читает

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_INIT_DB" <<-EOSQL
    -- Создание пользователя и БД для Core сервиса
    CREATE USER $CORE_DB_USER WITH PASSWORD '$CORE_DB_PASSWORD';
    CREATE DATABASE $CORE_DB_NAME;
    GRANT ALL PRIVILEGES ON DATABASE $CORE_DB_NAME TO $CORE_DB_USER;
    \c $CORE_DB_NAME; -- Подключиться к созданной БД
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- Для gen_random_uuid() если используется
    CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- Для pgcrypto функций, если используются

    -- Создание пользователя и БД для Frontend сервиса (если ему нужна своя БД)
    -- Обычно BFF не имеет своей БД, но если вдруг нужна:
    -- CREATE USER $FRONTEND_DB_USER WITH PASSWORD '$FRONTEND_DB_PASSWORD';
    -- CREATE DATABASE $FRONTEND_DB_NAME;
    -- GRANT ALL PRIVILEGES ON DATABASE $FRONTEND_DB_NAME TO $FRONTEND_DB_USER;
    -- \c $FRONTEND_DB_NAME;
    -- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    -- CREATE EXTENSION IF NOT EXISTS "pgcrypto";

    -- Создание пользователя и БД для Purchase сервиса
    CREATE USER $PURCHASE_DB_USER WITH PASSWORD '$PURCHASE_DB_PASSWORD';
    CREATE DATABASE $PURCHASE_DB_NAME;
    GRANT ALL PRIVILEGES ON DATABASE $PURCHASE_DB_NAME TO $PURCHASE_DB_USER;
    \c $PURCHASE_DB_NAME;
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS "pgcrypto";

    -- Добавьте здесь создание других БД для других сервисов по аналогии

EOSQL

echo "Databases and users created successfully!"