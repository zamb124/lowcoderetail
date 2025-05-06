# Быстрый старт

Это руководство поможет вам быстро настроить окружение и запустить основные компоненты фреймворка.

## Требования

*   Python 3.11 или выше
*   Poetry (менеджер зависимостей Python)
*   Docker и Docker Compose
*   Git

## Установка и запуск

1.  **Клонируйте репозиторий:**
    ```bash
    git clone https://github.com/zamb124/lowcoderetail.git # TODO: Замените URL
    cd lowcoderetail
    ```

2.  **Настройка переменных окружения:**
    Скопируйте файлы `.env_example` в соответствующие `.env` файлы для каждого сервиса (например, `core/.env_example` -> `core/.env`) и для корневого `docker-compose.yml` (если есть корневой `.env_example`).
    Заполните необходимые значения, особенно `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`.

    Пример для `core/.env`:
    ```env
    ENV=dev
    PROJECT_NAME=CoreService
    LOGGING_LEVEL=INFO
    DATABASE_URL=postgresql+asyncpg://main_user:main_password@db:5432/main_db
    REDIS_URL=redis://redis:6379/0
    SECRET_KEY=your_super_secret_key_for_core_service # TODO: Сгенерируйте надежный ключ
    # ... остальные переменные
    ```

3.  **Инициализация базы данных (первый запуск):**
    В корне проекта находится скрипт `init-db.sh`. Он будет выполнен при первом запуске контейнера `db` и должен создать основную базу данных и пользователя, указанных в `docker-compose.yml`. Убедитесь, что он корректен.

4.  **Сборка и запуск сервисов через Docker Compose:**
    ```bash
    docker-compose up --build -d
    ```
    Эта команда соберет образы (если они изменились) и запустит все сервисы в фоновом режиме.

5.  **Применение миграций Alembic (для `core` сервиса):**
    После того как база данных запущена, необходимо применить миграции для `core` сервиса (и для других сервисов, если у них есть свои БД и миграции).
    ```bash
    docker-compose exec core alembic -c /app/alembic.ini upgrade head
    ```
    Или, если вы настроили `script_location` в `alembic.ini` относительно корня проекта при сборке Docker-образа:
    ```bash
    docker-compose exec core alembic upgrade head
    ```
    *Примечание: Путь к `alembic.ini` и команда `alembic` могут немного отличаться в зависимости от того, как настроен `WORKDIR` и `CMD` в Dockerfile сервиса.*

6.  **Проверка работы:**
    *   **Core API**: Откройте в браузере `http://localhost:8000/docs` (или порт, указанный для `core` сервиса).
    *   **Логи сервисов**: `docker-compose logs -f core core-worker` (и для других сервисов).

## Следующие шаги

*   Изучите документацию по [Core SDK](core_sdk/index.md).
*   Следуйте руководству по [Созданию нового сервиса](creating_new_service.md).