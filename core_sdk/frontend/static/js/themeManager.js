// core_sdk/frontend/static/js/themeManager.js
class ThemeManager {
    constructor(selectorsConfig, defaultLayout, localStorageLayoutKey) {
        this.selectors = selectorsConfig;
        this.defaultLayout = defaultLayout;
        this.localStorageLayoutKey = localStorageLayoutKey;
        console.debug("ThemeManager initialized.");
    }

    // --- Методы для смены лэйаута (Vertical/Horizontal) ---
    changeLayout(layoutName) {
        if (layoutName !== 'vertical' && layoutName !== 'horizontal') {
            console.warn(`ThemeManager: Unsupported layout: ${layoutName}. Defaulting to ${this.defaultLayout}.`);
            layoutName = this.defaultLayout;
        }
        console.log(`ThemeManager: Request layout change to: ${layoutName}`);
        localStorage.setItem(this.localStorageLayoutKey, layoutName);
        window.location.reload();
    }

    applyLayoutSetting() {
        const savedLayout = localStorage.getItem(this.localStorageLayoutKey) || this.defaultLayout;
        const validLayout = (savedLayout === 'horizontal') ? 'horizontal' : 'vertical';
        document.body.setAttribute('data-pc-layout', validLayout);
        document.body.classList.remove('layout-2', 'layout-3', 'layout-compact', 'layout-tab');
        console.debug(`ThemeManager: Initial layout '${validLayout}' applied.`);
    }

    // --- Методы для управления темой (light/dark/system) ---
    layoutChangeTheme(theme) { // Переименовал, чтобы не путать с changeLayout (лэйаута)
        document.body.setAttribute('data-pc-theme', theme);
        localStorage.setItem('pc-theme', theme);
        const logoSuffix = theme === 'dark' ? 'white' : 'dark';
        const fullLogoPath = `${this.selectors.sdkStaticUrl}/datta-able/assets/images/logo-${logoSuffix}.svg`;
        this._updateLogo('.pc-sidebar .m-header .logo-lg', fullLogoPath);
        this._updateLogo('.auth-main .img-brand', fullLogoPath);
        this._updateActiveButton(this.selectors.themeLayoutBtns, theme === 'dark' ? 'false' : 'true'); // Для кнопок в кастомайзере
        this._updateActiveButton(this.selectors.themeSwitcherHeaderBtns, theme, 'data-theme'); // Для кнопок в хедере
        console.log(`ThemeManager: Theme changed to: ${theme}`);
    }

