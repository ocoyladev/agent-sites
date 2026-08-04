#!/usr/bin/env python
"""Corrida de extraccion end-to-end: descubrir -> filtrar -> detallar -> puntuar -> guardar.

El orden importa por costo. El filtro por tipo va ANTES de pedir detalle, porque
`detalle()` consume el SKU Enterprise (1.000 gratis/mes) y `buscar()` no.

Uso tipico -- primero mirar sin gastar ni escribir nada:

    uv run python -m scripts.run_extraction --dry-run

Luego una corrida acotada de verdad:

    uv run python -m scripts.run_extraction --zonas 1 --consultas 2 --limite 20
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import httpx

from backend.db import conexion, upsert_lead
from lead_gen.cost import BudgetExceeded, CostLedger
from lead_gen.models import RawLead
from lead_gen.nichos import Nicho, cargar_nicho
from lead_gen.scoring import calcular_score
from lead_gen.site_quality_check import evaluar_sitio
from lead_gen.sources.google_places import GooglePlacesSource
from settings import get_settings

logger = logging.getLogger("extraccion")


async def descubrir(
    fuente: GooglePlacesSource, nicho: Nicho, consultas: list[str], zonas: list[str]
) -> dict[str, RawLead]:
    """Barre consultas x zonas y devuelve candidatos unicos por `ref`.

    El mismo estudio juridico aparece en varias consultas y a veces en zonas
    vecinas; deduplicar aqui evita pagar su detalle mas de una vez.
    """
    encontrados: dict[str, RawLead] = {}
    for zona in zonas:
        for consulta in consultas:
            nuevos = 0
            async for lead in fuente.buscar(consulta, zona):
                if lead.ref not in encontrados:
                    encontrados[lead.ref] = lead
                    nuevos += 1
            logger.info("  '%s' en %s -> %d nuevos", consulta, zona, nuevos)
    return encontrados


async def procesar(args: argparse.Namespace) -> int:
    ajustes = get_settings()
    nicho = cargar_nicho(args.nicho)

    consultas = list(nicho.consultas[: args.consultas]) if args.consultas else list(nicho.consultas)
    zonas = list(nicho.zonas[: args.zonas]) if args.zonas else list(nicho.zonas)

    print(f"Nicho: {nicho.etiqueta}")
    print(f"Consultas: {len(consultas)}  Zonas: {len(zonas)}")
    print(f"Llamadas de descubrimiento: {len(consultas) * len(zonas)} (hasta 3x por paginacion)")

    if args.dry_run:
        print("\n--dry-run: no se llama a la API ni se escribe en la base.\n")
        for zona in zonas:
            for consulta in consultas:
                print(f"  buscaria: '{consulta} en {zona}'")
        return 0

    if not ajustes.google_places_api_key:
        print(
            "\nFalta GOOGLE_PLACES_API_KEY. Copia .env.example a .env y completala.\n"
            "Ver docs/setup-google-places.md para crear la key.",
            file=sys.stderr,
        )
        return 2

    ledger = CostLedger(limits=ajustes.limites_de_costo())

    async with (
        GooglePlacesSource(ajustes.google_places_api_key, ledger=ledger) as fuente,
        httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AgenciaWebIA/0.1)"},
        ) as http,
    ):
        print("\n=== Descubrimiento ===")
        candidatos = await descubrir(fuente, nicho, consultas, zonas)
        print(f"Candidatos unicos: {len(candidatos)}")

        # Filtro barato antes del filtro caro.
        del_nicho = [c for c in candidatos.values() if nicho.es_del_nicho(c.tipos)]
        print(f"Del nicho (tras filtrar tipos): {len(del_nicho)}")
        if args.limite:
            del_nicho = del_nicho[: args.limite]
            print(f"Acotado por --limite a: {len(del_nicho)}")

        print("\n=== Detalle y scoring ===")
        calificados = 0
        for i, candidato in enumerate(del_nicho, 1):
            try:
                detalle = await fuente.detalle(candidato)
            except BudgetExceeded as exc:
                print(f"\nCorrida detenida: {exc}", file=sys.stderr)
                break

            calidad = None
            if detalle.tiene_sitio_web and detalle.sitio_web:
                resultado = await evaluar_sitio(detalle.sitio_web, client=http)
                calidad = resultado.score

            score = calcular_score(detalle, nicho, calidad_sitio=calidad)
            if score.califica:
                calificados += 1

            marca = "OK " if score.califica else "-- "
            print(
                f"{marca}[{i:>3}/{len(del_nicho)}] {detalle.nombre[:44]:<44} "
                f"score={score.total:>6.2f}  {score.descartado_por or ''}"
            )

            if not args.sin_db:
                with conexion() as conn:
                    upsert_lead(conn, detalle, score, nicho=nicho.nombre, calidad_sitio=calidad)

        print(f"\nCalificados: {calificados} de {len(del_nicho)} evaluados")

    print()
    print(ledger.summary())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nicho", default=get_settings().nicho)
    parser.add_argument("--zonas", type=int, help="usar solo las primeras N zonas")
    parser.add_argument("--consultas", type=int, help="usar solo las primeras N consultas")
    parser.add_argument("--limite", type=int, help="tope de leads a detallar (controla el gasto)")
    parser.add_argument(
        "--dry-run", action="store_true", help="muestra el plan sin llamar a la API"
    )
    parser.add_argument(
        "--sin-db", action="store_true", help="no escribe en Postgres, solo imprime"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(procesar(args))


if __name__ == "__main__":
    raise SystemExit(main())
