# purchase/Dockerfile
FROM python:3.12-slim as builder

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
WORKDIR /app

# Устанавливаем Poetry (укажите вашу версию)
RUN pip install poetry==1.7.1

# Копируем файлы зависимостей из корня проекта
# Предполагается, что Dockerfile собирается из корня проекта (lowcoderetail/)
COPY pyproject.toml poetry.lock* ./

# Устанавливаем зависимости проекта, не включая dev-зависимости
RUN poetry config virtualenvs.create false && \
    poetry install --no-dev --no-interaction --no-ansi

# --- Финальный образ ---
FROM python:3.12-slim
WORKDIR /app

# Копируем установленные зависимости из builder-стадии
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копируем код приложения purchase/app и общую core_sdk
# Пути указаны относительно контекста сборки (корня проекта)
COPY ./purchase/app ./app
COPY ./core_sdk ./core_sdk

# Открываем порт, на котором будет работать FastAPI (должен совпадать с PORT_PURCHASE в .env)
EXPOSE 8002

# Команда для запуска приложения
CMD ["uvicorn", "purchase.app.main:app", "--host", "0.0.0.0", "--port", "8002"]