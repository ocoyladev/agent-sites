"""Heuristica de calidad del sitio web existente (seccion 3.3 del plan).

Responde una sola pregunta: si este negocio ya tiene sitio, ¿es lo bastante malo
como para que valga la pena venderle uno nuevo?

Deliberadamente sin LLM: son checks objetivos, baratos y reproducibles. Un
modelo aqui costaria plata y daria respuestas distintas para el mismo sitio.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx
from selectolax.parser import HTMLParser

logger = logging.getLogger(__name__)

__all__ = ["CalidadSitio", "evaluar_sitio"]

# Un sitio moderno decente supera holgadamente estos minimos. Cada check vale
# puntos; el total es `calidad_sitio_score` en la tabla `leads`.
_PUNTOS = {
    "responde": 20,
    "https": 15,
    "responsive": 25,
    "cta_contacto": 20,
    "titulo": 10,
    "contenido": 10,
}

_RE_TEL = re.compile(r"tel:|whatsapp|wa\.me|api\.whatsapp\.com", re.I)
_RE_CONTACTO = re.compile(r"cont[aá]ct|escr[ií]benos|ll[aá]manos|mailto:", re.I)
# Paginas de dominio estacionado o "en construccion": tienen sitio en el papel,
# no en la practica. Para nosotros valen igual que no tener nada.
_RE_PLACEHOLDER = re.compile(
    r"en\s+construcci[oó]n|coming\s+soon|domain\s+for\s+sale|dominio\s+en\s+venta"
    r"|this\s+domain|parked\s+(domain|free)|godaddy|sedoparking",
    re.I,
)


@dataclass(slots=True)
class CalidadSitio:
    """Resultado de la evaluacion. `score` es None si el sitio no se pudo ver."""

    url: str
    score: float | None
    alcanzable: bool
    checks: dict[str, bool] = field(default_factory=dict)
    motivo_fallo: str | None = None
    es_placeholder: bool = False

    @property
    def vale_la_pena_vender(self) -> bool:
        """Un sitio bajo 60 deja margen comercial evidente."""
        return self.score is None or self.score < 60


async def evaluar_sitio(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 10.0,
) -> CalidadSitio:
    """Visita el sitio y aplica las heuristicas.

    Nunca lanza por culpa del sitio remoto: un sitio caido, con certificado
    vencido o que nos bloquea es informacion util, no un error del pipeline.
    """
    propio = client is None
    cliente = client or httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        # Algunos hosts devuelven 403 a clientes sin User-Agent de navegador.
        headers={"User-Agent": "Mozilla/5.0 (compatible; AgenciaWebIA/0.1)"},
    )
    try:
        try:
            respuesta = await cliente.get(url)
        except httpx.HTTPError as exc:
            logger.debug("Sitio inalcanzable %s: %s", url, exc)
            return CalidadSitio(
                url=url, score=None, alcanzable=False, motivo_fallo=type(exc).__name__
            )

        if respuesta.status_code >= 400:
            return CalidadSitio(
                url=url,
                score=None,
                alcanzable=False,
                motivo_fallo=f"HTTP {respuesta.status_code}",
            )

        return _evaluar_respuesta(url, respuesta)
    finally:
        if propio:
            await cliente.aclose()


def _evaluar_respuesta(url: str, respuesta: httpx.Response) -> CalidadSitio:
    html = respuesta.text
    arbol = HTMLParser(html)
    texto = arbol.text(separator=" ", strip=True) if arbol.body else ""

    es_placeholder = bool(_RE_PLACEHOLDER.search(texto[:2000]))

    titulo_nodo = arbol.css_first("title")
    titulo = (titulo_nodo.text(strip=True) if titulo_nodo else "") or ""

    viewport = any(
        (nodo.attributes.get("name") or "").lower() == "viewport" for nodo in arbol.css("meta")
    )

    checks = {
        # `respuesta.url` es la URL final tras redirecciones: si el sitio
        # redirige http -> https, cuenta como https.
        "responde": True,
        "https": str(respuesta.url).startswith("https://"),
        "responsive": viewport,
        "cta_contacto": bool(_RE_TEL.search(html) or _RE_CONTACTO.search(html)),
        "titulo": len(titulo) >= 10,
        "contenido": len(texto) >= 500,
    }

    # Un dominio estacionado puede pasar checks tecnicos (https, viewport) sin
    # ser un sitio real. No lo dejamos puntuar por encima del piso.
    alcanzado = float(sum(_PUNTOS[k] for k, ok in checks.items() if ok))
    score = 0.0 if es_placeholder else alcanzado

    return CalidadSitio(
        url=url,
        score=score,
        alcanzable=True,
        checks=checks,
        es_placeholder=es_placeholder,
    )
