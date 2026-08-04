# Plan de Implementación: Agencia de Generación Automatizada de Webs con IA

**Objetivo del sistema:** un motor que, de forma masiva y semi-automática, (1) encuentra negocios locales candidatos, (2) les genera un sitio web personalizado con IA como "anzuelo" de venta, (3) los contacta, y (4) —si cierran— les da un sitio con backend ligero (formularios, citas, WhatsApp) y un panel de analítica que tú gestionas centralmente y ellos pueden ver.

Todo corre primero en tu servidor Linux (ia-node), con salida a la nube solo donde haga falta (hosting de los sitios, y quizá LLM en la nube para la generación).

> **Nota de mantenimiento (2026-08-04).** Este documento es el insumo original y
> se conserva como tal. Dos puntos quedaron superados durante la implementación
> y se corrigen en los ADR, que mandan sobre este texto:
>
> - **§3.1, costo de Google Places** — el crédito mensual de $200 fue retirado por
>   Google en marzo de 2025. El modelo vigente es cuota gratuita *por SKU*, y los
>   campos que el pipeline necesita caen en el nivel de menor cuota.
>   Ver [ADR 0002](adr/0002-field-masks-y-costo.md).
> - **§3.1, fuente única** — las fuentes de leads quedaron detrás de una interfaz
>   (`LeadSource`) en vez de acoplarse a Google. Ver
>   [ADR 0001](adr/0001-fuentes-de-leads.md).

**Este documento es el insumo inicial del proyecto.** Va dentro de la carpeta raíz del repo (ver estructura sugerida en la sección 1) y a partir de aquí se construye todo lo demás de forma incremental, con Claude Code operando sobre esta carpeta.

---

## 0. Decisiones de diseño ya tomadas (para no bloquear el arranque)

Donde había ambigüedad, elegí la opción más razonable y la explico. Al final del documento dejo lo que sigue abierto y necesita tu decisión.

- **Dominio para los sitios:** modelo de dos niveles. *Demo* → hosting gratuito con subdominio automático (Cloudflare Pages, Vercel o Netlify vía API). *Cliente cerrado* → dominio propio del cliente o subdominio bajo un dominio tuyo, servido desde ia-node con Caddy. Confirmado: aún no tienes dominio, se conecta cuando lo tengas — el resto del sistema no depende de eso para arrancar.
- **Obtención de datos de negocios:** **directo de Google Maps, sin Apify**, vía la API oficial de Google (Google Places API). Se detalla en la Fase 1 — sí es viable, y de hecho es la opción más limpia para lograr justo lo que pediste ("directo de lo que se encuentre en Google Maps").
- **Enriquecimiento con Instagram:** viable mas no trivial — Instagram es bastante más hostil a la automatización que Google Maps. Se detalla el approach y los límites reales en la Fase 1.2, con una skill dedicada.
- **Motor LLM para generación masiva:** aprovechar lo que ya tienes en ia-node (LiteLLM proxy, Ollama local, Google AI Studio con Gemini) — no necesitas una API key nueva de entrada.
- **WhatsApp (outreach):** Cloud API oficial de Meta como canal principal (barato a tu volumen, sin riesgo de baneo), con un piloto chico en automatización no oficial mientras se verifica la cuenta — detalle en Fase 7.
- El flujo manual de la imagen 3 (llamada por Meet, "lo tengo solo en mi computadora") **no escala** y se rediseña como: sitio generado → deploy automático a subdominio real → link enviado directo por WhatsApp. La videollamada se reserva para el cierre.

---

## 1. Estructura de carpeta sugerida para el proyecto

