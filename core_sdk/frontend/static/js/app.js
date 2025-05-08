// core_sdk/frontend/static/js/app.js

class App {
    constructor(config = {}) {
        // --- Инициализация конфигурации ---
        this.config = {
            wsEnabled: config.wsEnabled !== undefined ? config.wsEnabled : true,
            wsUrl: config.wsUrl || this._getDefaultWsUrl(), // Вызываем метод здесь
            wsReconnectInterval: config.wsReconnectInterval || 5000,
            selectors: {
                mainContentArea: '#main-content-area',
                modalPlaceholder: '#modal-placeholder',
                toastContainer: '#toast-container',
                simplebar: '[data-simplebar]',
                tooltip: '[data-bs-toggle="tooltip"]',
                popover: '[data-bs-toggle="popover"]',
                choicesjs: 'select[data-control="select2"][data-load-options-url]',
                sidebar: '.pc-sidebar',
                sidebarContent: '.pc-sidebar .navbar-content',
                headerNotificationScroll: '.header-notification-scroll',
                sidebarHideToggle: '#sidebar-hide',
                mobileCollapseToggle: '#mobile-collapse',
                // Customizer selectors
                customizerOffcanvas: '#offcanvas_pc_layout',
                customizerResetBtn: '#layoutreset',
                themeLayoutBtns: '.theme-layout .btn',
                themeLayoutTypeBtns: '.theme-layout-type .btn',
                layoutSwitcherBtns: '.layout-switcher',
                sidebarThemeBtns: '.sidebar-theme .btn',
                navCaptionBtns: '.theme-nav-caption .btn',
                themeDirectionBtns: '.theme-direction .btn',
                themeContainerBtns: '.theme-container .btn',
                presetColorBtns: '.preset-color > a',
                headerColorBtns: '.header-color > a',
                navbarColorBtns: '.navbar-color > a',
                logoColorBtns: '.logo-color > a',
                captionColorBtns: '.caption-color > a',
                navbarImgBtns: '.navbar-img > a',
                drpMenuIconBtns: '.drp-menu-icon > a',
                drpMenuLinkIconBtns: '.drp-menu-link-icon > a',
                langSwitchers: '.lng-dropdown .dropdown-item[data-lng]',
                sdkStaticUrl: config.sdkStaticUrl || '/sdk-static',
            },
            defaultLayout: 'vertical',
            localStorageLayoutKey: 'pc-layout-choice',
            //..config
        };

        // --- Инициализация состояния ---
        this.socket = null;
        this.isAuthenticated = this._checkAuthCookie(); // Вызываем метод здесь
        this.isConnectingWs = false;

        console.debug("App instance created. Config:", this.config);

        // Применяем лэйаут ДО загрузки DOM, чтобы избежать "прыжков"
        this._applyLayoutSetting();
    }

    /**
     * Инициализирует приложение: устанавливает слушатели событий и запускает
     * первичную инициализацию компонентов.
     */
    init() {
        document.addEventListener('DOMContentLoaded', () => {
            console.log("DOM fully loaded and parsed. Initializing App components.");
            this._initializeComponents(document);
            this._setupHtmxListeners();
            this._setupGlobalEventListeners();
            this._setupCustomizerListeners();

            if (this.config.wsEnabled && this.isAuthenticated) {
                this.connectWebSocket();
            } else if (this.config.wsEnabled) {
                console.log("WebSocket connection skipped: User not authenticated.");
            } else {
                console.log("WebSocket connection skipped: Disabled by configuration.");
            }
            // Применяем остальные настройки темы ПОСЛЕ загрузки DOM
            this._applyInitialSettings();
        });
    }

    /**
     * Настраивает слушатели событий HTMX.
     * @private
     */
    _setupHtmxListeners() {
        document.body.addEventListener('htmx:afterSwap', (event) => {
            console.log("htmx:afterSwap triggered.");
            const swappedElement = event.detail.elt;
            if (swappedElement && swappedElement instanceof Element) {
                setTimeout(() => {
                    console.log("Re-initializing components in swapped content:", swappedElement.nodeName);
                    this._initializeComponents(swappedElement);
                }, 50);
            } else {
                console.warn("htmx:afterSwap event triggered without valid target element (elt). Re-initializing on document.");
                setTimeout(() => {
                    this._initializeComponents(document);
                }, 50);
            }
        });

        document.body.addEventListener('htmx:responseError', (evt) => {
            console.warn("htmx:responseError", evt.detail.xhr);
            if (evt.detail.xhr.status >= 400) {
                try {
                    const errorData = JSON.parse(evt.detail.xhr.responseText);
                    let message = `Ошибка ${evt.detail.xhr.status}`;
                    if (errorData.detail) {
                        if (typeof errorData.detail === 'string') {
                            message += `: ${errorData.detail}`;
                        } else if (Array.isArray(errorData.detail)) {
                            message += ': ' + errorData.detail.map(err => `${err.loc ? err.loc.join('.') + ': ' : ''}${err.msg}`).join('; ');
                        } else if (typeof errorData.detail === 'object') {
                            message += `: ${JSON.stringify(errorData.detail)}`;
                        }
                    }
                    this.showNotification(message, 'error');
                } catch (e) {
                    this.showNotification(`Ошибка ${evt.detail.xhr.status}: ${evt.detail.xhr.statusText}`, 'error');
                    console.error("Could not parse error response:", e);
                }
            }
        });
        console.debug("HTMX listeners setup.");
    }

