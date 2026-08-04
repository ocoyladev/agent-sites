"""Cliente de Places API contra respuestas simuladas -- sin red, sin key, sin gasto."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from lead_gen.cost import BudgetExceeded, CostLedger, Sku
from lead_gen.models import RawLead
from lead_gen.sources.google_places import (
    FIELD_MASK_BUSQUEDA,
    GooglePlacesSource,
    PlacesError,
)

BASE = "https://places.googleapis.com/v1"


@pytest.fixture
def fuente() -> GooglePlacesSource:
    return GooglePlacesSource("clave-de-prueba", ledger=CostLedger())


class TestBuscar:
    @respx.mock
    async def test_mapea_resultados_a_raw_leads(
        self, fuente: GooglePlacesSource, respuesta_text_search: dict[str, Any]
    ) -> None:
        respx.post(f"{BASE}/places:searchText").mock(
            return_value=httpx.Response(200, json=respuesta_text_search)
        )

        leads = [lead async for lead in fuente.buscar("abogado", "Cercado, Arequipa")]

        assert [lead.nombre for lead in leads] == [
            "Estudio Juridico Vargas",
            "Corte Superior de Justicia",
        ]
        assert leads[0].ref == "ChIJaaa"
        assert leads[0].lat == pytest.approx(-16.398)
        assert leads[0].fuente == "google_places"

    @respx.mock
    async def test_arma_la_consulta_y_manda_el_field_mask_barato(
        self, fuente: GooglePlacesSource, respuesta_text_search: dict[str, Any]
    ) -> None:
        ruta = respx.post(f"{BASE}/places:searchText").mock(
            return_value=httpx.Response(200, json=respuesta_text_search)
        )

        [lead async for lead in fuente.buscar("abogado", "Cayma, Arequipa")]

        pedido = ruta.calls.last.request
        assert pedido.headers["X-Goog-FieldMask"] == FIELD_MASK_BUSQUEDA
        assert pedido.headers["X-Goog-Api-Key"] == "clave-de-prueba"
        import json

        cuerpo = json.loads(pedido.content)
        assert cuerpo["textQuery"] == "abogado en Cayma, Arequipa"
        assert cuerpo["regionCode"] == "PE"
        assert cuerpo["languageCode"] == "es"

    @respx.mock
    async def test_sigue_la_paginacion(self, fuente: GooglePlacesSource) -> None:
        pagina1 = {
            "places": [{"id": "p1", "displayName": {"text": "Uno"}}],
            "nextPageToken": "token-2",
        }
        pagina2 = {"places": [{"id": "p2", "displayName": {"text": "Dos"}}]}
        respx.post(f"{BASE}/places:searchText").mock(
            side_effect=[
                httpx.Response(200, json=pagina1),
                httpx.Response(200, json=pagina2),
            ]
        )

        leads = [lead async for lead in fuente.buscar("abogado", "Cercado")]

        assert [lead.ref for lead in leads] == ["p1", "p2"]
        assert fuente.ledger.calls(Sku.PRO) == 2

    @respx.mock
    async def test_corta_en_tres_paginas(self, fuente: GooglePlacesSource) -> None:
        # Google no entrega mas de 60 resultados; sin este tope, un
        # nextPageToken repetido nos haria pagar en un bucle infinito.
        pagina = {
            "places": [{"id": "p", "displayName": {"text": "N"}}],
            "nextPageToken": "siempre-hay-mas",
        }
        respx.post(f"{BASE}/places:searchText").mock(return_value=httpx.Response(200, json=pagina))

        leads = [lead async for lead in fuente.buscar("abogado", "Cercado")]

        assert fuente.ledger.calls(Sku.PRO) == 3
        # El mismo id en las 3 paginas se emite una sola vez.
        assert len(leads) == 1

    @respx.mock
    async def test_descarta_lugares_sin_id_o_sin_nombre(self, fuente: GooglePlacesSource) -> None:
        respx.post(f"{BASE}/places:searchText").mock(
            return_value=httpx.Response(
                200,
                json={
                    "places": [
                        {"id": "ok", "displayName": {"text": "Valido"}},
                        {"displayName": {"text": "Sin id"}},
                        {"id": "sin-nombre"},
                    ]
                },
            )
        )

        leads = [lead async for lead in fuente.buscar("abogado", "Cercado")]

        assert [lead.ref for lead in leads] == ["ok"]

    @respx.mock
    async def test_sin_resultados_no_explota(self, fuente: GooglePlacesSource) -> None:
        respx.post(f"{BASE}/places:searchText").mock(return_value=httpx.Response(200, json={}))

        assert [lead async for lead in fuente.buscar("abogado", "Nada")] == []


class TestDetalle:
    @respx.mock
    async def test_mapea_el_detalle_completo(
        self, fuente: GooglePlacesSource, respuesta_place_details: dict[str, Any]
    ) -> None:
        respx.get(f"{BASE}/places/ChIJaaa").mock(
            return_value=httpx.Response(200, json=respuesta_place_details)
        )
        crudo = RawLead(fuente="google_places", ref="ChIJaaa", nombre="Estudio")

        detalle = await fuente.detalle(crudo)

        assert detalle.telefono == "054 123456"
        assert detalle.rating == 4.5
        assert detalle.num_resenas == 23
        assert detalle.estado_negocio == "OPERATIONAL"
        assert detalle.tiene_sitio_web is False
        assert detalle.es_contactable is True
        assert detalle.esta_operativo is True
        assert len(detalle.horario) == 2
        assert detalle.fotos[0].ref == "places/ChIJaaa/photos/AXQ_foto1"
        assert detalle.fotos[0].atribuciones == ("Juan Perez",)

    @respx.mock
    async def test_cae_al_telefono_internacional_si_no_hay_nacional(
        self, fuente: GooglePlacesSource, respuesta_place_details: dict[str, Any]
    ) -> None:
        del respuesta_place_details["nationalPhoneNumber"]
        respx.get(f"{BASE}/places/ChIJaaa").mock(
            return_value=httpx.Response(200, json=respuesta_place_details)
        )

        detalle = await fuente.detalle(RawLead(fuente="google_places", ref="ChIJaaa", nombre="X"))

        assert detalle.telefono == "+51 54 123456"

    @respx.mock
    async def test_detalle_normal_consume_enterprise_no_atmosphere(
        self, fuente: GooglePlacesSource, respuesta_place_details: dict[str, Any]
    ) -> None:
        respx.get(f"{BASE}/places/ChIJaaa").mock(
            return_value=httpx.Response(200, json=respuesta_place_details)
        )

        await fuente.detalle(RawLead(fuente="google_places", ref="ChIJaaa", nombre="X"))

        assert fuente.ledger.calls(Sku.ENTERPRISE) == 1
        assert fuente.ledger.calls(Sku.ENTERPRISE_ATMOSPHERE) == 0

    @respx.mock
    async def test_con_resenas_consume_el_sku_de_atmosphere(
        self, fuente: GooglePlacesSource, respuesta_place_details: dict[str, Any]
    ) -> None:
        respuesta_place_details["reviews"] = [
            {
                "authorAttribution": {"displayName": "Ana"},
                "rating": 5,
                "text": {"text": "Excelente atencion", "languageCode": "es"},
            }
        ]
        ruta = respx.get(f"{BASE}/places/ChIJaaa").mock(
            return_value=httpx.Response(200, json=respuesta_place_details)
        )

        detalle = await fuente.detalle(
            RawLead(fuente="google_places", ref="ChIJaaa", nombre="X"), con_resenas=True
        )

        assert "reviews" in ruta.calls.last.request.headers["X-Goog-FieldMask"]
        assert fuente.ledger.calls(Sku.ENTERPRISE_ATMOSPHERE) == 1
        assert detalle.resenas[0].autor == "Ana"
        assert detalle.resenas[0].texto == "Excelente atencion"


class TestPresupuesto:
    @respx.mock
    async def test_el_tope_corta_la_corrida(self, respuesta_place_details: dict[str, Any]) -> None:
        fuente = GooglePlacesSource("clave", ledger=CostLedger(limits={Sku.ENTERPRISE: 1}))
        respx.get(f"{BASE}/places/ChIJaaa").mock(
            return_value=httpx.Response(200, json=respuesta_place_details)
        )
        crudo = RawLead(fuente="google_places", ref="ChIJaaa", nombre="X")

        await fuente.detalle(crudo)
        with pytest.raises(BudgetExceeded):
            await fuente.detalle(crudo)


class TestErrores:
    def test_sin_api_key_falla_al_construir(self) -> None:
        with pytest.raises(ValueError, match="GOOGLE_PLACES_API_KEY"):
            GooglePlacesSource("")

    @respx.mock
    async def test_key_invalida_no_se_reintenta(self, fuente: GooglePlacesSource) -> None:
        # Reintentar un 403 solo gasta tiempo: la key no se va a arreglar sola.
        ruta = respx.get(f"{BASE}/places/ChIJaaa").mock(
            return_value=httpx.Response(403, text="API key not valid")
        )

        with pytest.raises(PlacesError, match="403"):
            await fuente.detalle(RawLead(fuente="google_places", ref="ChIJaaa", nombre="X"))

        assert ruta.call_count == 1

    @respx.mock
    async def test_reintenta_ante_429_y_termina_bien(
        self,
        fuente: GooglePlacesSource,
        respuesta_place_details: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def sin_espera(_: float) -> None:
            return None

        monkeypatch.setattr("lead_gen.sources.google_places.asyncio.sleep", sin_espera)
        ruta = respx.get(f"{BASE}/places/ChIJaaa").mock(
            side_effect=[
                httpx.Response(429, text="rate limited"),
                httpx.Response(200, json=respuesta_place_details),
            ]
        )

        detalle = await fuente.detalle(RawLead(fuente="google_places", ref="ChIJaaa", nombre="X"))

        assert ruta.call_count == 2
        assert detalle.telefono == "054 123456"
