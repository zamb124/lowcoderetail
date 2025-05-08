# apps/frontend/app/ws_manager.py
import logging
import json
from typing import Dict, List, Set, Optional
from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger("app.ws_manager")

class ConnectionManager:
    def __init__(self):
        # Храним активные соединения: {user_id: {websocket1, websocket2}}
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        """Принимает соединение и добавляет его в пул."""
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        logger.info(f"User '{user_id}' connected via WebSocket ({websocket.client.host}:{websocket.client.port}). "
                    f"Total connections for user: {len(self.active_connections[user_id])}")

    def disconnect(self, websocket: WebSocket, user_id: str):
        """Удаляет соединение из пула."""
        if user_id in self.active_connections:
            connections = self.active_connections[user_id]
            if websocket in connections:
                connections.remove(websocket)
                logger.info(f"User '{user_id}' disconnected WebSocket ({websocket.client.host}:{websocket.client.port}).")
                if not connections:
                    del self.active_connections[user_id]
                    logger.info(f"User '{user_id}' has no more active WebSocket connections.")
            else:
                logger.warning(f"Attempted to disconnect an unknown websocket for user '{user_id}'.")
        else:
             logger.warning(f"Attempted to disconnect websocket for non-connected user '{user_id}'.")

    async def _send_json(self, websocket: WebSocket, data: dict):
        """Безопасная отправка JSON сообщения."""
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.send_json(data)
                return True
            except Exception as e:
                logger.warning(f"Failed to send WebSocket message to {websocket.client}: {e}")
                return False
        else:
            logger.warning(f"WebSocket {websocket.client} is not connected, cannot send message.")
            return False

    async def send_to_user(self, user_id: str, event: str, payload: Optional[dict] = None):
        """Отправляет сообщение конкретному пользователю (всем его соединениям)."""
        message = {"event": event, "payload": payload or {}}
        disconnected_sockets = set()

        if user_id in self.active_connections:
            connections = list(self.active_connections[user_id]) # Копируем для итерации
            logger.debug(f"Sending event '{event}' to user '{user_id}' ({len(connections)} connections). Payload: {payload}")
            for connection in connections:
                if not await self._send_json(connection, message):
                    disconnected_sockets.add(connection)

            # Очищаем отключенные сокеты
            if disconnected_sockets:
                for socket in disconnected_sockets:
                    self.disconnect(socket, user_id)
        else:
            logger.debug(f"No active WebSocket connections found for user '{user_id}' to send event '{event}'.")

    async def broadcast(self, event: str, payload: Optional[dict] = None):
        """Отправляет сообщение всем подключенным пользователям."""
        message = {"event": event, "payload": payload or {}}
        all_sockets = []
        user_ids_to_clean = []

        # Собираем все сокеты и ID пользователей для очистки
        for user_id, connections in self.active_connections.items():
            all_sockets.extend(list(connections)) # Копируем
            if not connections: # На всякий случай, если остались пустые записи
                 user_ids_to_clean.append(user_id)

        logger.info(f"Broadcasting event '{event}' to {len(all_sockets)} connections. Payload: {payload}")

        disconnected_sockets_map: Dict[str, Set[WebSocket]] = {}

        # Отправляем сообщения
        for socket in all_sockets:
            # Пытаемся найти user_id для сокета (неэффективно, но просто)
            socket_user_id = None
            for uid, conns in self.active_connections.items():
                if socket in conns:
                    socket_user_id = uid
                    break

            if not await self._send_json(socket, message):
                if socket_user_id:
                    if socket_user_id not in disconnected_sockets_map:
                        disconnected_sockets_map[socket_user_id] = set()
                    disconnected_sockets_map[socket_user_id].add(socket)
                else:
                     logger.warning("Could not find user_id for a disconnected socket during broadcast.")


        # Очищаем отключенные сокеты
        for user_id, sockets in disconnected_sockets_map.items():
            for socket in sockets:
                self.disconnect(socket, user_id)

        # Удаляем пустые записи пользователей
        for user_id in user_ids_to_clean:
            if user_id in self.active_connections and not self.active_connections[user_id]:
                 del self.active_connections[user_id]


# Глобальный экземпляр менеджера
manager = ConnectionManager()