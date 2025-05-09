// core_sdk/frontend/static/js/titleResolver.js
class TitleResolver {
    constructor(config = {}) {
        this.cache = new Map(); // Кэш: "modelName-id" -> "title"
        this.queue = new Map(); // Очередь: "modelName" -> Set of IDs
        this.debounceTimeout = config.debounceTimeout || 50; // Таймаут для группировки запросов
        this.debounceTimer = null;
        this.isFetching = new Set(); // "modelName" - для отслеживания уже запущенных запросов
        this.apiUrl = config.apiUrl || '/sdk/resolve-titles'; // URL ручки на бэкенде
        this.placeholder = config.placeholder || 'Загрузка...';
        this.notFoundText = config.notFoundText || 'Не найдено';

        console.debug("TitleResolver initialized.");
    }

    _getCacheKey(modelName, itemId) {
        return `${modelName}-${itemId}`;
    }

    resolve(modelName, itemId, targetElement) {
        if (!modelName || !itemId || !targetElement) {
            console.warn("TitleResolver.resolve: Missing modelName, itemId, or targetElement.", { modelName, itemId, targetElement });
            return;
        }

        const cacheKey = this._getCacheKey(modelName, itemId);
        if (this.cache.has(cacheKey)) {
            targetElement.textContent = this.cache.get(cacheKey);
            targetElement.classList.remove('needs-title-resolution-loading');
            targetElement.classList.add('title-resolved');
            // console.debug(`TitleResolver: Resolved '${cacheKey}' from cache for element:`, targetElement);
            return;
        }

        // Устанавливаем плейсхолдер и класс, если еще не в процессе
        if (!targetElement.classList.contains('needs-title-resolution-loading')) {
            const originalText = targetElement.textContent; // Сохраняем исходный текст (ID)
            targetElement.dataset.originalTitleText = originalText;
            targetElement.textContent = this.placeholder;
            targetElement.classList.add('needs-title-resolution-loading');
        }
        targetElement.dataset.titleCacheKey = cacheKey; // Сохраняем ключ для будущего обновления

        if (!this.queue.has(modelName)) {
            this.queue.set(modelName, new Set());
        }
        this.queue.get(modelName).add(itemId);

        // console.debug(`TitleResolver: Queued '${cacheKey}'. Current queue for ${modelName}:`, this.queue.get(modelName));

        this._scheduleFetch();
    }

    _scheduleFetch() {
        clearTimeout(this.debounceTimer);
        this.debounceTimer = setTimeout(() => {
            this.queue.forEach((idsSet, modelName) => {
                if (idsSet.size > 0 && !this.isFetching.has(modelName)) {
                    const idsToFetch = Array.from(idsSet);
                    idsSet.clear(); // Очищаем очередь для этой модели перед запросом
                    this._fetchTitles(modelName, idsToFetch);
                }
            });
        }, this.debounceTimeout);
    }

    async _fetchTitles(modelName, idsToFetch) {
        if (idsToFetch.length === 0) return;

        console.debug(`TitleResolver: Fetching titles for model '${modelName}', IDs:`, idsToFetch);
        this.isFetching.add(modelName);

        try {
            const response = await fetch(this.apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    // Добавьте CSRF токен, если используется
                },
                body: JSON.stringify({ model_name: modelName, ids: idsToFetch })
            });

            if (!response.ok) {
                const errorText = await response.text();
                console.error(`TitleResolver: Error fetching titles for ${modelName}. Status: ${response.status}. Response: ${errorText}`);
                this._handleFetchError(modelName, idsToFetch, `Ошибка ${response.status}`);
                return;
            }

            const resolvedTitles = await response.json(); // Ожидаем { root: { "id1": "title1", "id2": "title2" } }
            if (!resolvedTitles || typeof resolvedTitles.root !== 'object') {
                 console.error(`TitleResolver: Invalid response structure for ${modelName}. Expected {root: {id:title}}, got:`, resolvedTitles);
                 this._handleFetchError(modelName, idsToFetch, this.notFoundText);
                 return;
            }

            const titlesMap = resolvedTitles.root;

            idsToFetch.forEach(id => {
                const cacheKey = this._getCacheKey(modelName, id);
                const title = titlesMap[id] || `${this.notFoundText} (ID: ${String(id).substring(0,8)})`;
                this.cache.set(cacheKey, title);

                document.querySelectorAll(`[data-title-cache-key="${cacheKey}"]`).forEach(el => {
                    el.textContent = title;
                    el.classList.remove('needs-title-resolution-loading');
                    el.classList.add('title-resolved');
                    el.removeAttribute('data-title-cache-key');
                    el.removeAttribute('data-original-title-text');
                });
            });
            console.debug(`TitleResolver: Successfully fetched and updated titles for ${modelName}. Cache size: ${this.cache.size}`);

        } catch (error) {
            console.error(`TitleResolver: Network or parsing error fetching titles for ${model_name}:`, error);
            this._handleFetchError(modelName, idsToFetch, 'Ошибка сети');
        } finally {
            this.isFetching.delete(modelName);
            // Проверяем, есть ли еще что-то в очереди для этой модели (маловероятно из-за debounce, но на всякий случай)
            if (this.queue.has(modelName) && this.queue.get(modelName).size > 0) {
                this._scheduleFetch();
            }
        }
    }

    _handleFetchError(modelName, erroredIds, errorMessage) {
        erroredIds.forEach(id => {
            const cacheKey = this._getCacheKey(modelName, id);
            // Не кэшируем ошибку, чтобы можно было попробовать снова
            // this.cache.set(cacheKey, errorMessage);
            document.querySelectorAll(`[data-title-cache-key="${cacheKey}"]`).forEach(el => {
                el.textContent = el.dataset.originalTitleText || id; // Возвращаем исходный ID или сам ID
                el.classList.remove('needs-title-resolution-loading');
                el.classList.add('title-resolution-failed');
                el.title = errorMessage; // Показываем ошибку в title
                // el.removeAttribute('data-title-cache-key'); // Можно оставить для повторной попытки
            });
        });
    }


    scanAndResolve(parentElement) {
        if (!parentElement || !(parentElement instanceof Element || parentElement instanceof Document)) {
            console.warn("TitleResolver.scanAndResolve called with invalid parentElement:", parentElement);
            return;
        }
        // console.debug("TitleResolver: Scanning for elements needing title resolution in:", parentElement.nodeName);
        const elements = parentElement.querySelectorAll('.needs-title-resolution');
        elements.forEach(el => {
            // Проверяем, не обрабатывается ли уже
            if (el.classList.contains('needs-title-resolution-loading') || el.classList.contains('title-resolved') || el.classList.contains('title-resolution-failed')) {
                return;
            }
            const modelName = el.dataset.modelName;
            const itemId = el.dataset.itemId;
            if (modelName && itemId) {
                this.resolve(modelName, itemId, el);
            } else {
                console.warn("TitleResolver: Element has 'needs-title-resolution' class but missing data-model-name or data-item-id.", el);
            }
        });
    }
}