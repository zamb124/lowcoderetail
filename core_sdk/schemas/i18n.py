# core/app/schemas/i18n.py
from sqlmodel import SQLModel
from pydantic import Field # Можно использовать Field из Pydantic или SQLModel

class Language(SQLModel):
    """Schema for representing a language."""
    code: str = Field(..., description="ISO 639-1 language code (e.g., 'en', 'fr').")
    name: str = Field(..., description="Human-readable name of the language (in English).")

class Country(SQLModel):
    """Schema for representing a country."""
    code: str = Field(..., description="ISO 3166-1 alpha-2 country code (e.g., 'US', 'GB').")
    name: str = Field(..., description="Human-readable name of the country.")

class Currency(SQLModel):
    """Schema for representing a currency."""
    code: str = Field(..., description="ISO 4217 currency code (e.g., 'USD', 'EUR').")
    name: str = Field(..., description="Human-readable name of the currency.")
    # symbol: Optional[str] = Field(None, description="Currency symbol (e.g., '$', '€').") # Опционально