"""Harness de verificacion automatica (seccion 5.1 del plan).

Lo que separa "un sitio bien hecho" de "cientos de sitios consistentemente bien
hechos". Corre sobre el HTML ya construido, no sobre la spec, porque lo que le
llega al cliente es el HTML.

El check que importa es `_fact_check`: cada telefono, nombre y resena del sitio
tiene que coincidir con la spec. Un sitio que inventa el numero de telefono del
negocio es peor que no tener sitio, y es el unico error que el prospecto ve
antes de que lo veamos nosotros.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from selectolax.parser import HTMLParser

from site_generator.spec import SiteSpec

__all__ = ["ReporteQA", "revisar_html", "revisar_sitio"]

# Restos de plantilla que nunca deben llegar al HTML final.
#
# La distincion de mayusculas no es un detalle: 'TODO' es un marcador de codigo,
# pero 'todo' es una palabra comunisima en espanol -- "Todos los derechos
# reservados" del pie disparaba un falso positivo y rechazaba sitios correctos.
_MARCADORES_DE_CODIGO = re.compile(
    r"\{\{|\}\}|\bTODO\b|\bFIXME\b|\bundefined\b|\[object Object\]|\bNaN\b"
)
_TEXTO_DE_RELLENO = re.compile(r"lorem ipsum", re.I)

# Secuencias que parecen un telefono: digito, separadores, digito (minimo 7).
_POSIBLE_TELEFONO = re.compile(r"\d[\d\s().-]{5,}\d")

# Ciudades peruanas principales. Si el sitio nombra una que no es la del negocio,
# el modelo se invento la ubicacion. Paso de verdad: con `Zona: Cercado` (que
# existe en Lima y en Arequipa) escribio "en el Cercado de Lima" para un estudio
# arequipeno. Publicar la ciudad equivocada destruye la credibilidad del sitio
# ante el unico lector que importa: el dueno del negocio.
_CIUDADES_PERU = (
    "Lima",
    "Callao",
    "Arequipa",
    "Trujillo",
    "Chiclayo",
    "Piura",
    "Iquitos",
    "Cusco",
    "Cuzco",
    "Huancayo",
    "Tacna",
    "Juliaca",
    "Ica",
    "Chimbote",
    "Pucallpa",
    "Sullana",
    "Ayacucho",
    "Cajamarca",
    "Puno",
    "Tarapoto",
    "Huaraz",
    "Moquegua",
    "Tumbes",
    "Huanuco",
    "Pisco",
    "Chincha",
    "Jaen",
)


@dataclass(slots=True)
class ReporteQA:
    site_id: str
    checks: dict[str, bool] = field(default_factory=dict)
    errores: list[str] = field(default_factory=list)

    @property
    def aprobado(self) -> bool:
        return not self.errores and all(self.checks.values())

    def resumen(self) -> str:
        estado = "APROBADO" if self.aprobado else "RECHAZADO"
        lineas = [f"[{estado}] {self.site_id}"]
        for nombre, ok in self.checks.items():
            lineas.append(f"  {'ok ' if ok else 'FALLA'} {nombre}")
        lineas.extend(f"  -> {e}" for e in self.errores)
        return "\n".join(lineas)


def _solo_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def _sin_tildes(texto: str) -> str:
    """Normaliza para comparar: 'Huánuco' y 'Huanuco' son la misma ciudad."""
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def _fact_check(arbol: HTMLParser, spec: SiteSpec, reporte: ReporteQA) -> None:
    """Verifica que el sitio no contenga datos que la spec no respalda."""
    hechos = spec.hechos
    contacto = hechos.contacto
    texto = arbol.body.text(separator=" ", strip=True) if arbol.body else ""

    # -- El nombre del negocio aparece tal cual --
    reporte.checks["nombre_presente"] = hechos.nombre in texto
    if not reporte.checks["nombre_presente"]:
        reporte.errores.append(f"El nombre '{hechos.nombre}' no aparece en el sitio")

    # -- Todos los enlaces tel: apuntan al telefono real --
    hrefs = [
        (nodo.attributes.get("href") or "")
        for nodo in arbol.css("a[href]")
        if nodo.attributes.get("href")
    ]
    telefonos_href = [h for h in hrefs if h.startswith("tel:")]
    esperado = _solo_digitos(contacto.telefono_href)
    ajenos = [h for h in telefonos_href if _solo_digitos(h) != esperado]
    reporte.checks["telefono_correcto"] = not ajenos
    if ajenos:
        reporte.errores.append(f"Enlaces tel: que no son del negocio: {ajenos[:3]}")

    # -- Los enlaces de WhatsApp coinciden con el de la spec --
    wa = [h for h in hrefs if "wa.me" in h or "api.whatsapp.com" in h]
    if contacto.whatsapp_url:
        wa_esperado = _solo_digitos(contacto.whatsapp_url.split("?")[0])
        malos = [h for h in wa if _solo_digitos(h.split("?")[0]) != wa_esperado]
        reporte.checks["whatsapp_correcto"] = not malos
        if malos:
            reporte.errores.append(f"Enlaces de WhatsApp incorrectos: {malos[:3]}")
    else:
        # Sin movil no deberia haber ningun enlace de WhatsApp inventado.
        reporte.checks["whatsapp_correcto"] = not wa
        if wa:
            reporte.errores.append("Hay enlaces de WhatsApp pero el negocio no tiene movil")

    # -- Ningun otro numero del texto parece un telefono --
    permitidos = {esperado, _solo_digitos(contacto.telefono)}
    if contacto.whatsapp_url:
        permitidos.add(_solo_digitos(contacto.whatsapp_url.split("?")[0]))
    sospechosos = [
        m.group().strip()
        for m in _POSIBLE_TELEFONO.finditer(texto)
        if _solo_digitos(m.group()) not in permitidos and len(_solo_digitos(m.group())) >= 6
    ]
    reporte.checks["sin_telefonos_ajenos"] = not sospechosos
    if sospechosos:
        reporte.errores.append(f"Numeros que parecen telefonos ajenos: {sospechosos[:3]}")

    # -- El sitio no nombra una ciudad que no es la del negocio --
    zona_normalizada = _sin_tildes(hechos.zona)
    texto_normalizado = _sin_tildes(texto)
    ajenas = [
        ciudad
        for ciudad in _CIUDADES_PERU
        if _sin_tildes(ciudad) not in zona_normalizada
        and re.search(rf"\b{re.escape(_sin_tildes(ciudad))}\b", texto_normalizado, re.I)
    ]
    reporte.checks["ciudad_correcta"] = not ajenas
    if ajenas:
        reporte.errores.append(
            f"El sitio menciona {ajenas} pero el negocio esta en '{hechos.zona}'"
        )

    # -- Las resenas no fueron reescritas --
    if hechos.resenas:
        originales = {r.texto.strip() for r in hechos.resenas}
        citas = [nodo.text(strip=True) for nodo in arbol.css("blockquote") if nodo.text(strip=True)]
        alteradas = [c for c in citas if c not in originales]
        reporte.checks["resenas_intactas"] = not alteradas
        if alteradas:
            reporte.errores.append(f"Resenas que no coinciden con Google: {alteradas[:1]}")


def revisar_html(html: str, spec: SiteSpec) -> ReporteQA:
    """Aplica todos los checks del harness sobre el HTML final."""
    reporte = ReporteQA(site_id=spec.site_id)
    arbol = HTMLParser(html)
    texto = arbol.body.text(separator=" ", strip=True) if arbol.body else ""

    # -- Estructura basica --
    titulo = arbol.css_first("title")
    reporte.checks["tiene_titulo"] = bool(titulo and len(titulo.text(strip=True)) >= 10)

    reporte.checks["tiene_h1"] = len(arbol.css("h1")) == 1
    if len(arbol.css("h1")) != 1:
        reporte.errores.append(f"Se esperaba exactamente un h1, hay {len(arbol.css('h1'))}")

    reporte.checks["responsive"] = any(
        (nodo.attributes.get("name") or "").lower() == "viewport" for nodo in arbol.css("meta")
    )

    reporte.checks["tiene_contenido"] = len(texto) >= 600
    if len(texto) < 600:
        reporte.errores.append(f"El sitio tiene solo {len(texto)} caracteres de texto")

    # -- Hay una via de contacto clickeable --
    hrefs = [n.attributes.get("href") or "" for n in arbol.css("a[href]")]
    reporte.checks["tiene_cta"] = any(
        h.startswith("tel:") or "wa.me" in h or h.startswith("mailto:") for h in hrefs
    )
    if not reporte.checks["tiene_cta"]:
        reporte.errores.append("No hay ningun enlace de contacto (tel:, wa.me o mailto:)")

    # -- Sin enlaces rotos a ninguna parte --
    vacios = [h for h in hrefs if h in ("", "#", "javascript:void(0)")]
    reporte.checks["sin_enlaces_vacios"] = not vacios
    if vacios:
        reporte.errores.append(f"Hay {len(vacios)} enlaces sin destino")

    # -- Sin restos de plantilla --
    resto = _MARCADORES_DE_CODIGO.search(texto) or _TEXTO_DE_RELLENO.search(texto)
    reporte.checks["sin_placeholders"] = resto is None
    if resto:
        reporte.errores.append(f"Quedo un placeholder sin reemplazar: '{resto.group()}'")

    # -- Las imagenes reservan espacio (evita saltos de layout) --
    imgs = arbol.css("img")
    sin_medidas = [
        i for i in imgs if not (i.attributes.get("width") and i.attributes.get("height"))
    ]
    reporte.checks["imagenes_dimensionadas"] = not sin_medidas
    if sin_medidas:
        reporte.errores.append(f"{len(sin_medidas)} imagenes sin width/height")

    # -- Cero JavaScript: es la razon de usar Astro para estos sitios --
    scripts = [
        s
        for s in arbol.css("script")
        if (s.attributes.get("type") or "").lower() != "application/ld+json"
    ]
    reporte.checks["sin_javascript"] = not scripts
    if scripts:
        reporte.errores.append(f"El sitio carga {len(scripts)} scripts; deberia ser estatico puro")

    _fact_check(arbol, spec, reporte)
    return reporte


def revisar_sitio(dist: Path, spec: SiteSpec) -> ReporteQA:
    """Revisa el `index.html` construido."""
    index = dist / "index.html"
    if not index.is_file():
        reporte = ReporteQA(site_id=spec.site_id)
        reporte.checks["build_genero_html"] = False
        reporte.errores.append(f"No existe {index}")
        return reporte

    reporte = revisar_html(index.read_text(encoding="utf-8"), spec)
    reporte.checks["build_genero_html"] = True
    return reporte
