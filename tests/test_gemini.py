"""Proveedor Gemini y seleccion de proveedor. Sin key y sin red."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from settings import Settings
from site_generator.llm import construir_llm
from site_generator.llm.base import LLMError
from site_generator.llm.gemini import GeminiClient, a_esquema_gemini

MODELO = "gemini-2.5-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent"

ESQUEMA = {
    "type": "object",
    "properties": {
        "titular": {"type": "string", "description": "Maximo 10 palabras"},
        "servicios": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"nombre": {"type": "string"}},
                "required": ["nombre"],
            },
        },
    },
    "required": ["titular"],
}


def _respuesta(texto: str, fin: str = "STOP") -> dict[str, Any]:
    return {"candidates": [{"content": {"parts": [{"text": texto}]}, "finishReason": fin}]}


@pytest.fixture
def cliente() -> GeminiClient:
    return GeminiClient("clave-de-prueba", modelo=MODELO)


class TestConversionDeEsquema:
    """Gemini usa un subconjunto de OpenAPI, no JSON Schema tal cual."""

    def test_pasa_los_tipos_a_mayusculas(self) -> None:
        convertido = a_esquema_gemini(ESQUEMA)

        assert convertido["type"] == "OBJECT"
        assert convertido["properties"]["titular"]["type"] == "STRING"
        assert convertido["properties"]["servicios"]["type"] == "ARRAY"

    def test_convierte_recursivamente_los_items(self) -> None:
        convertido = a_esquema_gemini(ESQUEMA)

        items = convertido["properties"]["servicios"]["items"]
        assert items["type"] == "OBJECT"
        assert items["properties"]["nombre"]["type"] == "STRING"

    def test_conserva_required_y_description(self) -> None:
        convertido = a_esquema_gemini(ESQUEMA)

        assert convertido["required"] == ["titular"]
        assert "description" in convertido["properties"]["titular"]

    def test_descarta_claves_que_gemini_no_conoce(self) -> None:
        # Gemini rechaza el pedido entero si el esquema trae campos ajenos.
        convertido = a_esquema_gemini({"type": "string", "minLength": 5, "pattern": "x"})

        assert convertido == {"type": "STRING"}


class TestGeneracion:
    @respx.mock
    async def test_devuelve_el_json_parseado(self, cliente: GeminiClient) -> None:
        respx.post(URL).mock(
            return_value=httpx.Response(200, json=_respuesta('{"titular": "Abogados en Arequipa"}'))
        )

        resultado = await cliente.generar_json(instrucciones="escribe", esquema=ESQUEMA)

        assert resultado == {"titular": "Abogados en Arequipa"}

    @respx.mock
    async def test_manda_la_key_y_pide_json_estructurado(self, cliente: GeminiClient) -> None:
        ruta = respx.post(URL).mock(
            return_value=httpx.Response(200, json=_respuesta('{"titular": "x"}'))
        )

        await cliente.generar_json(instrucciones="escribe", esquema=ESQUEMA, max_tokens=333)

        pedido = ruta.calls.last.request
        assert pedido.headers["x-goog-api-key"] == "clave-de-prueba"
        import json

        cuerpo = json.loads(pedido.content)
        config = cuerpo["generationConfig"]
        assert config["responseMimeType"] == "application/json"
        assert config["maxOutputTokens"] == 333
        # El esquema obliga la forma del lado del servidor: es la ventaja
        # concreta sobre el modelo local, que degeneraba a mitad del JSON.
        assert config["responseSchema"]["type"] == "OBJECT"


class TestErrores:
    def test_sin_key_falla_al_construir(self) -> None:
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            GeminiClient("")

    @respx.mock
    async def test_truncado_por_tokens_se_reporta_como_tal(self, cliente: GeminiClient) -> None:
        respx.post(URL).mock(
            return_value=httpx.Response(200, json=_respuesta('{"titular": "a', fin="MAX_TOKENS"))
        )

        with pytest.raises(LLMError, match="limite de tokens"):
            await cliente.generar_json(instrucciones="x", esquema=ESQUEMA)

    @respx.mock
    async def test_cuota_agotada_se_distingue(self, cliente: GeminiClient) -> None:
        respx.post(URL).mock(return_value=httpx.Response(429, text="quota exceeded"))

        with pytest.raises(LLMError, match="free tier"):
            await cliente.generar_json(instrucciones="x", esquema=ESQUEMA)

    @respx.mock
    async def test_prompt_bloqueado_se_reporta(self, cliente: GeminiClient) -> None:
        respx.post(URL).mock(
            return_value=httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
        )

        with pytest.raises(LLMError, match="SAFETY"):
            await cliente.generar_json(instrucciones="x", esquema=ESQUEMA)

    @respx.mock
    async def test_json_invalido_se_reporta(self, cliente: GeminiClient) -> None:
        respx.post(URL).mock(return_value=httpx.Response(200, json=_respuesta("no soy json")))

        with pytest.raises(LLMError, match="JSON valido"):
            await cliente.generar_json(instrucciones="x", esquema=ESQUEMA)

    @respx.mock
    async def test_respuesta_vacia_se_reporta(self, cliente: GeminiClient) -> None:
        respx.post(URL).mock(return_value=httpx.Response(200, json=_respuesta("   ")))

        with pytest.raises(LLMError, match="vacia"):
            await cliente.generar_json(instrucciones="x", esquema=ESQUEMA)


class TestSeleccionDeProveedor:
    def test_auto_prefiere_gemini_si_hay_key(self) -> None:
        llm = construir_llm(Settings(llm_proveedor="auto", gemini_api_key="k"))

        assert llm is not None and llm.nombre == "gemini"

    def test_auto_cae_a_ollama_sin_key(self) -> None:
        llm = construir_llm(Settings(llm_proveedor="auto", gemini_api_key=""))

        assert llm is not None and llm.nombre == "ollama"

    def test_ninguno_desactiva_la_ia(self) -> None:
        assert construir_llm(Settings(llm_proveedor="ninguno")) is None

    def test_gemini_sin_key_falla_con_mensaje_util(self) -> None:
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            construir_llm(Settings(llm_proveedor="gemini", gemini_api_key=""))

    def test_proveedor_desconocido_lista_los_validos(self) -> None:
        with pytest.raises(ValueError, match="auto, gemini, ollama, ninguno"):
            construir_llm(Settings(llm_proveedor="chatgpt"))
