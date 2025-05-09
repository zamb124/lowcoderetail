# apps/core/Dockerfile
FROM python:3.12-slim as builder

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
WORKDIR /app_builder

# Устанавливаем Poetry
RUN pip install poetry==1.7.1 # Укажите вашу актуальную версию Poetry

# Копируем pyproject.toml и poetry.lock из корня проекта
# Контекст сборки docker-compose - корень проекта
COPY pyproject.toml poetry.lock* ./

# Устанавливаем зависимости проекта, НЕ включая dev-зависимости
# Отключаем создание virtualenv внутри образа, ставим в систему
RUN poetry config virtualenvs.create false && \
    poetry install --no-dev --no-interaction --no-ansi --only main # Устанавливаем только main группу

# --- Финальный образ ---
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV ENV=prod # Установите prod для production

WORKDIR /app

# Копируем установленные зависимости из builder-стадии
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копируем код core_sdk из корня проекта
COPY ./core_sdk ./core_sdk

# Копируем код приложения core
COPY ./apps/core/app ./app

# Копируем стартовый скрипт
COPY ./apps/core/start-core.sh /start-core.sh
RUN chmod +x /start-core.sh

# Открываем порт, на котором будет работать FastAPI
EXPOSE 8000

# CMD определяется в docker-compose или в start-core.sh
# CMD ["/start-core.sh"]