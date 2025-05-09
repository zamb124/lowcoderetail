#!/bin/sh
set -e

# Запуск миграций Alembic для core сервиса
echo "Running Core Alembic migrations..."
alembic -c /app/app/alembic.ini upgrade head # Путь к alembic.ini внутри контейнера

# Запуск Taskiq worker в фоновом режиме
echo "Starting Core Taskiq worker..."
taskiq worker apps.core.app.worker:broker \
    --fs-discover \
    --on-startup apps.core.app.worker:startup \
    --on-shutdown apps.core.app.worker:shutdown & # & - для запуска в фоне

# Запуск Uvicorn API сервера
echo "Starting Core Uvicorn API server..."
exec uvicorn apps.core.app.main:app --host 0.0.0.0 --port 8000
# exec используется, чтобы uvicorn стал PID 1 и правильно обрабатывал сигналы