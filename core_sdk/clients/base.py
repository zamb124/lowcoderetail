# core_sdk/clients/base.py
import logging
import httpx
from typing import Type, TypeVar, List, Optional, Generic, Any, Dict, Mapping
from uuid import UUID
from pydantic import BaseModel as PydanticBaseModel, HttpUrl
from sqlmodel import SQLModel

from core_sdk.exceptions import (
    ServiceCommunicationError,
)  # ConfigurationError не используется здесь

# Получаем логгер для этого модуля
logger = logging.getLogger("core_sdk.clients.base")

# Типы для моделей и схем, используемых клиентом
ModelType = TypeVar("ModelType", bound=SQLModel)  # Модель ответа, обычно SQLModel
CreateSchemaType = TypeVar(
    "CreateSchemaType", bound=PydanticBaseModel
)  # Схема для создания объекта
UpdateSchemaType = TypeVar(
    "UpdateSchemaType", bound=PydanticBaseModel
)  # Схема для обновления объекта


class RemoteServiceClient(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """
    Базовый класс для асинхронных HTTP-клиентов, взаимодействующих с удаленными API сервисов,
    которые следуют стандартному CRUD-паттерну, принятому на платформе.

    Предполагается, что удаленный сервис предоставляет эндпоинты вида:
    - GET /<model_endpoint>/{item_id}
    - POST /<model_endpoint>/
    - PUT /<model_endpoint>/{item_id}
    - DELETE /<model_endpoint>/{item_id}
    - GET /<model_endpoint>/list/ (с параметрами cursor и limit)
    """

    def __init__(
        self,
        base_url: HttpUrl,
        model_endpoint: str,
        model_cls: Type[ModelType],
        auth_token: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ):
        """
        Инициализирует HTTP-клиент для взаимодействия с удаленным сервисом.

        :param base_url: Базовый URL удаленного сервиса (например, "http://users-service:8000").
        :param model_endpoint: Базовый путь API для конкретной модели (например, "/users" или "products").
        :param model_cls: Класс SQLModel/Pydantic, представляющий удаленную модель.
                          Используется для парсинга ответов от сервиса.
        :param auth_token: Опциональный токен аутентификации (Bearer token).
        :param http_client: Опциональный, предварительно сконфигурированный экземпляр `httpx.AsyncClient`.
                            Если None, будет создан новый клиент. Передача клиента извне полезна
                            для управления соединениями на уровне приложения.
        :param timeout: Таймаут для HTTP-запросов в секундах.
        """
        self.base_url = str(base_url).rstrip("/")
        self.model_endpoint = "/" + model_endpoint.strip("/")
        self.model_cls = model_cls
        self.auth_token = auth_token
        # Полный базовый URL для API конкретной модели, например: "http://users-service:8000/api/v1/users"
        self.api_base_url = f"{self.base_url}{self.model_endpoint}"

        self._http_client = http_client or httpx.AsyncClient(timeout=timeout)
        # Флаг, указывающий, был ли клиент создан внутри этого экземпляра
        # или передан извне. Это важно для корректного закрытия клиента.
        self._owns_client = http_client is None
        logger.debug(
            f"RemoteServiceClient initialized for {self.api_base_url}. Owns client: {self._owns_client}"
        )

    def _get_auth_headers(self) -> Dict[str, str]:
        """Формирует заголовки авторизации, если присутствует токен."""
        if self.auth_token:
            if self.auth_token.startswith("Bearer "):
                return {"Authorization": self.auth_token}
            return {"Authorization": f"Bearer {self.auth_token}"}
        return {}

    async def _request(
        self,
        method: str,
        url: str,
        allowed_statuses: Optional[List[int]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Выполняет HTTP-запрос и обрабатывает основные ошибки.

        :param method: HTTP-метод (GET, POST, PUT, DELETE, etc.).
        :param url: Полный URL для запроса.
        :param allowed_statuses: Список HTTP статус-кодов, которые считаются успешными
                                 и не вызывают исключение `HTTPStatusError`.
                                 Если None, используются стандартные [200, 201, 204].
        :param kwargs: Дополнительные аргументы для `httpx.request` (например, `json`, `params`).
        :return: Объект `httpx.Response`.
        :raises ServiceCommunicationError: При ошибках сети, таймаутах или HTTP-ошибках.
        """
        headers = self._get_auth_headers()
        headers.update(kwargs.pop("headers", {}))

        if "json" in kwargs and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        request_params_log = kwargs.get("params")
        request_data_log = kwargs.get("json")
        logger.debug(
            f"Executing remote call: {method} {url}, Params: {request_params_log}, Data: {request_data_log}, Headers: {headers}"
        )

        try:
            response = await self._http_client.request(
                method, url, headers=headers, **kwargs
            )

            effective_allowed_statuses = (
                allowed_statuses if allowed_statuses is not None else [200, 201, 204]
            )

            if response.status_code not in effective_allowed_statuses:
                logger.warning(
                    f"Remote call to {url} returned unexpected status: {response.status_code}. "
                    f"Allowed: {effective_allowed_statuses}. Response text: {response.text[:500]}"
                )
                # Вызовет HTTPStatusError, если статус не в списке разрешенных
                response.raise_for_status()

            logger.debug(
                f"Remote call to {url} successful. Status: {response.status_code}"
            )
            return response

        except httpx.TimeoutException as e:
            logger.error(f"Timeout error accessing {url}: {e}", exc_info=True)
            raise ServiceCommunicationError(
                f"Timeout error accessing {url}: {e!s}", url=url
            ) from e
        except httpx.RequestError as e:
            # Ошибки сети, соединения и т.д.
            logger.error(f"Network error accessing {url}: {e}", exc_info=True)
            raise ServiceCommunicationError(
                f"Network error accessing {url}: {e!s}", url=url
            ) from e
        except httpx.HTTPStatusError as e:
            # HTTP ошибки (4xx, 5xx), которые не были в allowed_statuses
            detail_message = e.response.text
            try:
                # Попытка извлечь более структурированное сообщение об ошибке из JSON ответа
                error_json = e.response.json()
                if isinstance(error_json, dict) and "detail" in error_json:
                    detail_message = error_json["detail"]
            except Exception:
                # Если тело ответа не JSON или нет ключа "detail", используем полный текст
                pass
            logger.error(
                f"Service error accessing {url}: Status {e.response.status_code}, Detail: {detail_message}",
                exc_info=True,
            )
            raise ServiceCommunicationError(
                message=f"Service responded with error: {detail_message}",
                status_code=e.response.status_code,
                url=url,
            ) from e

    async def get(self, item_id: UUID) -> Optional[ModelType]:
        """
        Получает один объект по его ID.

        :param item_id: UUID объекта.
        :return: Экземпляр `ModelType` или `None`, если объект не найден (404).
        :raises ServiceCommunicationError: При других ошибках связи.
        """
        url = f"{self.api_base_url}/{item_id}"
        logger.info(f"Fetching item with ID {item_id} from {url}")
        try:
            # Разрешаем 404, так как это ожидаемый случай "не найдено"
            response = await self._request("GET", url, allowed_statuses=[200, 404])
            if response.status_code == 404:
                logger.info(f"Item with ID {item_id} not found at {url} (404).")
                return None
            # Используем model_validate для Pydantic v2 / SQLModel >= 0.0.15
            return self.model_cls.model_validate(response.json())
        except ServiceCommunicationError as e:
            # Перебрасываем ошибки связи, кроме 404, которая уже обработана
            if (
                e.status_code != 404
            ):  # Эта проверка может быть избыточной, если _request корректно обрабатывает allowed_statuses
                logger.error(
                    f"Failed to get item {item_id} from {url}: {e}", exc_info=True
                )
                raise
            return None  # Явный возврат None, если ошибка была 404 и прошла через ServiceCommunicationError

    async def list(
        self,
        *,
        cursor: Optional[int] = None,
        limit: int = 50,
        filters: Optional[Mapping[str, Any]] = None,
        direction: Optional[
            str
        ] = "asc",  # Добавим direction, если API его поддерживает
    ) -> List[ModelType]:  # Возвращает список моделей
        url = f"{self.api_base_url}"  # Для списка обычно базовый URL ресурса
        params: Dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        if direction is not None:
            params["direction"] = direction  # Добавляем direction в параметры
        if filters:
            for key, value in filters.items():
                if value is not None:
                    if isinstance(
                        value, list
                    ):  # Если фильтр - это список (например, для id__in)
                        # httpx правильно обработает список значений для одного ключа query параметра
                        params[key] = [str(v) for v in value]
                    else:
                        params[key] = str(value)

        logger.info(f"Fetching list of items from {url} with params: {params}")
        response = await self._request(
            "GET", url, params=params, allowed_statuses=[200]
        )
        response_json = response.json()

        # Проверяем, является ли ответ словарем с ключом 'items' (как от PaginatedResponse)
        if isinstance(response_json, dict) and "items" in response_json:
            items_data = response_json["items"]
        elif isinstance(response_json, list):  # Если API сразу возвращает список
            items_data = response_json
        else:
            logger.error(
                f"Invalid response format from {url} for list: expected a list or dict with 'items', got {type(response_json)}"
            )
            raise ServiceCommunicationError(
                f"Invalid list response format from {url}", url=url
            )

        if not isinstance(items_data, list):
            logger.error(
                f"Invalid 'items' format in list response from {url}: expected a list, got {type(items_data)}"
            )
            raise ServiceCommunicationError(
                f"Invalid 'items' format in list response from {url}", url=url
            )

        return [self.model_cls.model_validate(item) for item in items_data]

    async def create(self, data: CreateSchemaType) -> ModelType:
        """
        Создает новый объект на удаленном сервисе.

        :param data: Экземпляр `CreateSchemaType` с данными для создания.
        :return: Экземпляр `ModelType` созданного объекта.
        :raises ServiceCommunicationError: При ошибках связи.
        """
        url = f"{self.api_base_url}/"
        # Используем model_dump для Pydantic v2 / SQLModel >= 0.0.15
        json_data = data.model_dump(mode="json")
        logger.info(f"Creating new item at {url} with data: {json_data}")
        # Ожидаем статус 201 Created
        response = await self._request(
            "POST", url, json=json_data, allowed_statuses=[201]
        )
        return self.model_cls.model_validate(response.json())

    async def update(self, item_id: UUID, data: UpdateSchemaType) -> ModelType:
        """
        Обновляет существующий объект на удаленном сервисе.

        :param item_id: UUID объекта для обновления.
        :param data: Экземпляр `UpdateSchemaType` с полями для обновления.
                     Используется `exclude_unset=True` при сериализации,
                     чтобы отправлять только измененные поля.
        :return: Экземпляр `ModelType` обновленного объекта.
        :raises ServiceCommunicationError: При ошибках связи.
        """
        url = f"{self.api_base_url}/{item_id}"
        # exclude_unset=True важно, чтобы отправлять только переданные поля
        json_data = data.model_dump(mode="json", exclude_unset=True)
        logger.info(f"Updating item {item_id} at {url} with data: {json_data}")
        # Ожидаем статус 200 OK
        response = await self._request(
            "PUT", url, json=json_data, allowed_statuses=[200]
        )
        return self.model_cls.model_validate(response.json())

    async def delete(self, item_id: UUID) -> bool:
        """
        Удаляет объект по его ID на удаленном сервисе.

        :param item_id: UUID объекта для удаления.
        :return: True, если удаление прошло успешно (статус 204 или 404), иначе False.
        """
        url = f"{self.api_base_url}/{item_id}"
        logger.info(f"Deleting item {item_id} at {url}")
        try:
            # Ожидаем 204 No Content для успешного удаления.
            # Разрешаем 404, считая это успехом (идемпотентность - объект уже удален).
            await self._request("DELETE", url, allowed_statuses=[204, 404])
            logger.info(
                f"Item {item_id} deleted (or was already not found) successfully from {url}."
            )
            return True
        except ServiceCommunicationError as e:
            # Логируем ошибку, если это не 404 (который уже считается успехом)
            # Фактически, если _request работает правильно с allowed_statuses,
            # сюда должны попадать только непредвиденные ошибки, а не 204/404.
            logger.error(f"Error deleting item {item_id} at {url}: {e}", exc_info=True)
            raise e  # Возвращаем False при ошибке

    async def close(self) -> None:
        """
        Закрывает нижележащий HTTP-клиент, если данный экземпляр `RemoteServiceClient`
        создал его (т.е., `self._owns_client` равен True).
        Этот метод следует вызывать при завершении работы приложения или сервиса,
        чтобы освободить ресурсы.
        """
        if self._owns_client and self._http_client:
            logger.info(f"Closing owned HTTP client for {self.api_base_url}")
            try:
                await self._http_client.aclose()
                logger.info(
                    f"Owned HTTP client for {self.api_base_url} closed successfully."
                )
            except Exception as e:
                logger.error(
                    f"Error closing owned HTTP client for {self.api_base_url}: {e}",
                    exc_info=True,
                )
        elif not self._owns_client:
            logger.debug(
                f"HTTP client for {self.api_base_url} is managed externally, not closing."
            )
