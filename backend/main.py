"""API FastAPI multi-tenant.

Milestone 1 solo expone salud y consulta de leads. Los endpoints por sitio
(`/api/{site_id}/contacto`, `/cita`, `/whatsapp-redirect`) llegan en la Fase 5.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query
from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.db import conexion, get_engine
from lead_gen.models import EstadoPipeline
from lead_gen.nichos import nichos_disponibles

app = FastAPI(title="Agencia Web IA", version="0.1.0")


def _conn() -> Any:
    with conexion() as conn:
        yield conn


ConnDep = Annotated[Connection, Depends(_conn)]


@app.get("/health")
def health() -> dict[str, Any]:
    """Chequeo de vida. Incluye la base para que el healthcheck sea util."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "nichos": nichos_disponibles(),
    }


@app.get("/leads")
def listar_leads(
    conn: ConnDep,
    estado: EstadoPipeline | None = None,
    nicho: str | None = None,
    limite: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[dict[str, Any]]:
    """Leads ordenados por score, filtrables por estado y nicho."""
    consulta = text(
        """
        SELECT id, nombre_negocio, nicho, telefono, direccion,
               rating, num_resenas, tiene_sitio_web, url_sitio_actual,
               calidad_sitio_score, score_total, descartado_por,
               estado_pipeline, creado_en
        FROM leads
        -- El CAST explicito en el `IS NULL` no es adorno: sin el, Postgres no
        -- puede inferir el tipo del parametro y falla con AmbiguousParameter.
        WHERE (CAST(:estado AS text) IS NULL
               OR estado_pipeline = CAST(:estado AS estado_pipeline))
          AND (CAST(:nicho AS text) IS NULL OR nicho = :nicho)
        ORDER BY score_total DESC NULLS LAST, id
        LIMIT :limite
        """
    )
    filas = conn.execute(
        consulta,
        {"estado": estado.value if estado else None, "nicho": nicho, "limite": limite},
    ).mappings()
    return [dict(f) for f in filas]
