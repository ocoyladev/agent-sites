"""Construccion de la parte deterministica de la spec, desde `LeadDetail`.

Aqui no interviene ningun modelo. Todo lo que sale de este modulo es verificable
contra los datos de Google, y es exactamente lo que el harness de QA usara para
fact-checkear el sitio renderizado.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import quote

from lead_gen.models import LeadDetail
from lead_gen.nichos import Nicho
from site_generator.spec import Contacto, Hechos, Resena, SiteSpec, Tema

__all__ = ["construir_site_id", "construir_spec", "normalizar_telefono", "slug"]

# Longitud del hash en `site_id`. 6 hex = 16M combinaciones: suficiente para que
# dos negocios con el mismo nombre en distinta zona no colisionen.
_LARGO_HASH = 6

_MENSAJE_WHATSAPP = "Hola, vi su pagina web y quisiera consultar sobre sus servicios."


def slug(texto: str) -> str:
    """Convierte un nombre de negocio en algo apto para URL y subdominio."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    limpio = re.sub(r"[^a-z0-9]+", "-", sin_tildes.lower()).strip("-")
    return re.sub(r"-{2,}", "-", limpio)


def construir_site_id(nombre: str, ref: str) -> str:
    """Identificador estable: mismo lead -> mismo site_id, siempre.

    Se usa como subdominio y como clave del backend multi-tenant, asi que no
    puede depender de la fecha ni de un contador.
    """
    huella = hashlib.sha256(ref.encode()).hexdigest()[:_LARGO_HASH]
    base = slug(nombre)[:40].strip("-") or "sitio"
    return f"{base}-{huella}"


def normalizar_telefono(telefono: str) -> tuple[str, bool]:
    """Devuelve (E.164, es_movil) para un numero peruano.

    Google entrega formatos variados: '054 123456' (fijo de Arequipa),
    '987 654 321' (movil), '+51 54 123456'. WhatsApp solo funciona con moviles,
    y en Peru esos son 9 digitos que empiezan en 9.
    """
    digitos = re.sub(r"\D", "", telefono)

    # El 0 inicial es el prefijo nacional de larga distancia y no forma parte
    # del numero. Se quita primero porque '(051) 987654321' deja '51987654321',
    # que YA trae el codigo de pais -- anteponerle otro '51' daba numeros
    # invalidos de 13 digitos.
    digitos = digitos.lstrip("0")

    nacional = digitos[2:] if digitos.startswith("51") and len(digitos) in (10, 11) else digitos
    e164 = f"+51{nacional}"

    # Movil peruano: 9 digitos nacionales que empiezan en 9 (+51 9XXXXXXXX).
    # Se evalua sobre la parte nacional, no sobre el largo del E.164 completo,
    # que es facil de contar mal.
    es_movil = len(nacional) == 9 and nacional.startswith("9")
    return e164, es_movil


def _construir_contacto(lead: LeadDetail) -> Contacto:
    if not lead.telefono:
        raise ValueError(f"El lead {lead.ref} no tiene telefono: no puede generar sitio")

    e164, es_movil = normalizar_telefono(lead.telefono)
    whatsapp = None
    if es_movil:
        # `wa.me` espera el numero sin '+'.
        whatsapp = f"https://wa.me/{e164.lstrip('+')}?text={quote(_MENSAJE_WHATSAPP)}"

    return Contacto(
        telefono=lead.telefono,
        telefono_href=f"tel:{e164}",
        whatsapp_url=whatsapp,
        direccion=lead.direccion,
    )


def _extraer_zona(lead: LeadDetail, ciudad: str) -> str:
    """Saca el distrito de la direccion de Google y lo califica con la ciudad.

    El formato tipico es 'Calle X 123, Distrito 04001, Peru'. Nos quedamos con
    el penultimo tramo util, que suele ser el distrito.

    La ciudad SIEMPRE se anexa. Un distrito suelto es ambiguo -- 'Cercado' existe
    en Lima y en Arequipa -- y el modelo de copywriting resolvia esa ambiguedad
    por su cuenta: con `Zona: Cercado` escribio "en el Cercado de Lima" para un
    estudio de Arequipa. La zona que ve el prompt tiene que ser inequivoca.
    """
    if not lead.direccion:
        return ciudad

    tramos = [t.strip() for t in lead.direccion.split(",") if t.strip()]
    if len(tramos) < 2:
        return ciudad

    # El ultimo suele ser el pais; el anterior, distrito + codigo postal.
    candidato = tramos[-2] if tramos[-1].lower() in {"peru", "perú"} else tramos[-1]
    distrito = re.sub(r"\s*\d{5}\s*", " ", candidato).strip()

    if not distrito:
        return ciudad
    # Evita "Arequipa, Arequipa" cuando el distrito ya es la ciudad.
    if distrito.casefold() == ciudad.casefold():
        return ciudad
    return f"{distrito}, {ciudad}"


def _seleccionar_resenas(lead: LeadDetail, maximo: int = 3) -> tuple[Resena, ...]:
    """Se muestran las mejores resenas reales, sin reescribirlas.

    Reescribir una resena la volveria un testimonio inventado -- justo lo que el
    fact-check existe para impedir.
    """
    utiles = [
        Resena(autor=r.autor or "Cliente", calificacion=r.calificacion or 5, texto=r.texto.strip())
        for r in lead.resenas
        if r.texto and r.texto.strip() and (r.calificacion or 0) >= 4
    ]
    utiles.sort(key=lambda r: r.calificacion, reverse=True)
    return tuple(utiles[:maximo])


def construir_spec(
    lead: LeadDetail,
    nicho: Nicho,
    *,
    ciudad: str = "Arequipa",
    tema: Tema | None = None,
) -> SiteSpec:
    """`LeadDetail` -> `SiteSpec` sin copy. El paso de IA se aplica despues."""
    hechos = Hechos(
        nombre=lead.nombre,
        zona=_extraer_zona(lead, ciudad),
        contacto=_construir_contacto(lead),
        horario=lead.horario,
        resenas=_seleccionar_resenas(lead),
        rating=lead.rating,
        num_resenas=lead.num_resenas,
        fotos=tuple(foto.ref for foto in lead.fotos),
    )
    return SiteSpec(
        site_id=construir_site_id(lead.nombre, lead.ref),
        lead_ref=lead.ref,
        nicho=nicho.nombre,
        hechos=hechos,
        tema=tema or Tema(),
    )
