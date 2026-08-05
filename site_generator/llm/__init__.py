"""Proveedores de LLM detras de un protocolo comun."""

from __future__ import annotations

import logging

from settings import Settings
from site_generator.llm.base import LLMClient, LLMError

logger = logging.getLogger(__name__)

__all__ = ["LLMClient", "LLMError", "construir_llm"]


def construir_llm(ajustes: Settings) -> LLMClient | None:
    """Elige el proveedor segun la configuracion. `None` = solo plantillas.

    Con `auto` se prefiere Gemini cuando hay key: en ia-node (sin GPU) el modelo
    local tarda ~3 minutos por sitio, contra segundos de Gemini. Ollama queda
    como respaldo sin dependencias externas.
    """
    proveedor = ajustes.llm_proveedor.strip().lower()

    if proveedor == "ninguno":
        return None

    if proveedor == "auto":
        proveedor = "gemini" if ajustes.gemini_api_key else "ollama"

    if proveedor == "gemini":
        if not ajustes.gemini_api_key:
            raise ValueError(
                "LLM_PROVEEDOR=gemini pero falta GEMINI_API_KEY. "
                "Ver docs/setup-gemini.md, o usa LLM_PROVEEDOR=ollama."
            )
        from site_generator.llm.gemini import GeminiClient

        logger.info("Copywriting con Gemini (%s)", ajustes.gemini_modelo)
        return GeminiClient(ajustes.gemini_api_key, modelo=ajustes.gemini_modelo)

    if proveedor == "ollama":
        from site_generator.llm.ollama import OllamaClient

        logger.info("Copywriting con Ollama local (%s)", ajustes.ollama_modelo)
        return OllamaClient(ajustes.ollama_modelo)

    raise ValueError(
        f"LLM_PROVEEDOR desconocido: '{ajustes.llm_proveedor}'. "
        f"Valores validos: auto, gemini, ollama, ninguno."
    )