```
agencia-webs-ia/
├── README.md                        # resumen + link a este plan
├── docs/
│   └── plan-agencia-webs-ia.md      # este documento
├── lead-gen/
│   ├── google_places_client.py      # wrapper de Text Search / Place Details / Photos
│   ├── instagram_enrichment.py      # enriquecimiento opcional, best-effort
│   ├── scoring.py                   # cálculo del score de calificación
│   └── site_quality_check.py        # heurística de calidad del sitio existente (si tiene)
├── db/
│   ├── schema.sql
│   └── migrations/
├── site-generator/
│   ├── templates/
│   │   └── <nicho>/                 # un template base por nicho
│   ├── specs/                       # specs generadas por lead antes de la generación IA
│   └── harness/                     # checks automáticos post-generación (QA)
├── backend/                         # FastAPI multi-tenant (formularios, citas, WA redirect)
├── dashboard/                       # panel maestro + vista por cliente (Next.js/React)
├── n8n/                             # workflows de outreach exportados
├── skills/
│   ├── lead-research/
│   ├── site-generator/
│   ├── qa-review/
│   └── instagram-enrichment/
├── docker-compose.yml                # postgres, fastapi, n8n, umami, caddy
└── .env.example
```

---

## 2. Arquitectura general

```
┌─────────────┐     ┌──────────────┐     ┌───────────────────┐     ┌────────────┐
│  Fase 1      │ →   │  Fase 2       │ →   │  Fase 3            │ →   │  Fase 4     │
│  Lead Gen    │     │  CRM / DB     │     │  Generación (IA)   │     │  Deploy     │
│  (Google     │     │  (Postgres    │     │  (spec-driven +    │     │  (subdominio│
│  Places API) │     │  en ia-node)  │     │  harness engineering)│   │  gratis)    │
└─────────────┘     └──────────────┘     └───────────────────┘     └────────────┘
                                                                            │
                     ┌──────────────────────────────────────────────────────┘
                     ▼
        ┌─────────────────────┐     ┌───────────────────┐     ┌──────────────┐
        │  Fase 5              │     │  Fase 6            │     │  Fase 7       │
        │  Backend compartido   │ →   │  Analítica         │ →   │  Outreach     │
        │  (FastAPI multi-tenant│     │  (Umami self-host) │     │  (n8n + WA)   │
        │  formularios/citas)    │     │  + Dashboard maestro│    │               │
        └─────────────────────┘     └───────────────────┘     └──────────────┘
```

Todo (excepto el hosting de los sitios estáticos y opcionalmente el LLM) vive en **un solo `docker-compose.yml` en ia-node**: Postgres, FastAPI, n8n, Umami, Caddy como reverse proxy. Auto-contenido, movible a la nube pieza por pieza cuando el volumen lo exija.

---

## 3. Fase 1 — Obtención de datos (Lead Generation)

### 3.1 Fuente primaria: Google Maps directo, sin Apify

**Sí es viable manejarlo así**, y de hecho es la forma más limpia de lograr justo lo que pediste. En vez de un actor de terceros (Apify) que scrapea el HTML de Google Maps, se usa la **Google Places API (New)** — la interfaz oficial de Google sobre los mismos datos que ves en Maps. Sigue siendo "directo de Google Maps": no pasa por ningún intermediario, es Google mismo respondiendo.

**Cómo se arma el pipeline:**

1. **Descubrimiento — Text Search:** búsqueda por nicho + zona (ej. "electricista en Cercado, Arequipa"). Devuelve hasta 60 resultados por búsqueda (paginado), con nombre, dirección, ubicación y tipo de negocio.
2. **Detalle — Place Details:** para cada candidato, se piden los campos específicos que necesitas: teléfono, sitio web, horario, rating, número de reseñas. Google cobra por "nivel" de campos solicitados (mientras más datos pides por llamada, más caro el nivel) — hay que pedir solo lo necesario, no todos los campos "por si acaso".
3. **Fotos — Place Photos:** trae fotos reales ya subidas al listing del negocio (por el dueño o por usuarios). **Esto es importante: reduce bastante la necesidad de Instagram solo para conseguir imágenes** — ya tienes fotos reales y legítimas del negocio sin necesidad de scrapear nada más.

**Costo estimado para tu volumen (100-300 leads/mes):** Google Places API (New) cobra por SKU y nivel de campos — aproximadamente $32/1,000 para Text Search con campos básicos, y una tarifa más alta (~$35/1,000) para los campos "Enterprise" que incluyen reviews/rating y fotos. Para descubrir y calificar 300 negocios al mes (unas 15-20 búsquedas de Text Search + ~300 Place Details + fotos de los que califican), el costo estimado ronda los **$15-40/mes** — y Google Maps Platform da un crédito mensual de $200 combinado entre todos sus SKUs, así que en la práctica es muy probable que tu volumen quede **cubierto por el crédito gratuito**, con $0 de gasto real. Vale la pena monitorear el consumo en Google Cloud Console las primeras semanas para confirmarlo con tus números reales.

