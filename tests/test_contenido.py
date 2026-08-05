"""Paso de copywriting, con un LLM simulado.

Los tests corren en milisegundos y sin Ollama. La generacion se pide en tres
piezas cortas justamente porque una sola llamada larga degenera en modelos
locales; aqui se verifica que cada pieza falle de forma aislada y que el
respaldo cubra solo lo que falto.
"""

from __future__ import annotations

from typing import Any

import pytest

from lead_gen.models import LeadDetail
from lead_gen.nichos import Nicho
from site_generator.contenido import contenido_de_plantilla, generar_contenido
from site_generator.llm.base import LLMError
from site_generator.spec import SiteSpec
from site_generator.spec_builder import construir_spec

CABECERA = {
    "titular": "Abogados laboralistas en Arequipa",
    "subtitulo": "Asesoria legal clara para trabajadores y empresas de la region.",
    "cta_texto": "Conversemos sobre tu caso",
}
SOBRE = {
    "sobre_nosotros": (
        "Somos un estudio juridico dedicado al derecho laboral en Arequipa. Escuchamos "
        "tu caso, explicamos las alternativas y acompanamos el proceso hasta el cierre."
    )
}
SERVICIOS = {
    "servicios": [
        {"nombre": "Derecho laboral", "descripcion": "Despidos, beneficios sociales y reclamos."},
        {"nombre": "Derecho de familia", "descripcion": "Divorcios, alimentos y tenencia."},
        {"nombre": "Sucesiones", "descripcion": "Herencias y particion de bienes."},
    ]
}


