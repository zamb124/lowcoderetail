# Используем базовый образ Python 3.11 (или ваша версия)
FROM python:3.12-slim as builder

# Устанавливаем переменные окружения
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем Poetry
RUN pip install poetry==1.7.1 # Укажите вашу версию Poetry, если нужно

# Копируем файлы зависимостей из директории wms
COPY pyproject.toml poetry.lock* ./

# Устанавливаем зависимости проекта, не включая dev-зависимости
RUN poetry config virtualenvs.create false && \
    poetry install --no-dev --no-interaction --no-ansi

# --- Финальный образ ---
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем установленные зависимости из builder-стадии
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копируем код приложения wms
COPY ./app ./app

# Открываем порт для WMS сервиса
EXPOSE 8001

# Команда для запуска WMS приложения
CMD ["uvicorn", "wms.app.main:app", "--host", "0.0.0.0", "--port", "8001"]