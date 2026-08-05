"""Harness de QA.

Un harness que solo aprueba sitios buenos no sirve de nada: lo que importa es
que rechace los malos. Cada test de aqui construye un sitio roto de una forma
especifica y exige que el reporte lo detecte.
"""

from __future__ import annotations

import pytest

from lead_gen.models import LeadDetail, Resena
from lead_gen.nichos import Nicho
from site_generator.qa import revisar_html
from site_generator.spec import Contenido, Servicio, SiteSpec
from site_generator.spec_builder import construir_spec


@pytest.fixture
def spec(lead_base: LeadDetail, nicho_abogados: Nicho) -> SiteSpec:
    lead = lead_base.model_copy(
        update={
            "telefono": "987 654 321",
            "resenas": (
                Resena(
                    autor="Maria Quispe",
                    calificacion=5,
                    texto="Me asesoraron en un caso laboral y explicaron todo con claridad.",
                ),
            ),
        }
    )
    base = construir_spec(lead, nicho_abogados)
    contenido = Contenido(
        titular="Abogados laboralistas en Arequipa",
        subtitulo="Asesoria legal clara para trabajadores y empresas de la region.",
        sobre_nosotros=(
            "Somos un estudio juridico dedicado al derecho laboral. Escuchamos tu caso, "
            "explicamos las alternativas disponibles y acompanamos todo el proceso hasta "
            "el cierre, con comunicacion directa en cada etapa del camino."
        ),
        servicios=(
            Servicio(
                nombre="Derecho laboral",
                descripcion="Atendemos despidos, beneficios sociales y reclamos laborales.",
            ),
            Servicio(
                nombre="Derecho de familia",
                descripcion="Procesos de divorcio, alimentos y tenencia con trato reservado.",
            ),
        ),
        cta_texto="Conversemos sobre tu caso",
    )
    return base.model_copy(update={"contenido": contenido})


def _html(spec: SiteSpec, *, cuerpo: str | None = None) -> str:
    """Sitio minimo pero valido, para mutarlo en cada test."""
    contacto = spec.hechos.contacto
    relleno = "Asesoria legal profesional en Arequipa para empresas y trabajadores. " * 12
    interior = (
        cuerpo
        or f"""
      <h1>{spec.contenido.titular if spec.contenido else ""}</h1>
      <p>{relleno}</p>
      <p>{spec.hechos.nombre}</p>
      <a href="{contacto.telefono_href}">Llamar</a>
      <a href="{contacto.whatsapp_url}">WhatsApp</a>
      {"".join(f"<blockquote>{r.texto}</blockquote>" for r in spec.hechos.resenas)}
    """
    )
    return f"""<!doctype html><html lang="es"><head>
      <title>{spec.hechos.nombre} | Abogados</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      </head><body>{interior}</body></html>"""


class TestSitioCorrecto:
    def test_aprueba(self, spec: SiteSpec) -> None:
        reporte = revisar_html(_html(spec), spec)
        assert reporte.aprobado, reporte.resumen()


