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

from deploy.cloudflare import CloudflarePagesDeployer
from lead_gen.models import Foto, LeadDetail, Resena
from lead_gen.nichos import cargar_nicho
from settings import get_settings
from site_generator.contenido import generar_contenido
from site_generator.llm import LLMClient, construir_llm
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

    ajustes = get_settings()
    llm: LLMClient | None = None
    if not args.sin_ia:
        llm = construir_llm(ajustes)
        if llm is not None:
            print(f"Generando contenido con {llm.nombre}...")

    try:
        contenido, origen = await generar_contenido(spec, nicho, llm)
    finally:
        cerrar = getattr(llm, "aclose", None)
        if cerrar is not None:
            await cerrar()

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

    if not reporte.aprobado:
        return 1

    if not args.desplegar:
        print("\n(usa --desplegar para publicarlo en Cloudflare Pages)")
        return 0

    # El deploy va DESPUES del QA y solo si aprobo: publicar un sitio con el
    # telefono equivocado es peor que no publicar nada.
    deployer = CloudflarePagesDeployer(
        ajustes.cloudflare_pages_project,
        api_token=ajustes.cloudflare_api_token,
        account_id=ajustes.cloudflare_account_id,
    )
    print("\nDesplegando a Cloudflare Pages...")
    despliegue = await deployer.desplegar(resultado.dist, spec.site_id)

    if not despliegue.exito:
        print(f"\nEl despliegue fallo:\n{despliegue.salida}", file=sys.stderr)
        return 1

    print(f"Publicado en: {despliegue.url}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nicho", default=get_settings().nicho)
    parser.add_argument("--demo", action="store_true", help="usa un lead de ejemplo")
    parser.add_argument("--lead-ref", help="ref del lead en la base (pendiente)")
    parser.add_argument("--sin-ia", action="store_true", help="copy de plantilla, sin LLM")
    parser.add_argument(
        "--desplegar", action="store_true", help="publica en Cloudflare Pages si el QA aprueba"
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
