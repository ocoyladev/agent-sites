"""Despliegue a Cloudflare Pages.

Sin cuenta, sin token y sin red: se verifica la construccion del comando, el
calculo de la URL y el manejo de fallos. Lo que no se puede verificar aqui --
que Wrangler acepte `--branch` en direct upload -- esta anotado en
docs/setup-cloudflare.md como el paso a confirmar contra una cuenta real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deploy.cloudflare import (
    CloudflarePagesDeployer,
    construir_comando,
    extraer_url,
    url_esperada,
)

SITE_ID = "estudio-juridico-vargas-8bbf11"
PROYECTO = "agencia-demos"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    carpeta = tmp_path / "dist"
    carpeta.mkdir()
    (carpeta / "index.html").write_text("<html><body>hola</body></html>", encoding="utf-8")
    return carpeta


class TestUrl:
    def test_el_alias_de_rama_es_predecible(self) -> None:
        # No hace falta leerla de la salida de Wrangler: se calcula.
        assert url_esperada(SITE_ID, PROYECTO) == f"https://{SITE_ID}.{PROYECTO}.pages.dev"

    def test_el_site_id_ya_cumple_el_formato_de_rama_de_cloudflare(self) -> None:
        # Cloudflare pasa el nombre de rama a minusculas y cambia lo no
        # alfanumerico por guiones. Si `site_id` ya viene asi, el mapeo es 1 a 1
        # y la URL calculada coincide con la real.
        import re

        assert re.fullmatch(r"[a-z0-9-]+", SITE_ID)

    def test_extrae_la_ultima_url_de_la_salida(self) -> None:
        salida = (
            "Uploading... (3/3)\n"
            "Deployment complete! https://a1b2c3.agencia-demos.pages.dev\n"
            "Branch alias: https://estudio-juridico-vargas-8bbf11.agencia-demos.pages.dev\n"
        )

        assert extraer_url(salida) == f"https://{SITE_ID}.{PROYECTO}.pages.dev"

    def test_sin_url_en_la_salida_devuelve_none(self) -> None:
        assert extraer_url("Error: authentication failed") is None


class TestComando:
    def test_incluye_proyecto_y_rama(self, dist: Path) -> None:
        comando = construir_comando(dist, SITE_ID, PROYECTO)

        assert f"--project-name={PROYECTO}" in comando
        # La rama es lo que da un subdominio distinto por sitio dentro de un
        # unico proyecto, que es como se esquiva el tope de 100 proyectos.
        assert f"--branch={SITE_ID}" in comando
        assert str(dist) in comando

    def test_no_pide_confirmacion_interactiva(self, dist: Path) -> None:
        # Una corrida automatica no puede quedarse esperando un enter.
        assert "--commit-dirty=true" in construir_comando(dist, SITE_ID, PROYECTO)


class TestConfiguracion:
    def test_sin_credenciales_no_esta_configurado(self) -> None:
        deployer = CloudflarePagesDeployer(PROYECTO, api_token="", account_id="")

        assert deployer.configurado is False

    def test_con_credenciales_esta_configurado(self) -> None:
        deployer = CloudflarePagesDeployer(PROYECTO, api_token="tok", account_id="acc")

        assert deployer.configurado is True

    async def test_sin_credenciales_falla_diciendo_que_falta(self, dist: Path) -> None:
        deployer = CloudflarePagesDeployer(PROYECTO, api_token="", account_id="")

        resultado = await deployer.desplegar(dist, SITE_ID)

        assert resultado.exito is False
        assert resultado.url is None
        assert "CLOUDFLARE_API_TOKEN" in resultado.salida
        assert "CLOUDFLARE_ACCOUNT_ID" in resultado.salida

    async def test_falta_el_proyecto_tambien_se_reporta(self, dist: Path) -> None:
        deployer = CloudflarePagesDeployer("", api_token="tok", account_id="acc")

        resultado = await deployer.desplegar(dist, SITE_ID)

        assert "CLOUDFLARE_PAGES_PROJECT" in resultado.salida


class TestValidacionPrevia:
    async def test_no_despliega_un_dist_sin_index(self, tmp_path: Path) -> None:
        vacio = tmp_path / "dist"
        vacio.mkdir()
        deployer = CloudflarePagesDeployer(PROYECTO, api_token="tok", account_id="acc")

        resultado = await deployer.desplegar(vacio, SITE_ID)

        assert resultado.exito is False
        assert "index.html" in resultado.salida

    async def test_no_despliega_un_directorio_inexistente(self, tmp_path: Path) -> None:
        deployer = CloudflarePagesDeployer(PROYECTO, api_token="tok", account_id="acc")

        resultado = await deployer.desplegar(tmp_path / "no-existe", SITE_ID)

        assert resultado.exito is False
