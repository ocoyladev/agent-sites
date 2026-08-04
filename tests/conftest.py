"""Fixtures compartidas.

Las respuestas de Google se simulan con respx, asi que la suite corre sin API
key, sin red y sin gastar cuota.
"""

from __future__ import annotations

from typing import Any

import pytest

from lead_gen.models import LeadDetail
from lead_gen.nichos import Nicho


@pytest.fixture
def nicho_abogados() -> Nicho:
    return Nicho(
        nombre="abogados",
        etiqueta="Abogados",
        demanda_base=0.60,
        ticket_base=0.85,
        consultas=("abogado", "estudio juridico"),
        zonas=("Cercado, Arequipa", "Yanahuara, Arequipa"),
        tipos_esperados=frozenset({"lawyer", "legal_services"}),
        tipos_excluidos=frozenset({"courthouse", "local_government_office"}),
        umbral_calificacion=55.0,
    )


@pytest.fixture
def lead_base() -> LeadDetail:
    """Abogado contactable, sin sitio web: el perfil que mejor califica."""
    return LeadDetail(
        fuente="google_places",
        ref="ChIJtest",
        nombre="Estudio Juridico Vargas & Asociados",
        direccion="Calle Mercaderes 123, Arequipa",
        tipos=("lawyer", "point_of_interest"),
        telefono="054 123456",
        rating=4.5,
        num_resenas=20,
        estado_negocio="OPERATIONAL",
    )


@pytest.fixture
def respuesta_text_search() -> dict[str, Any]:
    return {
        "places": [
            {
                "id": "ChIJaaa",
                "displayName": {"text": "Estudio Juridico Vargas", "languageCode": "es"},
                "formattedAddress": "Calle Mercaderes 123, Arequipa",
                "location": {"latitude": -16.398, "longitude": -71.537},
                "types": ["lawyer", "point_of_interest"],
            },
            {
                "id": "ChIJbbb",
                "displayName": {"text": "Corte Superior de Justicia", "languageCode": "es"},
                "formattedAddress": "Plaza España s/n, Arequipa",
                "location": {"latitude": -16.395, "longitude": -71.535},
                "types": ["courthouse", "local_government_office"],
            },
        ]
    }


@pytest.fixture
def respuesta_place_details() -> dict[str, Any]:
    return {
        "id": "ChIJaaa",
        "displayName": {"text": "Estudio Juridico Vargas", "languageCode": "es"},
        "formattedAddress": "Calle Mercaderes 123, Arequipa",
        "location": {"latitude": -16.398, "longitude": -71.537},
        "types": ["lawyer", "point_of_interest"],
        "businessStatus": "OPERATIONAL",
        "nationalPhoneNumber": "054 123456",
        "internationalPhoneNumber": "+51 54 123456",
        "rating": 4.5,
        "userRatingCount": 23,
        "regularOpeningHours": {"weekdayDescriptions": ["lunes: 9:00-18:00", "martes: 9:00-18:00"]},
        "photos": [
            {
                "name": "places/ChIJaaa/photos/AXQ_foto1",
                "widthPx": 3024,
                "heightPx": 4032,
                "authorAttributions": [{"displayName": "Juan Perez"}],
            }
        ],
    }
