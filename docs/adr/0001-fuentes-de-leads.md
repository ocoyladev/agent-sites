# ADR 0001 — Fuentes de leads detras de una interfaz

**Fecha:** 2026-08-04
**Estado:** aceptado

## Contexto

El plan (seccion 3.1) elige Google Places API como fuente primaria y descarta
Apify. Al arrancar surgio la pregunta de si se podia evitar depender de Google:
una API key exige cuenta de Google Cloud con tarjeta, que es friccion real
aunque el gasto esperado sea cero.

Las alternativas evaluadas:

| Opcion | Costo | Esfuerzo | Fragilidad | Terminos |
|---|---|---|---|---|
| Places API (New) | ~$0 al volumen actual | bajo | nula | limpio |
| Scraping propio de Maps | $0 + proxies si bloquean | alto | alta | los viola |
| API de terceros (Serper, Outscraper) | ~$5-30/mes | bajo | baja | problema del proveedor |
| Fuentes no-Google (ICAA, directorios) | $0 | medio | baja | limpio |

Dos hechos especificos del nicho pesaron en la decision:

1. **Los abogados estan sub-representados en Google Maps.** Muchos ejercen de
   forma individual, desde casa o una oficina compartida, y no figuran como
   negocio. Una estrategia solo-Maps barre la parte superficial del mercado.
2. **El registro del Ilustre Colegio de Abogados de Arequipa los tiene a todos**,
   es publico y mucho menos hostil a la automatizacion que Maps. Pero esta sin
   verificar si expone telefonos, y la contactabilidad es un filtro duro
   (seccion 3.3). Google es fuerte justo donde el registro probablemente es debil.

## Decision

No elegir una sola fuente. Definir el protocolo `LeadSource`
(`lead_gen/source.py`) con dos metodos —`buscar()` y `detalle()`— e implementar
proveedores detras de el.

**Google Places es el primer proveedor implementado**, por decision del dueno del
proyecto.

La division en dos metodos no es estetica: en Google el descubrimiento es barato
(SKU Pro, 5.000 gratis/mes) y el detalle es caro (SKU Enterprise, 1.000
gratis/mes). El pipeline descubre en masa, filtra por tipo, y solo entonces paga
el detalle.

## Consecuencias

- Agregar el registro del ICAA, un directorio o un scraper es una clase nueva,
  no una reescritura del pipeline.
- La tabla `leads` usa `(fuente, ref)` en vez del `google_place_id` del plan
  original, con restriccion de unicidad. Varias fuentes conviven sin migracion.
- Falta una capa de deduplicacion cruzada entre fuentes (mismo estudio juridico
  encontrado en Google y en el ICAA). No hace falta con un solo proveedor; se
  resuelve cuando entre el segundo, probablemente por nombre normalizado +
  telefono.
- El scraping directo de Maps queda como opcion B documentada, no descartada.
