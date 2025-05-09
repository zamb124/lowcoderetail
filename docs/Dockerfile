# docs/Dockerfile
FROM python:3.12-slim

WORKDIR /app/docs_src

# Копируем только необходимые файлы для установки зависимостей документации
COPY pyproject.toml poetry.lock* /app/docs_src/

# Устанавливаем Poetry и зависимости только для группы 'docs' или 'dev', если там mkdocs
# Либо устанавливаем mkdocs и плагины напрямую через pip
RUN pip install poetry==1.7.1 && \
    poetry config virtualenvs.create false && \
    poetry install --no-dev --no-interaction --no-ansi --only main,docs # Предполагаем группу [tool.poetry.group.docs.dependencies]

# Если mkdocs и плагины не в poetry, а ставятся отдельно:
# RUN pip install mkdocs mkdocs-material mkdocstrings mkdocstrings-python

# Копируем весь остальной контент (исходники документации, mkdocs.yml, SDK, приложения)
# Это нужно, чтобы mkdocstrings мог найти исходный код для генерации документации по docstrings
COPY . /app/docs_src

WORKDIR /app/docs_src

EXPOSE 8000

# Команда для запуска mkdocs в режиме разработки (с live reload)
CMD ["mkdocs", "serve", "--dev-addr", "0.0.0.0:8000"]