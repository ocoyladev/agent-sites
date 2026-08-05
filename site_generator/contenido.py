"""Paso de copywriting: lo unico que escribe la IA.

Tres defensas, en orden:

1. **El prompt no recibe datos de contacto.** Si el modelo nunca ve el telefono,
   no puede colocarlo mal en el texto.
2. **Validacion de esquema** con pydantic, con reintentos.
3. **`_texto_con_datos_de_contacto`** rechaza cualquier texto que traiga
   telefonos, URLs o correos, aunque el modelo se los haya inventado de la nada.

El contenido se pide en tres llamadas cortas, no en una larga: los modelos
locales degeneran en bucles cuando se les pide un JSON grande de una sola vez
(ver ADR 0003). Cada pieza se valida y se reintenta por separado.

Si una pieza no sale, se usa su version de plantilla. Un sitio correcto y sobrio
siempre es mejor que ningun sitio -- y que un sitio con datos falsos.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from lead_gen.nichos import Nicho
from site_generator.llm.base import LLMClient, LLMError
from site_generator.spec import Contenido, Servicio, SiteSpec

logger = logging.getLogger(__name__)

__all__ = ["construir_instrucciones", "contenido_de_plantilla", "generar_contenido"]

_REINTENTOS = 2

# Lo que jamas debe aparecer en texto generado: son datos que solo pueden venir
# de `Hechos`, nunca de un modelo.
_PATRONES_PROHIBIDOS = (
    re.compile(r"\d[\d\s().-]{6,}"),  # secuencias que parecen telefono
    re.compile(r"https?://|www\.|wa\.me", re.I),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
)


def _textos_de(pieza: BaseModel) -> list[str]:
    """Todos los strings de una pieza, incluidos los anidados en servicios."""
    textos: list[str] = []
    for valor in pieza.model_dump().values():
        if isinstance(valor, str):
            textos.append(valor)
        elif isinstance(valor, (list, tuple)):
            for item in valor:
                if isinstance(item, dict):
                    textos.extend(v for v in item.values() if isinstance(v, str))
    return textos


def _texto_con_datos_de_contacto(pieza: BaseModel) -> str | None:
    """Devuelve el texto ofensor, o None si todo esta limpio."""
    for texto in _textos_de(pieza):
        for patron in _PATRONES_PROHIBIDOS:
            if patron.search(texto):
                return texto
    return None


def construir_instrucciones(spec: SiteSpec, nicho: Nicho) -> str:
    """Arma el prompt. Deliberadamente sin telefono, direccion ni URLs."""
    catalogo = ", ".join(nicho.servicios) if nicho.servicios else "sus servicios habituales"
    resenas = [r.texto for r in spec.hechos.resenas[:2]]
    contexto_resenas = (
        "\nLo que dicen sus clientes (usalo solo para captar el tono, NO lo copies):\n"
        + "\n".join(f"- {t[:200]}" for t in resenas)
        if resenas
        else ""
    )

    return (
        f"Eres copywriter profesional de sitios web para negocios locales en Peru.\n\n"
        f"Negocio: {spec.hechos.nombre}\n"
        f"Rubro: {nicho.etiqueta}\n"
        f"Zona: {spec.hechos.zona}\n"
        f"Servicios posibles del rubro: {catalogo}"
        f"{contexto_resenas}\n\n"
        f"Escribe el contenido del sitio en espanol peruano, claro y profesional.\n"
        f"Reglas estrictas:\n"
        f"- NO inventes anos de experiencia, premios, cifras ni cantidad de clientes.\n"
        f"- NO escribas telefonos, direcciones, correos ni URLs. Eso lo pone la plantilla.\n"
        f"- NO copies literalmente las resenas.\n"
        f"- Elige entre 3 y 5 servicios del catalogo y describe cada uno en 1-2 frases.\n"
        f"- Tono: cercano pero serio. Sin exageraciones ni superlativos vacios.\n"
    )


_ESQUEMA_CABECERA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "titular": {"type": "string", "description": "Maximo 10 palabras"},
        "subtitulo": {"type": "string", "description": "Una frase, maximo 25 palabras"},
        "cta_texto": {"type": "string", "description": "Llamada a la accion, 3-8 palabras"},
    },
    "required": ["titular", "subtitulo", "cta_texto"],
}

_ESQUEMA_SOBRE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sobre_nosotros": {"type": "string", "description": "2-3 frases, maximo 90 palabras"},
    },
    "required": ["sobre_nosotros"],
}

_ESQUEMA_SERVICIOS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "servicios": {
            "type": "array",
            "description": "Entre 3 y 4 servicios",
            "items": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string"},
                    "descripcion": {"type": "string", "description": "1-2 frases"},
                },
                "required": ["nombre", "descripcion"],
            },
        },
    },
    "required": ["servicios"],
}


class _Cabecera(BaseModel):
    titular: str = Field(min_length=10, max_length=90)
    subtitulo: str = Field(min_length=20, max_length=200)
    cta_texto: str = Field(min_length=5, max_length=80)


class _Sobre(BaseModel):
    sobre_nosotros: str = Field(min_length=80, max_length=900)


class _Servicios(BaseModel):
    servicios: tuple[Servicio, ...] = Field(min_length=2, max_length=8)


async def _pedir_pieza[T: BaseModel](
    llm: LLMClient,
    modelo: type[T],
    *,
    instrucciones: str,
    esquema: dict[str, Any],
    max_tokens: int,
    reintentos: int,
) -> T | None:
    """Pide una pieza del contenido. Devuelve None si no se pudo obtener.

    Cada pieza se valida por separado para que un fallo en los servicios no tire
    abajo un titular que salio bien.
    """
    etiqueta = modelo.__name__.lstrip("_")

    for intento in range(1, reintentos + 1):
        try:
            crudo = await llm.generar_json(
                instrucciones=instrucciones, esquema=esquema, max_tokens=max_tokens
            )
        except LLMError as exc:
            logger.warning("%s intento %d/%d: %s", etiqueta, intento, reintentos, exc)
            continue

        try:
            pieza = modelo.model_validate(crudo)
        except ValidationError as exc:
            logger.warning(
                "%s intento %d/%d: no cumple el esquema (%d errores)",
                etiqueta,
                intento,
                reintentos,
                exc.error_count(),
            )
            continue

        ofensor = _texto_con_datos_de_contacto(pieza)
        if ofensor:
            logger.warning(
                "%s intento %d/%d: trae datos de contacto inventados: %.60s",
                etiqueta,
                intento,
                reintentos,
                ofensor,
            )
            continue

        return pieza

    return None


async def generar_contenido(
    spec: SiteSpec,
    nicho: Nicho,
    llm: LLMClient | None,
    *,
    reintentos: int = _REINTENTOS,
) -> tuple[Contenido, str]:
    """Genera el contenido del sitio en tres pedidos chicos. Devuelve (contenido, origen).

    Pedir todo el sitio en un solo JSON no funciona con modelos locales: en
    ia-node, gemma4:26b degeneraba en un bucle de la misma silaba a los ~96
    caracteres y quemaba 3.000 tokens sin producir nada util. Pedidos cortos --
    del tamano de los que si completaba -- evitan ese modo de falla.

    `origen` dice quien escribio: el proveedor, 'plantilla' si ninguna pieza
    salio, o 'mixto' si algunas si. Se persiste para saber que regenerar despues.
    """
    respaldo = contenido_de_plantilla(spec, nicho)
    if llm is None:
        return respaldo, "plantilla"

    instrucciones = construir_instrucciones(spec, nicho)

    cabecera = await _pedir_pieza(
        llm,
        _Cabecera,
        instrucciones=instrucciones + "\nEscribe solo el titular, el subtitulo y el CTA.",
        esquema=_ESQUEMA_CABECERA,
        max_tokens=200,
        reintentos=reintentos,
    )
    sobre = await _pedir_pieza(
        llm,
        _Sobre,
        instrucciones=instrucciones + "\nEscribe solo el parrafo 'sobre nosotros'.",
        esquema=_ESQUEMA_SOBRE,
        max_tokens=300,
        reintentos=reintentos,
    )
    servicios = await _pedir_pieza(
        llm,
        _Servicios,
        instrucciones=instrucciones + "\nEscribe solo la lista de servicios.",
        esquema=_ESQUEMA_SERVICIOS,
        max_tokens=500,
        reintentos=reintentos,
    )

    contenido = Contenido(
        titular=cabecera.titular if cabecera else respaldo.titular,
        subtitulo=cabecera.subtitulo if cabecera else respaldo.subtitulo,
        cta_texto=cabecera.cta_texto if cabecera else respaldo.cta_texto,
        sobre_nosotros=sobre.sobre_nosotros if sobre else respaldo.sobre_nosotros,
        servicios=servicios.servicios if servicios else respaldo.servicios,
    )

    obtenidas = sum(pieza is not None for pieza in (cabecera, sobre, servicios))
    if obtenidas == 3:
        return contenido, llm.nombre
    if obtenidas == 0:
        logger.warning("Ninguna pieza salio de %s; el sitio queda con plantilla", llm.nombre)
        return contenido, "plantilla"

    logger.warning("Solo %d de 3 piezas salieron de %s", obtenidas, llm.nombre)
    return contenido, "mixto"


def contenido_de_plantilla(spec: SiteSpec, nicho: Nicho) -> Contenido:
    """Contenido deterministico, sin IA. Sobrio pero correcto y siempre disponible.

    Se limita a lo que se puede afirmar con certeza a partir de los hechos: el
    rubro, la zona y los servicios del catalogo del nicho.
    """
    nombre = spec.hechos.nombre
    zona = spec.hechos.zona
    catalogo = nicho.servicios or ("Asesoria personalizada", "Atencion de consultas")

    servicios = tuple(
        Servicio(
            nombre=servicio,
            descripcion=(
                f"Atendemos casos de {servicio.lower()} en {zona}. "
                f"Escribenos para revisar tu situacion y orientarte sobre los pasos a seguir."
            ),
        )
        for servicio in catalogo[:4]
    )

    return Contenido(
        titular=f"{nicho.etiqueta.split(' y ')[0]} en {zona}"[:90],
        subtitulo=(
            f"{nombre} atiende consultas en {zona}. "
            f"Conversemos sobre tu caso y las opciones que tienes."
        )[:200],
        sobre_nosotros=(
            f"{nombre} brinda servicios profesionales en {zona}. "
            f"Trabajamos de forma directa y clara: escuchamos tu caso, explicamos las "
            f"alternativas y acompanamos el proceso hasta el final. "
            f"Escribenos y coordinamos una primera conversacion."
        )[:900],
        servicios=servicios,
        cta_texto="Conversemos sobre tu caso",
    )
