// core_sdk/frontend/static/js/componentInitializer.js
class ComponentInitializer {
    constructor(selectorsConfig) {
        this.selectors = selectorsConfig || {}; // Обеспечиваем наличие selectors
        this.debounceTimers = new Map(); // Для хранения таймеров debounce для каждого select
        console.debug("ComponentInitializer initialized.");
    }

    initializeAll(parentElement) {
        if (!parentElement || !(parentElement instanceof Element || parentElement instanceof Document)) {
            console.warn("ComponentInitializer.initializeAll called with invalid parentElement:", parentElement);
            parentElement = document; // Фоллбэк на весь документ
        }
        // console.debug("ComponentInitializer: Initializing components within:", parentElement.nodeName);

        this.initFeatherIcons(); // Feather всегда глобально
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
                // Добавьте другие компоненты Bootstrap по необходимости (например, Collapse, Offcanvas)
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

            const initSpecificSimpleBar = (selector) => {
                if (!selector) return;
                let targetEl = null;
                if (parentElement instanceof Document) {
                    targetEl = document.querySelector(selector);
                } else if (parentElement instanceof Element) {
                    targetEl = parentElement.matches(selector) ? parentElement : parentElement.querySelector(selector);
                }
                if (targetEl && targetEl.offsetParent !== null && !SimpleBar.instances.has(targetEl)) {
                    new SimpleBar(targetEl);
                }
            };
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

    initChoicesJs(parentElement) {
        if (typeof Choices === 'undefined') {
            return;
        }
        if (!(parentElement instanceof Element || parentElement instanceof Document)) {
            return;
        }

        (parentElement.querySelectorAll(this.selectors.choicesjs || 'select[data-control="choicesjs"]') || []).forEach(selectEl => {
            if (selectEl._choicesInstance) {
                // console.debug("Choices.js instance already exists for:", selectEl.id || selectEl.name);
                return;
            }

            const loadUrl = selectEl.dataset.loadOptionsUrl;
            if (!loadUrl) {
                console.warn("Choices.js: data-load-options-url is missing for:", selectEl.id || selectEl.name);
                // Инициализируем с локальными опциями, если они есть, или как простой select
                try {
                    selectEl._choicesInstance = new Choices(selectEl, {
                        placeholder: selectEl.hasAttribute('data-placeholder'),
                        placeholderValue: selectEl.dataset.placeholder || null,
                        searchEnabled: selectEl.dataset.searchEnabled !== 'false',
                        removeItemButton: selectEl.dataset.removeItemButton === 'true' && selectEl.multiple,
                        itemSelectText: '',
                        disabled: selectEl.disabled,
                    });
                } catch (e) {
                    console.error("Error initializing basic Choices.js:", e, selectEl);
                }
                return;
            }

            const placeholderText = selectEl.dataset.placeholder || 'Выберите...';
            const searchEnabled = selectEl.dataset.searchEnabled !== 'false';
            const removeItemButton = selectEl.dataset.removeItemButton === 'true' && selectEl.multiple; // Только для мультивыбора
            const minSearchTextLength = parseInt(selectEl.dataset.minSearchTextLength, 10) || 0; // Минимальная длина для начала поиска

            const choicesConfig = {
                placeholder: true,
                placeholderValue: placeholderText,
                removeItemButton: removeItemButton,
                searchEnabled: searchEnabled,
                searchPlaceholderValue: "Поиск...",
                itemSelectText: '',
                noResultsText: 'Ничего не найдено',
                noChoicesText: 'Нет доступных вариантов',
                shouldSort: false,
                disabled: selectEl.disabled,
                // allowHTML: false, // По умолчанию
                //fuseOptions: { threshold: 0.3, distance: 100 }, // Настройки для Fuse.js (встроенный поиск)
            };

            try {
                const instance = new Choices(selectEl, choicesConfig);
                selectEl._choicesInstance = instance;

                const fetchAndSetChoices = async (query = null, forInitialValue = false) => {
                    const url = new URL(loadUrl, window.location.origin);
                    if (query) {
                        url.searchParams.append('q', query);
                    } else if (forInitialValue && selectEl.value) {
                        // Если это для начального значения, и оно есть, пытаемся загрузить его по ID
                        url.searchParams.append('id', selectEl.value);
                    } else if (!forInitialValue) {
                        // Если нет query и это не загрузка начального значения, не делаем запрос
                        // или загружаем дефолтный набор (если API это поддерживает без 'q' и 'id')
                        // instance.setChoices([{ value: '', label: placeholderText, placeholder: true }], 'value', 'label', true);
                        // return; // Раскомментировать, если не нужно грузить опции без query
                    }

                    // console.debug(`Choices: Fetching for ${selectEl.id || selectEl.name}. Query: ${query}, Initial: ${forInitialValue}, URL: ${url.href}`);

                    try {
                        const response = await fetch(url.href);
                        if (!response.ok) throw new Error(`HTTP error ${response.status}`);
                        const data = await response.json(); // Ожидаем [{value: "id", label: "Text"}, ...]

                        if (forInitialValue && data.length > 0) {
                            const newOption = data[0]; // {value: "uuid", label: "Name", id: "uuid"}
                            const currentSelectedChoiceObject = instance.getValue(true);
                            if (currentSelectedChoiceObject && currentSelectedChoiceObject.value === newOption.value && currentSelectedChoiceObject.label !== newOption.label) {
                            }
                            instance.setChoices(
                                [{
                                    value: newOption.value,
                                    label: newOption.label,
                                    selected: true,
                                    customProperties: {id: newOption.id}
                                }],
                                'value', // поле для значения
                                'label', // поле для отображения
                                false    // НЕ заменять все существующие опции
                            );
                        } else if (!forInitialValue) {
                            // Для поиска, устанавливаем новые опции
                            instance.setChoices(data, 'value', 'label', true);
                        } else if (forInitialValue && data.length === 0 && selectEl.value) {
                            // Начальное значение есть, но не найдено на сервере. Показываем ID.
                            const currentVal = selectEl.value;
                            instance.setChoices([{
                                value: currentVal,
                                label: `ID: ${String(currentVal).substring(0, 8)}... (не найдено)`
                            }], 'value', 'label', true);
                            instance.setValue([currentVal]);
                        }

                    } catch (error) {
                        console.error(`Choices.js: Error fetching options for ${selectEl.id || selectEl.name} from ${url.href}:`, error);
                        instance.setChoices([{
                            value: '',
                            label: 'Ошибка загрузки опций',
                            disabled: true
                        }], 'value', 'label', true);
                        selectEl.dispatchEvent(new CustomEvent('choices:error', {detail: error, bubbles: true}));
                    }
                };

                // Начальная загрузка (если есть выбранное значение, пытаемся загрузить его label)
                if (selectEl.value) {
                    // console.debug(`Choices: Attempting to preload label for ${selectEl.id || selectEl.name}, value: ${selectEl.value}`);
                    fetchAndSetChoices(null, true);
                } else if (!selectEl.value && selectEl.options.length <= 1 && !selectEl.multiple) { // Если нет значения и нет опций (кроме плейсхолдера)
                    // Можно загрузить начальный набор опций без поискового запроса, если API это поддерживает
                    // fetchAndSetChoices(null, false); // Загрузить первые N опций
                }


                // Слушатель для асинхронного поиска
                if (searchEnabled) {
                    const searchEventHandler = (event) => {
                        const searchQuery = event.detail.value.trim();
                        if (searchQuery.length >= minSearchTextLength) {
                            this._debounce(() => {
                                instance.clearChoices(); // Очищаем перед новым поиском
                                fetchAndSetChoices(searchQuery, false);
                            }, 300, `choices-${selectEl.id || selectEl.name}`); // 300ms debounce
                        } else if (searchQuery.length === 0 && !selectEl.multiple) {
                            // Если поле поиска очищено и это не мультиселект, можно сбросить опции
                            // или загрузить дефолтные
                            instance.clearChoices();
                            instance.setChoices([{
                                value: '',
                                label: placeholderText,
                                placeholder: true,
                                selected: true,
                                disabled: false
                            }], 'value', 'label', true);
                            // fetchAndSetChoices(null, false); // Загрузить первые N опций
                        }
                    };
                    selectEl.addEventListener('search', searchEventHandler);
                }
                // console.debug("Choices.js async initialized for:", selectEl.id || selectEl.name);

            } catch (error) {
                console.error("Error initializing Choices.js (async) for element:", selectEl.id || selectEl.name, error);
            }
        });
    }
}