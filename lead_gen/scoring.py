"""Scoring de calificacion de leads (seccion 3.3 del plan).

Score compuesto 0-100, no filtro binario, con el desglose expuesto para poder
calibrarlo con datos reales en vez de a ojo.

La ponderacion refleja la propuesta de valor: el mejor lead no es el negocio mas
grande, es el que mas obviamente le falta un sitio web. Por eso `brecha_digital`
pesa la mitad del score.
"""

from __future__ import annotations

from lead_gen.models import LeadDetail, LeadScore
from lead_gen.nichos import Nicho

__all__ = ["PESO_BRECHA", "PESO_DEMANDA", "PESO_TICKET", "calcular_score"]

PESO_DEMANDA = 0.30
PESO_TICKET = 0.20
PESO_BRECHA = 0.50

# Cantidad de resenas a partir de la cual consideramos el negocio "consolidado".
# Por encima de esto el score de demanda satura: un abogado con 200 resenas no
# es cuatro veces mejor lead que uno con 50, y probablemente ya tiene agencia.
RESENAS_SATURACION = 40


def _score_demanda(lead: LeadDetail, nicho: Nicho) -> float:
    """Proxy de volumen de consultas: resenas acumuladas + demanda del nicho.

    Las resenas son la mejor senal publica de que al negocio efectivamente le
    llega gente; sin ellas no sabemos si existe comercialmente.
    """
    resenas = lead.num_resenas or 0
    volumen = min(resenas / RESENAS_SATURACION, 1.0)
    # El nicho pone el piso y las resenas mueven el resto.
    return 100.0 * (nicho.demanda_base * 0.5 + volumen * 0.5)


def _score_ticket(nicho: Nicho) -> float:
    """El ticket medio es una propiedad del nicho, no del negocio individual."""
    return 100.0 * nicho.ticket_base


def _score_brecha(lead: LeadDetail, calidad_sitio: float | None) -> float:
    """Cuanto margen hay para mejorar su presencia digital.

    Sin sitio web = brecha maxima = mejor lead. Con sitio, la brecha es el
    complemento de su calidad: un sitio malo sigue siendo una venta, uno bueno
    no lo es.
    """
    if not lead.tiene_sitio_web:
        return 100.0
    if calidad_sitio is None:
        # Tiene sitio declarado pero no pudimos evaluarlo (caido, timeout,
        # bloqueo). Un sitio que no responde es casi tan vendible como no tener
        # ninguno, pero no lo damos por hecho.
        return 75.0
    return max(0.0, 100.0 - calidad_sitio)


def calcular_score(
    lead: LeadDetail,
    nicho: Nicho,
    *,
    calidad_sitio: float | None = None,
) -> LeadScore:
    """Calcula el score compuesto y aplica los filtros duros.

    `calidad_sitio` viene de `site_quality_check.evaluar_sitio()`; es `None`
    cuando el lead no tiene sitio o cuando no se pudo evaluar.
    """
    demanda = _score_demanda(lead, nicho)
    ticket = _score_ticket(nicho)
    brecha = _score_brecha(lead, calidad_sitio)

    total = demanda * PESO_DEMANDA + ticket * PESO_TICKET + brecha * PESO_BRECHA

    # Filtros duros: descalifican sin importar el total.
    descarte: str | None = None
    if not lead.es_contactable:
        descarte = "sin_telefono"
    elif not lead.esta_operativo:
        descarte = f"negocio_{(lead.estado_negocio or '').lower()}"
    elif not nicho.es_del_nicho(lead.tipos):
        descarte = "fuera_de_nicho"
    elif total < nicho.umbral_calificacion:
        descarte = "bajo_umbral"

    return LeadScore(
        total=round(total, 2),
        demanda=round(demanda, 2),
        ticket=round(ticket, 2),
        brecha_digital=round(brecha, 2),
        contactable=lead.es_contactable,
        descartado_por=descarte,
    )
