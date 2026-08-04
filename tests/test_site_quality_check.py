"""Heuristica de calidad del sitio existente."""

from __future__ import annotations

import httpx
import pytest
import respx

from lead_gen.site_quality_check import evaluar_sitio

SITIO_MODERNO = """
<html><head><title>Estudio Juridico Vargas y Asociados</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body><h1>Asesoria legal en Arequipa</h1>
<p>%s</p>
<a href="https://wa.me/51987654321">Escribenos por WhatsApp</a>
</body></html>
""" % ("Somos un estudio juridico con veinte anos de experiencia. " * 20)

SITIO_VIEJO = """
<html><head><title>Inicio</title></head>
<body><table><tr><td>Bienvenidos</td></tr></table></body></html>
"""

SITIO_ESTACIONADO = """
<html><head><title>Dominio</title>
<meta name="viewport" content="width=device-width"></head>
<body><h1>Este dominio esta en venta</h1><p>Domain for sale</p></body></html>
"""


class TestSitioAlcanzable:
    @respx.mock
    async def test_sitio_moderno_puntua_alto(self) -> None:
        respx.get("https://bueno.pe").mock(return_value=httpx.Response(200, html=SITIO_MODERNO))

        resultado = await evaluar_sitio("https://bueno.pe")

        assert resultado.alcanzable is True
        assert resultado.score == 100.0
        assert resultado.vale_la_pena_vender is False
        assert all(resultado.checks.values())

    @respx.mock
    async def test_sitio_viejo_puntua_bajo(self) -> None:
        respx.get("http://viejo.pe").mock(return_value=httpx.Response(200, html=SITIO_VIEJO))

        resultado = await evaluar_sitio("http://viejo.pe")

        assert resultado.score is not None and resultado.score < 40
        assert resultado.vale_la_pena_vender is True
        assert resultado.checks["responsive"] is False
        assert resultado.checks["cta_contacto"] is False
        assert resultado.checks["https"] is False

    @respx.mock
    async def test_redireccion_a_https_cuenta_como_https(self) -> None:
        respx.get("http://redirige.pe").mock(
            return_value=httpx.Response(301, headers={"Location": "https://redirige.pe/"})
        )
        respx.get("https://redirige.pe/").mock(return_value=httpx.Response(200, html=SITIO_MODERNO))

        resultado = await evaluar_sitio("http://redirige.pe")

        assert resultado.checks["https"] is True

    @respx.mock
    async def test_dominio_estacionado_puntua_cero(self) -> None:
        # Pasa checks tecnicos (viewport, https) sin ser un sitio real.
        respx.get("https://estacionado.pe").mock(
            return_value=httpx.Response(200, html=SITIO_ESTACIONADO)
        )

        resultado = await evaluar_sitio("https://estacionado.pe")

        assert resultado.es_placeholder is True
        assert resultado.score == 0.0
        assert resultado.vale_la_pena_vender is True

    @respx.mock
    @pytest.mark.parametrize(
        "cta",
        [
            '<a href="tel:054123456">Llamanos</a>',
            '<a href="https://wa.me/51999">WhatsApp</a>',
            '<a href="mailto:hola@x.pe">Correo</a>',
            "<p>Contactanos hoy</p>",
        ],
    )
    async def test_reconoce_distintas_formas_de_cta(self, cta: str) -> None:
        respx.get("https://x.pe").mock(
            return_value=httpx.Response(200, html=f"<html><body>{cta}</body></html>")
        )

        resultado = await evaluar_sitio("https://x.pe")

        assert resultado.checks["cta_contacto"] is True


class TestSitioInalcanzable:
    """Un sitio caido es informacion util, no un error del pipeline."""

    @respx.mock
    async def test_timeout_no_lanza(self) -> None:
        respx.get("https://caido.pe").mock(side_effect=httpx.ConnectTimeout("timeout"))

        resultado = await evaluar_sitio("https://caido.pe")

        assert resultado.alcanzable is False
        assert resultado.score is None
        assert resultado.motivo_fallo == "ConnectTimeout"
        assert resultado.vale_la_pena_vender is True

    @respx.mock
    async def test_certificado_invalido_no_lanza(self) -> None:
        respx.get("https://ssl-vencido.pe").mock(
            side_effect=httpx.ConnectError("certificate verify failed")
        )

        resultado = await evaluar_sitio("https://ssl-vencido.pe")

        assert resultado.alcanzable is False

    @respx.mock
    async def test_404_cuenta_como_inalcanzable(self) -> None:
        respx.get("https://x.pe").mock(return_value=httpx.Response(404))

        resultado = await evaluar_sitio("https://x.pe")

        assert resultado.alcanzable is False
        assert resultado.motivo_fallo == "HTTP 404"

    @respx.mock
    async def test_html_vacio_no_rompe(self) -> None:
        respx.get("https://vacio.pe").mock(return_value=httpx.Response(200, text=""))

        resultado = await evaluar_sitio("https://vacio.pe")

        assert resultado.alcanzable is True
        assert resultado.score is not None
