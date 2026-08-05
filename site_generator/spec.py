"""Especificacion de un sitio (spec-driven development, seccion 5 del plan).

La spec es la fuente de verdad, no el prompt. Y su division interna es la regla
mas importante de toda la Fase 3:

- `Hechos`  -- vienen de `LeadDetail`, deterministas. La IA NUNCA los escribe.
- `Contenido` -- prosa generada por la IA. Nunca contiene datos de contacto.

El harness de QA verifica esa separacion sobre el HTML renderizado: si un
telefono del sitio no coincide con el de la spec, el sitio se rechaza. Asi
"la IA no invento datos del negocio" deja de ser una esperanza y pasa a ser un
check mecanico.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Contacto", "Contenido", "Hechos", "Resena", "Servicio", "SiteSpec", "Tema"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Resena(_Base):
    """Resena real del listing de Google. Se muestra tal cual: no se reescribe."""

    autor: str
    calificacion: int = Field(ge=1, le=5)
    texto: str


class Contacto(_Base):
    telefono: str
    telefono_href: str
    """Listo para `<a href>`, ej. `tel:+5154123456`."""

    whatsapp_url: str | None = None
    """`https://wa.me/...` con mensaje prellenado, o None si no hay movil."""

    direccion: str | None = None


class Hechos(_Base):
    """Todo lo verificable. Sale de `LeadDetail` sin pasar por un modelo."""

    nombre: str
    zona: str
    contacto: Contacto
    horario: tuple[str, ...] = ()
    resenas: tuple[Resena, ...] = ()
    rating: float | None = None
    num_resenas: int | None = None
    fotos: tuple[str, ...] = ()
    """URLs o rutas locales de fotos del propio listing del negocio."""


class Servicio(_Base):
    nombre: str
    descripcion: str = Field(min_length=20, max_length=400)


class Contenido(_Base):
    """Lo unico que escribe la IA. Sin telefonos, sin direcciones, sin URLs."""

    titular: str = Field(min_length=10, max_length=90)
    subtitulo: str = Field(min_length=20, max_length=200)
    sobre_nosotros: str = Field(min_length=80, max_length=900)
    servicios: tuple[Servicio, ...] = Field(min_length=2, max_length=8)
    cta_texto: str = Field(min_length=5, max_length=80)

    def textos(self) -> list[str]:
        """Todo el texto generado, plano. Lo usa el fact-check del harness."""
        partes = [self.titular, self.subtitulo, self.sobre_nosotros, self.cta_texto]
        for servicio in self.servicios:
            partes.extend((servicio.nombre, servicio.descripcion))
        return partes


class Tema(_Base):
    """Ajustes visuales por nicho. No los decide la IA: vienen del config."""

    color_primario: str = "#1e3a5f"
    color_acento: str = "#c9a227"
    fuente_titulos: str = "Georgia, serif"
    fuente_texto: str = "system-ui, sans-serif"


class SiteSpec(_Base):
    """Contrato completo entre el generador y la plantilla Astro."""

    site_id: str
    """Identificador estable y URL-safe. Es el subdominio y la clave del backend."""

    lead_ref: str
    nicho: str
    hechos: Hechos
    tema: Tema = Tema()
    contenido: Contenido | None = None
    """None hasta que corre el paso de copywriting."""

    es_demo: bool = True
    """Un sitio demo lleva aviso de que no es el sitio oficial del negocio.

    Se genera sin que el negocio lo haya pedido, con sus datos publicos de
    Google. El aviso evita que se confunda con su sitio real, que es el riesgo
    concreto de la seccion 10 del plan. Pasa a False cuando el negocio cierra
    como cliente y el sitio va a produccion.
    """

    @property
    def esta_completa(self) -> bool:
        return self.contenido is not None
