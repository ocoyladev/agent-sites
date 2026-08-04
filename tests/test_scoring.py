"""El scoring decide en que leads se gasta tiempo y plata. Se prueba su forma."""

from __future__ import annotations

from lead_gen.models import LeadDetail
from lead_gen.nichos import Nicho
from lead_gen.scoring import calcular_score


def _con(lead: LeadDetail, **cambios: object) -> LeadDetail:
    return lead.model_copy(update=cambios)


class TestFiltrosDuros:
    def test_sin_telefono_no_califica_por_bueno_que_sea(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = _con(lead_base, telefono=None, num_resenas=500)
        score = calcular_score(lead, nicho_abogados)
        assert score.califica is False
        assert score.descartado_por == "sin_telefono"

    def test_negocio_cerrado_no_califica(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = _con(lead_base, estado_negocio="CLOSED_PERMANENTLY")
        score = calcular_score(lead, nicho_abogados)
        assert score.descartado_por == "negocio_closed_permanently"

    def test_estado_ausente_se_asume_operativo(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = _con(lead_base, estado_negocio=None)
        assert calcular_score(lead, nicho_abogados).califica is True

    def test_tipo_fuera_del_nicho_no_califica(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = _con(lead_base, tipos=("restaurant",))
        assert calcular_score(lead, nicho_abogados).descartado_por == "fuera_de_nicho"

    def test_tipo_excluido_gana_sobre_tipo_esperado(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        # La Corte aparece como 'lawyer' en Google, pero no es un cliente.
        lead = _con(lead_base, tipos=("lawyer", "courthouse"))
        assert calcular_score(lead, nicho_abogados).descartado_por == "fuera_de_nicho"


class TestBrechaDigital:
    def test_sin_sitio_web_es_la_brecha_maxima(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        score = calcular_score(_con(lead_base, sitio_web=None), nicho_abogados)
        assert score.brecha_digital == 100.0

    def test_sitio_bueno_reduce_la_brecha(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = _con(lead_base, sitio_web="https://estudiovargas.pe")
        score = calcular_score(lead, nicho_abogados, calidad_sitio=90.0)
        assert score.brecha_digital == 10.0

    def test_sitio_malo_sigue_siendo_venta(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = _con(lead_base, sitio_web="http://viejo.com")
        score = calcular_score(lead, nicho_abogados, calidad_sitio=20.0)
        assert score.brecha_digital == 80.0

    def test_sitio_no_evaluable_queda_alto_pero_no_maximo(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = _con(lead_base, sitio_web="https://caido.pe")
        score = calcular_score(lead, nicho_abogados, calidad_sitio=None)
        assert score.brecha_digital == 75.0

    def test_mejor_sitio_nunca_puntua_mas_que_peor_sitio(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        lead = _con(lead_base, sitio_web="https://x.pe")
        bueno = calcular_score(lead, nicho_abogados, calidad_sitio=95.0)
        malo = calcular_score(lead, nicho_abogados, calidad_sitio=15.0)
        assert malo.total > bueno.total


class TestDemanda:
    def test_mas_resenas_puntua_mas(self, lead_base: LeadDetail, nicho_abogados: Nicho) -> None:
        pocas = calcular_score(_con(lead_base, num_resenas=2), nicho_abogados)
        muchas = calcular_score(_con(lead_base, num_resenas=35), nicho_abogados)
        assert muchas.demanda > pocas.demanda

    def test_la_demanda_satura(self, lead_base: LeadDetail, nicho_abogados: Nicho) -> None:
        # Un abogado con 1000 resenas no es mejor lead que uno con 40:
        # probablemente ya tiene quien le maneje el marketing.
        en_tope = calcular_score(_con(lead_base, num_resenas=40), nicho_abogados)
        pasado = calcular_score(_con(lead_base, num_resenas=1000), nicho_abogados)
        assert en_tope.demanda == pasado.demanda

    def test_sin_resenas_no_rompe(self, lead_base: LeadDetail, nicho_abogados: Nicho) -> None:
        score = calcular_score(_con(lead_base, num_resenas=None), nicho_abogados)
        assert score.demanda >= 0


class TestTotal:
    def test_esta_en_rango(self, lead_base: LeadDetail, nicho_abogados: Nicho) -> None:
        score = calcular_score(lead_base, nicho_abogados)
        assert 0.0 <= score.total <= 100.0

    def test_el_desglose_reconstruye_el_total(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        from lead_gen.scoring import PESO_BRECHA, PESO_DEMANDA, PESO_TICKET

        score = calcular_score(lead_base, nicho_abogados)
        esperado = (
            score.demanda * PESO_DEMANDA
            + score.ticket * PESO_TICKET
            + score.brecha_digital * PESO_BRECHA
        )
        assert score.total == round(esperado, 2)

    def test_bajo_umbral_se_marca_pero_conserva_el_score(
        self, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        # Sitio excelente + casi sin resenas: no vale la pena perseguirlo,
        # pero guardamos el numero para poder recalibrar despues.
        lead = _con(lead_base, sitio_web="https://muy-bueno.pe", num_resenas=0)
        score = calcular_score(lead, nicho_abogados, calidad_sitio=100.0)
        assert score.descartado_por == "bajo_umbral"
        assert score.total > 0
