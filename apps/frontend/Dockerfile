# Этап сборки зависимостей
FROM python:3.12-slim as builder

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
WORKDIR /install

# Устанавливаем Poetry
RUN pip install poetry==1.7.1 # Используйте версию, указанную в core_sdk

# Копируем файлы зависимостей
COPY ./pyproject.toml ./poetry.lock* /install/

# Устанавливаем зависимости, включая опциональные (например, redis)
# --no-dev: не устанавливать dev зависимости
# --no-root: не устанавливать сам проект (frontend), только его зависимости
RUN poetry config virtualenvs.create false && \
    poetry install --no-dev --no-interaction --no-ansi --no-root --extras "redis"

# --- Основной этап ---
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV ENV=prod

WORKDIR /app

# Копируем установленные зависимости из builder'а
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копируем код SDK (предполагается, что Dockerfile в корне проекта)
COPY ./core_sdk ./core_sdk

# Копируем код сервиса frontend
COPY ./apps/frontend/app ./app
COPY ./apps/frontend/.env.example ./.env # Используем .env.example как базовый .env

# Открываем порт (из .env будет прочитано конкретное значение)
# EXPOSE 8080 # Можно закомментировать, т.к. порт берется из env

# Команда запуска (использует порт из .env)
# Замените на production-ready сервер, если нужно (например, gunicorn + uvicorn workers)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${FRONTEND_PORT:-8080}"]