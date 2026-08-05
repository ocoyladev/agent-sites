// @ts-check
import { defineConfig } from 'astro/config';

// Sitio estatico puro: cero JavaScript al cliente. Estos sitios se abren desde
// un link de WhatsApp en un celular con datos moviles -- cada KB cuenta.
export default defineConfig({
  output: 'static',
  build: { inlineStylesheets: 'always' },
  compressHTML: true,
  devToolbar: { enabled: false },
});
