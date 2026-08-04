"""Acceso a Postgres.

Sin ORM por ahora: las consultas del pipeline son pocas y explicitas, y SQL
directo hace mas facil razonar sobre el UPSERT idempotente de leads.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from lead_gen.models import LeadDetail, LeadScore
from settings import get_settings

__all__ = ["conexion", "get_engine", "upsert_lead"]

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, future=True)
    return _engine


@contextmanager
def conexion() -> Iterator[Connection]:
    with get_engine().begin() as conn:
        yield conn


_UPSERT_LEAD = text(
    """
    INSERT INTO leads (
        fuente, ref, nombre_negocio, nicho,
        telefono, direccion, lat, lng, tipos,
        rating, num_resenas, estado_negocio,
        tiene_sitio_web, url_sitio_actual, calidad_sitio_score,
        score_total, score_demanda, score_ticket, score_brecha, descartado_por
    ) VALUES (
        :fuente, :ref, :nombre_negocio, :nicho,
        :telefono, :direccion, :lat, :lng, :tipos,
        :rating, :num_resenas, :estado_negocio,
        :tiene_sitio_web, :url_sitio_actual, :calidad_sitio_score,
        :score_total, :score_demanda, :score_ticket, :score_brecha, :descartado_por
    )
    ON CONFLICT (fuente, ref) DO UPDATE SET
        nombre_negocio      = EXCLUDED.nombre_negocio,
        telefono            = EXCLUDED.telefono,
        direccion           = EXCLUDED.direccion,
        rating              = EXCLUDED.rating,
        num_resenas         = EXCLUDED.num_resenas,
        estado_negocio      = EXCLUDED.estado_negocio,
        tiene_sitio_web     = EXCLUDED.tiene_sitio_web,
        url_sitio_actual    = EXCLUDED.url_sitio_actual,
        calidad_sitio_score = EXCLUDED.calidad_sitio_score,
        score_total         = EXCLUDED.score_total,
        score_demanda       = EXCLUDED.score_demanda,
        score_ticket        = EXCLUDED.score_ticket,
        score_brecha        = EXCLUDED.score_brecha,
        descartado_por      = EXCLUDED.descartado_por
    RETURNING id
    """
)


def upsert_lead(
    conn: Connection,
    lead: LeadDetail,
    score: LeadScore,
    *,
    nicho: str,
    calidad_sitio: float | None = None,
) -> int:
    """Inserta o refresca un lead. Idempotente por (fuente, ref).

    No toca `estado_pipeline` ni `notas`: re-correr una extraccion actualiza los
    datos del negocio sin pisar el avance comercial ni lo que hayas escrito a mano.
    """
    params: dict[str, Any] = {
        "fuente": lead.fuente,
        "ref": lead.ref,
        "nombre_negocio": lead.nombre,
        "nicho": nicho,
        "telefono": lead.telefono,
        "direccion": lead.direccion,
        "lat": lead.lat,
        "lng": lead.lng,
        "tipos": list(lead.tipos),
        "rating": lead.rating,
        "num_resenas": lead.num_resenas,
        "estado_negocio": lead.estado_negocio,
        "tiene_sitio_web": lead.tiene_sitio_web,
        "url_sitio_actual": lead.sitio_web,
        "calidad_sitio_score": calidad_sitio,
        "score_total": score.total,
        "score_demanda": score.demanda,
        "score_ticket": score.ticket,
        "score_brecha": score.brecha_digital,
        "descartado_por": score.descartado_por,
    }
    lead_id: int = conn.execute(_UPSERT_LEAD, params).scalar_one()
    return lead_id