    /**
     * Настраивает глобальные слушатели событий (клики по кнопкам хедера/сайдбара).
     * @private
     */
    _setupGlobalEventListeners() {
        document.body.addEventListener('click', (event) => {
            const sidebarHideBtn = event.target.closest(this.config.selectors.sidebarHideToggle);
            const mobileCollapseBtn = event.target.closest(this.config.selectors.mobileCollapseToggle);
            const langSwitcher = event.target.closest(this.config.selectors.langSwitchers);
            // Ищем кнопки смены темы в хедере или кастомайзере
            const themeSwitcherBtn = event.target.closest('.theme-switcher[data-theme]'); // <--- ИЗМЕНЕНО: Используем класс и data-атрибут
            const layoutSwitcherBtn = event.target.closest(this.config.selectors.layoutSwitcherBtns + '[data-layout]');

            if (sidebarHideBtn) {
                event.preventDefault();
                this.toggleSidebarHide();
            } else if (mobileCollapseBtn) {
                event.preventDefault();
                this.toggleMobileSidebar();
            } else if (langSwitcher) {
                event.preventDefault();
                const lang = langSwitcher.getAttribute('data-lng');
                if (lang) this.changeLanguage(lang);
            } else if (themeSwitcherBtn) { // <--- ДОБАВЛЕНА ОБРАБОТКА
                event.preventDefault();
                const themeValue = themeSwitcherBtn.getAttribute('data-theme'); // Получаем значение из data-theme
                if (themeValue === 'light') this.layoutChange('light');
                else if (themeValue === 'dark') this.layoutChange('dark');
                else this.layoutChangeDefault(); // Для data-theme="default"
            } else if (layoutSwitcherBtn) {
                event.preventDefault();
                const layoutValue = layoutSwitcherBtn.getAttribute('data-layout');
                if (layoutValue) this.changeLayout(layoutValue);
            }
            // Убираем обработку themeLayoutBtn, т.к. она дублирует themeSwitcherBtn
            // else if (themeLayoutBtn) { ... }
        });
        console.debug("Global event listeners setup.");
    }

    /**
     * Настраивает слушатели для кнопок внутри кастомайзера.
     * @private
     */
    _setupCustomizerListeners() {
        const customizer = document.querySelector(this.config.selectors.customizerOffcanvas);
        if (!customizer) return;

        customizer.addEventListener('click', (event) => {
            const targetButton = event.target.closest('button[data-value], a[data-value]');
            if (!targetButton) return;
            const value = targetButton.getAttribute('data-value');
            const parentGroup = targetButton.closest('.theme-layout-type, [class*="theme-color"], [class*="-theme"], [class*="-caption"], [class*="-direction"], [class*="-container"]');
            if (!parentGroup || value === null) return;
            event.preventDefault();

            if (parentGroup.classList.contains('theme-layout-type')) this.changeLayout(value);
            else if (parentGroup.classList.contains('preset-color')) this.presetChange(value);
            else if (parentGroup.classList.contains('header-color')) this.headerChange(value);
            else if (parentGroup.classList.contains('navbar-color')) this.navbarChange(value);
            else if (parentGroup.classList.contains('logo-color')) this.logoChange(value);
            else if (parentGroup.classList.contains('caption-color')) this.captionChange(value);
            else if (parentGroup.classList.contains('navbar-img')) this.navImageChange(value);
            else if (parentGroup.classList.contains('sidebar-theme')) this.layoutThemeSidebarChange(value);
            else if (parentGroup.classList.contains('theme-nav-caption')) this.layoutCaptionChange(value);
            else if (parentGroup.classList.contains('theme-direction')) this.layoutRtlChange(value);
            else if (parentGroup.classList.contains('theme-container')) this.changeBoxContainer(value);
            else if (parentGroup.classList.contains('drp-menu-icon')) this.drpMenuIconChange(value);
            else if (parentGroup.classList.contains('drp-menu-link-icon')) this.drpMenuLinkIconChange(value);
        });

        const resetButton = customizer.querySelector(this.config.selectors.customizerResetBtn);
        if (resetButton) resetButton.addEventListener('click', () => this.resetLayoutSettings());
        console.debug("Customizer event listeners setup.");
    }

