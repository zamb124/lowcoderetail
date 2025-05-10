// core_sdk/frontend/static/js/htmxManager.js
class HtmxManager {
    constructor(componentInitializer, notificationService, titleResolver) {
        this.componentInitializer = componentInitializer;
        this.notificationService = notificationService;
        this.titleResolver = titleResolver;
        console.debug("HtmxManager initialized.");
    }

    setupListeners() {
        document.body.addEventListener('htmx:beforeRequest', function(evt) {
            // console.log("HTMX Before Request:", evt.detail.requestConfig);
        });

        // Этот обработчик не нужен, если beforeSwap и responseError покрывают все
        // document.body.addEventListener('htmx:afterRequest', function(evt) {
        //     console.log("HTMX After Request. XHR Status:", evt.detail.xhr.status);
        // });

        document.body.addEventListener('htmx:beforeSwap', (event) => {
            const xhr = event.detail.xhr;
            // console.log("HTMX Before Swap. Target:", event.detail.target, "XHR Status:", xhr.status, "isError:", event.detail.isError);

            if (xhr.status === 422) { // Ошибка валидации от сервера
                const contentType = xhr.getResponseHeader("Content-Type");
                if (contentType && contentType.toLowerCase().includes("text/html")) {
                    // Сервер вернул HTML с ошибками валидации
                    console.log("HtmxManager (beforeSwap): Status 422 with HTML response. Allowing swap.");
                    event.detail.shouldSwap = true; // Разрешаем HTMX вставить этот HTML

                    // Помечаем, что эту "ошибку" мы обработали как HTML-свап,
                    // чтобы htmx:responseError не пытался парсить ее как JSON.
                    event.detail.serverValidationHtmlSwapped = true;

                    // Мы хотим, чтобы htmx:afterSwap все равно сработал для инициализации компонентов
                    // в новом HTML. HTMX должен это сделать, если shouldSwap = true.
                    // Установка isError = false здесь может быть рискованной, так как
                    // это может повлиять на другие аспекты обработки ошибок в HTMX.
                    // Лучше положиться на флаг serverValidationHtmlSwapped.
                }
            }
        });

        document.body.addEventListener('htmx:afterSwap', (event) => {
            // console.log("htmx:afterSwap triggered by HtmxManager.");
            const swappedElement = event.detail.elt;
            const targetElement = event.detail.target;
            const xhr = event.detail.xhr;

            const elementToScan = swappedElement && swappedElement.isConnected ? swappedElement : (targetElement && targetElement.isConnected ? targetElement : document.body);

            if (elementToScan) {
                setTimeout(() => {
                    // console.log("HtmxManager: Re-initializing components and resolving titles in swapped content:", elementToScan.nodeName);
                    this.componentInitializer.initializeAll(elementToScan);
                    if (this.titleResolver) this.titleResolver.scanAndResolve(elementToScan);

                    // Логика фокуса для инлайн-редактирования
                    const inlineInput = elementToScan.querySelector('[autofocus][id*="--inline-input"]');
                    if (inlineInput) {
                        inlineInput.focus();
                        if (inlineInput.select && typeof inlineInput.select === 'function' && (inlineInput.type === 'text' || inlineInput.type === 'number' || inlineInput.type === 'email' || inlineInput.type === 'url' || inlineInput.type === 'search' || inlineInput.type === 'tel' || inlineInput.type === 'password')) {
                            try { inlineInput.select(); } catch (e) { console.warn("Could not select text in inline input:", e); }
                        }
                    } else {
                         const inputInsideSwapped = elementToScan.querySelector('input[autofocus][id*="--inline-input"], select[autofocus][id*="--inline-input"]');
                         if(inputInsideSwapped){
                            inputInsideSwapped.focus();
                             if (inputInsideSwapped.select && typeof inputInsideSwapped.select === 'function' && (inputInsideSwapped.type === 'text' || inputInsideSwapped.type === 'number')) {
                                try { inputInsideSwapped.select(); } catch (e) { console.warn("Could not select text:", e); }
                            }
                        }
                    }

                    // Показать уведомление, если были ошибки валидации (даже если статус 422 и HTML свапнулся)
                    // Это опционально, т.к. ошибки уже видны в форме.
                    if (xhr && xhr.status === 422 && event.detail.serverValidationHtmlSwapped) {
                         this.notificationService.show("Пожалуйста, проверьте ошибки в форме.", "warning");
                    }

                }, 50);
            }
        });

        document.body.addEventListener('htmx:responseError', (event) => {
            const xhr = event.detail.xhr;
            const target = event.target; // Элемент, который инициировал запрос
            console.warn(`HtmxManager (responseError): Status ${xhr.status} for ${target.id || target.tagName}. Path: ${event.detail.pathInfo ? event.detail.pathInfo.path : 'N/A'}`);

            // Если это ошибка валидации 422, и мы ее уже обработали, вставив HTML,
            // то не нужно пытаться парсить ее как JSON для стандартного уведомления.
            if (event.detail.serverValidationHtmlSwapped) {
                console.log("HtmxManager (responseError): Validation error (422) already handled by HTML swap. Notification (if any) handled in afterSwap.");
                return;
            }

            // Обработка других ошибок (не 422 с HTML, или 422 без HTML)
            if (xhr.status >= 400) {
                const contentType = xhr.getResponseHeader("Content-Type");
                if (contentType && contentType.toLowerCase().includes("application/json")) {
                    try {
                        const errorData = JSON.parse(xhr.responseText);
                        let message = `Ошибка ${xhr.status}`;
                        if (errorData.detail) {
                            if (typeof errorData.detail === 'string') { message += `: ${errorData.detail}`; }
                            else if (Array.isArray(errorData.detail)) { message += ': ' + errorData.detail.map(err => `${err.loc ? err.loc.join('.') + ': ' : ''}${err.msg}`).join('; '); }
                            else if (typeof errorData.detail === 'object') { message += `: ${JSON.stringify(errorData.detail)}`; }
                        }
                        this.notificationService.show(message, 'error');
                    } catch (e) {
                        this.notificationService.show(`Ошибка ${xhr.status}: ${xhr.statusText} (не удалось обработать JSON ответа)`, 'error');
                        console.error("HtmxManager: Could not parse JSON error response:", e, "Response text:", xhr.responseText);
                    }
                } else {
                    // Если ошибка не JSON (например, HTML от 500 ошибки или простой текст)
                    let errorDetail = xhr.responseText.substring(0, 200); // Показать часть ответа
                    if (xhr.statusText) {
                        errorDetail = `${xhr.statusText} (${errorDetail}...)`;
                    }
                    this.notificationService.show(`Ошибка ${xhr.status}: ${errorDetail}`, 'error');
                    console.warn("HtmxManager (responseError): Non-JSON error response. Text:", xhr.responseText.substring(0, 500));
                }
            }
        });
        console.debug("HtmxManager: HTMX listeners setup.");
    }
}