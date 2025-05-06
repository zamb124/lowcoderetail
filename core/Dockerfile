# Используем базовый образ Python 3.11 (или ваша версия)
FROM python:3.12-slim as builder

# Устанавливаем переменные окружения
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем Poetry
RUN pip install poetry==1.7.1 # Укажите вашу версию Poetry, если нужно

# Копируем файлы зависимостей
COPY pyproject.toml poetry.lock* ./

# Устанавливаем зависимости проекта, не включая dev-зависимости
# Отключаем создание virtualenv внутри образа, ставим в систему
RUN poetry config virtualenvs.create false && \
    poetry install --no-dev --no-interaction --no-ansi

# --- Финальный образ ---
FROM python:3.12-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем установленные зависимости из builder-стадии
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копируем код приложения (app и core_sdk)
# Убедитесь, что структура соответствует: /app/app и /app/core_sdk
COPY ./app ./app
COPY ./core_sdk ./core_sdk

# Открываем порт, на котором будет работать FastAPI
EXPOSE 8000

# Команда для запуска приложения (без --reload для production)
# Uvicorn будет искать core.app.main внутри /app
CMD ["uvicorn", "core.app.main:app", "--host", "0.0.0.0", "--port", "8000"]