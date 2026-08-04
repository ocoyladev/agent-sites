# Crear la API key de Google Places

Pasos exactos para habilitar Places API (New) y dejar la key restringida. Toma
unos 10 minutos. Requiere una tarjeta de credito en el proyecto de Google Cloud,
aunque a nuestro volumen el gasto esperado es **$0** (ver seccion "Costo real").

## 1. Proyecto y facturacion

1. Entra a <https://console.cloud.google.com/>.
2. Crea un proyecto nuevo, por ejemplo `agencia-web-ia`.
3. Menu -> **Billing** -> vincula una cuenta de facturacion al proyecto.
   Sin esto las llamadas devuelven `REQUEST_DENIED`, incluso dentro de la cuota
   gratuita.

## 2. Habilitar la API correcta

Menu -> **APIs & Services** -> **Library** -> busca **"Places API (New)"**.

> Cuidado: existen dos entradas parecidas. La vieja se llama solo "Places API".
> Necesitamos la que dice **(New)** — el cliente usa los endpoints
> `places.googleapis.com/v1/*`, que la vieja no expone.

Presiona **Enable**.

## 3. Crear y restringir la key

1. **APIs & Services** -> **Credentials** -> **Create credentials** -> **API key**.
2. Copia la key y presiona **Edit API key**.
3. **API restrictions** -> *Restrict key* -> marca solo **Places API (New)**.
   Una key sin restringir que se filtre puede consumir todos los SKU del proyecto.
4. **Application restrictions** -> *IP addresses* -> agrega la IP publica de
   ia-node. Para averiguarla: `curl -s ifconfig.me`.

   Si la IP es dinamica, deja esta parte en *None* pero manten la restriccion
   de API del paso 3.

## 4. Alerta de presupuesto (no opcional)

**Billing** -> **Budgets & alerts** -> **Create budget**:

- Alcance: el proyecto `agencia-web-ia`.
- Monto: **$10/mes**. No es lo que esperamos gastar — es el monto que, si se
  alcanza, significa que algo esta mal.
- Alertas por correo al 50%, 90% y 100%.

El `CostLedger` del codigo frena una corrida antes de pasarse de los topes de
`.env`, pero solo conoce lo que gasta esa corrida. La alerta de Google es la que
ve el mes completo.

## 5. Cargar la key

```bash
cp .env.example .env      # si aun no existe
# editar .env y poner la key en GOOGLE_PLACES_API_KEY=
```

## 6. Probar sin gastar casi nada

```bash
# 1. Ver el plan de la corrida, sin llamar a la API
uv run python -m scripts.run_extraction --dry-run

# 2. Corrida minima real: 1 zona, 1 consulta, tope de 5 leads detallados
uv run python -m scripts.run_extraction --zonas 1 --consultas 1 --limite 5 --sin-db
```

La segunda consume aproximadamente 1-3 llamadas Text Search Pro y hasta 5 de
Place Details Enterprise. Al final imprime el consumo por SKU.

Revisa los datos antes de automatizar nada: nombres, telefonos y si el filtro de
tipos esta dejando pasar ruido (municipalidades, notarias, academias). Ajustar
`tipos_excluidos` en `nichos/abogados.toml` sale gratis; descubrirlo despues de
300 llamadas Enterprise, no.

## Costo real

Google retiro el credito unico de $200/mes en marzo de 2025. El modelo actual da
una **cuota gratuita por SKU**:

| SKU | Gratis/mes | Que usa nuestro pipeline |
|---|---|---|
| Text Search Pro | 5.000 | descubrimiento (`buscar`) |
| Place Details Enterprise | 1.000 | telefono, sitio, rating (`detalle`) |
| Place Details Enterprise + Atmosphere | 1.000 | resenas (`detalle(con_resenas=True)`) |
| Place Details Photos | 1.000 | fotos del listing |

A 300 leads/mes el pipeline queda holgadamente dentro de todas. **El cuello de
botella es Enterprise: ~1.000 leads detallados al mes** antes de empezar a pagar.

Si algun dia hay que pasarse, el precio esta en la lista oficial de SKU:
<https://developers.google.com/maps/billing-and-pricing/pricing>
