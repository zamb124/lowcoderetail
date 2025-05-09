#!/bin/sh
set -e

# Запуск миграций Alembic для purchase сервиса
echo "Running Purchase Alembic migrations..."
alembic -c /app/app/alembic.ini upgrade head # Путь к alembic.ini внутри контейнера

# Запуск Taskiq worker в фоновом режиме (если у purchase есть воркер)
# echo "Starting Purchase Taskiq worker..."
# taskiq worker apps.purchase.app.worker:broker \
#     --fs-discover \
#     --on-startup apps.purchase.app.worker:startup \
#     --on-shutdown apps.purchase.app.worker:shutdown &

# Запуск Uvicorn API сервера
echo "Starting Purchase Uvicorn API server..."
exec uvicorn apps.purchase.app.main:app --host 0.0.0.0 --port 8002