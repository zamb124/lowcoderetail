// core_sdk/frontend/static/js/htmxManager.js
class HtmxManager {
    constructor(componentInitializer, notificationService) {
        this.componentInitializer = componentInitializer;
        this.notificationService = notificationService;
        console.debug("HtmxManager initialized.");
    }

    setupListeners() {
        document.body.addEventListener('htmx:afterSwap', (event) => {
            console.log("htmx:afterSwap triggered by HtmxManager.");
            const swappedElement = event.detail.elt;
            if (swappedElement && swappedElement instanceof Element) {
                setTimeout(() => {
                    console.log("HtmxManager: Re-initializing components in swapped content:", swappedElement.nodeName);
                    this.componentInitializer.initializeAll(swappedElement);

                    // Логика фокуса для инлайн-редактирования
                    const inlineInput = swappedElement.querySelector('[autofocus][id*="--inline-input"]');
                    if (inlineInput) {
                        console.debug("HtmxManager: Found inline input with autofocus:", inlineInput.id);
                        inlineInput.focus();
                        if (inlineInput.select && (inlineInput.type === 'text' || inlineInput.type === 'number' /* ... */)) {
                            try { inlineInput.select(); } catch (e) { console.warn("Could not select text in inline input:", e); }
                        }
                    } else {
                         const inputInsideSwapped = swappedElement.querySelector('input[autofocus][id*="--inline-input"], select[autofocus][id*="--inline-input"]');
                         if(inputInsideSwapped){
                            console.debug("HtmxManager: Found inline input inside swapped target:", inputInsideSwapped.id);
                            inputInsideSwapped.focus();
                             if (inputInsideSwapped.select && (inputInsideSwapped.type === 'text' || inputInsideSwapped.type === 'number' /* ... */)) {
                                try { inputInsideSwapped.select(); } catch (e) { console.warn("Could not select text:", e); }
                            }
                        }
                    }

                }, 50);
            } else {
                console.warn("HtmxManager: htmx:afterSwap event without valid target. Re-initializing on document.");
                setTimeout(() => {
                    this.componentInitializer.initializeAll(document);
                }, 50);
            }
        });

        document.body.addEventListener('htmx:responseError', (evt) => {
            console.warn("HtmxManager: htmx:responseError", evt.detail.xhr);
            if (evt.detail.xhr.status >= 400) {
                try {
                    const errorData = JSON.parse(evt.detail.xhr.responseText);
                    let message = `Ошибка ${evt.detail.xhr.status}`;
                    if (errorData.detail) {
                        if (typeof errorData.detail === 'string') { message += `: ${errorData.detail}`; }
                        else if (Array.isArray(errorData.detail)) { message += ': ' + errorData.detail.map(err => `${err.loc ? err.loc.join('.') + ': ' : ''}${err.msg}`).join('; '); }
                        else if (typeof errorData.detail === 'object') { message += `: ${JSON.stringify(errorData.detail)}`; }
                    }
                    this.notificationService.show(message, 'error');
                } catch (e) {
                    this.notificationService.show(`Ошибка ${evt.detail.xhr.status}: ${evt.detail.xhr.statusText}`, 'error');
                    console.error("HtmxManager: Could not parse error response:", e);
                }
            }
        });
        console.debug("HtmxManager: HTMX listeners setup.");
    }
}