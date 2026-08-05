"""Carga de la configuracion por nicho desde `nichos/*.toml`."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["DIR_NICHOS", "Nicho", "cargar_nicho", "nichos_disponibles"]

DIR_NICHOS = Path(__file__).resolve().parent.parent / "nichos"


@dataclass(frozen=True, slots=True)
class Nicho:
    nombre: str
    etiqueta: str
    demanda_base: float
    ticket_base: float
    consultas: tuple[str, ...]
    zonas: tuple[str, ...]
    tipos_esperados: frozenset[str]
    tipos_excluidos: frozenset[str]
    umbral_calificacion: float
    servicios: tuple[str, ...] = ()
    """Catalogo del rubro. La IA elige de aqui; no puede inventar servicios."""

    tema: Mapping[str, str] = field(default_factory=dict)
    """Paleta y tipografias del nicho, se vuelca en `SiteSpec.tema`."""

    @property
    def llamadas_de_descubrimiento(self) -> int:
        """Cuantas llamadas de Text Search cuesta un barrido completo.

        Google pagina hasta 3 veces por consulta, asi que el peor caso es el
        triple de este numero. Sirve para dimensionar el barrido antes de
        lanzarlo, no despues.
        """
        return len(self.consultas) * len(self.zonas)

    def es_del_nicho(self, tipos: tuple[str, ...]) -> bool:
        """Filtra ruido de Text Search antes de pagar un Place Details."""
        conjunto = set(tipos)
        if conjunto & self.tipos_excluidos:
            return False
        if not self.tipos_esperados:
            return True
        return bool(conjunto & self.tipos_esperados)


def cargar_nicho(nombre: str, *, directorio: Path | None = None) -> Nicho:
    ruta = (directorio or DIR_NICHOS) / f"{nombre}.toml"
    if not ruta.is_file():
        disponibles = ", ".join(nichos_disponibles(directorio=directorio)) or "ninguno"
        raise FileNotFoundError(f"No existe el nicho '{nombre}'. Disponibles: {disponibles}")

    datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
    return Nicho(
        nombre=datos["nombre"],
        etiqueta=datos.get("etiqueta", datos["nombre"]),
        demanda_base=float(datos["demanda_base"]),
        ticket_base=float(datos["ticket_base"]),
        consultas=tuple(datos["consultas"]),
        zonas=tuple(datos["zonas"]),
        tipos_esperados=frozenset(datos.get("tipos_esperados", ())),
        tipos_excluidos=frozenset(datos.get("tipos_excluidos", ())),
        umbral_calificacion=float(datos.get("umbral_calificacion", 55.0)),
        servicios=tuple(datos.get("servicios", ())),
        tema=dict(datos.get("tema", {})),
    )


def nichos_disponibles(*, directorio: Path | None = None) -> list[str]:
    carpeta = directorio or DIR_NICHOS
    if not carpeta.is_dir():
        return []
    return sorted(p.stem for p in carpeta.glob("*.toml"))