class LLMFalso:
    """Devuelve respuestas guionadas segun los campos que pide el esquema."""

    nombre = "falso"

    def __init__(self, respuestas: dict[str, Any] | None = None) -> None:
        self.respuestas = respuestas if respuestas is not None else {
            "titular": CABECERA,
            "sobre_nosotros": SOBRE,
            "servicios": SERVICIOS,
        }
        self.llamadas: list[str] = []

    async def generar_json(
        self,
        *,
        instrucciones: str,
        esquema: dict[str, Any],
        temperatura: float = 0.4,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        clave = next(iter(esquema["properties"]))
        self.llamadas.append(clave)
        valor = self.respuestas.get(clave)
        if valor is None:
            raise LLMError(f"sin respuesta guionada para {clave}")
        assert isinstance(valor, dict)
        return valor


@pytest.fixture
def spec(lead_base: LeadDetail, nicho_abogados: Nicho) -> SiteSpec:
    return construir_spec(lead_base, nicho_abogados)


class TestSinLLM:
    async def test_usa_plantilla(self, spec: SiteSpec, nicho_abogados: Nicho) -> None:
        contenido, origen = await generar_contenido(spec, nicho_abogados, None)

        assert origen == "plantilla"
        assert contenido == contenido_de_plantilla(spec, nicho_abogados)


class TestGeneracionPorPiezas:
    async def test_pide_las_tres_piezas_por_separado(
        self, spec: SiteSpec, nicho_abogados: Nicho
    ) -> None:
        # Una sola llamada grande es exactamente el modo de falla que se evita.
        llm = LLMFalso()

        contenido, origen = await generar_contenido(spec, nicho_abogados, llm)

        assert llm.llamadas == ["titular", "sobre_nosotros", "servicios"]
        assert origen == "falso"
        assert contenido.titular == CABECERA["titular"]
        assert contenido.sobre_nosotros == SOBRE["sobre_nosotros"]
        assert len(contenido.servicios) == 3

    async def test_si_falla_una_pieza_las_otras_sobreviven(
        self, spec: SiteSpec, nicho_abogados: Nicho
    ) -> None:
        respaldo = contenido_de_plantilla(spec, nicho_abogados)
        llm = LLMFalso({"titular": CABECERA, "sobre_nosotros": SOBRE})  # servicios falla

        contenido, origen = await generar_contenido(spec, nicho_abogados, llm)

        assert origen == "mixto"
        assert contenido.titular == CABECERA["titular"]
        assert contenido.servicios == respaldo.servicios

    async def test_si_fallan_todas_el_origen_es_plantilla(
        self, spec: SiteSpec, nicho_abogados: Nicho
    ) -> None:
        contenido, origen = await generar_contenido(spec, nicho_abogados, LLMFalso({}))

        assert origen == "plantilla"
        assert contenido == contenido_de_plantilla(spec, nicho_abogados)

    async def test_reintenta_cada_pieza(self, spec: SiteSpec, nicho_abogados: Nicho) -> None:
        llm = LLMFalso({})

        await generar_contenido(spec, nicho_abogados, llm, reintentos=3)

        # 3 piezas x 3 intentos
        assert len(llm.llamadas) == 9


class TestRechazoDeContenidoInvalido:
    async def test_rechaza_una_pieza_que_no_cumple_el_esquema(
        self, spec: SiteSpec, nicho_abogados: Nicho
    ) -> None:
        respaldo = contenido_de_plantilla(spec, nicho_abogados)
        corta = {"titular": "Hola", "subtitulo": "Muy corto", "cta_texto": "Ya"}
        llm = LLMFalso({"titular": corta, "sobre_nosotros": SOBRE, "servicios": SERVICIOS})

        contenido, origen = await generar_contenido(spec, nicho_abogados, llm)

        assert origen == "mixto"
        assert contenido.titular == respaldo.titular

    @pytest.mark.parametrize(
        "texto_sucio",
        [
            "Llamanos al 054 123456 y te asesoramos hoy mismo sin compromiso alguno.",
            "Visita https://estudio-vargas.pe para conocer todos nuestros servicios.",
            "Escribenos a contacto@estudio.pe y coordinamos una cita esta semana.",
        ],
    )
    async def test_rechaza_datos_de_contacto_inventados(
        self, spec: SiteSpec, nicho_abogados: Nicho, texto_sucio: str
    ) -> None:
        # La defensa que impide que el modelo publique un telefono que no existe.
        respaldo = contenido_de_plantilla(spec, nicho_abogados)
        sucio = {**SOBRE, "sobre_nosotros": texto_sucio * 2}
        llm = LLMFalso({"titular": CABECERA, "sobre_nosotros": sucio, "servicios": SERVICIOS})

        contenido, origen = await generar_contenido(spec, nicho_abogados, llm)

        assert origen == "mixto"
        assert contenido.sobre_nosotros == respaldo.sobre_nosotros

    async def test_detecta_datos_de_contacto_dentro_de_los_servicios(
        self, spec: SiteSpec, nicho_abogados: Nicho
    ) -> None:
        # El texto sucio esta anidado dentro del array, no en el nivel superior.
        respaldo = contenido_de_plantilla(spec, nicho_abogados)
        sucios = {
            "servicios": [
                {"nombre": "Laboral", "descripcion": "Despidos y beneficios sociales laborales."},
                {"nombre": "Familia", "descripcion": "Escribenos a wa.me/51999888777 hoy mismo."},
            ]
        }
        llm = LLMFalso({"titular": CABECERA, "sobre_nosotros": SOBRE, "servicios": sucios})

        contenido, origen = await generar_contenido(spec, nicho_abogados, llm)

        assert origen == "mixto"
        assert contenido.servicios == respaldo.servicios


class TestPrompt:
    def test_el_prompt_no_incluye_datos_de_contacto(
        self, spec: SiteSpec, nicho_abogados: Nicho
    ) -> None:
        from site_generator.contenido import construir_instrucciones

        # Primera defensa: lo que el modelo no ve, no lo puede ubicar mal.
        instrucciones = construir_instrucciones(spec, nicho_abogados)

        assert spec.hechos.contacto.telefono not in instrucciones
        assert "054" not in instrucciones
        if spec.hechos.contacto.direccion:
            assert spec.hechos.contacto.direccion not in instrucciones

    def test_el_prompt_lista_el_catalogo_del_nicho(
        self, spec: SiteSpec, nicho_abogados: Nicho
    ) -> None:
        from site_generator.contenido import construir_instrucciones

        instrucciones = construir_instrucciones(spec, nicho_abogados)

        assert spec.hechos.nombre in instrucciones
        assert nicho_abogados.etiqueta in instrucciones
