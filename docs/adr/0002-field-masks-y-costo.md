# ADR 0002 — El FieldMask es una decision de arquitectura, no de estilo

**Fecha:** 2026-08-04
**Estado:** aceptado

## Contexto

La seccion 3.1 del plan estimaba $15-40/mes para Places API y confiaba en el
"credito mensual de $200 combinado" de Google Maps Platform.

**Ese credito ya no existe.** Google lo retiro en marzo de 2025 y lo reemplazo
por una cuota gratuita **por SKU**:

| Nivel | Llamadas gratis por SKU al mes |
|---|---|
| Essentials | 10.000 |
| Pro | 5.000 |
| Enterprise | 1.000 |

Y el detalle que cambia el diseno: **Google factura cada request al SKU mas alto
que toque cualquier campo del FieldMask.** Un solo campo de mas convierte una
llamada Pro (5.000 gratis) en una Enterprise (1.000 gratis).

Los campos que el pipeline necesita si o si —`nationalPhoneNumber`,
`websiteUri`, `rating`, `userRatingCount`, `regularOpeningHours`— son **todos
Enterprise**. No Pro, como se supuso al principio.

## Decision

1. **Dos FieldMask fijos y separados**, en `lead_gen/sources/google_places.py`:
   - `FIELD_MASK_BUSQUEDA` — descubrimiento, tope Pro.
   - `FIELD_MASK_DETALLE` — detalle, Enterprise, sin `reviews`.
   - `FIELD_MASK_DETALLE_CON_RESENAS` — solo cuando se piden resenas de verdad.

2. **El mapeo campo -> SKU vive en codigo probado** (`lead_gen/cost.py`), no en
   un comentario. Un campo desconocido se asume del SKU mas caro: preferimos
   sobrestimar y frenar antes que enterarnos en la factura.

3. **Tests que fallan si alguien encarece una mascara.**
   `test_detalle_es_enterprise_pero_no_atmosphere` existe para que agregar
   `reviews` al detalle normal —que duplicaria el consumo del SKU mas escaso—
   rompa la suite en vez de pasar desapercibido.

4. **`CostLedger` con topes por corrida**, configurables en `.env`. Aborta con
   `BudgetExceeded` antes de excederse. Es una red contra un bug que dispare
   miles de requests, no un reemplazo de las alertas de presupuesto de Google.

5. **Filtrar por tipo antes de pedir detalle.** `Nicho.es_del_nicho()` corre
   sobre los datos baratos del descubrimiento. Cada municipalidad o notaria que
   se descarta ahi es una llamada Enterprise que no se gasta.

## Consecuencias

- Costo esperado a 300 leads/mes: **$0**. El limite real es ~1.000 leads
  detallados al mes, marcado por Enterprise, no por dinero.
- Pedir resenas o fotos es una decision explicita por lead, no algo que pase por
  descuido.
- El mapeo campo -> SKU hay que revisarlo si Google cambia su tabla de niveles.
  Fuente: <https://developers.google.com/maps/documentation/places/web-service/data-fields>
- `businessStatus` es un campo Pro incluido en la mascara de detalle: como la
  llamada ya factura Enterprise por otros campos, sale gratis y evita trabajar
  sobre negocios cerrados.
