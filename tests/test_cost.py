"""El mapeo campo -> SKU es lo que decide la factura. Se prueba explicitamente."""

from __future__ import annotations

import pytest

from lead_gen.cost import BudgetExceeded, CostLedger, Sku, sku_for_field_mask
from lead_gen.sources.google_places import (
    FIELD_MASK_BUSQUEDA,
    FIELD_MASK_DETALLE,
    FIELD_MASK_DETALLE_CON_RESENAS,
)


class TestSkuPorFieldMask:
    def test_solo_ids_es_el_sku_mas_barato(self) -> None:
        assert sku_for_field_mask("id,name") is Sku.ESSENTIALS_IDS_ONLY

    def test_direccion_y_ubicacion_son_essentials(self) -> None:
        assert sku_for_field_mask("id,formattedAddress,location") is Sku.ESSENTIALS

    def test_display_name_empuja_a_pro(self) -> None:
        assert sku_for_field_mask("id,location,displayName") is Sku.PRO

    def test_telefono_y_sitio_son_enterprise(self) -> None:
        # El punto de la correccion: NO son Pro. La cuota gratuita cae de
        # 5.000 a 1.000 llamadas/mes.
        assert sku_for_field_mask("nationalPhoneNumber") is Sku.ENTERPRISE
        assert sku_for_field_mask("websiteUri") is Sku.ENTERPRISE
        assert sku_for_field_mask("rating,userRatingCount") is Sku.ENTERPRISE

    def test_resenas_son_atmosphere(self) -> None:
        assert sku_for_field_mask("reviews") is Sku.ENTERPRISE_ATMOSPHERE

    def test_se_factura_el_campo_mas_caro_de_la_mezcla(self) -> None:
        mezcla = "id,location,displayName,websiteUri"
        assert sku_for_field_mask(mezcla) is Sku.ENTERPRISE

    def test_prefijo_places_de_text_search(self) -> None:
        assert sku_for_field_mask("places.id,places.displayName") is Sku.PRO

    def test_campo_anidado_se_resuelve_por_su_raiz(self) -> None:
        assert sku_for_field_mask("places.location.latitude") is Sku.ESSENTIALS

    def test_campo_desconocido_se_asume_carisimo(self) -> None:
        # Preferimos sobrestimar y frenar antes que descubrirlo en la factura.
        assert sku_for_field_mask("campoQueGoogleAgregoAyer") is Sku.ENTERPRISE_ATMOSPHERE

    def test_comodin_es_el_sku_mas_caro(self) -> None:
        assert sku_for_field_mask("*") is Sku.ENTERPRISE_ATMOSPHERE

    def test_mask_vacio_es_error(self) -> None:
        with pytest.raises(ValueError):
            sku_for_field_mask("  ")


class TestMascarasDelCliente:
    """Las mascaras reales del cliente deben caer donde creemos que caen."""

    def test_busqueda_no_pasa_de_pro(self) -> None:
        assert sku_for_field_mask(FIELD_MASK_BUSQUEDA) is Sku.PRO

    def test_detalle_es_enterprise_pero_no_atmosphere(self) -> None:
        # Si esto sube a ATMOSPHERE, alguien agrego `reviews` al detalle normal
        # y duplico el consumo del SKU mas escaso.
        assert sku_for_field_mask(FIELD_MASK_DETALLE) is Sku.ENTERPRISE

    def test_detalle_con_resenas_si_es_atmosphere(self) -> None:
        assert sku_for_field_mask(FIELD_MASK_DETALLE_CON_RESENAS) is Sku.ENTERPRISE_ATMOSPHERE


class TestCostLedger:
    def test_acumula_por_sku(self) -> None:
        ledger = CostLedger()
        ledger.record(Sku.PRO, 3)
        ledger.record(Sku.ENTERPRISE)
        assert ledger.calls(Sku.PRO) == 3
        assert ledger.calls(Sku.ENTERPRISE) == 1
        assert ledger.total_calls == 4

    def test_frena_antes_de_pasarse_del_tope(self) -> None:
        ledger = CostLedger(limits={Sku.ENTERPRISE: 2})
        ledger.record(Sku.ENTERPRISE)
        ledger.record(Sku.ENTERPRISE)
        with pytest.raises(BudgetExceeded, match="ENTERPRISE"):
            ledger.record(Sku.ENTERPRISE)
        # La llamada que excede no se contabiliza: no se hizo.
        assert ledger.calls(Sku.ENTERPRISE) == 2

    def test_sku_sin_tope_no_se_limita(self) -> None:
        ledger = CostLedger(limits={Sku.ENTERPRISE: 1})
        for _ in range(100):
            ledger.record(Sku.PRO)
        assert ledger.calls(Sku.PRO) == 100

    def test_cuotas_gratuitas_conocidas(self) -> None:
        assert Sku.PRO.free_calls_per_month == 5_000
        assert Sku.ENTERPRISE.free_calls_per_month == 1_000