**Alternativa que existe pero no recomiendo como default — scraping directo del HTML/app de Maps** (con Playwright/Selenium, sin pasar por la API oficial ni por Apify): es técnicamente posible, y de hecho es exactamente lo que actors como los de Apify hacen por dentro. La diferencia es que ahí *tú* asumes el trabajo que Apify ya resolvió: rotación de proxies (Google bloquea IPs agresivamente a volumen), mantenimiento cuando Google cambia el HTML/clases internas, y manejo de CAPTCHAs. Para 100-300 leads/mes la API oficial es más barata en tiempo de desarrollo y más estable. Dejo esto como opción B disponible si en algún momento necesitas un dato específico que la API no expone — pero la arquitectura por defecto usa la API oficial.

### 3.2 Enriquecimiento cruzado con Instagram

Aquí hay que ser realista sobre lo que es viable, porque Instagram es un caso bastante distinto a Google Maps:

- **No existe un equivalente al Places API para esto.** El Instagram Graph API oficial de Meta solo permite consultar cuentas que tú administras o que te dieron permiso explícito vía OAuth — no está diseñado para "consultar el Instagram de cualquier negocio que encuentre en Maps". Para leads que no son tuyos, la única vía es acceder a lo que el perfil muestra públicamente sin sesión iniciada.
- **Lo público sin login es real, pero cada vez más frágil.** Bio, foto de perfil y grid de posts recientes de una cuenta pública son técnicamente visibles sin iniciar sesión — pero para 2026 Instagram ha vuelto su sistema antibot más agresivo: exige login en más situaciones de las que exigía antes, bloquea IPs rápido cuando detecta patrones automatizados, y sus endpoints internos cambian con frecuencia. Un scraper simple sin cuidado se rompe en días, no en meses.
- **Es más caro de mantener por tu cuenta que Google Maps.** Con Google Maps evitar Apify es razonable porque la API oficial de Google es una alternativa robusta y barata. Con Instagram no hay un "Places API equivalente" — la alternativa a un proveedor especializado (Apify u otro) es construir y mantener tú mismo el manejo de rate limiting, proxies y los cambios de estructura, lo cual consume tiempo de forma continua, no solo en el setup inicial.

**Tres formas de resolverlo, de más simple a más ambiciosa:**

1. **(Recomendada para arrancar) Instagram solo para los leads que ya calificaron.** En vez de cruzar los 100-300 leads/mes contra Instagram automáticamente, se reserva ese enriquecimiento para los que pasan a estado `calificado` o superior — volumen mucho menor (probablemente 20-40/mes), lo que hace viable un scraper propio sin login, cuidadoso con el rate limiting, sin necesitar infraestructura de proxies seria.
2. **Política mixta:** Google Maps directo (como ya se definió) + Instagram vía un proveedor especializado (Apify u otro) solo para esa pieza específica. Es razonable tener "todo directo excepto donde de verdad conviene tercerizar" en vez de una regla todo-o-nada.
3. **Prescindir de Instagram como fuente automatizada** y usarlo solo manualmente, cuando tú mismo revises un lead antes de contactarlo. Es la opción de menor riesgo técnico, al costo de tu tiempo.

Dado que Google Place Photos ya te da imágenes reales del negocio (punto 3.1), mi recomendación es la opción 1: usar Instagram como enriquecimiento de *texto* (bio, descripción de servicios, tono de comunicación del negocio) más que como fuente principal de imágenes, y solo para el subconjunto de leads que ya avanzó en el pipeline — no para los 300 iniciales.

**Skill a crear: `instagram-enrichment`** — recibe nombre del negocio + zona (o el handle si ya se encontró), intenta ubicar el perfil público, y extrae de forma best-effort: bio, foto de perfil, texto de los últimos posts visibles sin login. Diseñada explícitamente para fallar de forma silenciosa (si Instagram bloquea o pide login, el lead sigue su flujo normal sin ese dato extra) — nunca debe ser un punto de falla del pipeline principal.

