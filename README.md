# Agencia Web IA

Motor que encuentra negocios locales, les genera un sitio web con IA como
anzuelo de venta, los contacta y —si cierran— les entrega backend ligero y
analitica.

Plan completo: [`docs/plan-agencia-webs-ia.md`](docs/plan-agencia-webs-ia.md)

**Nicho activo:** abogados / estudios juridicos en Arequipa.

## Estado

| Fase | Que hace | Estado |
|---|---|---|
| 1 — Lead generation | descubrir y calificar negocios | **funcionando** (Google Places) |
| 2 — CRM / base | Postgres, pipeline comercial | **funcionando** (esquema + upsert) |
| 3 — Generacion de sitios | spec-driven + harness de QA | pendiente |
| 4 — Deploy | subdominio automatico | pendiente |
| 5 — Backend compartido | formularios, citas, WhatsApp | esqueleto |
| 6 — Analitica | Umami + dashboard | pendiente |
| 7 — Outreach | n8n + WhatsApp | pendiente |

## Arranque

```bash
# 1. Dependencias
uv sync

# 2. Configuracion
cp .env.example .env      # editar: password de Postgres y la API key

# 3. Base de datos (puerto 5435; 5432-5434 estan ocupados en ia-node)
docker compose up -d db

# 4. Verificar
uv run pytest             # los tests de base se saltan solos si no esta levantada
```

Para la API key de Google: [`docs/setup-google-places.md`](docs/setup-google-places.md).

## Correr una extraccion

```bash
# Ver el plan sin llamar a la API ni escribir nada
uv run python -m scripts.run_extraction --dry-run

# Corrida acotada de verdad, sin tocar la base
uv run python -m scripts.run_extraction --zonas 1 --consultas 1 --limite 5 --sin-db

# Corrida completa del nicho activo
uv run python -m scripts.run_extraction
```

Cada corrida termina imprimiendo su consumo por SKU de Google.

## Como esta armado

```
lead_gen/          descubrimiento, scoring y calidad de sitios
  source.py          protocolo LeadSource: el contrato de toda fuente
  sources/           implementaciones (hoy: google_places)
  cost.py            mapeo campo -> SKU de Google y topes por corrida
  scoring.py         score compuesto 0-100 + filtros duros
  site_quality_check.py   heuristicas sobre el sitio actual del negocio
  nichos.py          carga de nichos/*.toml
nichos/            un archivo TOML por nicho -- agregar nicho no toca codigo
db/migrations/     esquema SQL versionado
backend/           API FastAPI (multi-tenant, en construccion)
scripts/           corridas operativas
docs/adr/          decisiones de diseno y su porque
```

### Dos ideas que explican el resto

**1. La fuente de leads es intercambiable.** Todo va detras del protocolo
`LeadSource`. Google es el primer proveedor, no el unico posible — el registro
del Colegio de Abogados, un directorio o un scraper entran como clases nuevas
sin tocar el pipeline. Ver [ADR 0001](docs/adr/0001-fuentes-de-leads.md).

**2. El FieldMask decide la factura.** Google cobra cada request al SKU mas alto
que toque cualquier campo pedido, y los campos que necesitamos (telefono, sitio,
rating) son del nivel con menos cuota gratuita. Por eso el mapeo campo -> SKU
esta en codigo probado y hay tests que fallan si alguien encarece una mascara.
Ver [ADR 0002](docs/adr/0002-field-masks-y-costo.md).

## Verificacion

```bash
uv run mypy .        # tipado estricto
uv run ruff check .  # lint
uv run pytest        # tests
```

Los tests de `test_db_integration.py` necesitan Postgres arriba; se saltan solos
si no esta. El resto corre sin red, sin API key y sin gastar cuota: las
respuestas de Google se simulan con `respx`.

## Notas operativas

- Los puertos 5432, 5433 y 5434 de ia-node ya estan usados por otros Postgres.
  Este proyecto usa el **5435**, solo en loopback.
- `.env` nunca se commitea. `.env.example` es la plantilla.
- Re-correr una extraccion es idempotente por `(fuente, ref)`: refresca los datos
  del negocio sin pisar `estado_pipeline` ni `notas`.
