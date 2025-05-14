# core_sdk/clients/base.py
import logging
import httpx
from typing import Type, TypeVar, List, Optional, Generic, Any, Dict, Mapping
from uuid import UUID
from pydantic import BaseModel as PydanticBaseModel, HttpUrl

from core_sdk.exceptions import ServiceCommunicationError

logger = logging.getLogger("core_sdk.clients.base")

# ModelType_client - это то, во что клиент парсит *одиночный* объект из ответа (обычно ReadSchema)
ModelType_client = TypeVar("ModelType_client", bound=PydanticBaseModel)
CreateSchemaType_client = TypeVar("CreateSchemaType_client", bound=PydanticBaseModel)
UpdateSchemaType_client = TypeVar("UpdateSchemaType_client", bound=PydanticBaseModel)


class RemoteServiceClient(Generic[ModelType_client, CreateSchemaType_client, UpdateSchemaType_client]):
    """
    Базовый HTTP-клиент для взаимодействия с удаленными CRUD API.
    """

    def __init__(
        self,
        base_url: HttpUrl,
        model_endpoint: str,
        model_cls: Type[ModelType_client], # Класс для парсинга одиночного объекта (ReadSchema)
        auth_token: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ):
        self.base_url_str = str(base_url).rstrip("/")
        self.model_endpoint_path = model_endpoint.strip("/")
        self.parsing_model_cls = model_cls # Класс, в который парсим ответы
        self.auth_token = auth_token
        self.api_base_url = f"{self.base_url_str}/{self.model_endpoint_path}"

        self._http_client = http_client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = http_client is None
        logger.debug(f"RemoteServiceClient initialized for API base: {self.api_base_url}. Owns client: {self._owns_client}")

    def _get_auth_headers(self) -> Dict[str, str]:
        # ... (без изменений) ...
        if self.auth_token:
            prefix = "Bearer "
            if self.auth_token.lower().startswith(prefix.lower()):
                return {"Authorization": self.auth_token}
            return {"Authorization": f"{prefix}{self.auth_token}"}
        return {}

    async def _request(
        self,
        method: str,
        url: str,
        allowed_statuses: Optional[List[int]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        # ... (без изменений) ...
        headers = self._get_auth_headers()
        headers.update(kwargs.pop("headers", {}))
        if "json" in kwargs and "Content-Type" not in headers: headers["Content-Type"] = "application/json"
        request_params_log = kwargs.get("params"); request_data_log = kwargs.get("json")
        logger.debug(f"Executing remote call: {method} {url}, Params: {request_params_log}, Data: {request_data_log}, Headers: {headers}")
        try:
            response = await self._http_client.request(method, url, headers=headers, **kwargs)
            effective_allowed_statuses = allowed_statuses if allowed_statuses is not None else [200, 201, 204]
            if response.status_code not in effective_allowed_statuses:
                logger.warning(f"Remote call to {url} returned unexpected status: {response.status_code}. Allowed: {effective_allowed_statuses}. Response text: {response.text[:500]}")
                response.raise_for_status()
            logger.debug(f"Remote call to {url} successful. Status: {response.status_code}")
            return response
        except httpx.TimeoutException as e:
            raise ServiceCommunicationError(f"Timeout error accessing {url}: {e!s}", url=url) from e
        except httpx.RequestError as e:
            raise ServiceCommunicationError(f"Network error accessing {url}: {e!s}", url=url) from e
        except httpx.HTTPStatusError as e:
            detail_message = e.response.text
            try:
                error_json = e.response.json()
                if isinstance(error_json, dict) and "detail" in error_json: detail_message = error_json["detail"]
            except Exception: pass
            raise ServiceCommunicationError(message=f"Service responded with error: {detail_message}", status_code=e.response.status_code, url=url) from e

    async def get(self, item_id: UUID) -> Optional[ModelType_client]:
        url = f"{self.api_base_url}/{item_id}"
        logger.info(f"Client GET: Fetching item with ID {item_id} from {url}")
        try:
            response = await self._request("GET", url, allowed_statuses=[200, 404])
            if response.status_code == 404: return None
            return self.parsing_model_cls.model_validate(response.json())
        except ServiceCommunicationError as e:
            if e.status_code != 404: raise
            return None

    async def list(
        self,
        *,
        cursor: Optional[int] = None,
        limit: int = 50,
        filters: Optional[Mapping[str, Any]] = None,
        direction: Optional[str] = "asc",
    ) -> Dict[str, Any]: # ИЗМЕНЕНО: Возвращает словарь
        url = f"{self.api_base_url}"
        params: Dict[str, Any] = {"limit": limit}
        if cursor is not None: params["cursor"] = cursor
        if direction is not None: params["direction"] = direction
        if filters:
            for key, value in filters.items():
                if value is not None:
                    if isinstance(value, list): params[key] = [str(v) for v in value]
                    else: params[key] = str(value)

        logger.info(f"Client LIST: Fetching list from {url} with params: {params}")
        response = await self._request("GET", url, params=params, allowed_statuses=[200])
        response_json = response.json()

        # Ожидаем, что удаленный API вернет структуру PaginatedResponse
        if not isinstance(response_json, dict) or "items" not in response_json:
            logger.error(f"Invalid paginated response format from {url}: expected dict with 'items', got {type(response_json)}")
            # Если формат неверный, пытаемся обработать как простой список для обратной совместимости,
            # но пагинация будет неполной.
            if isinstance(response_json, list):
                logger.warning(f"Remote API for {url} returned a list instead of paginated dict. Adapting response.")
                items_data = response_json
                return {
                    "items": [self.parsing_model_cls.model_validate(item_data) for item_data in items_data],
                    "next_cursor": None, # Не можем определить
                    "limit": limit,
                    "count": len(items_data)
                }
            raise ServiceCommunicationError(f"Invalid paginated list response format from {url}", url=url)

        items_data = response_json.get("items", [])
        if not isinstance(items_data, list):
            logger.error(f"Invalid 'items' format in paginated response from {url}: expected list, got {type(items_data)}")
            raise ServiceCommunicationError(f"Invalid 'items' format in paginated list response from {url}", url=url)

        deserialized_items = [self.parsing_model_cls.model_validate(item_data) for item_data in items_data]
        return {
            **response_json,
            "items": deserialized_items
        }

    async def create(self, data: CreateSchemaType_client) -> ModelType_client:
        url = f"{self.api_base_url}/"
        json_data = data.model_dump(mode="json")
        logger.info(f"Client CREATE: Posting to {url} with data: {json_data}")
        response = await self._request("POST", url, json=json_data, allowed_statuses=[201])
        return self.parsing_model_cls.model_validate(response.json())


    async def update(self, item_id: UUID, data: UpdateSchemaType_client) -> ModelType_client:
        url = f"{self.api_base_url}/{item_id}"
        json_data = data.model_dump(mode="json", exclude_unset=True)
        logger.info(f"Client UPDATE: Putting to {url} for ID {item_id} with data: {json_data}")
        response = await self._request("PUT", url, json=json_data, allowed_statuses=[200])
        return self.parsing_model_cls.model_validate(response.json())

    async def delete(self, item_id: UUID) -> bool:
        url = f"{self.api_base_url}/{item_id}"
        logger.info(f"Client DELETE: Deleting item {item_id} at {url}")
        try:
            await self._request("DELETE", url, allowed_statuses=[204, 404])
            return True
        except ServiceCommunicationError: raise

    async def close(self) -> None:
        if self._owns_client and self._http_client:
            logger.info(f"Closing owned HTTP client for {self.api_base_url}")
            try: await self._http_client.aclose()
            except Exception as e: logger.error(f"Error closing owned HTTP client for {self.api_base_url}: {e}", exc_info=True)
        elif not self._owns_client:
            logger.debug(f"HTTP client for {self.api_base_url} is managed externally, not closing.")