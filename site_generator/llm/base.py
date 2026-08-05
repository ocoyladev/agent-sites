"""Contrato de los proveedores de LLM.

Mismo patron que `LeadSource`: cambiar de Ollama local a Gemini o Anthropic es
una linea de configuracion, no una reescritura. Ver seccion 5.2 del plan.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["LLMClient", "LLMError"]


class LLMError(RuntimeError):
    """El proveedor fallo o devolvio algo que no cumple el esquema pedido."""


@runtime_checkable
class LLMClient(Protocol):
    """Genera JSON que cumple un esquema dado.

    Solo hay un metodo, y devuelve JSON estructurado en vez de texto libre: el
    generador nunca quiere prosa suelta, siempre quiere campos concretos que
    pueda validar contra un modelo de pydantic.
    """

    nombre: str

    async def generar_json(
        self,
        *,
        instrucciones: str,
        esquema: dict[str, Any],
        temperatura: float = 0.4,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        """Devuelve un dict que deberia cumplir `esquema`.

        No garantiza validez -- el llamador valida con pydantic y reintenta.
        """
        ...