### 3.3 Criterios de calificación (scoring)

Arma un score compuesto por negocio, no un filtro binario:

- **Volumen de consultas (proxy):** número de reseñas alto + categoría de negocio de alta demanda (fontaneros, HVAC, dentistas, etc., de la imagen 1).
- **Ticket medio/alto:** implícito en la categoría (HVAC/dentistas > peluquería básica).
- **Bajo perfil digital:** sin sitio web, o con sitio de baja calidad. Automatizable: visita el sitio existente (si lo hay, dato que ya viene de Place Details) y evalúa heurísticas simples — ¿tiene HTTPS?, ¿es responsive?, ¿tiene un CTA claro de contacto/WhatsApp? Esto da un `calidad_sitio_score` sin revisión manual.
- **Contactabilidad:** debe tener teléfono/WhatsApp visible — sin esto, no califica sin importar lo demás.

Empieza con **un solo nicho** (ej. Electricistas) para construir la máquina end-to-end antes de paralelizar a los otros nichos marcados.

### 3.4 Skill a crear: `lead-research`

Encapsula: cómo construir las queries de Text Search por nicho+zona, qué campos pedir en Place Details (y a qué nivel, para controlar costo), cuándo intentar `instagram-enrichment`, cómo calcular el score, y el formato de salida estandarizado que alimenta la Fase 2.

---

## 4. Fase 2 — Almacenamiento y seguimiento

**Postgres en Docker (ia-node)** — dominio de datos distinto al esquema Oracle ADB de DEVOL+ (leads/sitios/analítica vs. autenticación), y Postgres da más flexibilidad para las consultas del dashboard.

```
leads
  id, nombre_negocio, nicho, telefono, whatsapp, direccion,
  google_place_id, rating, num_resenas, tiene_sitio_web,
  url_sitio_actual, calidad_sitio_score,
  instagram_handle, instagram_bio, tiene_datos_instagram,
  estado_pipeline, fecha_creacion, fecha_ultimo_contacto, notas

sitios_generados
  id, lead_id, url_demo, url_produccion, template_usado,
  version, estado_qa, fecha_generacion, fuente_fotos

mensajes_outreach
  id, lead_id, canal, contenido, fecha_envio, respuesta, fecha_respuesta
```

**Estados del pipeline:** `nuevo → calificado → sitio_generado → qa_aprobado → contactado → interesado → demo_agendada → negociacion → cliente → descartado`

**Exportación a Excel:** endpoint simple (`GET /export/leads.xlsx`) que dumpea la tabla filtrada por estado — mismo mecanismo que luego usarás para entregarle a cada cliente sus leads.

---

## 5. Fase 3 — Generación de sitios (spec-driven development + harness engineering)

- **Spec-driven development:** antes de generar contenido, se define una especificación explícita (qué secciones lleva el sitio, qué tono, qué información va dónde, qué CTAs) — la spec es la fuente de verdad, no el prompt suelto.
- **Harness engineering:** el scaffolding alrededor del agente de IA que garantiza que lo generado cumple la spec de forma confiable y repetible — plantillas base, reglas de verificación, y un paso de QA automático antes de considerar el sitio listo. Es lo que separa "un sitio bien hecho a mano" de "cientos de sitios consistentemente bien hechos".

### 5.1 Diseño concreto

1. **Plantilla base por nicho** (no por cliente): estructura fija con secciones parametrizables (hero, servicios, reseñas reales del negocio, zona de cobertura, CTA WhatsApp, formulario). Un nicho = un template.
2. **Spec por lead:** generada automáticamente a partir de los datos de Fase 1 (nombre, servicios, zona, reseñas destacadas, teléfono, fotos de Place Photos, y bio de Instagram si está disponible).
3. **Generación:** la IA llena el template con copy y ajustes específicos del negocio.
4. **Harness / QA automático** antes de pasar a `qa_aprobado`:
   - ¿Renderiza sin errores?
   - ¿Los links (WhatsApp, teléfono, formulario) son válidos?
   - ¿Pasa un check básico de mobile-responsive?
   - ¿El copy no inventó datos falsos del negocio? — validación cruzada contra los datos originales.

