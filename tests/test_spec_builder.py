"""Construccion deterministica de la spec.

`normalizar_telefono` merece esta cobertura: de ella depende que aparezca o no
el boton de WhatsApp, que es la unica via de conversion real de estos sitios.
Un fallo aqui no rompe nada visiblemente -- solo borra el CTA.
"""

from __future__ import annotations

import pytest

from lead_gen.models import LeadDetail, Resena
from lead_gen.nichos import Nicho
from site_generator.spec_builder import (
    construir_site_id,
    construir_spec,
    normalizar_telefono,
    slug,
)


class TestNormalizarTelefono:
    @pytest.mark.parametrize(
        ("entrada", "e164", "es_movil"),
        [
            # Moviles: 9 digitos que empiezan en 9.
            ("987 654 321", "+51987654321", True),
            ("987654321", "+51987654321", True),
            ("+51 987 654 321", "+51987654321", True),
            ("+51987654321", "+51987654321", True),
            ("(051) 987654321", "+51987654321", True),
            # Fijos de Arequipa (codigo 54): no llevan WhatsApp.
            ("054 123456", "+5154123456", False),
            ("+51 54 123456", "+5154123456", False),
            ("054-21-3456", "+5154213456", False),
        ],
    )
    def test_formatos_reales_de_google(self, entrada: str, e164: str, es_movil: bool) -> None:
        assert normalizar_telefono(entrada) == (e164, es_movil)

    def test_un_movil_da_exactamente_doce_caracteres(self) -> None:
        # El bug original comparaba contra 13 y desactivaba WhatsApp siempre.
        numero, es_movil = normalizar_telefono("987654321")
        assert len(numero) == 12
        assert es_movil is True


class TestSlugYSiteId:
    def test_quita_tildes_y_simbolos(self) -> None:
        assert slug("Estudio Jurídico Vargas & Asociados") == "estudio-juridico-vargas-asociados"

    def test_no_deja_guiones_repetidos_ni_en_los_bordes(self) -> None:
        resultado = slug("  ¡¡Abogados!!  --  Arequipa  ")
        assert resultado == "abogados-arequipa"

    def test_el_site_id_es_estable(self) -> None:
        # Se usa como subdominio: si cambiara entre corridas, se romperian los
        # links ya enviados por WhatsApp.
        primero = construir_site_id("Estudio Vargas", "ChIJabc")
        segundo = construir_site_id("Estudio Vargas", "ChIJabc")
        assert primero == segundo

    def test_mismo_nombre_distinto_negocio_no_colisiona(self) -> None:
        uno = construir_site_id("Estudio Juridico", "ChIJaaa")
        otro = construir_site_id("Estudio Juridico", "ChIJbbb")
        assert uno != otro

    def test_nombre_sin_caracteres_utiles_no_produce_id_vacio(self) -> None:
        assert construir_site_id("!!!", "ref").startswith("sitio-")


class TestConstruirSpec:
    def test_arma_los_hechos_desde_el_lead(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        spec = construir_spec(lead_base, nicho_abogados)

        assert spec.hechos.nombre == lead_base.nombre
        assert spec.hechos.contacto.telefono == lead_base.telefono
        assert spec.lead_ref == lead_base.ref
        assert spec.nicho == "abogados"
        assert spec.contenido is None
        assert spec.esta_completa is False

    def test_un_movil_genera_enlace_de_whatsapp(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = lead_base.model_copy(update={"telefono": "987 654 321"})

        spec = construir_spec(lead, nicho_abogados)

        assert spec.hechos.contacto.whatsapp_url is not None
        assert spec.hechos.contacto.whatsapp_url.startswith("https://wa.me/51987654321")
        assert "text=" in spec.hechos.contacto.whatsapp_url

    def test_un_fijo_no_genera_whatsapp(self, lead_base: LeadDetail, nicho_abogados: Nicho) -> None:
        lead = lead_base.model_copy(update={"telefono": "054 123456"})

        spec = construir_spec(lead, nicho_abogados)

        assert spec.hechos.contacto.whatsapp_url is None

    def test_sin_telefono_no_se_puede_generar_sitio(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = lead_base.model_copy(update={"telefono": None})

        with pytest.raises(ValueError, match="no tiene telefono"):
            construir_spec(lead, nicho_abogados)

    def test_extrae_el_distrito_de_la_direccion(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = lead_base.model_copy(
            update={"direccion": "Calle Mercaderes 214, Yanahuara 04001, Peru"}
        )

        # La ciudad va siempre: 'Yanahuara' a secas no le dice nada al modelo.
        assert construir_spec(lead, nicho_abogados).hechos.zona == "Yanahuara, Arequipa"

    def test_la_zona_siempre_incluye_la_ciudad(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        # 'Cercado' existe en Lima y en Arequipa. Sin la ciudad, el modelo
        # escribio "en el Cercado de Lima" para un estudio arequipeno.
        lead = lead_base.model_copy(
            update={"direccion": "Calle Mercaderes 214, Cercado 04001, Peru"}
        )

        zona = construir_spec(lead, nicho_abogados, ciudad="Arequipa").hechos.zona

        assert zona == "Cercado, Arequipa"

    def test_no_repite_la_ciudad_cuando_el_distrito_ya_es_la_ciudad(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = lead_base.model_copy(
            update={"direccion": "Calle Mercaderes 214, Arequipa 04001, Peru"}
        )

        assert construir_spec(lead, nicho_abogados).hechos.zona == "Arequipa"

    def test_sin_direccion_usa_el_respaldo(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = lead_base.model_copy(update={"direccion": None})

        spec = construir_spec(lead, nicho_abogados, ciudad="Arequipa")

        assert spec.hechos.zona == "Arequipa"


class TestSeleccionDeResenas:
    def test_descarta_resenas_malas_y_vacias(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = lead_base.model_copy(
            update={
                "resenas": (
                    Resena(autor="A", calificacion=5, texto="Excelente servicio legal"),
                    Resena(autor="B", calificacion=2, texto="Mala experiencia"),
                    Resena(autor="C", calificacion=5, texto="   "),
                    Resena(autor="D", calificacion=4, texto="Muy buena atencion"),
                )
            }
        )

        resenas = construir_spec(lead, nicho_abogados).hechos.resenas

        textos = [r.texto for r in resenas]
        assert "Mala experiencia" not in textos
        assert len(resenas) == 2

    def test_toma_como_maximo_tres(self, lead_base: LeadDetail, nicho_abogados: Nicho) -> None:
        lead = lead_base.model_copy(
            update={
                "resenas": tuple(
                    Resena(autor=f"A{i}", calificacion=5, texto=f"Buen servicio numero {i}")
                    for i in range(8)
                )
            }
        )

        assert len(construir_spec(lead, nicho_abogados).hechos.resenas) == 3
