# Брокер задач (Taskiq)

Интеграция с Taskiq позволяет выполнять длительные или ресурсоемкие операции в фоновом режиме, не блокируя основной поток обработки HTTP-запросов.

## Настройка брокера (`core_sdk.broker.setup`)

Модуль `core_sdk.broker.setup` отвечает за инициализацию экземпляра брокера Taskiq.
В зависимости от переменной окружения `ENV`, используется:
*   `InMemoryBroker`: для тестового окружения (`ENV=test`) или если Redis недоступен.
*   `RedisStreamBroker`: для production и development окружений, если `REDIS_URL` настроен.

Экземпляр брокера доступен как `core_sdk.broker.setup.broker`.

## Задачи (`core_sdk.broker.tasks`)

### `execute_dam_operation`
Основная задача Taskiq, предназначенная для выполнения методов `DataAccessManager` (DAM) в воркере.
Она принимает имя модели, имя метода и сериализованные аргументы, выполняет соответствующий метод DAM в контексте сессии БД и возвращает результат.

::: core_sdk.broker.tasks.execute_dam_operation
    handler: python
    options:
      heading_level: 3

## Настройка воркера (`core_sdk.worker_setup`)
Утилиты для инициализации и завершения работы контекста воркера Taskiq.

::: core_sdk.worker_setup.initialize_worker_context
    handler: python
    options:
      heading_level: 3
::: core_sdk.worker_setup.shutdown_worker_context
    handler: python
    options:
      heading_level: 3

## Использование в сервисах

1.  **Файл `app/worker.py` в сервисе:**
    Создается файл, который импортирует `broker` из SDK и определяет хуки `startup` и `shutdown`, вызывающие `initialize_worker_context` и `shutdown_worker_context`. `initialize_worker_context` должен получить путь к `registry_config.py` вашего сервиса.

2.  **Запуск воркера:**
    ```bash
    taskiq worker my_service.app.worker:broker --fs-discover --on-startup my_service.app.worker:startup --on-shutdown my_service.app.worker:shutdown
    ```

3.  **Отправка задач из API:**
    `BaseDataAccessManager` имеет property `broker`, которое возвращает экземпляр `BrokerTaskProxy`. Вызов метода DAM через этот прокси автоматически отправит задачу в Taskiq.

    ```python
    # В вашем API эндпоинте или сервисной логике
    dam_factory: DataAccessManagerFactory = Depends(get_dam_factory)
    my_manager = dam_factory.get_manager("MyModel")

    # Этот вызов будет выполнен асинхронно через Taskiq,
    # если my_manager.broker используется для вызова метода.
    # BrokerTaskProxy.kiq() отправляет задачу и возвращает TaskiqResult для ожидания.
    task_result = await my_manager.broker.some_long_operation(arg1, arg2, _broker_timeout=30)
    # result = await task_result.wait_result(timeout=...) # Если нужно дождаться результата
    ```