### 5.2 Qué API usar (sin quemar tu suscripción)

- **Ollama local (ia-node):** tareas mecánicas de bajo riesgo — normalizar datos, clasificar categoría, variaciones simples. Gratis, ilimitado.
- **Google AI Studio / Gemini (free tier):** copywriting real de cada sitio — calidad superior a modelos locales pequeños.
- **Tu LiteLLM proxy:** capa de enrutamiento con fallback (si Gemini free tier se satura, cae a Ollama u otro proveedor) sin tocar el código de generación.
- **API de Anthropic (pagada, no tu suscripción de claude.ai):** reservada para los pasos donde la calidad importa más — leads con score alto.

### 5.3 Skills a crear

- `site-generator`: ciclo completo spec → generación → harness, parametrizado por nicho.
- `qa-review`: harness de verificación automática, invocable de forma independiente.
- Un archivo de configuración por nicho (no una skill nueva por nicho) — agregar un nicho es agregar un archivo de config, no reescribir la skill.

Puedes usar la skill `skill-creator` como punto de partida para formalizar estas skills.

---

## 6. Fase 4 — Despliegue

- **Sitios demo (pre-venta):** deploy automático vía API a Cloudflare Pages o Vercel — subdominio gratuito, HTTPS incluido, sin costo a este volumen.
- **Sitios cliente (post-venta):** subdominio bajo tu dominio (cuando lo tengas) servido desde ia-node vía Caddy, o dominio propio del cliente apuntando al mismo hosting.

---

## 7. Fase 5 — Backend compartido (multi-tenant)

**Una sola API FastAPI en ia-node** sirve a todos los sitios generados:

- `POST /api/{site_id}/contacto` — formulario de contacto.
- `POST /api/{site_id}/cita` — solicitudes de agendamiento.
- `GET /api/{site_id}/whatsapp-redirect` — genera el link `wa.me` con mensaje prellenado, registrando el clic como evento antes de redirigir (esto alimenta el dato de "leads" del dashboard).

Cada sitio estático solo necesita un `fetch()` apuntando a este backend con su `site_id`.

---

## 8. Fase 6 — Analítica y dashboard maestro

**Umami** (open source, self-hostable en Docker, multi-sitio nativo, API REST). Cada sitio lleva su script de tracking con `website_id` propio.

- Visitantes, pageviews, referrers — nativo de Umami.
- Clics en WhatsApp/formulario/citas — eventos custom vía el backend de Fase 5.
- **Dashboard maestro:** vista agregada combinando Postgres (pipeline comercial) + API de Umami (tráfico).
- **Vista por cliente:** mismo dashboard filtrado por `site_id`, con export a Excel de sus leads.

App web ligera (React/Next.js) — no Flet aquí, es multiusuario orientado a web, distinto de DEVOL+.

---

## 9. Fase 7 — Contacto (outreach) y cierre

1. Lead pasa a `qa_aprobado` → trigger en n8n.
2. n8n arma el mensaje de prospección (nombre del negocio + link real del sitio ya desplegado).
3. Envío por WhatsApp — ver 9.1.
4. Respuesta positiva → estado `interesado`, te notifica para que tomes el cierre manual.
5. Cierre → migración del sitio de demo a producción (Fase 4) + alta en Umami con `website_id` propio.

La imagen 4 (walk-ins, cold DMs, referidos) entra al mismo pipeline en `nuevo` — un canal de entrada más, sin lógica distinta.

### 9.1 WhatsApp: comparación y recomendación (agosto 2026)

**Opción A — WhatsApp Business Cloud API (oficial)**
- Sin cuota mensual por la API en sí, se paga por mensaje. Desde julio 2025, Meta cobra por mensaje según país y categoría: *marketing* (tu primer contacto en frío) es la más cara, ~$0.01-$0.14 según país (LatAm ronda $0.03-$0.06); *servicio/utilidad* dentro de una ventana de 24h después de que el negocio responde es gratis.
- Para 100-300 leads/mes: ~$3-18/mes solo en el primer mensaje. El costo no es el obstáculo — el trámite sí: verificación de negocio (días) y plantilla de mensaje pre-aprobada por Meta.
- Cumplimiento total, sin riesgo de baneo, escalable.

