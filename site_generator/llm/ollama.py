"""Proveedor Ollama local (ia-node).

Medido en ia-node (8 nucleos, sin GPU) con gemma4:26b: ~2,5 tokens/segundo, o
sea 5-8 minutos por sitio completo. Sirve de sobra para el piloto supervisado de
5-10 sitios; para volumen conviene un proveedor en la nube detras del mismo
protocolo.

`repeat_penalty` NO es opcional: sin el, el modelo degenera en bucles de una
misma palabra a mitad de la generacion. Se comprobo en la practica.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from site_generator.llm.base import LLMError

logger = logging.getLogger(__name__)

__all__ = ["OllamaClient"]

# Por debajo de esto el modelo se repite. Ver docstring del modulo.
_REPEAT_PENALTY = 1.15


class OllamaClient:
    nombre = "ollama"

    def __init__(
        self,
        modelo: str = "gemma4:26b",
        *,
        base_url: str = "http://localhost:11434",
        client: httpx.AsyncClient | None = None,
        timeout: float = 900.0,
    ) -> None:
        self._modelo = modelo
        self._base_url = base_url.rstrip("/")
        # El timeout es generoso a proposito: en CPU una generacion larga
        # tranquilamente pasa los 8 minutos.
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._propio = client is None

    async def aclose(self) -> None:
        if self._propio:
            await self._client.aclose()

    async def __aenter__(self) -> OllamaClient:
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
        prompt = (
            f"{instrucciones}\n\n"
            f"Responde UNICAMENTE con un JSON que cumpla este esquema:\n"
            f"{json.dumps(esquema, ensure_ascii=False, indent=2)}\n"
        )
        cuerpo = {
            "model": self._modelo,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": temperatura,
                "num_predict": max_tokens,
                "repeat_penalty": _REPEAT_PENALTY,
            },
        }

        try:
            respuesta = await self._client.post(f"{self._base_url}/api/generate", json=cuerpo)
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama inalcanzable en {self._base_url}: {exc}") from exc

        if respuesta.status_code >= 400:
            raise LLMError(f"Ollama devolvio {respuesta.status_code}: {respuesta.text[:300]}")

        datos = respuesta.json()
        crudo = datos.get("response", "")
        motivo = datos.get("done_reason")
        logger.debug("Ollama genero %s tokens (done_reason=%s)", datos.get("eval_count"), motivo)

        # Distinguir truncado de malformado importa: son problemas distintos con
        # arreglos distintos (subir num_predict / partir el pedido, frente a
        # ajustar el prompt). Sin esto, ambos llegaban como "JSON invalido".
        if motivo == "length":
            raise LLMError(
                f"La generacion se corto por limite de tokens tras {datos.get('eval_count')} "
                f"tokens (max_tokens={max_tokens}). Subi el limite o pedi menos campos por llamada."
            )

        try:
            resultado: Any = json.loads(crudo)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Ollama no devolvio JSON valido: {crudo[:300]}") from exc

        if not isinstance(resultado, dict):
            raise LLMError(f"Se esperaba un objeto JSON, llego {type(resultado).__name__}")
        return resultado
