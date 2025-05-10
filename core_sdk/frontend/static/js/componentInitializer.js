// core_sdk/frontend/static/js/componentInitializer.js
class ComponentInitializer {
    constructor(selectorsConfig) {
        this.selectors = selectorsConfig || {};
        this.debounceTimers = new Map(); // Для хранения таймеров debounce для каждого select
        console.debug("ComponentInitializer initialized.");
    }

    initializeAll(parentElement) {
        if (!parentElement || !(parentElement instanceof Element || parentElement instanceof Document)) {
            parentElement = document;
        }
        this.initFeatherIcons();
        this.initBootstrapComponents(parentElement);
        this.initSimpleBar(parentElement);
        this.initChoicesJs(parentElement);
    }

    initFeatherIcons() {
        try {
            if (typeof feather !== 'undefined' && typeof feather.replace === 'function') {
                feather.replace();
            }
        } catch (error) {
            console.error("Error initializing Feather icons:", error);
        }
    }

    initBootstrapComponents(parentElement) {
        try {
            if (typeof bootstrap !== 'undefined') {
                if (bootstrap.Tooltip) {
                    const tooltipTriggerList = Array.from(parentElement.querySelectorAll(this.selectors.tooltip || '[data-bs-toggle="tooltip"]'));
                    tooltipTriggerList.forEach(el => {
                        if (!bootstrap.Tooltip.getInstance(el)) new bootstrap.Tooltip(el);
                    });
                }
                if (bootstrap.Popover) {
                    const popoverTriggerList = Array.from(parentElement.querySelectorAll(this.selectors.popover || '[data-bs-toggle="popover"]'));
                    popoverTriggerList.forEach(el => {
                        if (!bootstrap.Popover.getInstance(el)) new bootstrap.Popover(el);
                    });
                }
                if (bootstrap.Dropdown) {
                    const dropdownElementList = Array.from(parentElement.querySelectorAll(this.selectors.dropdownToggle || '.dropdown-toggle'));
                    dropdownElementList.forEach(el => {
                        if (!bootstrap.Dropdown.getInstance(el)) new bootstrap.Dropdown(el);
                    });
                }
            }
        } catch (error) {
            console.error("Error initializing Bootstrap components:", error);
        }
    }

    initSimpleBar(parentElement) {
        try {
            if (typeof SimpleBar === 'undefined') return;
            if (!(parentElement instanceof Element || parentElement instanceof Document)) return;

            (parentElement.querySelectorAll(this.selectors.simplebar || '[data-simplebar]') || []).forEach(el => {
                if (el.offsetParent !== null && !SimpleBar.instances.has(el)) {
                    new SimpleBar(el);
                }
            });

            const initSpecificSimpleBar = (selector) => { /* ... как было ... */ };
            initSpecificSimpleBar(this.selectors.sidebarContent);
            initSpecificSimpleBar(this.selectors.headerNotificationScroll);

        } catch (error) {
            console.error("Error initializing SimpleBar:", error);
        }
    }

    _debounce(func, delay, timerIdKey) {
        clearTimeout(this.debounceTimers.get(timerIdKey));
        const timer = setTimeout(() => func(), delay);
        this.debounceTimers.set(timerIdKey, timer);
    }

