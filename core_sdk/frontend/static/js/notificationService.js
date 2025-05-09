// core_sdk/frontend/static/js/notificationService.js
class NotificationService {
    constructor(toastContainerSelector = '#toast-container') {
        this.toastContainerSelector = toastContainerSelector;
        console.debug("NotificationService initialized.");
    }

    show(message, type = 'info') {
        const toastContainer = document.querySelector(this.toastContainerSelector);
        if (!toastContainer) {
            console.error("Toast container not found! Selector:", this.toastContainerSelector);
            alert(`${type.toUpperCase()}: ${message}`); // Fallback
            return;
        }
        if (typeof bootstrap === 'undefined' || !bootstrap.Toast) {
            console.error("Bootstrap Toast component not found!");
            alert(`${type.toUpperCase()}: ${message}`); // Fallback
            return;
        }

        const toastId = `toast-${Date.now()}`;
        const bgClass = {
            'info': 'bg-info text-white',
            'success': 'bg-success text-white',
            'warning': 'bg-warning text-dark', // text-dark для лучшей читаемости на желтом
            'error': 'bg-danger text-white'
        }[type] || 'bg-secondary text-white';

        const iconClass = {
            'info': 'ti ti-info-circle',
            'success': 'ti ti-circle-check',
            'warning': 'ti ti-alert-triangle',
            'error': 'ti ti-alert-circle'
        }[type] || 'ti ti-bell';

        const toastHtml = `
            <div id="${toastId}" class="toast align-items-center ${bgClass} border-0" role="alert" aria-live="assertive" aria-atomic="true" data-bs-delay="5000">
                <div class="d-flex">
                    <div class="toast-body">
                       <i class="${iconClass} me-2"></i> ${message}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
            </div>
        `;
        toastContainer.insertAdjacentHTML('beforeend', toastHtml);

        const toastElement = document.getElementById(toastId);
        if (toastElement) {
            const toast = new bootstrap.Toast(toastElement);
            toast.show();
            toastElement.addEventListener('hidden.bs.toast', () => {
                toastElement.remove();
            }, { once: true });
        }
    }
}