    /**
     * Инициализирует все UI компоненты в указанном родительском элементе.
     * @param {Element|Document} parentElement - Элемент, в котором искать компоненты.
     * @private
     */
    _initializeComponents(parentElement) {
        if (!parentElement || !(parentElement instanceof Element || parentElement instanceof Document)) {
            console.warn("_initializeComponents called with invalid parentElement:", parentElement);
            parentElement = document;
        }
        // console.debug("Initializing components within:", parentElement.nodeName);
        this._initFeatherIcons();
        this._initBootstrapComponents(parentElement);
        this._initSimpleBar(parentElement);
        this._initChoicesJs(parentElement);
        // Вызов menu_click для инициализации подменю Datta Able, если необходимо
        // и если эта функция определена глобально скриптами темы
        if (typeof menu_click === 'function') {
            try {
                // menu_click(); // Раскомментируйте, если стандартная логика меню Datta нужна
                console.debug("Datta Able menu_click() function found (but not called automatically to avoid conflicts).");
            } catch (e) {
                console.error("Error calling menu_click:", e);
            }
        }
    }

    /**
     * Инициализирует или обновляет иконки Feather.
     * @private
     */
    _initFeatherIcons() {
        try {
            if (typeof feather !== 'undefined') {
                feather.replace();
            }
        } catch (error) {
            console.error("Error initializing Feather icons:", error);
        }
    }

    /**
     * Инициализирует компоненты Bootstrap (Tooltips, Popovers, Dropdowns).
     * @param {Element|Document} parentElement
     * @private
     */
    _initBootstrapComponents(parentElement) {
        // Tooltips
        try {
            if (typeof bootstrap !== 'undefined' && bootstrap.Tooltip) {
                const tooltipTriggerList = Array.from(parentElement.querySelectorAll(this.config.selectors.tooltip));
                tooltipTriggerList.forEach(tooltipTriggerEl => {
                    if (!bootstrap.Tooltip.getInstance(tooltipTriggerEl)) {
                        new bootstrap.Tooltip(tooltipTriggerEl);
                    }
                });
            }
        } catch (error) {
            console.error("Error initializing Bootstrap tooltips:", error);
        }
        // Popovers
        try {
            if (typeof bootstrap !== 'undefined' && bootstrap.Popover) {
                const popoverTriggerList = Array.from(parentElement.querySelectorAll(this.config.selectors.popover));
                popoverTriggerList.forEach(popoverTriggerEl => {
                    if (!bootstrap.Popover.getInstance(popoverTriggerEl)) {
                        new bootstrap.Popover(popoverTriggerEl);
                    }
                });
            }
        } catch (error) {
            console.error("Error initializing Bootstrap popovers:", error);
        }
        // Dropdowns
        try {
            if (typeof bootstrap !== 'undefined' && bootstrap.Dropdown) {
                const dropdownElementList = Array.from(parentElement.querySelectorAll('.dropdown-toggle'));
                dropdownElementList.forEach(dropdownToggleEl => {
                    if (!bootstrap.Dropdown.getInstance(dropdownToggleEl)) {
                        new bootstrap.Dropdown(dropdownToggleEl);
                    }
                });
            }
        } catch (error) {
            console.error("Error initializing Bootstrap dropdowns:", error);
        }
    }

    /**
     * Инициализирует SimpleBar для элементов скролла.
     * @param {Element|Document} parentElement
     * @private
     */
    _initSimpleBar(parentElement) {
        try {
            if (typeof SimpleBar === 'undefined') return;
            if (!(parentElement instanceof Element || parentElement instanceof Document)) return;

            const simpleBarElements = parentElement.querySelectorAll(this.config.selectors.simplebar);
            simpleBarElements.forEach(el => {
                if (el.offsetParent !== null && !SimpleBar.instances.has(el)) new SimpleBar(el);
            });

            const initSpecificSimpleBar = (selector) => {
                let targetElement = null;
                if (parentElement instanceof Document) targetElement = document.querySelector(selector);
                else if (parentElement instanceof Element) targetElement = parentElement.matches(selector) ? parentElement : parentElement.querySelector(selector);
                if (targetElement && targetElement.offsetParent !== null && !SimpleBar.instances.has(targetElement)) new SimpleBar(targetElement);
            };

            initSpecificSimpleBar(this.config.selectors.sidebarContent);
            initSpecificSimpleBar(this.config.selectors.headerNotificationScroll);

        } catch (error) {
            console.error("Error initializing SimpleBar:", error);
        }
    }