    layoutChangeThemeDefault() { // Переименовал
        localStorage.removeItem('pc-theme');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)');
        this.layoutChangeTheme(prefersDark.matches ? 'dark' : 'light');
        this._updateActiveButton(this.selectors.themeLayoutBtns, 'default');
        this._updateActiveButton(this.selectors.themeSwitcherHeaderBtns, 'default', 'data-theme');
        console.log("ThemeManager: Theme set to default (system preference).");
    }


    _updateLogo(selector, logoPath) { const el = document.querySelector(selector); if (el) el.setAttribute('src', logoPath); }
    _updateActiveButton(selector, value, attribute = 'data-value') {
        const buttons = document.querySelectorAll(selector);
        buttons.forEach(btn => {
            btn.classList.remove('active'); // Сначала убираем active со всех в группе
        });
        buttons.forEach(btn => { // Затем добавляем к нужной
            if (btn.getAttribute(attribute) === value) {
                btn.classList.add('active');
            }
        });
    }
    _changeAttribute(type, value, selector) { document.body.setAttribute(`data-pc-${type}`, value); this._updateActiveButton(selector, value); localStorage.setItem(`pc-${type}`, value); console.debug(`ThemeManager: Attr 'data-pc-${type}' set: '${value}' & saved.`); }

    presetChange(v) { this._changeAttribute('preset', v, this.selectors.presetColorBtns); }
    headerChange(v) { this._changeAttribute('header', v, this.selectors.headerColorBtns); }
    navbarChange(v) { this._changeAttribute('navbar', v, this.selectors.navbarColorBtns); }
    logoChange(v) { this._changeAttribute('logo', v, this.selectors.logoColorBtns); }
    captionChange(v) { this._changeAttribute('caption', v, this.selectors.captionColorBtns); }
    navImageChange(v) { this._changeAttribute('navimg', v, this.selectors.navbarImgBtns); }
    drpMenuIconChange(v) { this._changeAttribute('drp-menu-icon', v, this.selectors.drpMenuIconBtns); }
    drpMenuLinkIconChange(v) { this._changeAttribute('drp-menu-link-icon', v, this.selectors.drpMenuLinkIconBtns); }
    layoutThemeSidebarChange(v) { this._changeAttribute('sidebar_theme', v, this.selectors.sidebarThemeBtns); const logoSuffix = v === 'true' ? 'dark' : 'white'; const fullLogoPath = `${this.selectors.sdkStaticUrl}/datta-able/assets/images/logo-${logoSuffix}.svg`; this._updateLogo('.pc-sidebar .m-header .logo-lg', fullLogoPath); }
    layoutCaptionChange(v) { this._changeAttribute('sidebar-caption', v, this.selectors.navCaptionBtns); }
    layoutRtlChange(v) { const html = document.documentElement; if (v === 'true') { document.body.setAttribute('data-pc-direction', 'rtl'); html.setAttribute('dir', 'rtl'); html.setAttribute('lang', 'ar'); } else { document.body.setAttribute('data-pc-direction', 'ltr'); html.removeAttribute('dir'); html.removeAttribute('lang'); } this._updateActiveButton(this.selectors.themeDirectionBtns, v); localStorage.setItem('pc-direction', v === 'true' ? 'rtl' : 'ltr'); }
    changeBoxContainer(v) { const c = document.querySelector('.pc-content'); const f = document.querySelector('.footer-wrapper'); if (c && f) { if (v === 'true') { c.classList.add('container'); f.classList.add('container'); f.classList.remove('container-fluid'); } else { c.classList.remove('container'); f.classList.remove('container'); f.classList.add('container-fluid'); } this._updateActiveButton(this.selectors.themeContainerBtns, v); localStorage.setItem('pc-container-width', v); } }

    resetLayoutSettings() {
        console.log("ThemeManager: Resetting layout settings...");
        Object.keys(localStorage).forEach(key => {
            if (key.startsWith('pc-')) localStorage.removeItem(key);
        });
        window.location.reload();
    }

    applyInitialSettings() {
        const currentLayout = document.body.getAttribute('data-pc-layout') || this.defaultLayout;
        this._updateActiveButton(this.selectors.themeLayoutTypeBtns, currentLayout); // Для кастомайзера
        this._updateActiveButton(this.selectors.layoutSwitcherBtns, currentLayout, 'data-layout'); // Для хедера

        this.layoutChangeThemeDefault(); // Установит light/dark/system и активную кнопку
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
        console.debug("ThemeManager: Initial theme settings applied.");
    }

    // --- Методы для управления сайдбаром и меню (если они не зависят от конкретного layout-*.js) ---
    toggleSidebarHide() {
        const sidebar = document.querySelector(this.selectors.sidebar);
        const body = document.body;
        if (sidebar) {
            const isHidden = sidebar.classList.toggle('pc-sidebar-hide');
            body.classList.toggle('pc-sidebar-hide', isHidden);
            console.debug(`ThemeManager: Sidebar hide toggled. Body class 'pc-sidebar-hide' ${isHidden ? 'added' : 'removed'}.`);
        }
    }

    toggleMobileSidebar() {
        const sidebar = document.querySelector(this.selectors.sidebar);
        const hamburger = document.querySelector(this.selectors.mobileCollapseToggle + ' .hamburger'); // Если используется анимация гамбургера
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
        }
    }

    _addMobileOverlay(targetElement) {
        if (!targetElement.querySelector('.pc-menu-overlay')) {
            targetElement.insertAdjacentHTML('beforeend', '<div class="pc-menu-overlay"></div>');
            targetElement.querySelector('.pc-menu-overlay').addEventListener('click', () => this.toggleMobileSidebar(), { once: true });
        }
    }
    _removeMobileOverlay() {
        const o = document.querySelector('.pc-sidebar .pc-menu-overlay') || document.querySelector('.pc-menu-overlay');
        if (o) o.remove();
    }

    // --- Логика для Horizontal Layout ---
    _buildHorizontalMenu() {
        const navbar = document.querySelector(this.selectors.navbar);
        if (!navbar || window.innerWidth < 1025) {
            console.debug("ThemeManager: Skipping horizontal menu build (navbar not found or mobile).");
            return;
        }
        console.debug("ThemeManager: Building horizontal menu...");

        const originalNavbarContentContainer = document.querySelector(this.selectors.sidebarContent); // Это контейнер .navbar-content
        if (originalNavbarContentContainer && !originalNavbarContentContainer.dataset.originalHtml) {
             const originalNavbar = originalNavbarContentContainer.querySelector('.pc-navbar');
             if (originalNavbar) {
                originalNavbarContentContainer.dataset.originalHtml = originalNavbar.innerHTML; // Сохраняем HTML самого .pc-navbar
             }
        }

        if (originalNavbarContentContainer && originalNavbarContentContainer.dataset.originalHtml) {
             navbar.innerHTML = originalNavbarContentContainer.dataset.originalHtml; // Восстанавливаем содержимое .pc-navbar
        } else {
             console.warn("ThemeManager: Original sidebar .pc-navbar content cache not found for horizontal menu.");
             // Если кеша нет, пытаемся работать с текущим DOM, но это может быть не исходное меню
        }

        let flag_w = 0;
        let pc_new_list = '';
        let flag_item = null;

        const existingOther = navbar.querySelector('li.pc-item.pc-hasmenu > a > span.pc-mtext');
        if (existingOther && existingOther.textContent === 'Other' && existingOther.closest('.pc-item')) {
             const otherMenuItem = existingOther.closest('.pc-item');
             const otherSubmenu = otherMenuItem.querySelector('.pc-submenu');
             if (otherSubmenu) pc_new_list = otherSubmenu.innerHTML;
             otherMenuItem.remove();
         }

        const pc_menu_list = navbar.querySelectorAll(':scope > li.pc-item');
        pc_menu_list.forEach((item) => {
            if (item.classList.contains('pc-caption')) { item.style.display = 'none'; return; }
            item.style.display = 'inline-block';
            const itemWidth = item.offsetWidth;
            if (flag_w + itemWidth + 50 > window.innerWidth) { pc_new_list += item.outerHTML; item.remove(); }
            else { flag_w += itemWidth + 49; flag_item = item; }
        });

        if (pc_new_list.length > 0 && flag_item && flag_item.parentNode) { // Добавил flag_item.parentNode
             const otherLi = document.createElement('li');
             otherLi.className = 'pc-item pc-hasmenu';
             otherLi.innerHTML = `<a href="#" class="pc-link"><span class="pc-micon"><svg class="pc-icon"><use xlink:href="#custom-clipboard"></use></svg></span><span class="pc-mtext">Other</span><span class="pc-arrow"><i data-feather="chevron-right"></i></span></a><ul class="pc-submenu">${pc_new_list}</ul>`;
             flag_item.parentNode.insertBefore(otherLi, flag_item.nextSibling);
             if (typeof feather !== 'undefined') feather.replace();
        }
         navbar.querySelectorAll('.pc-trigger').forEach(item => { item.classList.remove('pc-trigger'); const submenu = item.querySelector('.pc-submenu'); if (submenu) submenu.removeAttribute('style'); });
    }

    _setHorizontalMenuEdgeDetection() {
        const menuItems = document.querySelectorAll('.pc-sidebar .pc-navbar .pc-hasmenu'); // Селектор для горизонтального меню
        menuItems.forEach(item => {
            item.removeEventListener('mouseenter', this._handleHorizontalMenuMouseEnter);
            item.removeEventListener('mouseleave', this._handleHorizontalMenuMouseLeave);
            item.addEventListener('mouseenter', this._handleHorizontalMenuMouseEnter.bind(this));
            item.addEventListener('mouseleave', this._handleHorizontalMenuMouseLeave.bind(this));
        });
         console.debug("ThemeManager: Horizontal menu edge detection listeners added/updated.");
    }
    _handleHorizontalMenuMouseEnter(event) { if (window.innerWidth < 1025) return; const targetElement = event.currentTarget; const elm = targetElement.querySelector(':scope > .pc-submenu'); if (!elm) return; const off = elm.getBoundingClientRect(); const l = off.left, t = off.top, w = off.width, h = off.height; const docW = window.innerWidth, docH = window.innerHeight; if (!(l + w <= docW)) elm.classList.add('edge'); if (!(t + h <= docH)) { elm.classList.add('edge-alt'); if (!(t >= h)) { elm.classList.add('edge-alt-full'); const drp_t = t - 140, drp_b = docH - t - 140; elm.style.top = `${drp_t}px`; elm.style.bottom = `-${drp_b}px`; } } }
    _handleHorizontalMenuMouseLeave(event) { if (window.innerWidth < 1025) return; const targetElement = event.currentTarget; const elm = targetElement.querySelector(':scope > .pc-submenu'); if (elm) { elm.classList.remove('edge', 'edge-alt', 'edge-alt-full'); elm.style.top = ''; elm.style.bottom = ''; } }

    // --- Общая логика для Vertical Layout и инициализации кликов ---
    _initVerticalMenu() { console.debug("ThemeManager: Initializing vertical menu (standard click handlers)."); }

    _initMenuClicks(menuContainer = document) {
         if (!menuContainer || !(menuContainer instanceof Element || menuContainer instanceof Document)) {
             console.warn("ThemeManager._initMenuClicks called with invalid container:", menuContainer);
             return;
         }
         const markHandled = (el) => el.dataset.menuClickHandled = 'true';
         const isHandled = (el) => el.dataset.menuClickHandled === 'true';

         menuContainer.querySelectorAll('.pc-navbar > li.pc-hasmenu').forEach(item => {
             if (isHandled(item)) return;
             const link = item.querySelector(':scope > a.pc-link');
             if (link) { // Слушатель на ссылку, а не на LI
                 link.addEventListener('click', (event) => {
                     event.preventDefault(); // Предотвращаем переход по ссылке, если это #!
                     event.stopPropagation();
                     this._toggleMenuItem(item); // Передаем LI
                 });
             }
             markHandled(item);
         });
         menuContainer.querySelectorAll('.pc-submenu li.pc-hasmenu').forEach(item => {
              if (isHandled(item)) return;
              const link = item.querySelector(':scope > a.pc-link');
              if (link) {
                  link.addEventListener('click', (event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      this._toggleMenuItem(item);
                  });
              }
              markHandled(item);
         });
         console.debug("ThemeManager: Menu click handlers initialized/re-initialized for container:", menuContainer.nodeName);
    }

    _toggleMenuItem(targetLi) {
        const submenu = targetLi.querySelector(':scope > .pc-submenu');
        if (!submenu) return;
        const isTriggered = targetLi.classList.contains('pc-trigger');
        if (!isTriggered) {
            const siblings = targetLi.parentNode.children;
            Array.from(siblings).forEach(sibling => { if (sibling !== targetLi && sibling.classList.contains('pc-trigger')) { sibling.classList.remove('pc-trigger'); const siblingSubmenu = sibling.querySelector(':scope > .pc-submenu'); if (siblingSubmenu) this._slideUp(siblingSubmenu, 200); } });
        }
        targetLi.classList.toggle('pc-trigger');
        if (targetLi.classList.contains('pc-trigger')) { this._slideDown(submenu, 200); }
        else { this._slideUp(submenu, 200); }
    }

    // --- Анимации SlideUp/SlideDown ---
    _slideUp(target, duration = 200) { if (!target || target.style.display === 'none') return; target.style.transitionProperty = 'height, margin, padding'; target.style.transitionDuration = duration + 'ms'; target.style.boxSizing = 'border-box'; target.style.height = target.offsetHeight + 'px'; target.offsetHeight; target.style.overflow = 'hidden'; target.style.height = '0'; target.style.paddingTop = '0'; target.style.paddingBottom = '0'; target.style.marginTop = '0'; target.style.marginBottom = '0'; window.setTimeout(() => { target.style.display = 'none'; target.style.removeProperty('height'); target.style.removeProperty('padding-top'); target.style.removeProperty('padding-bottom'); target.style.removeProperty('margin-top'); target.style.removeProperty('margin-bottom'); target.style.removeProperty('overflow'); target.style.removeProperty('transition-duration'); target.style.removeProperty('transition-property'); }, duration); }
    _slideDown(target, duration = 200) { if (!target) return; target.style.removeProperty('display'); let display = window.getComputedStyle(target).display; if (display === 'none') display = 'block'; target.style.display = display; let height = target.offsetHeight; target.style.overflow = 'hidden'; target.style.height = '0'; target.style.paddingTop = '0'; target.style.paddingBottom = '0'; target.style.marginTop = '0'; target.style.marginBottom = '0'; target.offsetHeight; target.style.boxSizing = 'border-box'; target.style.transitionProperty = "height, margin, padding"; target.style.transitionDuration = duration + 'ms'; target.style.height = height + 'px'; window.setTimeout(() => { target.style.removeProperty('height'); target.style.removeProperty('overflow'); target.style.removeProperty('transition-duration'); target.style.removeProperty('transition-property'); target.style.removeProperty('padding-top'); target.style.removeProperty('padding-bottom'); target.style.removeProperty('margin-top'); target.style.removeProperty('margin-bottom'); }, duration); }

    initLayoutSpecificScripts() {
        const currentLayout = document.body.getAttribute('data-pc-layout');
        console.log(`ThemeManager: Initializing scripts for layout: ${currentLayout}`);

        const logoLg = document.querySelector('.pc-sidebar .m-header .logo-lg');
        const logoSm = document.querySelector('.pc-sidebar .m-header .logo-sm');

        if (logoLg && logoSm) {
            // Для Vertical и Horizontal показываем большой логотип
            if (currentLayout === 'vertical' || currentLayout === 'horizontal') {
                logoLg.style.display = 'inline-block';
                logoSm.style.display = 'none';
            } else {
                // Для других (если бы были Compact, Tab) - маленькое
                logoLg.style.display = 'none';
                logoSm.style.display = 'inline-block';
            }
            console.debug(`ThemeManager: Logos visibility updated for layout: ${currentLayout}`);
        }

        switch (currentLayout) {
            case 'horizontal':
                this._buildHorizontalMenu();
                this._setHorizontalMenuEdgeDetection();
                break;
            case 'vertical':
            default:
                this._initVerticalMenu();
                break;
        }
        // Общая инициализация кликов по меню должна происходить после построения меню
        // Если сайдбар грузится через HTMX, то _initMenuClicks нужно вызывать в htmx:afterSwap
        // для элемента .pc-sidebar .pc-navbar
        // Здесь мы вызываем для всего документа, что может быть избыточно, если меню уже обработано
        // this._initMenuClicks(document.querySelector(this.selectors.sidebar) || document);
    }
    // --- НОВЫЙ МЕТОД для настройки слушателей кастомайзера ---
    setupCustomizerListeners() {
        const customizer = document.querySelector(this.selectors.customizerOffcanvas);
        if (!customizer) {
            console.warn("ThemeManager: Customizer offcanvas not found, skipping listeners setup.");
            return;
        }

        customizer.addEventListener('click', (event) => {
            const targetButton = event.target.closest('button[data-value], a[data-value]');
            if (!targetButton) return;

            const value = targetButton.getAttribute('data-value');
            const parentGroup = targetButton.closest('.theme-layout-type, .theme-layout, [class*="theme-color"], [class*="-theme"], [class*="-caption"], [class*="-direction"], [class*="-container"]');

            if (!parentGroup || value === null) return;
            event.preventDefault();

            if (parentGroup.classList.contains('theme-layout-type')) this.changeLayout(value); // Смена Vertical/Horizontal
            else if (parentGroup.classList.contains('theme-layout')) { // Кнопки Light/Dark/Default в кастомайзере
                 if (value === 'true') this.layoutChangeTheme('light');
                 else if (value === 'false') this.layoutChangeTheme('dark');
                 else this.layoutChangeThemeDefault();
            }
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

        const resetButton = customizer.querySelector(this.selectors.customizerResetBtn);
        if (resetButton) {
            resetButton.addEventListener('click', (e) => { e.preventDefault(); this.resetLayoutSettings(); });
        }
        console.debug("ThemeManager: Customizer event listeners setup.");
    }

    // Метод для смены языка (если он относится к теме/UI)
    changeLanguage(lang) {
        if (typeof i18next !== 'undefined' && i18next.changeLanguage) {
            i18next.changeLanguage(lang).then((t) => {
                document.querySelectorAll('[data-i18n]').forEach((el) => { el.innerHTML = t(el.dataset.i18n); });
                document.documentElement.setAttribute('lang', lang);
                console.log(`ThemeManager: Lang changed: ${lang}`);
                this._updateActiveButton(this.selectors.langSwitchers, lang, 'data-lng');
            }).catch(err => console.error(`ThemeManager: Lang change error: ${lang}`, err));
        } else {
            console.warn("ThemeManager: i18next not configured for language switching.");
        }
    }
}
