"""Carga de configuracion por nicho."""

from __future__ import annotations

import pytest

from lead_gen.nichos import cargar_nicho, nichos_disponibles


class TestCarga:
    def test_abogados_existe_y_esta_completo(self) -> None:
        nicho = cargar_nicho("abogados")
        assert nicho.nombre == "abogados"
        assert nicho.consultas
        assert nicho.zonas
        assert 0.0 <= nicho.demanda_base <= 1.0
        assert 0.0 <= nicho.ticket_base <= 1.0

    def test_aparece_en_los_disponibles(self) -> None:
        assert "abogados" in nichos_disponibles()

    def test_nicho_inexistente_dice_cuales_hay(self) -> None:
        with pytest.raises(FileNotFoundError, match="abogados"):
            cargar_nicho("veterinarias")

    def test_dimensiona_el_barrido_antes_de_lanzarlo(self) -> None:
        nicho = cargar_nicho("abogados")
        assert nicho.llamadas_de_descubrimiento == len(nicho.consultas) * len(nicho.zonas)


class TestFiltroDeTipos:
    def test_acepta_tipo_esperado(self) -> None:
        assert cargar_nicho("abogados").es_del_nicho(("lawyer", "point_of_interest"))

    def test_rechaza_tipo_ajeno(self) -> None:
        assert not cargar_nicho("abogados").es_del_nicho(("restaurant",))

    def test_excluido_gana_sobre_esperado(self) -> None:
        assert not cargar_nicho("abogados").es_del_nicho(("lawyer", "courthouse"))

    def test_sin_tipos_no_pasa(self) -> None:
        assert not cargar_nicho("abogados").es_del_nicho(())
