"""Renderizado: `SiteSpec` -> sitio estatico construido con Astro.

Cada sitio se construye en su propio directorio, partiendo de una copia de la
plantilla del nicho. `node_modules` se enlaza en vez de copiarse: son miles de
archivos y copiarlos por sitio haria el batch inviable.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from site_generator.spec import SiteSpec

logger = logging.getLogger(__name__)

__all__ = ["DIR_PLANTILLAS", "ResultadoBuild", "construir_sitio", "preparar_directorio"]

DIR_PLANTILLAS = Path(__file__).resolve().parent.parent / "templates"

# Un build de Astro de este tamano tarda segundos; si pasa de esto, algo colgo.
_TIMEOUT_BUILD = 300


@dataclass(slots=True)
class ResultadoBuild:
    exito: bool
    dist: Path | None
    salida: str
    """stdout+stderr del build. Es lo primero que se mira cuando algo falla."""


class PlantillaNoEncontrada(FileNotFoundError):
    pass


def ruta_plantilla(nicho: str, *, directorio: Path | None = None) -> Path:
    ruta = (directorio or DIR_PLANTILLAS) / nicho
    if not (ruta / "package.json").is_file():
        raise PlantillaNoEncontrada(f"No hay plantilla Astro para el nicho '{nicho}' en {ruta}")
    return ruta


def preparar_directorio(
    spec: SiteSpec,
    destino: Path,
    *,
    directorio_plantillas: Path | None = None,
) -> Path:
    """Copia la plantilla del nicho a `destino` y le inyecta la spec.

    Devuelve la ruta del directorio de trabajo listo para construir.
    """
    if not spec.esta_completa:
        raise ValueError(f"La spec de {spec.site_id} no tiene copy: falta el paso de generacion")

    plantilla = ruta_plantilla(spec.nicho, directorio=directorio_plantillas)
    trabajo = destino / spec.site_id

    if trabajo.exists():
        shutil.rmtree(trabajo)
    # `node_modules` y `dist` de la plantilla no se copian: el primero se enlaza
    # abajo y el segundo es basura de un build anterior.
    shutil.copytree(
        plantilla,
        trabajo,
        ignore=shutil.ignore_patterns("node_modules", "dist", ".astro"),
    )

    modulos_plantilla = plantilla / "node_modules"
    if modulos_plantilla.is_dir():
        enlace = trabajo / "node_modules"
        # Relativo para que el directorio siga siendo movible.
        os.symlink(os.path.relpath(modulos_plantilla, trabajo), enlace, target_is_directory=True)

    spec_json = trabajo / "src" / "spec.json"
    spec_json.write_text(
        json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.debug("Directorio de trabajo listo en %s", trabajo)
    return trabajo


def construir_sitio(
    spec: SiteSpec,
    destino: Path,
    *,
    directorio_plantillas: Path | None = None,
) -> ResultadoBuild:
    """Prepara y construye el sitio. No lanza si Astro falla: lo reporta."""
    trabajo = preparar_directorio(spec, destino, directorio_plantillas=directorio_plantillas)

    if not (trabajo / "node_modules").exists():
        plantilla = ruta_plantilla(spec.nicho, directorio=directorio_plantillas)
        return ResultadoBuild(
            exito=False,
            dist=None,
            salida=(
                "Faltan las dependencias de la plantilla. Corre una vez:\n"
                f"  npm install --prefix {plantilla}"
            ),
        )

    try:
        proceso = subprocess.run(
            ["npm", "run", "build", "--silent"],
            cwd=trabajo,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_BUILD,
            check=False,
        )
    except FileNotFoundError:
        return ResultadoBuild(
            exito=False, dist=None, salida="npm no esta instalado o no esta en PATH"
        )
    except subprocess.TimeoutExpired:
        return ResultadoBuild(
            exito=False, dist=None, salida=f"El build supero {_TIMEOUT_BUILD}s y se aborto"
        )

    salida = (proceso.stdout or "") + (proceso.stderr or "")
    dist = trabajo / "dist"

    if proceso.returncode != 0:
        return ResultadoBuild(exito=False, dist=None, salida=salida)
    if not (dist / "index.html").is_file():
        return ResultadoBuild(
            exito=False, dist=None, salida=salida + "\nEl build termino sin generar dist/index.html"
        )

    return ResultadoBuild(exito=True, dist=dist, salida=salida)
