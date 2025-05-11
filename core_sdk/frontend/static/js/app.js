// core_sdk/frontend/static/js/app.js

class App {
    constructor(config = {}) {
        this.config = {

            wsEnabled: config.wsEnabled !== undefined ? config.wsEnabled : true,
            wsUrl: this._getDefaultWsUrl(),
            wsReconnectInterval: config.wsReconnectInterval || 5000,
            selectors: {
                mainContentArea: '#main-content-area',
                modalPlaceholder: '#modal-placeholder',
                toastContainer: '#toast-container',
                sidebar: '.pc-sidebar',
                dropdownToggle: '[data-bs-toggle="dropdown"]',
                sidebarHideToggle: '#sidebar-hide',
                mobileCollapseToggle: '#mobile-collapse',
                layoutSwitcherBtns: '.layout-switcher', // В хедере
                langSwitchers: '.lng-dropdown .dropdown-item[data-lng]', // В хедере
                themeSwitcherHeaderBtns: '.pc-header .theme-switcher[data-theme]', // В хедере
                sdkStaticUrl: config.sdkStaticUrl || '/sdk-static',
                // Селекторы для ComponentInitializer
                simplebar: '[data-simplebar]',
                tooltip: '[data-bs-toggle="tooltip"]',
                popover: '[data-bs-toggle="popover"]',
                choicesjs: 'select[data-control="choicesjs"][data-load-options-url]',
                sidebarContent: '.pc-sidebar .navbar-content',
                headerNotificationScroll: '.header-notification-scroll',
                // Селекторы для ThemeManager (кастомайзер)
                customizerOffcanvas: '#offcanvas_pc_layout',
                customizerResetBtn: '#layoutreset',
                themeLayoutBtns: '.theme-layout .btn', // Light/Dark/System в кастомайзере
                themeLayoutTypeBtns: '.theme-layout-type .btn', // Vertical/Horizontal в кастомайзере
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
            },
            defaultLayout: 'vertical',
            localStorageLayoutKey: 'pc-layout-choice',
            titleResolver: { // Новая конфигурация для TitleResolver
                debounceTimeout: 100,
                apiUrl: '/sdk/resolve-titles', // Убедитесь, что URL правильный
                placeholder: '...',
                notFoundText: '(не найдено)'
            },
            //...config
        };

        this.isAuthenticated = this._checkAuthCookie();

        this.notificationService = new NotificationService(this.config.selectors.toastContainer);
        this.componentInitializer = new ComponentInitializer(this.config.selectors);
        this.themeManager = new ThemeManager(this.config.selectors, this.config.defaultLayout, this.config.localStorageLayoutKey);
        this.htmxManager = new HtmxManager(this.componentInitializer, this.notificationService);
        this.webSocketManager = new WebSocketManager(
            { wsUrl: this.config.wsUrl, wsReconnectInterval: this.config.wsReconnectInterval, wsEnabled: this.config.wsEnabled },
            this.notificationService,
            this.isAuthenticated
        );
        this.titleResolver = new TitleResolver(this.config.titleResolver);
        console.debug("App instance and managers created.");
        this.themeManager.applyLayoutSetting();
        this.htmxManager = new HtmxManager(this.componentInitializer, this.notificationService, this.titleResolver); // <--- ПЕРЕДАЕМ
    }

    init() {
        document.addEventListener('DOMContentLoaded', () => {
            console.log("DOM fully loaded and parsed. Initializing App systems.");
            this.componentInitializer.initializeAll(document);
            this.htmxManager.setupListeners();
            this._setupGlobalEventListeners();
            this.themeManager.setupCustomizerListeners(); // Вызываем метод ThemeManager
            this.themeManager.applyInitialSettings();
            this.themeManager.initLayoutSpecificScripts();

            if (this.isAuthenticated && this.config.wsEnabled) { // Проверяем isEnabled здесь
                this.webSocketManager.connect();
            }
            this.titleResolver.scanAndResolve(document.body);
        });
    }

    _setupGlobalEventListeners() {
        document.body.addEventListener('click', (event) => {
            const sidebarHideBtn = event.target.closest(this.config.selectors.sidebarHideToggle);
            const mobileCollapseBtn = event.target.closest(this.config.selectors.mobileCollapseToggle);
            const langSwitcher = event.target.closest(this.config.selectors.langSwitchers);
            const layoutSwitcherBtn = event.target.closest(this.config.selectors.layoutSwitcherBtns + '[data-layout]');
            const themeSwitcherBtnInHeader = event.target.closest(this.config.selectors.themeSwitcherHeaderBtns);

            if (sidebarHideBtn) { event.preventDefault(); this.themeManager.toggleSidebarHide(); }
            else if (mobileCollapseBtn) { event.preventDefault(); this.themeManager.toggleMobileSidebar(); }
            else if (langSwitcher) { event.preventDefault(); const lang = langSwitcher.getAttribute('data-lng'); if (lang) this.themeManager.changeLanguage(lang); }
            else if (layoutSwitcherBtn) { event.preventDefault(); const layoutValue = layoutSwitcherBtn.getAttribute('data-layout'); if (layoutValue) this.themeManager.changeLayout(layoutValue); }
            else if (themeSwitcherBtnInHeader) {
                event.preventDefault();
                const themeValue = themeSwitcherBtnInHeader.getAttribute('data-theme');
                if (themeValue === 'light') this.themeManager.layoutChangeTheme('light'); // Используем layoutChangeTheme
                else if (themeValue === 'dark') this.themeManager.layoutChangeTheme('dark');
                else this.themeManager.layoutChangeThemeDefault(); // Используем layoutChangeThemeDefault
            }
        });
        console.debug("App: Global event listeners setup.");
    }

    _getDefaultWsUrl() { const p = window.location.protocol === 'https:' ? 'wss:' : 'ws:'; return `${p}//${window.location.host}/ws`; }
    _checkAuthCookie() { return document.cookie.split(';').some((i) => i.trim().startsWith('Authorization=')); }
    _getCookie(name) { let v = null; if (document.cookie && document.cookie !== '') { const c = document.cookie.split(';'); for (let i = 0; i < c.length; i++) { const ck = c[i].trim(); if (ck.substring(0, name.length + 1) === (name + '=')) { v = decodeURIComponent(ck.substring(name.length + 1)); break; } } } return v; }
}

// --- Create and initialize App instance ---
const app = new App({
    selectors: {
        sdkStaticUrl: '/sdk-static'
    }
});
window.app = app;
app.init();