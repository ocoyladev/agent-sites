#!/usr/bin/env python
"""Genera el sitio de un lead: spec -> copy -> build Astro -> QA.

Con `--sin-ia` usa copy de plantilla y no toca Ollama: util para probar el
pipeline completo en segundos en vez de minutos.

    uv run python -m scripts.generar_sitio --demo --sin-ia
    uv run python -m scripts.generar_sitio --lead-ref ChIJxxx
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from lead_gen.models import Foto, LeadDetail, Resena
from lead_gen.nichos import cargar_nicho
from settings import get_settings
from site_generator.contenido import generar_contenido
from site_generator.llm.base import LLMClient
from site_generator.llm.ollama import OllamaClient
from site_generator.qa import revisar_sitio
from site_generator.render import construir_sitio
from site_generator.spec import Tema
from site_generator.spec_builder import construir_spec

logger = logging.getLogger("generador")

DIR_SALIDA = Path("out/sitios")


def _lead_demo() -> LeadDetail:
    """Lead ficticio con la forma exacta de uno real de Google Places."""
    return LeadDetail(
        fuente="demo",
        ref="demo-estudio-vargas",
        nombre="Estudio Juridico Vargas & Asociados",
        direccion="Calle Mercaderes 214, Cercado 04001, Peru",
        tipos=("lawyer", "point_of_interest"),
        telefono="987 654 321",
        rating=4.6,
        num_resenas=27,
        estado_negocio="OPERATIONAL",
        horario=(
            "lunes: 9:00 - 18:00",
            "martes: 9:00 - 18:00",
            "miercoles: 9:00 - 18:00",
            "jueves: 9:00 - 18:00",
            "viernes: 9:00 - 17:00",
        ),
        resenas=(
            Resena(
                autor="Maria Quispe",
                calificacion=5,
                texto="Me asesoraron en un caso laboral y explicaron todo con claridad.",
            ),
            Resena(
                autor="Jorge Ticona",
                calificacion=5,
                texto="Atencion puntual y seria. Resolvieron mi consulta sobre una sucesion.",
            ),
        ),
        fotos=(Foto(ref="places/demo/photos/1", ancho=1600, alto=900),),
    )


async def procesar(args: argparse.Namespace) -> int:
    nicho = cargar_nicho(args.nicho)

    if args.demo:
        lead = _lead_demo()
    else:
        print("Cargar leads desde la base aun no esta implementado; usa --demo", file=sys.stderr)
        return 2

    tema = Tema(**nicho.tema) if nicho.tema else Tema()
    spec = construir_spec(lead, nicho, tema=tema)
    print(f"site_id: {spec.site_id}")

    llm: LLMClient | None = None
    if not args.sin_ia:
        llm = OllamaClient(args.modelo)
        print(f"Generando copy con {args.modelo} (puede tardar varios minutos en CPU)...")

    try:
        contenido, origen = await generar_contenido(spec, nicho, llm)
    finally:
        if isinstance(llm, OllamaClient):
            await llm.aclose()

    spec = spec.model_copy(update={"contenido": contenido})
    print(f"Contenido generado por: {origen}")
    print(f"  titular: {contenido.titular}")

    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    print("\nConstruyendo con Astro...")
    resultado = construir_sitio(spec, DIR_SALIDA)

    if not resultado.exito or resultado.dist is None:
        print(f"\nEl build fallo:\n{resultado.salida}", file=sys.stderr)
        return 1

    print(f"Sitio construido en {resultado.dist}")

    reporte = revisar_sitio(resultado.dist, spec)
    print()
    print(reporte.resumen())

    return 0 if reporte.aprobado else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nicho", default=get_settings().nicho)
    parser.add_argument("--demo", action="store_true", help="usa un lead de ejemplo")
    parser.add_argument("--lead-ref", help="ref del lead en la base (pendiente)")
    parser.add_argument("--sin-ia", action="store_true", help="copy de plantilla, sin LLM")
    parser.add_argument("--modelo", default="gemma4:26b")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(procesar(args))


if __name__ == "__main__":
    raise SystemExit(main())
