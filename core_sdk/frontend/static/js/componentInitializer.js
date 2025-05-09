// core_sdk/frontend/static/js/componentInitializer.js
class ComponentInitializer {
    constructor(selectorsConfig) {
        this.selectors = selectorsConfig;
        console.debug("ComponentInitializer initialized.");
    }

    initializeAll(parentElement) {
        if (!parentElement || !(parentElement instanceof Element || parentElement instanceof Document)) {
            console.warn("ComponentInitializer.initializeAll called with invalid parentElement:", parentElement);
            parentElement = document;
        }
        // console.debug("ComponentInitializer: Initializing components within:", parentElement.nodeName);

        this.initFeatherIcons(); // Feather всегда глобально
        this.initBootstrapComponents(parentElement);
        this.initSimpleBar(parentElement);
        this.initChoicesJs(parentElement);
        // Можно добавить вызов инициализации меню Datta Able, если оно не конфликтует
        // this.initDattaAbleMenu(parentElement);
    }

    initFeatherIcons() {
        try {
            if (typeof feather !== 'undefined') {
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
                    const tooltipTriggerList = Array.from(parentElement.querySelectorAll(this.selectors.tooltip));
                    tooltipTriggerList.forEach(el => { if (!bootstrap.Tooltip.getInstance(el)) new bootstrap.Tooltip(el); });
                }
                if (bootstrap.Popover) {
                    const popoverTriggerList = Array.from(parentElement.querySelectorAll(this.selectors.popover));
                    popoverTriggerList.forEach(el => { if (!bootstrap.Popover.getInstance(el)) new bootstrap.Popover(el); });
                }
                if (bootstrap.Dropdown) {
                    const dropdownElementList = Array.from(parentElement.querySelectorAll('.dropdown-toggle'));
                    dropdownElementList.forEach(el => { if (!bootstrap.Dropdown.getInstance(el)) new bootstrap.Dropdown(el); });
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

            parentElement.querySelectorAll(this.selectors.simplebar).forEach(el => {
                if (el.offsetParent !== null && !SimpleBar.instances.has(el)) new SimpleBar(el);
            });
            const initSpecific = (sel) => {
                let tEl = null;
                if (parentElement instanceof Document) tEl = document.querySelector(sel);
                else if (parentElement instanceof Element) tEl = parentElement.matches(sel) ? parentElement : parentElement.querySelector(sel);
                if (tEl && tEl.offsetParent !== null && !SimpleBar.instances.has(tEl)) new SimpleBar(tEl);
            };
            initSpecific(this.selectors.sidebarContent);
            initSpecific(this.selectors.headerNotificationScroll);
        } catch (error) {
            console.error("Error initializing SimpleBar:", error);
        }
    }

    initChoicesJs(parentElement) {
        try {
            if (typeof Choices === 'undefined') return;
            if (!(parentElement instanceof Element || parentElement instanceof Document)) return;

            parentElement.querySelectorAll(this.selectors.choicesjs).forEach(selectEl => {
                if (selectEl._choicesInstance) return;
                const loadUrl = selectEl.dataset.loadOptionsUrl;
                if (!loadUrl) return;
                const ph = selectEl.dataset.placeholder || 'Выберите...';
                const clear = selectEl.dataset.allowClear === 'true';
                selectEl._choicesInstance = new Choices(selectEl, {
                    placeholderValue: ph, removeItemButton: clear, searchPlaceholderValue: "Поиск...",
                    itemSelectText: '', noResultsText: 'Не найдено', noChoicesText: 'Нет опций',
                    shouldSort: false,
                    callbackOnInit: function () {
                        const choicesInstance = this;
                        fetch(loadUrl)
                            .then(response => { if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`); return response.json(); })
                            .then(data => {
                                if (!Array.isArray(data)) throw new Error("Invalid data format for choices.");
                                choicesInstance.setChoices(data, 'value', 'label', true);
                                const selOpt = selectEl.querySelector('option[selected]');
                                if (selOpt && selOpt.value) choicesInstance.setValue([selOpt.value]);
                                else if (!ph) choicesInstance.clearInput();
                            })
                            .catch(error => { console.error(`Choices load error from ${loadUrl}:`, error); choicesInstance.setChoices([{ value: '', label: 'Ошибка загрузки', disabled: true }], 'value', 'label', true); });
                    },
                });
            });
        } catch (error) {
            console.error("Error initializing Choices.js:", error);
        }
    }

    // Если решите интегрировать menu_click из Datta Able сюда:
    // initDattaAbleMenu(menuContainer = document) {
    //     if (typeof menu_click === 'function') {
    //         try {
    //             // menu_click(); // Вызов оригинальной функции
    //             // Или переписанная логика menu_click здесь
    //             console.debug("Datta Able menu logic initialized/checked.");
    //         } catch (e) {
    //             console.error("Error in Datta Able menu_click:", e);
    //         }
    //     }
    // }
}