# apps/purchase/Dockerfile
FROM python:3.12-slim as builder

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
WORKDIR /app_builder

RUN pip install poetry==1.7.1

COPY pyproject.toml poetry.lock* ./

RUN poetry config virtualenvs.create false && \
    poetry install --no-dev --no-interaction --no-ansi --only main

# --- Финальный образ ---
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV ENV=${ENV:-prod}

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY ./core_sdk ./core_sdk
COPY ./apps/purchase/app ./app
# Копируем alembic.ini и директорию alembic для миграций
COPY ./apps/purchase/alembic.ini ./app/alembic.ini
COPY ./apps/purchase/alembic ./app/alembic


# Если purchase вызывает core и схемы core не в SDK, скопируйте их:
# COPY ./apps/core/app/schemas ./apps/core/app/schemas
# COPY ./apps/core/app/models ./apps/core/app/models

COPY ./apps/purchase/start-purchase.sh /start-purchase.sh
RUN chmod +x /start-purchase.sh

# Порт будет браться из переменной окружения PURCHASE_PORT
EXPOSE 8002

# CMD определяется в docker-compose.yml (через start-purchase.sh)
# CMD ["/start-purchase.sh"]