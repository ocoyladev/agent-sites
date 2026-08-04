"""Cliente de Google Places API (New).

Implementa `LeadSource` en dos pasos deliberadamente asimetricos:

- `buscar()` usa un FieldMask barato (SKU Text Search Pro, 5.000 gratis/mes) para
  descubrir candidatos en masa.
- `detalle()` usa un FieldMask caro (SKU Place Details Enterprise, solo 1.000
  gratis/mes) y por eso se llama unicamente sobre los que ya pasaron un filtro.

Las resenas viven en un SKU aparte (Enterprise + Atmosphere, otras 1.000
gratis/mes) y se piden solo cuando `con_resenas=True`, tipicamente para el
subconjunto que llegara a generacion de sitio.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any, Final

import httpx

from lead_gen.cost import CostLedger, Sku, sku_for_field_mask
from lead_gen.models import Foto, LeadDetail, RawLead, Resena

logger = logging.getLogger(__name__)

__all__ = ["GooglePlacesSource", "PlacesError"]

_BASE_URL: Final = "https://places.googleapis.com/v1"

# Descubrimiento: lo minimo para decidir si vale la pena pagar el detalle.
# `displayName` es lo que empuja esto a Pro; sin el, seria Essentials, pero un
# lead sin nombre es inutil para el resto del pipeline.
FIELD_MASK_BUSQUEDA: Final = ",".join(
    (
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.types",
        "nextPageToken",
    )
)

# Detalle: todo lo que el scoring y la generacion necesitan, y nada mas.
# `photos` es Essentials (solo devuelve las referencias); descargar la imagen
# es lo que consume el SKU de fotos, y eso pasa en `descargar_foto()`.
FIELD_MASK_DETALLE: Final = ",".join(
    (
        "id",
        "displayName",
        "formattedAddress",
        "location",
        "types",
        # Pro, pero la llamada ya factura Enterprise por los campos de abajo:
        # incluirlo no cuesta nada y evita gastar trabajo en negocios cerrados.
        "businessStatus",
        "nationalPhoneNumber",
        "internationalPhoneNumber",
        "websiteUri",
        "rating",
        "userRatingCount",
        "regularOpeningHours",
        "photos",
    )
)

FIELD_MASK_DETALLE_CON_RESENAS: Final = FIELD_MASK_DETALLE + ",reviews"

_MAX_PAGINAS: Final = 3  # Google corta en 3 paginas de 20 = 60 resultados por consulta
_REINTENTOS: Final = 3


class PlacesError(RuntimeError):
    """Fallo no recuperable al hablar con Places API."""


class GooglePlacesSource:
    """Fuente de leads basada en la API oficial de Google Places (New)."""

    nombre = "google_places"

    def __init__(
        self,
        api_key: str,
        *,
        ledger: CostLedger | None = None,
        client: httpx.AsyncClient | None = None,
        region_code: str = "PE",
        language_code: str = "es",
    ) -> None:
        if not api_key:
            raise ValueError("Falta GOOGLE_PLACES_API_KEY")
        self._api_key = api_key
        self._ledger = ledger or CostLedger()
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._region_code = region_code
        self._language_code = language_code

    @property
    def ledger(self) -> CostLedger:
        return self._ledger

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> GooglePlacesSource:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # -- LeadSource -------------------------------------------------------

    async def buscar(self, consulta: str, zona: str) -> AsyncIterator[RawLead]:
        """Text Search paginado. Rinde hasta 60 negocios por consulta+zona."""
        texto = f"{consulta} en {zona}"
        sku = sku_for_field_mask(FIELD_MASK_BUSQUEDA)
        page_token: str | None = None
        vistos: set[str] = set()

        for pagina in range(_MAX_PAGINAS):
            cuerpo: dict[str, Any] = {
                "textQuery": texto,
                "pageSize": 20,
                "languageCode": self._language_code,
                "regionCode": self._region_code,
            }
            if page_token:
                cuerpo["pageToken"] = page_token

            self._ledger.record(sku)
            datos = await self._post("places:searchText", FIELD_MASK_BUSQUEDA, cuerpo)

            lugares: Sequence[dict[str, Any]] = datos.get("places", [])
            if not lugares:
                logger.debug("'%s' pagina %d: sin resultados", texto, pagina)
                return

            for lugar in lugares:
                lead = _a_raw_lead(lugar)
                # Una misma zona puede repetir negocios entre paginas.
                if lead is None or lead.ref in vistos:
                    continue
                vistos.add(lead.ref)
                yield lead

            page_token = datos.get("nextPageToken")
            if not page_token:
                return

    async def detalle(self, lead: RawLead, *, con_resenas: bool = False) -> LeadDetail:
        """Place Details. Cada llamada consume cuota Enterprise -- usar con criterio."""
        mask = FIELD_MASK_DETALLE_CON_RESENAS if con_resenas else FIELD_MASK_DETALLE
        self._ledger.record(sku_for_field_mask(mask))
        datos = await self._get(f"places/{lead.ref}", mask)
        return _a_lead_detail(datos, fuente=self.nombre)

    # -- Fotos ------------------------------------------------------------

    async def descargar_foto(self, foto: Foto, *, ancho_max: int = 1600) -> bytes:
        """Descarga el binario de una foto del listing.

        Estas son las imagenes que el generador de sitios debe preferir: ya son
        publicas en el propio listing del negocio, a diferencia de imagenes de
        terceros con derechos inciertos (seccion 10 del plan).
        """
        self._ledger.record(Sku.ENTERPRISE)
        url = f"{_BASE_URL}/{foto.ref}/media"
        respuesta = await self._request(
            "GET",
            url,
            params={"maxWidthPx": ancho_max, "key": self._api_key},
            headers={},
        )
        return respuesta.content

    # -- HTTP -------------------------------------------------------------

    async def _post(self, ruta: str, field_mask: str, cuerpo: dict[str, Any]) -> dict[str, Any]:
        respuesta = await self._request(
            "POST", f"{_BASE_URL}/{ruta}", headers=self._headers(field_mask), json=cuerpo
        )
        return respuesta.json()  # type: ignore[no-any-return]

    async def _get(self, ruta: str, field_mask: str) -> dict[str, Any]:
        respuesta = await self._request(
            "GET", f"{_BASE_URL}/{ruta}", headers=self._headers(field_mask)
        )
        return respuesta.json()  # type: ignore[no-any-return]

    def _headers(self, field_mask: str) -> dict[str, str]:
        return {
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": field_mask,
            "Content-Type": "application/json",
        }

    async def _request(self, metodo: str, url: str, **kwargs: Any) -> httpx.Response:
        ultimo_error: Exception | None = None
        for intento in range(_REINTENTOS):
            try:
                respuesta = await self._client.request(metodo, url, **kwargs)
            except httpx.HTTPError as exc:  # red caida, timeout, DNS
                ultimo_error = exc
            else:
                if respuesta.status_code < 400:
                    return respuesta
                # 429 y 5xx son transitorios; 4xx restantes son culpa nuestra
                # (key invalida, mask mal formado) y reintentar solo gasta tiempo.
                if respuesta.status_code != 429 and respuesta.status_code < 500:
                    raise PlacesError(
                        f"{metodo} {url} -> {respuesta.status_code}: {respuesta.text[:500]}"
                    )
                ultimo_error = PlacesError(f"{respuesta.status_code}: {respuesta.text[:200]}")

            espera = 2.0**intento
            logger.warning(
                "Reintento %d/%d en %.0fs: %s", intento + 1, _REINTENTOS, espera, ultimo_error
            )
            await asyncio.sleep(espera)

        raise PlacesError(f"{metodo} {url} fallo tras {_REINTENTOS} intentos: {ultimo_error}")


# -- Mapeo de la respuesta de Google a modelos de dominio -------------------


def _texto(valor: Any) -> str | None:
    """Google envuelve textos localizados en {'text': ..., 'languageCode': ...}."""
    if isinstance(valor, dict):
        texto = valor.get("text")
        return texto if isinstance(texto, str) else None
    return valor if isinstance(valor, str) else None


def _a_raw_lead(lugar: dict[str, Any]) -> RawLead | None:
    ref = lugar.get("id")
    nombre = _texto(lugar.get("displayName"))
    if not ref or not nombre:
        return None
    loc = lugar.get("location") or {}
    return RawLead(
        fuente=GooglePlacesSource.nombre,
        ref=ref,
        nombre=nombre,
        direccion=lugar.get("formattedAddress"),
        lat=loc.get("latitude"),
        lng=loc.get("longitude"),
        tipos=tuple(lugar.get("types") or ()),
    )


def _a_lead_detail(datos: dict[str, Any], *, fuente: str) -> LeadDetail:
    loc = datos.get("location") or {}
    horario = datos.get("regularOpeningHours") or {}

    fotos = tuple(
        Foto(
            ref=f["name"],
            ancho=f.get("widthPx"),
            alto=f.get("heightPx"),
            atribuciones=tuple(
                a.get("displayName", "") for a in (f.get("authorAttributions") or ())
            ),
        )
        for f in (datos.get("photos") or ())
        if f.get("name")
    )

    resenas = tuple(
        Resena(
            autor=_texto((r.get("authorAttribution") or {}).get("displayName")),
            calificacion=r.get("rating"),
            texto=_texto(r.get("text")),
        )
        for r in (datos.get("reviews") or ())
    )

    return LeadDetail(
        fuente=fuente,
        ref=datos["id"],
        nombre=_texto(datos.get("displayName")) or "",
        direccion=datos.get("formattedAddress"),
        lat=loc.get("latitude"),
        lng=loc.get("longitude"),
        tipos=tuple(datos.get("types") or ()),
        telefono=datos.get("nationalPhoneNumber") or datos.get("internationalPhoneNumber"),
        sitio_web=datos.get("websiteUri"),
        rating=datos.get("rating"),
        num_resenas=datos.get("userRatingCount"),
        horario=tuple(horario.get("weekdayDescriptions") or ()),
        estado_negocio=datos.get("businessStatus"),
        fotos=fotos,
        resenas=resenas,
    )