    /**
     * Инициализирует Choices.js для select элементов.
     * @param {Element|Document} parentElement
     * @private
     */
    _initChoicesJs(parentElement) {
        try {
            if (typeof Choices === 'undefined') return;
            if (!(parentElement instanceof Element || parentElement instanceof Document)) return;

            const selectElements = parentElement.querySelectorAll(this.config.selectors.choicesjs);
            selectElements.forEach(selectEl => {
                if (selectEl._choicesInstance) return;
                const loadUrl = selectEl.dataset.loadOptionsUrl;
                if (!loadUrl) return;
                const placeholder = selectEl.dataset.placeholder || 'Выберите...';
                const allowClear = selectEl.dataset.allowClear === 'true';
                selectEl._choicesInstance = new Choices(selectEl, {
                    placeholderValue: placeholder, removeItemButton: allowClear, searchPlaceholderValue: "Поиск...",
                    itemSelectText: '', noResultsText: 'Не найдено', noChoicesText: 'Нет опций',
                    shouldSort: false,
                    callbackOnInit: function () {
                        const choicesInstance = this;
                        fetch(loadUrl)
                            .then(response => {
                                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                                return response.json();
                            })
                            .then(data => {
                                if (!Array.isArray(data)) throw new Error("Invalid data format received for choices.");
                                choicesInstance.setChoices(data, 'value', 'label', true);
                                const selectedOption = selectEl.querySelector('option[selected]');
                                if (selectedOption && selectedOption.value) choicesInstance.setValue([selectedOption.value]);
                                else if (!placeholder) choicesInstance.clearInput();
                            })
                            .catch(error => {
                                console.error(`Error loading choices from ${loadUrl}:`, error);
                                choicesInstance.setChoices([{
                                    value: '',
                                    label: 'Ошибка загрузки опций',
                                    disabled: true
                                }], 'value', 'label', true);
                            });
                    },
                });
            });
        } catch (error) {
            console.error("Error initializing Choices.js:", error);
        }
    }

    /**
     * Переключает состояние скрытия/показа основного сайдбара.
     */
    toggleSidebarHide() {
        const sidebar = document.querySelector(this.config.selectors.sidebar);
        const body = document.body;
        if (sidebar) {
            const isHidden = sidebar.classList.toggle('pc-sidebar-hide');
            body.classList.toggle('pc-sidebar-hide', isHidden);
            console.debug(`Sidebar hide toggled. Body class 'pc-sidebar-hide' ${isHidden ? 'added' : 'removed'}.`);
        } else {
            console.warn("Sidebar element not found for toggleSidebarHide.");
        }
    }

    /**
     * Переключает состояние мобильного сайдбара.
     */
    toggleMobileSidebar() {
        const sidebar = document.querySelector(this.config.selectors.sidebar);
        const hamburger = document.querySelector(this.config.selectors.mobileCollapseToggle + ' .hamburger');
        if (sidebar) {
            if (sidebar.classList.contains('mob-sidebar-active')) {
                this._removeMobileOverlay();
                sidebar.classList.remove('mob-sidebar-active');
                if (hamburger) hamburger.classList.remove('is-active');
            } else {
                sidebar.classList.add('mob-sidebar-active');
                this._addMobileOverlay(sidebar);
                if (hamburger) hamburger.classList.add('is-active');
            }
            console.debug("Mobile sidebar toggled.");
        } else {
            console.warn("Sidebar element not found for toggleMobileSidebar.");
        }
    }

    _addMobileOverlay(targetElement) {
        if (!targetElement.querySelector('.pc-menu-overlay')) {
            targetElement.insertAdjacentHTML('beforeend', '<div class="pc-menu-overlay"></div>');
            targetElement.querySelector('.pc-menu-overlay').addEventListener('click', () => this.toggleMobileSidebar(), {once: true});
        }
    }

    _removeMobileOverlay() {
        const o = document.querySelector('.pc-sidebar .pc-menu-overlay') || document.querySelector('.pc-menu-overlay');
        if (o) o.remove();
    }

    /**
     * Изменяет язык интерфейса.
     */
    changeLanguage(lang) {
        if (typeof i18next !== 'undefined' && i18next.changeLanguage) {
            i18next.changeLanguage(lang).then((t) => {
                document.querySelectorAll('[data-i18n]').forEach((el) => {
                    el.innerHTML = t(el.dataset.i18n);
                });
                document.documentElement.setAttribute('lang', lang);
                console.log(`Lang changed: ${lang}`);
                this._updateActiveButton(this.config.selectors.langSwitchers, lang, 'data-lng');
            }).catch(err => console.error(`Lang change error: ${lang}`, err));
        } else {
            console.warn("i18next not configured.");
        }
    }

    // --- Layout and Theme Methods ---

    /**
     * Изменяет лэйаут темы (перезагрузкой страницы).
     */
    changeLayout(layoutName) {
        console.log(`Request layout change to: ${layoutName}`);
        localStorage.setItem(this.config.localStorageLayoutKey, layoutName);
        window.location.reload();
    }

    /**
     * Применяет сохраненный лэйаут при загрузке страницы.
     * @private
     */
    _applyLayoutSetting() {
        const savedLayout = localStorage.getItem(this.config.localStorageLayoutKey) || this.config.defaultLayout;
        document.body.setAttribute('data-pc-layout', savedLayout);
        document.body.classList.toggle('layout-2', savedLayout === 'layout-2');
        document.body.classList.toggle('layout-3', savedLayout === 'layout-3');
        console.debug(`Initial layout '${savedLayout}' applied.`);
    }

