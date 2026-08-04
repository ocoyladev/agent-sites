"""Contrato que cumple toda fuente de leads.

La decision de que fuente usar (Google Places, registro del ICAA, un directorio,
un scraper propio) es una linea de configuracion, no una reescritura. Ver
docs/adr/0001-fuentes-de-leads.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from lead_gen.models import LeadDetail, RawLead

__all__ = ["LeadSource"]


@runtime_checkable
class LeadSource(Protocol):
    """Descubre negocios y luego amplia el detalle de los que interesan.

    La separacion en dos pasos no es estetica: en Google el descubrimiento es
    barato y el detalle es caro, asi que el pipeline descubre en masa y solo
    paga el detalle de los que pasan el primer filtro.
    """

    nombre: str
    """Identificador de la fuente, se persiste en `leads.fuente`."""

    def buscar(self, consulta: str, zona: str) -> AsyncIterator[RawLead]:
        """Descubre negocios para un nicho + zona.

        Devuelve un iterador asincrono porque las fuentes suelen paginar y no
        queremos materializar todo en memoria antes de empezar a filtrar.
        """
        ...

    async def detalle(self, lead: RawLead, *, con_resenas: bool = False) -> LeadDetail:
        """Amplia un lead descubierto con los datos caros.

        `con_resenas` se separa porque en Google las resenas caen en un SKU
        distinto y mas escaso que el resto del detalle.
        """
        ...