class TestFactCheck:
    """Los checks que impiden publicar datos falsos del negocio."""

    def test_rechaza_un_telefono_inventado(self, spec: SiteSpec) -> None:
        cuerpo = _html(spec).replace('href="tel:+51987654321"', 'href="tel:+51999888777"')

        reporte = revisar_html(cuerpo, spec)

        assert not reporte.aprobado
        assert reporte.checks["telefono_correcto"] is False

    def test_rechaza_un_whatsapp_de_otro_numero(self, spec: SiteSpec) -> None:
        cuerpo = _html(spec).replace("wa.me/51987654321", "wa.me/51900000000")

        reporte = revisar_html(cuerpo, spec)

        assert reporte.checks["whatsapp_correcto"] is False

    def test_rechaza_whatsapp_si_el_negocio_no_tiene_movil(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        fijo = construir_spec(
            lead_base.model_copy(update={"telefono": "054 123456"}), nicho_abogados
        )
        fijo = fijo.model_copy(
            update={
                "contenido": Contenido(
                    titular="Abogados en Arequipa",
                    subtitulo="Asesoria legal clara para trabajadores y empresas.",
                    sobre_nosotros="Somos un estudio juridico dedicado al derecho laboral. " * 3,
                    servicios=(
                        Servicio(nombre="Laboral", descripcion="Despidos y beneficios sociales."),
                        Servicio(nombre="Familia", descripcion="Divorcios, alimentos y tenencia."),
                    ),
                    cta_texto="Conversemos",
                )
            }
        )
        html = _html(fijo).replace("None", "https://wa.me/51987654321")

        reporte = revisar_html(html, fijo)

        assert reporte.checks["whatsapp_correcto"] is False

    def test_rechaza_si_falta_el_nombre_del_negocio(self, spec: SiteSpec) -> None:
        html = _html(spec).replace(f"<p>{spec.hechos.nombre}</p>", "<p>Otro estudio</p>")

        reporte = revisar_html(html, spec)

        assert reporte.checks["nombre_presente"] is False

    def test_rechaza_un_telefono_suelto_en_el_texto(self, spec: SiteSpec) -> None:
        # El modelo escribio un numero en la prosa: dato inventado.
        html = _html(spec).replace("</body>", "<p>Llamanos al 054 998877</p></body>")

        reporte = revisar_html(html, spec)

        assert reporte.checks["sin_telefonos_ajenos"] is False

    def test_rechaza_una_resena_reescrita(self, spec: SiteSpec) -> None:
        original = spec.hechos.resenas[0].texto
        html = _html(spec).replace(original, "El mejor estudio del Peru, sin duda alguna.")

        reporte = revisar_html(html, spec)

        assert reporte.checks["resenas_intactas"] is False

    def test_rechaza_una_ciudad_inventada(self, spec: SiteSpec) -> None:
        # Caso real: el modelo escribio "en el Cercado de Lima" para un estudio
        # de Arequipa, porque el prompt decia solo "Zona: Cercado".
        html = _html(spec).replace(
            "</body>", "<p>Asesoria juridica profesional en el Cercado de Lima</p></body>"
        )

        reporte = revisar_html(html, spec)

        assert reporte.checks["ciudad_correcta"] is False
        assert not reporte.aprobado

    def test_acepta_la_ciudad_propia_del_negocio(self, spec: SiteSpec) -> None:
        html = _html(spec).replace(
            "</body>", f"<p>Atendemos en {spec.hechos.zona} y alrededores</p></body>"
        )

        assert revisar_html(html, spec).checks["ciudad_correcta"] is True

    def test_no_confunde_una_ciudad_dentro_de_otra_palabra(self, spec: SiteSpec) -> None:
        # 'Ica' esta dentro de 'juridica', 'practica', 'dedicada'...
        html = _html(spec).replace(
            "</body>", "<p>Asesoria juridica y practica dedicada a cada caso</p></body>"
        )

        assert revisar_html(html, spec).checks["ciudad_correcta"] is True

    def test_el_horario_no_cuenta_como_telefono(self, spec: SiteSpec) -> None:
        # Falso positivo evidente: '9:00 - 18:00' tiene digitos y separadores.
        html = _html(spec).replace("</body>", "<p>lunes: 9:00 - 18:00</p></body>")

        reporte = revisar_html(html, spec)

        assert reporte.checks["sin_telefonos_ajenos"] is True


class TestEstructura:
    def test_rechaza_sin_viewport(self, spec: SiteSpec) -> None:
        html = _html(spec).replace(
            '<meta name="viewport" content="width=device-width, initial-scale=1">', ""
        )

        assert revisar_html(html, spec).checks["responsive"] is False

    def test_rechaza_dos_h1(self, spec: SiteSpec) -> None:
        html = _html(spec).replace("</body>", "<h1>Otro titulo</h1></body>")

        assert revisar_html(html, spec).checks["tiene_h1"] is False

    def test_rechaza_sin_via_de_contacto(self, spec: SiteSpec) -> None:
        html = _html(spec, cuerpo=f"<h1>Hola</h1><p>{spec.hechos.nombre}</p>")

        assert revisar_html(html, spec).checks["tiene_cta"] is False

    def test_rechaza_enlaces_vacios(self, spec: SiteSpec) -> None:
        html = _html(spec).replace("</body>", '<a href="#">Leer mas</a></body>')

        assert revisar_html(html, spec).checks["sin_enlaces_vacios"] is False

    def test_rechaza_contenido_demasiado_corto(self, spec: SiteSpec) -> None:
        html = _html(spec, cuerpo="<h1>Hola</h1><a href='tel:+51987654321'>x</a>")

        assert revisar_html(html, spec).checks["tiene_contenido"] is False

    def test_rechaza_imagenes_sin_dimensiones(self, spec: SiteSpec) -> None:
        html = _html(spec).replace("</body>", '<img src="/foto.jpg" alt=""></body>')

        assert revisar_html(html, spec).checks["imagenes_dimensionadas"] is False

    def test_rechaza_javascript(self, spec: SiteSpec) -> None:
        html = _html(spec).replace("</body>", '<script src="/app.js"></script></body>')

        assert revisar_html(html, spec).checks["sin_javascript"] is False

    def test_el_ld_json_no_cuenta_como_javascript(self, spec: SiteSpec) -> None:
        html = _html(spec).replace(
            "</body>", '<script type="application/ld+json">{"a":1}</script></body>'
        )

        assert revisar_html(html, spec).checks["sin_javascript"] is True


class TestPlaceholders:
    def test_rechaza_marcadores_de_codigo(self, spec: SiteSpec) -> None:
        html = _html(spec).replace("</body>", "<p>TODO: escribir esto</p></body>")

        assert revisar_html(html, spec).checks["sin_placeholders"] is False

    def test_rechaza_lorem_ipsum(self, spec: SiteSpec) -> None:
        html = _html(spec).replace("</body>", "<p>Lorem ipsum dolor sit amet</p></body>")

        assert revisar_html(html, spec).checks["sin_placeholders"] is False

    def test_rechaza_undefined_de_javascript(self, spec: SiteSpec) -> None:
        html = _html(spec).replace("</body>", "<p>undefined</p></body>")

        assert revisar_html(html, spec).checks["sin_placeholders"] is False

    def test_la_palabra_todo_en_espanol_no_es_placeholder(self, spec: SiteSpec) -> None:
        # 'Todos los derechos reservados' rechazaba sitios correctos.
        html = _html(spec).replace("</body>", "<p>Todos los derechos reservados</p></body>")

        assert revisar_html(html, spec).checks["sin_placeholders"] is True

    def test_todo_en_mayusculas_dentro_de_una_frase_si_es_placeholder(self, spec: SiteSpec) -> None:
        html = _html(spec).replace("</body>", "<p>Servicios TODO completar</p></body>")

        assert revisar_html(html, spec).checks["sin_placeholders"] is False