    /**
     * Применяет остальные начальные настройки (кроме лэйаута).
     * @private
     */
    _applyInitialSettings() {
        const currentLayout = document.body.getAttribute('data-pc-layout') || this.config.defaultLayout;
        this._updateActiveButton(this.config.selectors.themeLayoutTypeBtns, currentLayout);
        this.layoutChangeDefault(); // Устанавливает light/dark/system и активную кнопку
        this.layoutThemeSidebarChange(localStorage.getItem('pc-sidebar_theme') || 'false');
        this.layoutCaptionChange(localStorage.getItem('pc-sidebar-caption') || 'true');
        this.layoutRtlChange(localStorage.getItem('pc-direction') === 'rtl' ? 'true' : 'false');
        this.changeBoxContainer(localStorage.getItem('pc-container-width') || 'false');
        this.presetChange(localStorage.getItem('pc-preset') || 'preset-1');
        this.headerChange(localStorage.getItem('pc-header') || '');
        this.navbarChange(localStorage.getItem('pc-navbar') || '');
        this.logoChange(localStorage.getItem('pc-logo') || '');
        this.captionChange(localStorage.getItem('pc-caption') || '');
        this.navImageChange(localStorage.getItem('pc-navimg') || '');
        this.drpMenuIconChange(localStorage.getItem('pc-drp-menu-icon') || 'preset-1');
        this.drpMenuLinkIconChange(localStorage.getItem('pc-drp-menu-link-icon') || 'preset-1');
        console.debug("Initial theme settings applied.");
    }

    /** Изменяет тему (light/dark). @param {'light'|'dark'} layout */
    layoutChange(layout) {
        document.body.setAttribute('data-pc-theme', layout);
        localStorage.setItem('pc-theme', layout);
        const fullLogoPath = `${this.config.selectors.sdkStaticUrl}/datta-able/assets/images/logo-${layout === 'dark' ? 'white' : 'dark'}.svg`;
        this._updateLogo('.pc-sidebar .m-header .logo-lg', fullLogoPath);
        this._updateLogo('.auth-main .img-brand', fullLogoPath);
        this._updateActiveButton(this.config.selectors.themeLayoutBtns, layout === 'dark' ? 'false' : 'true');
        console.log(`Theme changed: ${layout}`);
    }

