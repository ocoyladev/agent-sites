"""Configuracion del proyecto, leida de variables de entorno / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from lead_gen.cost import Sku

__all__ = ["Settings", "get_settings"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://agencia:agencia@localhost:5435/agencia"

    google_places_api_key: str = ""

    # Topes por corrida. Red de seguridad contra un bug que dispare miles de
    # requests; no reemplaza las alertas de presupuesto de Google Cloud.
    places_max_enterprise_calls_per_run: int = 350
    places_max_atmosphere_calls_per_run: int = 100
    places_max_photo_calls_per_run: int = 100

    nicho: str = "abogados"
    ciudad: str = "Arequipa"

    def limites_de_costo(self) -> dict[Sku, int]:
        return {
            Sku.ENTERPRISE: self.places_max_enterprise_calls_per_run,
            Sku.ENTERPRISE_ATMOSPHERE: self.places_max_atmosphere_calls_per_run,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
