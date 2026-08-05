"""Proveedor Google Gemini via AI Studio (seccion 5.2 del plan).

Es la respuesta al cuello de botella del modelo local: en ia-node, gemma4:26b
tarda ~3 minutos de CPU por sitio, o sea ~15 horas de computo al mes a 300
sitios. Gemini responde en segundos y su free tier cubre de sobra ese volumen.

Ventaja sobre Ollama para este uso: `responseSchema` obliga la forma del JSON
del lado del servidor. El modo de falla que rompia la generacion local -- el
modelo degenerando en un bucle a mitad del JSON -- deja de ser posible.

La key es de **Google AI Studio** (<https://aistudio.google.com/apikey>) y es
distinta de la de Places, aunque ambas sean de Google. No requiere tarjeta.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from site_generator.llm.base import LLMError

logger = logging.getLogger(__name__)

__all__ = ["GeminiClient", "a_esquema_gemini"]

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Los tipos de JSON Schema van en minusculas; Gemini los espera en mayusculas.
_TIPOS = {
    "object": "OBJECT",
    "string": "STRING",
    "array": "ARRAY",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
}


def a_esquema_gemini(esquema: dict[str, Any]) -> dict[str, Any]:
    """Traduce un JSON Schema al subconjunto de OpenAPI que acepta Gemini.

    Permite que los mismos `_ESQUEMA_*` de `contenido.py` sirvan para Ollama y
    para Gemini sin duplicarlos.
    """
    convertido: dict[str, Any] = {}

    for clave, valor in esquema.items():
        if clave == "type" and isinstance(valor, str):
            convertido["type"] = _TIPOS.get(valor, valor.upper())
        elif clave == "properties" and isinstance(valor, dict):
            convertido["properties"] = {k: a_esquema_gemini(v) for k, v in valor.items()}
        elif clave == "items" and isinstance(valor, dict):
            convertido["items"] = a_esquema_gemini(valor)
        elif clave in ("required", "description", "enum"):
            convertido[clave] = valor
        # Cualquier otra clave de JSON Schema se descarta: Gemini rechaza el
        # pedido completo si el esquema trae campos que no conoce.

    return convertido


class GeminiClient:
    nombre = "gemini"

    def __init__(
        self,
        api_key: str,
        *,
        modelo: str = "gemini-2.5-flash",
        client: httpx.AsyncClient | None = None,
        timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise ValueError("Falta GEMINI_API_KEY")
        self._api_key = api_key
        self._modelo = modelo
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._propio = client is None

    async def aclose(self) -> None:
        if self._propio:
            await self._client.aclose()

    async def __aenter__(self) -> GeminiClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def generar_json(
        self,
        *,
        instrucciones: str,
        esquema: dict[str, Any],
        temperatura: float = 0.4,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        cuerpo = {
            "contents": [{"parts": [{"text": instrucciones}]}],
            "generationConfig": {
                "temperature": temperatura,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
                "responseSchema": a_esquema_gemini(esquema),
            },
        }

        try:
            respuesta = await self._client.post(
                f"{_BASE_URL}/models/{self._modelo}:generateContent",
                headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
                json=cuerpo,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini inalcanzable: {exc}") from exc

        if respuesta.status_code == 429:
            raise LLMError("Gemini devolvio 429: se agoto la cuota del free tier por ahora")
        if respuesta.status_code >= 400:
            raise LLMError(f"Gemini devolvio {respuesta.status_code}: {respuesta.text[:300]}")

        datos = respuesta.json()
        candidatos = datos.get("candidates") or []
        if not candidatos:
            # Sin candidatos suele significar que el prompt fue bloqueado.
            motivo = (datos.get("promptFeedback") or {}).get("blockReason", "desconocido")
            raise LLMError(f"Gemini no devolvio candidatos (blockReason={motivo})")

        candidato = candidatos[0]
        fin = candidato.get("finishReason")
        if fin == "MAX_TOKENS":
            raise LLMError(
                f"La generacion se corto por limite de tokens (max_tokens={max_tokens}). "
                f"Subi el limite o pedi menos campos por llamada."
            )
        if fin not in (None, "STOP"):
            raise LLMError(f"Gemini termino con finishReason={fin}")

        partes = (candidato.get("content") or {}).get("parts") or []
        crudo = "".join(p.get("text", "") for p in partes)
        if not crudo.strip():
            raise LLMError("Gemini devolvio una respuesta vacia")

        try:
            resultado: Any = json.loads(crudo)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Gemini no devolvio JSON valido: {crudo[:300]}") from exc

        if not isinstance(resultado, dict):
            raise LLMError(f"Se esperaba un objeto JSON, llego {type(resultado).__name__}")
        return resultado