    /** Устанавливает тему по умолчанию (системную). */
    layoutChangeDefault() {
        localStorage.removeItem('pc-theme');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)');
        this.layoutChange(prefersDark.matches ? 'dark' : 'light');
        this._updateActiveButton(this.config.selectors.themeLayoutBtns, 'default');
        console.log("Theme set to default.");
    }

    /** Инициализирует обработчики кликов для меню (вертикальное, горизонтальное, табы). @private */
    _initMenuClicks(menuContainer = document) {
        if (!menuContainer || !(menuContainer instanceof Element || menuContainer instanceof Document)) {
            console.warn("_initMenuClicks called with invalid container:", menuContainer);
            return;
        }
        const markHandled = (el) => el.dataset.menuClickHandled = 'true';
        const isHandled = (el) => el.dataset.menuClickHandled === 'true';

        // Уровень 1 (прямые потомки .pc-navbar или внутри табов .tab-pane > .pc-navbar)
        // Используем более конкретный селектор, чтобы не захватить подменю случайно
        menuContainer.querySelectorAll('.pc-navbar > li.pc-hasmenu').forEach(item => {
            if (isHandled(item)) return;
            // Навешиваем слушатель на сам элемент LI
            item.addEventListener('click', (event) => {
                // Предотвращаем всплытие, чтобы не сработали другие слушатели на родителях
                event.stopPropagation();
                // Клик по ссылке внутри LI не должен триггерить открытие/закрытие меню LI
                if (event.target.closest('a') !== item.querySelector(':scope > a.pc-link')) {
                    return;
                }
                this._toggleMenuItem(item);
            });
            markHandled(item);
        });

        // Уровень 2 и глубже (li внутри .pc-submenu)
        menuContainer.querySelectorAll('.pc-submenu li.pc-hasmenu').forEach(item => {
            if (isHandled(item)) return;
            item.addEventListener('click', (event) => {
                event.stopPropagation();
                if (event.target.closest('a') !== item.querySelector(':scope > a.pc-link')) {
                    return;
                }
                this._toggleMenuItem(item);
            });
            markHandled(item);
        });
        console.debug("Menu click handlers initialized/re-initialized for container:", menuContainer.nodeName);
    }

    /** Переключает состояние пункта меню (открыт/закрыт). @private */
    _toggleMenuItem(targetLi) {
        // Ищем подменю как прямого потомка
        const submenu = targetLi.querySelector(':scope > .pc-submenu');
        if (!submenu) {
            console.warn("Submenu not found for target LI:", targetLi);
            return; // Нет подменю для переключения
        }

        const isTriggered = targetLi.classList.contains('pc-trigger');

        // Закрываем всех "соседей" на том же уровне перед открытием нового
        if (!isTriggered) {
            const siblings = targetLi.parentNode.children;
            Array.from(siblings).forEach(sibling => {
                if (sibling !== targetLi && sibling.classList.contains('pc-trigger')) {
                    sibling.classList.remove('pc-trigger');
                    const siblingSubmenu = sibling.querySelector(':scope > .pc-submenu');
                    if (siblingSubmenu) this._slideUp(siblingSubmenu, 200);
                }
            });
        }

        // Переключаем текущий элемент
        targetLi.classList.toggle('pc-trigger');
        if (targetLi.classList.contains('pc-trigger')) {
            this._slideDown(submenu, 200);
        } else {
            this._slideUp(submenu, 200);
        }
    }

    // --- Анимации SlideUp/SlideDown (вспомогательные) ---
    // Убедимся, что они правильно работают с display
    _slideUp(target, duration = 200) { // Уменьшил duration для скорости
        if (!target || target.style.display === 'none') return;
        target.style.transitionProperty = 'height, margin, padding';
        target.style.transitionDuration = duration + 'ms';
        target.style.boxSizing = 'border-box';
        target.style.height = target.offsetHeight + 'px';
        target.offsetHeight; // reflow
        target.style.overflow = 'hidden';
        target.style.height = '0';
        target.style.paddingTop = '0';
        target.style.paddingBottom = '0';
        target.style.marginTop = '0';
        target.style.marginBottom = '0';
        window.setTimeout(() => {
            target.style.display = 'none'; // Скрываем элемент после анимации
            target.style.removeProperty('height');
            target.style.removeProperty('padding-top');
            target.style.removeProperty('padding-bottom');
            target.style.removeProperty('margin-top');
            target.style.removeProperty('margin-bottom');
            target.style.removeProperty('overflow');
            target.style.removeProperty('transition-duration');
            target.style.removeProperty('transition-property');
        }, duration);
    }

    _slideDown(target, duration = 200) { // Уменьшил duration
        if (!target) return;
        target.style.removeProperty('display'); // Убираем display: none, если был
        let display = window.getComputedStyle(target).display;
        if (display === 'none') display = 'block'; // Если display был none, ставим block
        target.style.display = display;

        let height = target.offsetHeight; // Получаем реальную высоту
        target.style.overflow = 'hidden';
        target.style.height = '0';
        target.style.paddingTop = '0';
        target.style.paddingBottom = '0';
        target.style.marginTop = '0';
        target.style.marginBottom = '0';
        target.offsetHeight; // reflow
        target.style.boxSizing = 'border-box';
        target.style.transitionProperty = "height, margin, padding";
        target.style.transitionDuration = duration + 'ms';
        target.style.height = height + 'px'; // Анимируем к реальной высоте
        // Убираем инлайновые стили после анимации, чтобы не мешать CSS
        window.setTimeout(() => {
            target.style.removeProperty('height');
            target.style.removeProperty('overflow');
            target.style.removeProperty('transition-duration');
            target.style.removeProperty('transition-property');
            target.style.removeProperty('padding-top');
            target.style.removeProperty('padding-bottom');
            target.style.removeProperty('margin-top');
            target.style.removeProperty('margin-bottom');
        }, duration);
    }

    _updateLogo(selector, logoPath) {
        const el = document.querySelector(selector);
        if (el) el.setAttribute('src', logoPath);
    }

    _updateActiveButton(selector, value, attribute = 'data-value') {
        document.querySelectorAll(selector).forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute(attribute) === value);
        });
    }

    _changeAttribute(type, value, selector) {
        document.body.setAttribute(`data-pc-${type}`, value);
        this._updateActiveButton(selector, value);
        localStorage.setItem(`pc-${type}`, value);
        console.debug(`Attr 'data-pc-${type}' set: '${value}' & saved.`);
    }

    presetChange(v) {
        this._changeAttribute('preset', v, this.config.selectors.presetColorBtns);
    }

    headerChange(v) {
        this._changeAttribute('header', v, this.config.selectors.headerColorBtns);
    }

    navbarChange(v) {
        this._changeAttribute('navbar', v, this.config.selectors.navbarColorBtns);
    }

    logoChange(v) {
        this._changeAttribute('logo', v, this.config.selectors.logoColorBtns);
    }

    captionChange(v) {
        this._changeAttribute('caption', v, this.config.selectors.captionColorBtns);
    }

    navImageChange(v) {
        this._changeAttribute('navimg', v, this.config.selectors.navbarImgBtns);
    }

    drpMenuIconChange(v) {
        this._changeAttribute('drp-menu-icon', v, this.config.selectors.drpMenuIconBtns);
    }

    drpMenuLinkIconChange(v) {
        this._changeAttribute('drp-menu-link-icon', v, this.config.selectors.drpMenuLinkIconBtns);
    }

    layoutThemeSidebarChange(v) {
        this._changeAttribute('sidebar_theme', v, this.config.selectors.sidebarThemeBtns);
        const logoPath = `${this.config.selectors.sdkStaticUrl}/datta-able/assets/images/logo-${v === 'true' ? 'dark' : 'white'}.svg`;
        this._updateLogo('.pc-sidebar .m-header .logo-lg', logoPath);
    }

    layoutCaptionChange(v) {
        this._changeAttribute('sidebar-caption', v, this.config.selectors.navCaptionBtns);
    }

    layoutRtlChange(v) {
        const html = document.documentElement;
        if (v === 'true') {
            document.body.setAttribute('data-pc-direction', 'rtl');
            html.setAttribute('dir', 'rtl');
            html.setAttribute('lang', 'ar');
        } else {
            document.body.setAttribute('data-pc-direction', 'ltr');
            html.removeAttribute('dir');
            html.removeAttribute('lang');
        }
        this._updateActiveButton(this.config.selectors.themeDirectionBtns, v);
        localStorage.setItem('pc-direction', v === 'true' ? 'rtl' : 'ltr');
    }

    changeBoxContainer(v) {
        const c = document.querySelector('.pc-content');
        const f = document.querySelector('.footer-wrapper');
        if (c && f) {
            if (v === 'true') {
                c.classList.add('container');
                f.classList.add('container');
                f.classList.remove('container-fluid');
            } else {
                c.classList.remove('container');
                f.classList.remove('container');
                f.classList.add('container-fluid');
            }
            this._updateActiveButton(this.config.selectors.themeContainerBtns, v);
            localStorage.setItem('pc-container-width', v);
        }
    }

    resetLayoutSettings() {
        console.log("Resetting settings...");
        Object.keys(localStorage).forEach(key => {
            if (key.startsWith('pc-')) localStorage.removeItem(key);
        });
        window.location.reload();
    }

    _initThemeScripts() { /* Пусто, т.к. настройки применяются в _applyInitialSettings */
    }

    // --- WebSocket Methods ---
    _getDefaultWsUrl() {
        const p = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${p}//${window.location.host}/ws`;
    } // Метод возвращен
    _checkAuthCookie() {
        return document.cookie.split(';').some((i) => i.trim().startsWith('Authorization='));
    } // Метод возвращен
    connectWebSocket() {
        if (!this.config.wsEnabled || (this.socket && this.socket.readyState === WebSocket.OPEN) || this.isConnectingWs) return;
        this.isConnectingWs = true;
        console.log(`Attempting WS connect: ${this.config.wsUrl}`);
        try {
            this.socket = new WebSocket(this.config.wsUrl);
            this.socket.onopen = (e) => this._onWsOpen(e);
            this.socket.onmessage = (e) => this._onWsMessage(e);
            this.socket.onerror = (e) => this._onWsError(e);
            this.socket.onclose = (e) => this._onWsClose(e);
        } catch (err) {
            console.error("WS creation failed:", err);
            this.isConnectingWs = false;
            this._scheduleWsReconnect();
        }
    }

    _onWsOpen(event) {
        console.log("WS connected");
        this.isConnectingWs = false;
    }

    _onWsMessage(event) {
        console.debug("WS message:", event.data);
        try {
            const msg = JSON.parse(event.data);
            this._handleWebSocketMessage(msg);
        } catch (e) {
            console.error("WS parse error:", e);
        }
    }

    _onWsError(error) {
        console.error("WS error:", error);
        this.isConnectingWs = false;
    }

    _onWsClose(event) {
        console.log(`WS closed: Code=${event.code}, Clean=${event.wasClean}`);
        this.socket = null;
        this.isConnectingWs = false;
        if (!event.wasClean && this.config.wsEnabled) this._scheduleWsReconnect();
    }

    _scheduleWsReconnect() {
        console.log(`WS reconnect in ${this.config.wsReconnectInterval / 1000}s.`);
        setTimeout(() => {
            if (this.isAuthenticated) this.connectWebSocket(); else console.log("WS reconnect skipped: Not authenticated.");
        }, this.config.wsReconnectInterval);
    }

    _sendWebSocketMessage(message) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) try {
            this.socket.send(JSON.stringify(message));
        } catch (e) {
            console.error("WS send error:", e);
        } else console.warn("WS not connected. Cannot send:", message);
    }

    _handleWebSocketMessage(message) {
        const eventType = message.event;
        const payload = message.payload || {};
        const uiKey = payload.model_name && payload.id ? `${payload.model_name}--${payload.id}` : null;
        console.log(`Handling WS event: ${eventType}`, payload);
        switch (eventType) {
            case 'MODEL_UPDATED':
            case 'MODEL_CREATED':
                const elUpd = uiKey ? document.querySelector(`[ui_key="${uiKey}"]`) : null;
                if (elUpd && typeof htmx !== 'undefined') {
                    htmx.trigger(elUpd, 'backend_update');
                } else {
                    const listEl = document.querySelector(`[list-model="${payload.model_name}"]`);
                    if (listEl && typeof htmx !== 'undefined') htmx.trigger(listEl, 'refreshData');
                }
                break;
            case 'MODEL_DELETED':
                const elDel = uiKey ? document.querySelector(`[ui_key="${uiKey}"]`) : null;
                if (elDel) {
                    elDel.style.transition = 'opacity 0.5s ease-out';
                    elDel.style.opacity = '0';
                    setTimeout(() => elDel.remove(), 500);
                }
                break;
            case 'RELOAD_VIEW':
                const mainCt = document.querySelector(this.config.selectors.mainContentArea);
                if (mainCt && typeof htmx !== 'undefined') htmx.trigger(mainCt, 'reloadView');
                break;
            case 'NOTIFICATION':
                this.showNotification(payload.message, payload.type || 'info');
                break;
            case 'AUTH_REFRESH_REQUIRED':
                console.warn("WS: Auth refresh required.");
                this.showNotification("Сессия скоро истечет.", "warning");
                break;
            case 'AUTH_LOGOUT':
                console.warn("WS: Logout required.");
                this.showNotification("Сессия завершена.", "error");
                document.cookie = "Authorization=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT;";
                document.cookie = "refresh_token=; path=/auth/refresh; expires=Thu, 01 Jan 1970 00:00:01 GMT;";
                window.location.href = '/login';
                break;
            default:
                console.warn("Unhandled WS event:", eventType);
        }
    }

    // --- Notification Method ---
    showNotification(message, type = 'info') {
        const cont = document.querySelector(this.config.selectors.toastContainer);
        if (!cont) {
            console.error("Toast container not found:", this.config.selectors.toastContainer);
            alert(`${type.toUpperCase()}: ${message}`);
            return;
        }
        if (typeof bootstrap === 'undefined' || !bootstrap.Toast) {
            console.error("Bootstrap Toast not found!");
            alert(`${type.toUpperCase()}: ${message}`);
            return;
        }
        const id = `toast-${Date.now()}`;
        const bg = {
            info: 'bg-info',
            success: 'bg-success',
            warning: 'bg-warning',
            error: 'bg-danger'
        }[type] || 'bg-secondary';
        const icon = {
            info: 'ti-info-circle',
            success: 'ti-circle-check',
            warning: 'ti-alert-triangle',
            error: 'ti-alert-circle'
        }[type] || 'ti-bell';
        const html = `<div id="${id}" class="toast align-items-center text-white ${bg} border-0" role="alert" aria-live="assertive" aria-atomic="true" data-bs-delay="5000"><div class="d-flex"><div class="toast-body"><i class="ti ${icon} me-2"></i> ${message}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div></div>`;
        cont.insertAdjacentHTML('beforeend', html);
        const el = document.getElementById(id);
        if (el) {
            const toast = new bootstrap.Toast(el);
            toast.show();
            el.addEventListener('hidden.bs.toast', () => el.remove(), {once: true});
        }
    }

    // --- Cookie Helper ---
    _getCookie(name) {
        let v = null;
        if (document.cookie && document.cookie !== '') {
            const c = document.cookie.split(';');
            for (let i = 0; i < c.length; i++) {
                const ck = c[i].trim();
                if (ck.substring(0, name.length + 1) === (name + '=')) {
                    v = decodeURIComponent(ck.substring(name.length + 1));
                    break;
                }
            }
        }
        return v;
    }
}

