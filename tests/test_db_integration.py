"""Tests contra Postgres real.

Se saltan solos si la base no esta levantada, para que `pytest` siga corriendo
en cualquier maquina sin docker. Para correrlos: `docker compose up -d db`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.db import get_engine, upsert_lead
from lead_gen.models import EstadoPipeline, LeadDetail
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


@pytest.fixture
def conn() -> Iterator[Connection]:
    """Cada test corre en una transaccion que se revierte al terminar."""
    with get_engine().connect() as conexion_cruda:
        transaccion = conexion_cruda.begin()
        try:
            yield conexion_cruda
        finally:
            transaccion.rollback()


class TestEnumsAlineados:
    """Si el enum de Python y el de Postgres se desincronizan, el INSERT falla
    en produccion y no en los tests. Mejor detectarlo aqui."""

    def test_estado_pipeline_coincide_con_postgres(self, conn: Connection) -> None:
        etiquetas = conn.execute(
            text(
                "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'estado_pipeline' ORDER BY e.enumsortorder"
            )
        ).scalars()
        assert list(etiquetas) == [estado.value for estado in EstadoPipeline]


class TestUpsertLead:
    def test_inserta_y_devuelve_id(
        self, conn: Connection, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        score = calcular_score(lead_base, nicho_abogados)

        lead_id = upsert_lead(conn, lead_base, score, nicho="abogados")

        fila = (
            conn.execute(
                text("SELECT nombre_negocio, telefono, score_total FROM leads WHERE id = :i"),
                {"i": lead_id},
            )
            .mappings()
            .one()
        )
        assert fila["nombre_negocio"] == lead_base.nombre
        assert fila["telefono"] == lead_base.telefono
        assert float(fila["score_total"]) == score.total

    def test_es_idempotente_por_fuente_y_ref(
        self, conn: Connection, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        # Re-correr una extraccion no debe duplicar leads ni multiplicar costos.
        score = calcular_score(lead_base, nicho_abogados)

        primero = upsert_lead(conn, lead_base, score, nicho="abogados")
        segundo = upsert_lead(conn, lead_base, score, nicho="abogados")

        assert primero == segundo
        total = conn.execute(
            text("SELECT count(*) FROM leads WHERE ref = :r"), {"r": lead_base.ref}
        ).scalar_one()
        assert total == 1

    def test_refresca_los_datos_del_negocio(
        self, conn: Connection, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        upsert_lead(conn, lead_base, calcular_score(lead_base, nicho_abogados), nicho="abogados")

        crecido = lead_base.model_copy(update={"num_resenas": 99, "nombre": "Estudio Vargas SAC"})
        lead_id = upsert_lead(
            conn, crecido, calcular_score(crecido, nicho_abogados), nicho="abogados"
        )

        fila = (
            conn.execute(
                text("SELECT nombre_negocio, num_resenas FROM leads WHERE id = :i"), {"i": lead_id}
            )
            .mappings()
            .one()
        )
        assert fila["num_resenas"] == 99
        assert fila["nombre_negocio"] == "Estudio Vargas SAC"

    def test_no_pisa_el_avance_comercial_ni_las_notas(
        self, conn: Connection, lead_base: LeadDetail, nicho_abogados: Nicho
    ) -> None:
        # Lo mas importante del upsert: re-extraer no puede borrar trabajo manual.
        score = calcular_score(lead_base, nicho_abogados)
        lead_id = upsert_lead(conn, lead_base, score, nicho="abogados")
        conn.execute(
            text(
                "UPDATE leads SET estado_pipeline = 'negociacion', notas = 'pidio propuesta' "
                "WHERE id = :i"
            ),
            {"i": lead_id},
        )

        upsert_lead(conn, lead_base, score, nicho="abogados")

        fila = (
            conn.execute(
                text("SELECT estado_pipeline, notas FROM leads WHERE id = :i"), {"i": lead_id}
            )
            .mappings()
            .one()
        )
        assert fila["estado_pipeline"] == "negociacion"
        assert fila["notas"] == "pidio propuesta"


class TestRestricciones:
    def test_rechaza_rating_fuera_de_rango(self, conn: Connection) -> None:
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO leads (fuente, ref, nombre_negocio, nicho, rating) "
                    "VALUES ('x', 'y', 'Z', 'abogados', 9.9)"
                )
            )

    def test_respuesta_sin_fecha_es_incoherente(self, conn: Connection) -> None:
        from sqlalchemy.exc import IntegrityError

        lead_id = conn.execute(
            text(
                "INSERT INTO leads (fuente, ref, nombre_negocio, nicho) "
                "VALUES ('x', 'ref-msg', 'Z', 'abogados') RETURNING id"
            )
        ).scalar_one()

        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO mensajes_outreach (lead_id, canal, contenido, respuesta) "
                    "VALUES (:i, 'whatsapp', 'hola', 'me interesa')"
                ),
                {"i": lead_id},
            )
