"""Tests de la API contra Postgres real.

Los filtros opcionales de `/leads` son la parte fragil: un parametro sin CAST
explicito hace que Postgres no pueda inferir su tipo y devuelva 500. Solo se ve
ejecutando la consulta de verdad, por eso estos tests no usan mocks.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.db import conexion, get_engine, upsert_lead
from backend.main import app
from lead_gen.models import LeadDetail
from lead_gen.nichos import Nicho
from lead_gen.scoring import calcular_score


def _hay_base() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _hay_base(), reason="Postgres no disponible (docker compose up -d db)"
)

REF_PRUEBA = "ref-api-test"


@pytest.fixture
def cliente(lead_base: LeadDetail, nicho_abogados: Nicho) -> Iterator[TestClient]:
    """Deja un lead conocido en la base y lo limpia al terminar."""
    lead = lead_base.model_copy(update={"ref": REF_PRUEBA})
    with conexion() as conn:
        upsert_lead(conn, lead, calcular_score(lead, nicho_abogados), nicho="abogados")
    try:
        yield TestClient(app)
    finally:
        with conexion() as conn:
            conn.execute(text("DELETE FROM leads WHERE ref = :r"), {"r": REF_PRUEBA})


class TestHealth:
    def test_reporta_la_base_y_los_nichos(self, cliente: TestClient) -> None:
        respuesta = cliente.get("/health")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["status"] == "ok"
        assert cuerpo["db"] is True
        assert "abogados" in cuerpo["nichos"]


class TestListarLeads:
    def test_sin_filtros_devuelve_leads(self, cliente: TestClient) -> None:
        respuesta = cliente.get("/leads")

        assert respuesta.status_code == 200
        refs = [fila["nombre_negocio"] for fila in respuesta.json()]
        assert refs

    def test_filtra_por_estado(self, cliente: TestClient) -> None:
        respuesta = cliente.get("/leads", params={"estado": "nuevo"})

        assert respuesta.status_code == 200
        assert all(f["estado_pipeline"] == "nuevo" for f in respuesta.json())

    def test_filtra_por_nicho(self, cliente: TestClient) -> None:
        respuesta = cliente.get("/leads", params={"nicho": "abogados"})

        assert respuesta.status_code == 200
        assert all(f["nicho"] == "abogados" for f in respuesta.json())

    def test_combina_ambos_filtros(self, cliente: TestClient) -> None:
        respuesta = cliente.get("/leads", params={"estado": "nuevo", "nicho": "abogados"})

        assert respuesta.status_code == 200

    def test_nicho_inexistente_devuelve_vacio_no_error(self, cliente: TestClient) -> None:
        respuesta = cliente.get("/leads", params={"nicho": "no-existe"})

        assert respuesta.status_code == 200
        assert respuesta.json() == []

    def test_estado_invalido_es_422(self, cliente: TestClient) -> None:
        assert cliente.get("/leads", params={"estado": "inventado"}).status_code == 422

    def test_respeta_el_limite(self, cliente: TestClient) -> None:
        assert cliente.get("/leads", params={"limite": 1}).status_code == 200
        assert cliente.get("/leads", params={"limite": 0}).status_code == 422
        assert cliente.get("/leads", params={"limite": 9999}).status_code == 422

    def test_ordena_por_score_descendente(self, cliente: TestClient) -> None:
        filas = cliente.get("/leads").json()

        scores = [float(f["score_total"]) for f in filas if f["score_total"] is not None]
        assert scores == sorted(scores, reverse=True)
