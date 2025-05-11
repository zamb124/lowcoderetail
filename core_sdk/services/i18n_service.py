# core/app/services/i18n_service.py

import pycountry
from babel import Locale, UnknownLocaleError
from babel.numbers import list_currencies
from typing import List, Dict, Optional

# --- ИЗМЕНЕНИЕ: Импортируем схемы из локального модуля schemas ---
from ..schemas import i18n as i18n_schemas
# -------------------------------------------------------------

# Кэширование результатов (оставляем как есть)
_language_cache: Optional[List[i18n_schemas.Language]] = None
_country_cache: Optional[List[i18n_schemas.Country]] = None
_currency_cache: Optional[List[i18n_schemas.Currency]] = None


async def get_languages() -> List[i18n_schemas.Language]:
    """Возвращает список поддерживаемых языков."""
    global _language_cache
    if _language_cache is not None:
        return _language_cache

    languages = []
    processed_codes = (
        set()
    )  # Для избежания дубликатов, если pycountry дает несколько записей

    for lang in pycountry.languages:
        # Предпочитаем alpha_2 (ISO 639-1), если есть
        code = getattr(lang, "alpha_2", None)
        if code and code not in processed_codes:
            try:
                locale = Locale.parse(code)
                # Используем английское название языка из Babel
                name = locale.get_language_name("en")
                # --- ИЗМЕНЕНИЕ: Создаем экземпляр схемы ---
                languages.append(i18n_schemas.Language(code=code, name=name))
                # -----------------------------------------
                processed_codes.add(code)
            except UnknownLocaleError:
                # print(f"Warning: Babel does not know language code {code}")
                pass  # Пропускаем языки, которые Babel не знает
            except Exception as e:
                print(f"Error processing language {code}: {e}")

    # Сортируем по имени
    languages.sort(key=lambda x: x.name)
    _language_cache = languages
    print(f"Loaded {len(languages)} languages.")
    return languages


async def get_countries() -> List[i18n_schemas.Country]:
    """Возвращает список стран."""
    global _country_cache
    if _country_cache is not None:
        return _country_cache

    countries = []
    for country in pycountry.countries:
        # --- ИЗМЕНЕНИЕ: Создаем экземпляр схемы ---
        countries.append(i18n_schemas.Country(code=country.alpha_2, name=country.name))
        # -----------------------------------------

    countries.sort(key=lambda x: x.name)
    _country_cache = countries
    print(f"Loaded {len(countries)} countries.")
    return countries


async def get_currencies() -> List[i18n_schemas.Currency]:
    """Возвращает список валют."""
    global _currency_cache
    if _currency_cache is not None:
        return _currency_cache

    currencies = []
    # Используем Babel для получения списка валют и их названий
    # 'en' гарантирует английские названия
    currency_names = Locale("en").currencies
    for code in sorted(list_currencies()):  # Сортируем коды для консистентности
        name = currency_names.get(code, code)  # Используем код, если имя не найдено
        # --- ИЗМЕНЕНИЕ: Создаем экземпляр схемы ---
        currencies.append(i18n_schemas.Currency(code=code, name=name))
        # -----------------------------------------

    # Сортировка уже не нужна, т.к. отсортировали коды
    # currencies.sort(key=lambda x: x.name)
    _currency_cache = currencies
    print(f"Loaded {len(currencies)} currencies.")
    return currencies
