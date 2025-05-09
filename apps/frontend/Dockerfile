# apps/frontend/Dockerfile
FROM python:3.12-slim as builder

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
WORKDIR /app_builder

RUN pip install poetry==1.7.1

COPY pyproject.toml poetry.lock* ./

# Устанавливаем зависимости, включая опциональные (например, redis для frontend, если он его использует)
# --no-root, т.к. сам frontend не является пакетом, который нужно устанавливать
# Устанавливаем только main группу и опциональные, если они нужны для frontend
RUN poetry config virtualenvs.create false && \
    poetry install --no-dev --no-interaction --no-ansi --only main # --extras "redis" - если нужны

# --- Основной этап ---
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV ENV=${ENV:-prod}

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копируем код SDK
COPY ./core_sdk ./core_sdk

# Копируем код сервиса frontend
COPY ./apps/frontend/app ./app

# Копируем схемы и модели Core, если они нужны для ModelRegistry в Frontend
# Это необходимо, если Frontend использует RemoteConfig для доступа к Core
# и эти схемы/модели еще не вынесены в core_sdk
COPY ./apps/core/app/schemas ./apps/core/app/schemas
COPY ./apps/core/app/models ./apps/core/app/models

# Копируем .env.example как .env по умолчанию
# Переменные из docker-compose.yml или .env файла в корне проекта их переопределят
COPY ./apps/frontend/.env.example ./.env

# Порт будет браться из переменной окружения FRONTEND_PORT
EXPOSE 8080

# Команда запуска (использует порт из .env или дефолтный 8080)
# Путь к приложению теперь apps.frontend.app.main:app
CMD ["uvicorn", "apps.frontend.app.main:app", "--host", "0.0.0.0", "--port", "${FRONTEND_PORT:-8080}"]