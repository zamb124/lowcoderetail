# purchase/app/registry_config.py
import logging
from core_sdk.registry import ModelRegistry, RemoteConfig
from .models.purchase_order import PurchaseOrder, PurchaseOrderFilter
from .schemas.purchase_order_schema import PurchaseOrderCreate, PurchaseOrderUpdate, PurchaseOrderRead
from .data_access.purchase_order_manager import PurchaseOrderManager

# Импортируем схемы Company и настройки
from .schemas.company_schema import CompanyReadPurchase, CompanyCreatePurchase, CompanyUpdatePurchase
from .config import settings as purchase_settings # Используем настройки текущего сервиса

logger = logging.getLogger("app.registry_config")

def configure_purchase_registry():
    service_name = "Purchase"
    model_to_register = "PurchaseOrder"

    try:
        if ModelRegistry.is_configured() and ModelRegistry.get_model_info(model_to_register):
            logger.warning(f"Model '{model_to_register}' already registered. Skipping local configuration for {service_name} service.")
        else:
            logger.info(f"Configuring local ModelRegistry for {service_name} service...")
            ModelRegistry.register_local(
                model_cls=PurchaseOrder,
                manager_cls=PurchaseOrderManager,
                filter_cls=PurchaseOrderFilter,
                create_schema_cls=PurchaseOrderCreate,
                update_schema_cls=PurchaseOrderUpdate,
                read_schema_cls=PurchaseOrderRead,
                model_name=model_to_register
            )
    except Exception:
        # Если первая проверка упала, значит PurchaseOrder еще не зарегистрирован, продолжаем с локальной регистрацией
        logger.info(f"Configuring local ModelRegistry for {service_name} service (model not found initially)...")
        ModelRegistry.register_local(
            model_cls=PurchaseOrder,
            manager_cls=PurchaseOrderManager,
            filter_cls=PurchaseOrderFilter,
            create_schema_cls=PurchaseOrderCreate,
            update_schema_cls=PurchaseOrderUpdate,
            read_schema_cls=PurchaseOrderRead,
            model_name=model_to_register
        )


    # Регистрация удаленной модели Company из Core сервиса
    remote_company_model_name = "CoreCompany" # Уникальное имя для удаленной модели в реестре Purchase

    try:
        if ModelRegistry.is_configured() and ModelRegistry.get_model_info(remote_company_model_name):
            logger.warning(f"Remote model '{remote_company_model_name}' already registered. Skipping remote configuration.")
        else:
            if not purchase_settings.CORE_SERVICE_URL:
                logger.error(f"CORE_SERVICE_URL is not set in Purchase settings. Cannot register remote model '{remote_company_model_name}'.")
            else:
                logger.info(f"Registering remote model '{remote_company_model_name}' (from Core service at {purchase_settings.CORE_SERVICE_URL})...")
                ModelRegistry.register_remote(
                    model_cls=CompanyReadPurchase, # Схема, в которую будут парситься ответы от Core
                    config=RemoteConfig(
                        service_url=purchase_settings.CORE_SERVICE_URL,
                        model_endpoint="/api/v1/companies" # Стандартный эндпоинт для Company в Core
                    ),
                    create_schema_cls=CompanyCreatePurchase, # Схема для создания Company в Core
                    update_schema_cls=CompanyUpdatePurchase, # Схема для обновления Company в Core
                    read_schema_cls=CompanyReadPurchase,   # Схема для чтения (та же, что и model_cls)
                    model_name=remote_company_model_name
                )
                logger.info(f"Remote model '{remote_company_model_name}' registered successfully.")
    except Exception as e:
        logger.error(f"Failed to register remote model '{remote_company_model_name}'. Error: {e}", exc_info=True)
        # Решите, критична ли эта ошибка для запуска сервиса Purchase
        # raise # Раскомментируйте, если это должно останавливать запуск

    logger.info(f"ModelRegistry configuration complete for {service_name} service.")

# Вызываем конфигурацию при импорте модуля
configure_purchase_registry()