**Opción B — Automatización no oficial** (whatsapp-web.js, Baileys, etc.)
- Gratis, se monta en horas, mensaje 100% libre.
- Viola los términos de WhatsApp. A 100-300 mensajes fríos/mes concentrados, el riesgo de baneo del número es real.

**Recomendación:** arranca la verificación de Meta Business ya, en paralelo al resto del sistema. Mientras se aprueba, usa la opción B solo para un piloto de 10-20 leads desde un número secundario. Migra el volumen real a la Cloud API una vez aprobada. Intenta calificar la plantilla de primer contacto como *utilidad* en vez de *marketing* si el contenido lo permite — la tarifa es más baja.

---

## 10. Cumplimiento y riesgos a tener en cuenta

- **Google Places API:** uso 100% dentro de los términos de Google, sin riesgo de bloqueo — es la ventaja concreta de este approach frente a scraping directo.
- **Instagram:** scrapear perfiles públicos sin login está en una zona defendible legalmente en varias jurisdicciones (no es lo mismo que acceder a contenido privado), pero sí contraviene los términos de servicio de Meta — el riesgo práctico es de bloqueo técnico (cuenta/IP), no tanto legal, si el enriquecimiento se mantiene a bajo volumen (opción 1 de la sección 3.2) y sin intentar sortear muros de login.
- **WhatsApp:** ver 9.1.
- **Datos de negocios y Ley 29733 (Perú):** aplica sobre todo a datos de personas naturales identificables; datos de contacto comercial público generan menos fricción legal, pero el envío masivo no solicitado sí puede generar fricción de reputación/spam independientemente del marco legal — de ahí la importancia de personalizar y mantener volumen razonable.
- **Tu situación particular:** como auditor en SUNAT, vale la pena revisar si existe alguna política interna sobre actividades económicas paralelas antes de facturar formalmente como agencia — verificación que te corresponde a ti internamente.
- **Contenido de los sitios demo:** usar nombre, teléfono y reseñas públicas del negocio en un sitio demo no autorizado es una práctica común y de bajo riesgo si no se hace pasar por el sitio oficial del negocio ni se publica agresivamente. Para fotos, prioriza las que vienen de Google Place Photos (ya públicas en el listing del propio negocio) antes que imágenes de terceros con derechos de autor inciertos.

---

## 11. Cronograma sugerido

| Semana | Foco |
|---|---|
| 1 | Estructura de carpeta + Postgres/FastAPI base en ia-node + cuenta de Google Cloud con Places API habilitada + primera extracción de prueba de un nicho |
| 2 | Skill `lead-research` (Google Places + scoring) + carga a la tabla + export Excel |
| 2-3 | Piloto de `instagram-enrichment` sobre un grupo pequeño de leads ya calificados |
| 3-4 | Template de 1 nicho + skill `site-generator` + `qa-review` (harness) + 5-10 sitios de prueba supervisados |
| 4 | Pipeline de deploy automático (Cloudflare Pages/Vercel API) |
| 5 | Backend compartido (formularios/citas/WA redirect) + Umami instalado |
| 5-6 | Dashboard maestro + vista por cliente + export Excel de leads |
| 6 | Verificación de Meta Business en paralelo (arrancar temprano por el tiempo de aprobación) |
| 6+ | n8n + outreach, primero piloto no oficial chico, luego Cloud API oficial |
| 7+ | Iterar con datos reales, agregar 2º nicho, evaluar qué mover a nube |

---

## 12. Próximos pasos inmediatos

1. Crear la carpeta del proyecto con la estructura de la sección 1.
2. Habilitar Google Places API (New) en Google Cloud Console y confirmar el crédito mensual disponible.
3. Levantar Postgres + FastAPI base en ia-node (`docker-compose.yml` inicial).
4. Correr una primera extracción de prueba con Text Search + Place Details para un nicho y zona específicos, revisar la calidad de los datos antes de automatizar el scoring.
5. Construir la skill `lead-research` como primera pieza formal.
6. Iniciar en paralelo el trámite de verificación de Meta Business (por el tiempo de aprobación).
