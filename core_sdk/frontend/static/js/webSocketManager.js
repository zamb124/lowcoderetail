// core_sdk/frontend/static/js/webSocketManager.js
class WebSocketManager {
    constructor(config, notificationService, isAuthenticated) {
        this.wsUrl = config.wsUrl;
        this.reconnectInterval = config.wsReconnectInterval;
        this.notificationService = notificationService;
        this.socket = null;
        this.isConnecting = false;
        this.isAuthenticated = isAuthenticated; // Получаем из App
        this.isEnabled = config.wsEnabled;
        console.debug("WebSocketManager initialized.");
    }

    connect() {
        if (!this.isEnabled) {
            console.log("WebSocketManager: WS is disabled by configuration.");
            return;
        }
        if (!this.isAuthenticated) {
            console.log("WebSocketManager: WS connection skipped, user not authenticated.");
            return;
        }
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            console.log("WebSocketManager: Already connected.");
            return;
        }
        if (this.isConnecting) {
            console.log("WebSocketManager: Connection attempt already in progress.");
            return;
        }

        this.isConnecting = true;
        console.log(`WebSocketManager: Attempting to connect to ${this.wsUrl}`);
        try {
            this.socket = new WebSocket(this.wsUrl);
            this.socket.onopen = (event) => this._onOpen(event);
            this.socket.onmessage = (event) => this._onMessage(event);
            this.socket.onerror = (error) => this._onError(error);
            this.socket.onclose = (event) => this._onClose(event);
        } catch (error) {
            console.error("WebSocketManager: Failed to create WebSocket:", error);
            this.isConnecting = false;
            this._scheduleReconnect();
        }
    }

    _onOpen(event) {
        console.log("WebSocketManager: Connection established.");
        this.isConnecting = false;
        // Опционально: аутентификация
        // const token = this._getCookie("Authorization"); // Нужен доступ к getCookie
        // if (token) { this.sendMessage({ type: "auth", token: token.replace("Bearer ", "") }); }
    }

    _onMessage(event) {
        console.debug("WebSocketManager: Message received:", event.data);
        try {
            const message = JSON.parse(event.data);
            this._handleMessage(message);
        } catch (e) {
            console.error("WebSocketManager: Failed to parse message:", e);
        }
    }

    _onError(error) {
        console.error("WebSocketManager: Error:", error);
        this.isConnecting = false;
    }

    _onClose(event) {
        console.log(`WebSocketManager: Connection closed: Code=${event.code}, Clean=${event.wasClean}`);
        this.socket = null;
        this.isConnecting = false;
        if (!event.wasClean && this.isEnabled && this.isAuthenticated) { // Переподключаемся, только если были аутентифицированы
            this._scheduleReconnect();
        }
    }

    _scheduleReconnect() {
        console.log(`WebSocketManager: Scheduling reconnection in ${this.reconnectInterval / 1000}s.`);
        setTimeout(() => {
            if (this.isAuthenticated) { // Проверяем снова перед попыткой
                 this.connect();
            } else {
                 console.log("WebSocketManager: Reconnection skipped, user no longer authenticated.");
            }
        }, this.reconnectInterval);
    }

    sendMessage(message) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            try {
                this.socket.send(JSON.stringify(message));
            } catch (e) {
                console.error("WebSocketManager: Send error:", e);
            }
        } else {
            console.warn("WebSocketManager: Not connected. Cannot send:", message);
        }
    }

    _handleMessage(message) {
        const eventType = message.event;
        const payload = message.payload || {};
        const uiKey = payload.model_name && payload.id ? `${payload.model_name}--${payload.id}` : null;
        console.log(`WebSocketManager: Handling event: ${eventType}`, payload);

        switch (eventType) {
            case 'MODEL_UPDATED':
            case 'MODEL_CREATED':
                const elUpd = uiKey ? document.querySelector(`[ui_key="${uiKey}"]`) : null;
                if (elUpd && typeof htmx !== 'undefined') htmx.trigger(elUpd, 'backend_update');
                else { const listEl = document.querySelector(`[list-model="${payload.model_name}"]`); if (listEl && typeof htmx !== 'undefined') htmx.trigger(listEl, 'refreshData'); }
                break;
            case 'MODEL_DELETED':
                const elDel = uiKey ? document.querySelector(`[ui_key="${uiKey}"]`) : null;
                if (elDel) { elDel.style.transition = 'opacity 0.5s ease-out'; elDel.style.opacity = '0'; setTimeout(() => elDel.remove(), 500); }
                break;
            case 'RELOAD_VIEW':
                const mainCt = document.querySelector(this.notificationService.config?.selectors?.mainContentArea || '#main-content-area'); // Доступ к селектору
                if (mainCt && typeof htmx !== 'undefined') htmx.trigger(mainCt, 'reloadView');
                break;
            case 'NOTIFICATION':
                this.notificationService.show(payload.message, payload.type || 'info');
                break;
            case 'AUTH_REFRESH_REQUIRED':
                this.notificationService.show("Сессия скоро истечет.", "warning");
                break;
            case 'AUTH_LOGOUT':
                this.notificationService.show("Сессия завершена. Перенаправление...", "error");
                document.cookie = "Authorization=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT;";
                document.cookie = "refresh_token=; path=/auth/refresh; expires=Thu, 01 Jan 1970 00:00:01 GMT;";
                window.location.href = '/login';
                break;
            default:
                console.warn("WebSocketManager: Unhandled event type:", eventType);
        }
    }
}