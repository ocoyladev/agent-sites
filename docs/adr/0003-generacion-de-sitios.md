# ADR 0003 — Astro, y la IA no escribe hechos

**Fecha:** 2026-08-04
**Estado:** aceptado

## Contexto

La Fase 3 genera cientos de sitios con IA. Dos preguntas abiertas: con que stack,
y como evitar que un modelo publique datos falsos del negocio.

## Decision 1 — Astro para todo el proyecto

Astro para los sitios generados, y tambien para el dashboard de la Fase 6
(el plan decia React/Next.js). Un solo stack, por decision del dueno del proyecto.

Para los sitios el caso es claro: se abren desde un link de WhatsApp, en un
celular, con datos moviles. Astro emite **cero JavaScript** por defecto. El sitio
demo generado pesa **16 KB en un unico HTML**, sin un solo `.js`. Next.js con
export estatico arrastra un runtime de hidratacion que estos sitios no usan.

Para el dashboard, Astro con SSR e islas alcanza: tabla de leads, graficos de
Umami y export a Excel no exigen interactividad de cliente pesada. Donde Astro es
peor que Next.js es en filtrado en vivo sin recarga; si la Fase 6 termina
pidiendolo, se resuelve con una isla, no cambiando de framework.

## Decision 2 — La IA solo escribe prosa

La spec (`site_generator/spec.py`) se parte en dos:

- **`Hechos`** — nombre, telefono, direccion, horario, resenas, fotos, rating.
  Salen de `LeadDetail` de forma determinista. Ningun modelo los toca.
- **`Contenido`** — titular, subtitulo, servicios, sobre nosotros, CTA. Es lo
  unico que genera la IA.

Sobre esa separacion se apoyan tres defensas, en orden:

1. **El prompt nunca recibe datos de contacto.** Si el modelo no ve el telefono,
   no puede ubicarlo mal.
2. **Validacion de esquema** con pydantic y reintentos.
3. **Rechazo por patron**: cualquier texto generado con algo que parezca
   telefono, URL o correo se descarta, aunque el modelo lo haya inventado solo.

Y despues del build, el harness (`site_generator/qa.py`) verifica el **HTML
final** contra la spec: todo `tel:` tiene que ser el telefono real, los enlaces
de WhatsApp tienen que coincidir, las resenas tienen que estar textuales, y
ningun numero suelto del texto puede parecer un telefono ajeno.

Asi "la IA no invento datos del negocio" (seccion 5.1 del plan) deja de ser una
esperanza y pasa a ser un check que falla el build.

## Decision 3 — Respaldo deterministico

Si la IA falla o se agotan los reintentos, `contenido_de_plantilla()` arma copy
sobrio a partir de los hechos y el catalogo de servicios del nicho. El origen se
registra para poder regenerar despues esos sitios.

No es un mock de tests: es resiliencia. Un Ollama caido a mitad de un batch no
puede dejar sitios sin generar, y un sitio sobrio siempre es mejor que ninguno.

## Decision 4 — Tres pedidos cortos, no uno largo

Un solo JSON con todo el sitio **no funciona** con el modelo local. Medido:
gemma4:26b degeneraba en un bucle de la misma silaba (`_und_und_und...`) a los
~96 caracteres, quemaba los 3.000 tokens del limite (`done_reason: length`) y no
producia nada usable. Subir el limite solo compra un bucle mas largo.

El contenido se pide en tres llamadas cortas -- cabecera, sobre nosotros,
servicios -- del tamano de las que si completaban. Cada una se valida y se
reintenta por separado, y si una no sale se usa su version de plantilla. `origen`
queda en `ollama`, `mixto` o `plantilla` segun cuantas piezas salieron.

## Consecuencias medidas

- **Rendimiento local**: gemma4:26b en ia-node (8 nucleos, sin GPU) da ~2,9
  tokens/s. Con el pedido unico, 14m39s para terminar en plantilla. Con pedidos
  cortos, 2 de 3 piezas salieron del modelo.
- **`repeat_penalty` es obligatorio pero no suficiente.** Evita el bucle en
  generaciones cortas; en las largas el modelo igual degenera, esta vez rellenando
  con espacios. Por eso la solucion real fue acortar los pedidos.
- **A volumen conviene un proveedor en la nube.** ~3 min de CPU por sitio son
  ~15 horas de computo al mes a 300 sitios. Gemini free tier (seccion 5.2 del
  plan) entra detras del mismo `LLMClient` sin reescribir nada.
- El catalogo de servicios vive en `nichos/*.toml`: la IA elige de esa lista y
  no puede inventar servicios fuera de ella.
- Agregar un nicho son dos cosas: un `.toml` y una plantilla Astro.

## Errores que esto ya evito

Tres bugs reales aparecieron al verificar end-to-end, y los tres eran
silenciosos -- ninguno rompia el build:

1. **`es_movil` comparaba contra 13 caracteres** cuando un movil peruano en E.164
   tiene 12 (`+51` + 9 digitos). Resultado: `whatsapp_url` siempre `None` y el
   CTA de WhatsApp desaparecia de todos los sitios. Es la unica via de conversion
   real que tienen.
2. **Doble prefijo de pais**: `(051) 987654321` quedaba como `+5151987654321`.
3. **`\bTODO\b` con `re.I`** marcaba como placeholder la palabra "Todos" de
   "Todos los derechos reservados" del pie, y rechazaba sitios correctos.
4. **El modelo publico la ciudad equivocada.** El prompt decia `Zona: Cercado`,
   distrito que existe en Lima y en Arequipa, y el modelo escribio *"Asesoria
   juridica profesional en el Cercado de Lima"* para un estudio arequipeno. El
   fact-check no lo detectaba: verificaba telefonos, nombre y resenas, pero no la
   ubicacion. Se corrigio en los dos lados -- la zona que ve el prompt ahora
   siempre lleva la ciudad, y el harness rechaza cualquier sitio que nombre una
   ciudad peruana que no sea la del negocio.