    initChoicesJs(parentElement) { // ИСПРАВЛЕНИЯ ЗДЕСЬ
        if (typeof Choices === 'undefined') return;
        if (!(parentElement instanceof Element || parentElement instanceof Document)) return;

        (parentElement.querySelectorAll(this.selectors.choicesjs || 'select[data-control="choicesjs"]') || []).forEach(selectEl => {
            if (selectEl._choicesInstance) return;

            const loadUrl = selectEl.dataset.loadOptionsUrl;
            const isMultiple = selectEl.multiple;
            const placeholderText = selectEl.dataset.placeholder || (isMultiple ? 'Выберите...' : 'Выберите...');
            const searchEnabled = selectEl.dataset.searchEnabled !== 'false';
            // removeItemButton имеет смысл только для мультиселекта
            const removeItemButton = selectEl.dataset.removeItemButton === 'true' && isMultiple;
            const minSearchTextLength = parseInt(selectEl.dataset.minSearchTextLength, 10) || 0;

            if (!loadUrl) {
                try {
                    selectEl._choicesInstance = new Choices(selectEl, {
                        placeholder: selectEl.options.length > 0 && selectEl.options[0].value === "" ? true : false,
                        placeholderValue: placeholderText,
                        searchEnabled: searchEnabled,
                        removeItemButton: true,
                        itemSelectText: '',
                        // Choices.js сам должен учитывать атрибут disabled на <select>
                        // Если нет, то: disabled: selectEl.disabled,
                        shouldSort: false,
                        noResultsText: 'Ничего не найдено',
                        noChoicesText: 'Нет доступных вариантов',
                    });
                } catch (e) { console.error("Error initializing basic Choices.js:", e, selectEl); }
                return;
            }

            const choicesConfig = {
                placeholder: true,
                placeholderValue: placeholderText,
                removeItemButton: removeItemButton,
                searchEnabled: searchEnabled,
                // searchItems: searchEnabled, // УДАЛЕНО - searchEnabled достаточно
                searchFields: ['label', 'value'],
                searchResultLimit: 15,
                searchFloor: minSearchTextLength,
                searchPlaceholderValue: "Поиск...",
                itemSelectText: '',
                noResultsText: 'Ничего не найдено',
                noChoicesText: 'Нет доступных вариантов для выбора',
                shouldSort: false,
                // disabled: selectEl.disabled, // УДАЛЕНО - Choices.js должен сам это подхватывать
                                               // Если нет, то после создания instance: if(selectEl.disabled) instance.disable();
            };

            try {
                const instance = new Choices(selectEl, choicesConfig);
                selectEl._choicesInstance = instance;

                // Если select изначально disabled, применяем это к Choices.js
                if (selectEl.disabled) {
                    instance.disable();
                }

                const fetchAndSet = async (query, initialValueToLoadLabel) => {
                    const url = new URL(loadUrl, window.location.origin);
                    let isFetchingInitialLabel = !!initialValueToLoadLabel; // Преобразуем в boolean

                    if (initialValueToLoadLabel) {
                        url.searchParams.append('id', initialValueToLoadLabel);
                    } else if (query) {
                        url.searchParams.append('q', query);
                    }

                    // Ручная индикация загрузки (простой вариант)
                    const choicesElement = instance.containerOuter.element; // Внешний div Choices.js
                    choicesElement.classList.add('choices-loading'); // Добавляем класс для стилизации

                    try {
                        const response = await fetch(url.href);
                        if (!response.ok) throw new Error(`HTTP error ${response.status}`);
                        const data = await response.json();

                        choicesElement.classList.remove('choices-loading');

                        if (isFetchingInitialLabel) {
                            if (data && data.length === 1 && data[0].value === initialValueToLoadLabel) {
                                const newOption = data[0];
                                let choicesToSet = [{
                                    value: newOption.value, label: newOption.label,
                                    selected: true,
                                    customProperties: { id: newOption.id || newOption.value }
                                }];
                                const placeholderOpt = Array.from(selectEl.options).find(opt => opt.value === "");
                                if (placeholderOpt && newOption.value !== "") {
                                     choicesToSet.unshift({
                                         value: "", label: placeholderOpt.textContent || placeholderText,
                                         placeholder: true, selected: false, disabled: false
                                     });
                                }
                                instance.setChoices(choicesToSet, 'value', 'label', true);
                                //instance.setValue([newOption.value]);
                            } else if (selectEl.value === initialValueToLoadLabel) { // Лейбл не найден, но значение было
                                console.warn(`Choices: Label for initial value ID ${initialValueToLoadLabel} not found.`);
                            }
                        } else {
                            let choicesData = data;
                            if (!isMultiple && !data.some(opt => opt.placeholder || opt.value === "")) {
                                choicesData = [{ value: '', label: placeholderText, placeholder: true, selected: !selectEl.value }, ...data];
                            }
                            instance.setChoices(choicesData, 'value', 'label', true);
                            if (query && selectEl.value && data.some(d => d.value === selectEl.value)) { // Если текущее значение есть в результатах поиска
                                instance.setValue([selectEl.value]);
                            } else if (query && !isMultiple) {
                                // instance.clearInput(); // Можно очистить ввод после поиска
                            }
                        }
                    } catch (error) {
                        console.error(`Choices.js: Error fetching/setting for ${selectEl.id || selectEl.name}:`, error);
                        choicesElement.classList.remove('choices-loading');
                        if (!isFetchingInitialLabel) {
                           instance.setChoices([{ value: '', label: 'Ошибка загрузки', disabled: true }], 'value', 'label', true);
                        }
                        selectEl.dispatchEvent(new CustomEvent('choices:error', { detail: error, bubbles: true }));
                    }
                };

                // Начальная загрузка лейблов
                if (isMultiple && selectEl.selectedOptions && selectEl.selectedOptions.length > 0) {
                    Array.from(selectEl.selectedOptions).forEach(option => {
                        if (option.value && option.text && (option.text.trim().toLowerCase().startsWith("id:") || option.text.includes("(загрузка"))) {
                            fetchAndSet(null, option.value);
                        }
                    });
                } else if (!isMultiple && selectEl.value) {
                    const selectedOptionHtml = selectEl.querySelector('option[value="' + selectEl.value + '"]');
                    if (selectedOptionHtml && selectedOptionHtml.text &&
                        (selectedOptionHtml.text.trim().toLowerCase().startsWith("id:") || selectedOptionHtml.text.includes("(загрузка"))) {
                        fetchAndSet(null, selectEl.value);
                    }
                } else if (selectEl.options.length <= 1 && !selectEl.value) {
                     fetchAndSet(null, null);
                }

                if (searchEnabled) {
                    selectEl.addEventListener('search', (event) => {
                        const searchQuery = event.detail.value.trim();
                        if (searchQuery.length >= minSearchTextLength || searchQuery.length === 0) {
                            this._debounce(() => {
                                fetchAndSet(searchQuery, null);
                            }, 300, `choices-search-${selectEl.id || selectEl.name}`);
                        }
                    });
                }
            } catch (error) {
                console.error("Error initializing Choices.js instance for:", selectEl.id || selectEl.name, error);
            }
        });
    }
}