"""Despliegue a Cloudflare Pages via Wrangler.

## Por que un solo proyecto y no uno por sitio

Cloudflare limita a **100 proyectos de Pages por cuenta**, y su propia
documentacion dice que ese tope "no se amplia de forma rutinaria". Un proyecto
por sitio agotaria la cuenta a los 100 sitios -- en total, no por mes. A 300
leads mensuales eso se acaba en dos semanas.

La salida es usar **un solo proyecto y un alias de rama por sitio**. Cada
deployment con `--branch=<site_id>` queda publicado en
`https://<site_id>.<proyecto>.pages.dev`, que es justo la URL que se manda por
WhatsApp. Cloudflare normaliza el nombre de rama a minusculas cambiando lo no
alfanumerico por guiones; `site_id` ya viene en ese formato, asi que el mapeo es
uno a uno y la URL es predecible sin tener que leerla de la salida del comando.

Requisitos de entorno: `CLOUDFLARE_API_TOKEN` (permiso `Cloudflare Pages: Edit`)
y `CLOUDFLARE_ACCOUNT_ID`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

from deploy.base import ResultadoDeploy

logger = logging.getLogger(__name__)

__all__ = ["CloudflarePagesDeployer", "construir_comando", "extraer_url", "url_esperada"]

_TIMEOUT = 300

# Wrangler imprime la URL en una linea suelta; se usa solo como confirmacion,
# porque la URL del alias ya la sabemos de antemano.
_RE_URL = re.compile(r"https://[\w.-]+\.pages\.dev\b")


def url_esperada(site_id: str, proyecto: str) -> str:
    """URL del alias de rama, calculada sin depender de la salida del comando."""
    return f"https://{site_id}.{proyecto}.pages.dev"


def extraer_url(salida: str) -> str | None:
    """Ultima URL *.pages.dev que aparezca en la salida de Wrangler."""
    encontradas = _RE_URL.findall(salida)
    return encontradas[-1] if encontradas else None


def construir_comando(dist: Path, site_id: str, proyecto: str) -> list[str]:
    """Comando de despliegue.

    `--commit-dirty` evita que Wrangler pida confirmacion interactiva al detectar
    un repo con cambios sin commitear, que es el estado normal en una corrida
    automatica.
    """
    return [
        "npx",
        "--yes",
        "wrangler@latest",
        "pages",
        "deploy",
        str(dist),
        f"--project-name={proyecto}",
        f"--branch={site_id}",
        "--commit-dirty=true",
    ]


class CloudflarePagesDeployer:
    nombre = "cloudflare_pages"

    def __init__(
        self,
        proyecto: str,
        *,
        api_token: str | None = None,
        account_id: str | None = None,
    ) -> None:
        self._proyecto = proyecto
        self._api_token = api_token or os.environ.get("CLOUDFLARE_API_TOKEN", "")
        self._account_id = account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")

    @property
    def configurado(self) -> bool:
        return bool(self._proyecto and self._api_token and self._account_id)

    async def desplegar(self, dist: Path, site_id: str) -> ResultadoDeploy:
        if not self.configurado:
            faltan = [
                nombre
                for nombre, valor in (
                    ("CLOUDFLARE_API_TOKEN", self._api_token),
                    ("CLOUDFLARE_ACCOUNT_ID", self._account_id),
                    ("CLOUDFLARE_PAGES_PROJECT", self._proyecto),
                )
                if not valor
            ]
            return ResultadoDeploy(
                exito=False,
                url=None,
                salida=f"Falta configurar: {', '.join(faltan)}. Ver docs/setup-cloudflare.md",
            )

        if not (dist / "index.html").is_file():
            return ResultadoDeploy(
                exito=False, url=None, salida=f"No hay index.html en {dist}: nada que desplegar"
            )

        entorno = {
            **os.environ,
            "CLOUDFLARE_API_TOKEN": self._api_token,
            "CLOUDFLARE_ACCOUNT_ID": self._account_id,
        }
        comando = construir_comando(dist, site_id, self._proyecto)
        logger.info("Desplegando %s a Cloudflare Pages...", site_id)

        try:
            proceso = await asyncio.create_subprocess_exec(
                *comando,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=entorno,
            )
            crudo, _ = await asyncio.wait_for(proceso.communicate(), timeout=_TIMEOUT)
        except FileNotFoundError:
            return ResultadoDeploy(exito=False, url=None, salida="npx no esta disponible en PATH")
        except TimeoutError:
            return ResultadoDeploy(
                exito=False, url=None, salida=f"El despliegue supero {_TIMEOUT}s y se aborto"
            )

        salida = crudo.decode("utf-8", errors="replace")

        if proceso.returncode != 0:
            return ResultadoDeploy(exito=False, url=None, salida=salida)

        # Se prefiere la URL calculada: es la del alias estable, mientras que la
        # que imprime Wrangler suele ser la del deployment con hash.
        return ResultadoDeploy(exito=True, url=url_esperada(site_id, self._proyecto), salida=salida)
