"""Modelos de dominio compartidos por todas las fuentes de leads.

Estos tipos son deliberadamente independientes de Google: son el contrato que
cualquier proveedor (Places API, registro del ICAA, directorios, scraper) debe
cumplir. Agregar una fuente nueva no cambia nada rio abajo.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "EstadoPipeline",
    "Foto",
    "LeadDetail",
    "LeadScore",
    "RawLead",
    "Resena",
]


class EstadoPipeline(StrEnum):
    """Estados del pipeline comercial (seccion 4 del plan)."""

    NUEVO = "nuevo"
    CALIFICADO = "calificado"
    SITIO_GENERADO = "sitio_generado"
    QA_APROBADO = "qa_aprobado"
    CONTACTADO = "contactado"
    INTERESADO = "interesado"
    DEMO_AGENDADA = "demo_agendada"
    NEGOCIACION = "negociacion"
    CLIENTE = "cliente"
    DESCARTADO = "descartado"


class _Base(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RawLead(_Base):
    """Identidad minima de un negocio, tal como la devuelve un descubrimiento.

    Barato de obtener: es lo que se consigue con campos Essentials/Pro. El
    detalle caro (telefono, sitio, rating) se pide despues y solo para los que
    valen la pena.
    """

    fuente: str
    """Identificador del proveedor, ej. 'google_places'."""

    ref: str
    """Identificador del negocio dentro del proveedor. Para Google, el place_id."""

    nombre: str
    direccion: str | None = None
    lat: float | None = None
    lng: float | None = None
    tipos: tuple[str, ...] = ()


class Foto(_Base):
    ref: str
    """Referencia opaca del proveedor para descargar la imagen."""

    ancho: int | None = None
    alto: int | None = None
    atribuciones: tuple[str, ...] = ()
    """Google exige mostrar estas atribuciones junto a la foto."""


class Resena(_Base):
    autor: str | None = None
    calificacion: int | None = None
    texto: str | None = None
    fecha: datetime | None = None


class LeadDetail(_Base):
    """Datos completos de un negocio, ya listos para scoring y generacion."""

    fuente: str
    ref: str
    nombre: str
    direccion: str | None = None
    lat: float | None = None
    lng: float | None = None
    tipos: tuple[str, ...] = ()

    telefono: str | None = None
    sitio_web: str | None = None
    rating: float | None = None
    num_resenas: int | None = None
    horario: tuple[str, ...] = ()

    estado_negocio: str | None = None
    """OPERATIONAL / CLOSED_TEMPORARILY / CLOSED_PERMANENTLY segun Google."""

    fotos: tuple[Foto, ...] = ()
    resenas: tuple[Resena, ...] = ()

    @property
    def es_contactable(self) -> bool:
        """Sin telefono no hay outreach posible -- es un filtro duro (seccion 3.3)."""
        return bool(self.telefono)

    @property
    def esta_operativo(self) -> bool:
        # `None` cuenta como operativo: Google omite el campo cuando no tiene
        # senal de cierre, y no queremos descartar leads por un dato ausente.
        return self.estado_negocio in (None, "OPERATIONAL")

    @property
    def tiene_sitio_web(self) -> bool:
        return bool(self.sitio_web)


class LeadScore(_Base):
    """Resultado del scoring, con el desglose visible para poder calibrarlo."""

    total: float = Field(ge=0, le=100)
    demanda: float
    ticket: float
    brecha_digital: float
    contactable: bool
    descartado_por: str | None = None
    """Si esta seteado, el lead no califica sin importar el total."""

    @property
    def califica(self) -> bool:
        return self.descartado_por is None
