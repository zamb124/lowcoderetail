# Используем базовый образ Python, на котором работает MkDocs
FROM python:3.12-slim

# Устанавливаем рабочую директорию
WORKDIR /app/docs_src

# Копируем только необходимые файлы для сборки документации
COPY mkdocs.yml mkdocs.yml
COPY docs/ ./docs/

# Копируем исходный код core_sdk, так как mkdocstrings будет его анализировать
# Предполагается, что Dockerfile находится в корне проекта, где core_sdk - поддиректория
COPY core_sdk/ ./core_sdk/

# Устанавливаем MkDocs и необходимые плагины/темы
# Лучше зафиксировать версии для консистентности сборок
RUN pip install --no-cache-dir \
    mkdocs==1.6.1 \
    mkdocs-material==9.6.12 \
    mkdocstrings[python]~=0.29.1 \
    pymdown-extensions~=10.15

# Открываем порт, на котором MkDocs будет сервировать документацию
EXPOSE 8000

# Команда по умолчанию для сборки и запуска сервера MkDocs
# `mkdocs serve` по умолчанию слушает на 0.0.0.0:8000
# `--dev-addr 0.0.0.0:8000` явно указывает адрес
# `--no-livereload` можно добавить, если livereload не нужен в контейнере
CMD ["mkdocs", "serve", "--dev-addr", "0.0.0.0:8000"]

# Альтернативная команда, если вы хотите только собрать статику:
# CMD ["mkdocs", "build", "--site-dir", "/app/docs_site"]
# В этом случае вам понадобится веб-сервер (например, Nginx) для раздачи /app/docs_site