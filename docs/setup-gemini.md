# Configurar Gemini para el copywriting

Reemplaza al modelo local en el paso de redaccion. Toma 2 minutos y no pide
tarjeta.

## Por que

En ia-node (8 nucleos, sin GPU) gemma4:26b rinde ~2,9 tokens/s: unos 3 minutos
de CPU por sitio, o sea **~15 horas de computo al mes** a 300 sitios. Y aun asi
solo 2 de 3 piezas salen del modelo; la tercera cae a plantilla.

Gemini responde en segundos y, sobre todo, acepta `responseSchema`: obliga la
forma del JSON del lado del servidor. El modo de falla que rompia la generacion
local -- el modelo degenerando en un bucle a mitad del JSON -- deja de ser
posible.

## 1. Crear la key

1. Entra a <https://aistudio.google.com/apikey>.
2. **Create API key**. Podes usar el mismo proyecto de Google Cloud que creaste
   para Places, o uno nuevo.
3. Copiala.

> **No es la misma key que la de Places.** Ambas son de Google, pero son
> servicios distintos con cuotas distintas. `GOOGLE_PLACES_API_KEY` y
> `GEMINI_API_KEY` son dos valores separados en `.env`.

## 2. Cargar en `.env`

```bash
LLM_PROVEEDOR=auto
GEMINI_API_KEY=<tu key>
GEMINI_MODELO=gemini-2.5-flash
```

Con `auto`, el sistema usa Gemini si hay key y cae a Ollama local si no. Para
forzar uno u otro: `LLM_PROVEEDOR=gemini` o `LLM_PROVEEDOR=ollama`.
`LLM_PROVEEDOR=ninguno` desactiva la IA y usa solo plantillas.

## 3. Probar

```bash
uv run python -m scripts.generar_sitio --demo
```

Deberia imprimir `Contenido generado por: gemini` y terminar en segundos, no en
minutos. Si dice `mixto` o `plantilla`, alguna pieza fallo -- el detalle queda
en los warnings.

## Cuotas del free tier

Cambian seguido y dependen del modelo, la region y la antiguedad de la cuenta.
Los ordenes de magnitud al momento de escribir esto: **1.500 peticiones por dia**
y 10-30 peticiones por minuto segun modelo.

Nuestro consumo es de **3 peticiones por sitio** (cabecera, sobre nosotros,
servicios). A 300 sitios al mes son ~900 peticiones mensuales: muy por debajo de
1.500 diarias. El limite por minuto si puede molestar en un batch grande; si
aparecen errores 429, el generador los reporta como
*"se agoto la cuota del free tier por ahora"* y cae a plantilla en esa pieza.

La cuota real de tu proyecto se ve en AI Studio.

## Modelos

`gemini-2.5-flash` es el default por estar confirmado en el free tier y ser
suficiente para redaccion corta en espanol. Existen modelos Flash mas nuevos; se
cambian con `GEMINI_MODELO` sin tocar codigo. Si pones uno que no existe, la API
devuelve 404 y el error sale en el warning de la pieza.
