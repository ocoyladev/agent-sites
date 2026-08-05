# Configurar Cloudflare Pages

Publica los sitios demo en `https://<site_id>.<proyecto>.pages.dev`, gratis y con
HTTPS incluido. Toma unos 10 minutos.

## El limite que define el diseno

Cloudflare permite **100 proyectos de Pages por cuenta**, y su documentacion
aclara que ese tope "no se amplia de forma rutinaria".

Un proyecto por sitio agotaria la cuenta a los 100 sitios **en total**, no por
mes. A 300 leads mensuales, eso se acaba en dos semanas.

Por eso el sistema usa **un solo proyecto** y publica cada sitio como un **alias
de rama** dentro de el:

```
proyecto: agencia-demos
  |- estudio-vargas-8bbf11.agencia-demos.pages.dev
  |- bufete-torres-a41c02.agencia-demos.pages.dev
  |- ...sin limite practico
```

Ocupa 1 de los 100 proyectos, y la URL sigue siendo un subdominio limpio para
mandar por WhatsApp.

## 1. Cuenta y proyecto

1. Crea una cuenta gratuita en <https://dash.cloudflare.com/sign-up>. No hace
   falta tener un dominio ni cargar tarjeta.
2. Ve a **Workers & Pages** -> **Create** -> pestana **Pages** -> **Create using
   direct upload**.
3. Nombre del proyecto: **`agencia-demos`** (o el que prefieras; tiene que
   coincidir con `CLOUDFLARE_PAGES_PROJECT` en `.env`).
4. Sube cualquier archivo para que el proyecto quede creado. Ese primer
   deployment se reemplaza solo despues.

## 2. Account ID

En el panel, entra a **Workers & Pages**. El **Account ID** aparece en la
columna derecha. Copialo.

## 3. Token de API

1. <https://dash.cloudflare.com/profile/api-tokens> -> **Create Token**.
2. Usa la plantilla **Custom token**.
3. Permisos: **Account** -> **Cloudflare Pages** -> **Edit**.
4. Account Resources: la cuenta donde creaste el proyecto.
5. Crea el token y copialo -- **no se vuelve a mostrar**.

Ese unico permiso es todo lo que necesita. No le des acceso a DNS ni a Zonas: si
el token se filtra, lo maximo que alguien puede hacer es tocar los sitios demo.

## 4. Cargar en `.env`

```bash
CLOUDFLARE_API_TOKEN=<el token>
CLOUDFLARE_ACCOUNT_ID=<el account id>
CLOUDFLARE_PAGES_PROJECT=agencia-demos
```

## 5. Probar

```bash
# Genera y publica un sitio de ejemplo
uv run python -m scripts.generar_sitio --demo --sin-ia --desplegar
```

El deploy corre **solo si el harness de QA aprueba**. Publicar un sitio con el
telefono equivocado es peor que no publicar nada.

## Pendiente de confirmar contra una cuenta real

`wrangler pages deploy --branch=<nombre>` con **direct upload** deberia crear el
alias de rama igual que lo hace la integracion con Git, pero la documentacion de
Cloudflare no lo dice de forma explicita para direct upload.

En la primera corrida real hay que verificar que
`https://<site_id>.<proyecto>.pages.dev` responde. Si no lo hiciera, el plan B es
servir los sitios por ruta (`agencia-demos.pages.dev/<site_id>/`), que funciona
seguro pero da una URL menos vendible. El codigo calcula la URL en
`deploy/cloudflare.py:url_esperada()`, asi que el cambio queda en un solo lugar.

## Limites del plan gratuito

| Limite | Free |
|---|---|
| Proyectos por cuenta | 100 (por eso se usa uno solo) |
| Builds por mes | 500 |
| Archivos por sitio | 20.000 |
| Tamano por archivo | 25 MiB |
| Dominios personalizados por proyecto | 100 |
| Ancho de banda y peticiones | ilimitados |

Nuestros sitios son **un HTML de ~16 KB**, asi que solo el conteo de
deployments es relevante.