// --- Create and initialize App instance ---
const app = new App({
    selectors: {
        sdkStaticUrl: '/sdk-static' // Ensure this matches your SDK static path
    }
});
window.app = app;
app.init();

// --- Global helper functions (DEPRECATED - Use event delegation) ---
// function layout_change(layout) { if (window.app) app.changeLayout(layout); } // Use changeLayout now
// function layout_change_default() { if (window.app) app.layoutChangeDefault(); }
// function layout_theme_sidebar_change(value) { if (window.app) app.layoutThemeSidebarChange(value); }
// function layout_caption_change(value) { if (window.app) app.layoutCaptionChange(value); }
// function layout_rtl_change(value) { if (window.app) app.layoutRtlChange(value); }
// function change_box_container(value) { if (window.app) app.changeBoxContainer(value); }
// function preset_change(value) { if (window.app) app.presetChange(value); }
// function header_change(value) { if (window.app) app.headerChange(value); }
// function navbar_change(value) { if (window.app) app.navbarChange(value); }
// function logo_change(value) { if (window.app) app.logoChange(value); }
// function caption_change(value) { if (window.app) app.captionChange(value); }
// function nav_image_change(value) { if (window.app) app.navImageChange(value); }
// function drp_menu_icon_change(value) { if (window.app) app.drpMenuIconChange(value); }
// function drp_menu_link_icon_change(value) { if (window.app) app.drpMenuLinkIconChange(value); }