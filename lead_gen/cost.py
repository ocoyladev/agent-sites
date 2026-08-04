"""Modelo de costo de Places API (New).

Google factura cada request al **SKU mas alto** que toque cualquier campo del
FieldMask. Un solo campo Enterprise de mas convierte una llamada gratuita en una
que consume la cuota mas escasa. Por eso el mapeo campo -> SKU vive aqui, en
codigo verificable, y no en un comentario que se desactualiza.

Referencia: https://developers.google.com/maps/documentation/places/web-service/data-fields

Cuotas gratuitas mensuales (modelo vigente desde marzo 2025, que reemplazo al
credito unico de $200): 10.000 llamadas/mes por SKU Essentials, 5.000 por SKU
Pro, 1.000 por SKU Enterprise. Cada SKU lleva su propio contador.
"""

from __future__ import annotations

from enum import IntEnum

__all__ = ["BudgetExceeded", "CostLedger", "Sku", "sku_for_field_mask"]


class Sku(IntEnum):
    """Niveles de facturacion, ordenados de mas barato a mas caro.

    El orden importa: `max()` sobre los SKU de cada campo da el SKU de la
    llamada completa, que es exactamente como factura Google.
    """

    ESSENTIALS_IDS_ONLY = 0
    ESSENTIALS = 1
    PRO = 2
    ENTERPRISE = 3
    ENTERPRISE_ATMOSPHERE = 4

    @property
    def free_calls_per_month(self) -> int:
        return _FREE_TIER[self]


_FREE_TIER: dict[Sku, int] = {
    Sku.ESSENTIALS_IDS_ONLY: 10_000,
    Sku.ESSENTIALS: 10_000,
    Sku.PRO: 5_000,
    Sku.ENTERPRISE: 1_000,
    Sku.ENTERPRISE_ATMOSPHERE: 1_000,
}

# Campo -> SKU minimo que lo habilita. Un campo ausente de este mapa se trata
# como ENTERPRISE_ATMOSPHERE: ante un campo desconocido preferimos sobrestimar
# el costo y frenar, no descubrirlo en la factura.
_FIELD_SKU: dict[str, Sku] = {
    # --- Essentials (IDs Only) ---
    "id": Sku.ESSENTIALS_IDS_ONLY,
    "name": Sku.ESSENTIALS_IDS_ONLY,
    "photos": Sku.ESSENTIALS_IDS_ONLY,
    "attributions": Sku.ESSENTIALS_IDS_ONLY,
    "nextPageToken": Sku.ESSENTIALS_IDS_ONLY,
    # --- Essentials ---
    "location": Sku.ESSENTIALS,
    "formattedAddress": Sku.ESSENTIALS,
    "shortFormattedAddress": Sku.ESSENTIALS,
    "addressComponents": Sku.ESSENTIALS,
    "addressDescriptor": Sku.ESSENTIALS,
    "adrFormatAddress": Sku.ESSENTIALS,
    "plusCode": Sku.ESSENTIALS,
    "postalAddress": Sku.ESSENTIALS,
    "types": Sku.ESSENTIALS,
    "viewport": Sku.ESSENTIALS,
    # --- Pro ---
    "displayName": Sku.PRO,
    "primaryType": Sku.PRO,
    "primaryTypeDisplayName": Sku.PRO,
    "businessStatus": Sku.PRO,
    "openingDate": Sku.PRO,
    "timeZone": Sku.PRO,
    "utcOffsetMinutes": Sku.PRO,
    "googleMapsUri": Sku.PRO,
    "googleMapsLinks": Sku.PRO,
    "iconBackgroundColor": Sku.PRO,
    "iconMaskBaseUri": Sku.PRO,
    "containingPlaces": Sku.PRO,
    "pureServiceAreaBusiness": Sku.PRO,
    "subDestinations": Sku.PRO,
    # --- Enterprise ---
    "nationalPhoneNumber": Sku.ENTERPRISE,
    "internationalPhoneNumber": Sku.ENTERPRISE,
    "websiteUri": Sku.ENTERPRISE,
    "rating": Sku.ENTERPRISE,
    "userRatingCount": Sku.ENTERPRISE,
    "priceLevel": Sku.ENTERPRISE,
    "priceRange": Sku.ENTERPRISE,
    "regularOpeningHours": Sku.ENTERPRISE,
    "regularSecondaryOpeningHours": Sku.ENTERPRISE,
    "currentOpeningHours": Sku.ENTERPRISE,
    "currentSecondaryOpeningHours": Sku.ENTERPRISE,
    "transitStation": Sku.ENTERPRISE,
    # --- Enterprise + Atmosphere ---
    "reviews": Sku.ENTERPRISE_ATMOSPHERE,
    "reviewSummary": Sku.ENTERPRISE_ATMOSPHERE,
    "editorialSummary": Sku.ENTERPRISE_ATMOSPHERE,
    "generativeSummary": Sku.ENTERPRISE_ATMOSPHERE,
}


def sku_for_field_mask(field_mask: str) -> Sku:
    """Devuelve el SKU al que Google facturaria este FieldMask.

    Acepta tanto la forma de Place Details (`websiteUri`) como la de Text Search
    (`places.websiteUri`), y tolera el comodin `*` tratandolo como el SKU mas
    caro -- que es literalmente lo que pedir todos los campos significa.
    """
    fields = [f.strip() for f in field_mask.split(",") if f.strip()]
    if not fields:
        raise ValueError("El FieldMask no puede estar vacio")

    skus: list[Sku] = []
    for field in fields:
        if field == "*" or field == "places.*":
            return Sku.ENTERPRISE_ATMOSPHERE
        leaf = field.removeprefix("places.").split(".", 1)[0]
        skus.append(_FIELD_SKU.get(leaf, Sku.ENTERPRISE_ATMOSPHERE))
    return max(skus)


class BudgetExceeded(RuntimeError):
    """La corrida alcanzo el tope configurado para un SKU."""


class CostLedger:
    """Cuenta llamadas por SKU y aborta la corrida antes de pasarse del tope.

    El tope es por corrida, no por mes: es una red de seguridad contra un bug
    que dispare miles de requests, no un reemplazo de las alertas de
    presupuesto de Google Cloud (que igual conviene configurar).
    """

    def __init__(self, limits: dict[Sku, int] | None = None) -> None:
        self._limits = limits or {}
        self._calls: dict[Sku, int] = dict.fromkeys(Sku, 0)

    def record(self, sku: Sku, count: int = 1) -> None:
        limit = self._limits.get(sku)
        if limit is not None and self._calls[sku] + count > limit:
            raise BudgetExceeded(
                f"{sku.name}: la corrida alcanzo su tope de {limit} llamadas. "
                f"Subi el tope en .env si es intencional."
            )
        self._calls[sku] += count

    def calls(self, sku: Sku) -> int:
        return self._calls[sku]

    @property
    def total_calls(self) -> int:
        return sum(self._calls.values())

    def summary(self) -> str:
        """Reporte legible para el final de cada corrida."""
        lines = ["Consumo de Places API por SKU:"]
        for sku in Sku:
            used = self._calls[sku]
            if not used:
                continue
            free = sku.free_calls_per_month
            lines.append(f"  {sku.name:<24} {used:>5} llamadas  (cuota gratuita mensual: {free})")
        if self.total_calls == 0:
            lines.append("  (ninguna)")
        return "\n".join(lines)
