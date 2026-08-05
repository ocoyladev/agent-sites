"""Contrato de los destinos de despliegue.

Mismo patron que `LeadSource` y `LLMClient`: el proveedor es configuracion, no
arquitectura. Hoy Cloudflare Pages; manana un subdominio propio servido desde
ia-node con Caddy (Fase 4 del plan, sitios de cliente cerrado).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = ["DeployError", "Deployer", "ResultadoDeploy"]


class DeployError(RuntimeError):
    """El despliegue no se pudo completar."""


@dataclass(slots=True)
class ResultadoDeploy:
    exito: bool
    url: str | None
    salida: str
    """Salida cruda del comando. Es lo primero que se mira cuando algo falla."""


@runtime_checkable
class Deployer(Protocol):
    nombre: str

    async def desplegar(self, dist: Path, site_id: str) -> ResultadoDeploy:
        """Publica el contenido de `dist` y devuelve la URL publica."""
        ...
