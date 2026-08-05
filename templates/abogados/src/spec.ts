/**
 * Tipos de la spec que produce `site_generator/spec.py`.
 *
 * Se mantienen a mano y en espejo con el modelo de pydantic. El harness de QA
 * verifica el HTML final contra la spec, asi que un desajuste entre ambos lados
 * se detecta en el build, no en produccion.
 */

export interface Resena {
  autor: string;
  calificacion: number;
  texto: string;
}

export interface Contacto {
  telefono: string;
  telefono_href: string;
  whatsapp_url: string | null;
  direccion: string | null;
}

export interface Hechos {
  nombre: string;
  zona: string;
  contacto: Contacto;
  horario: string[];
  resenas: Resena[];
  rating: number | null;
  num_resenas: number | null;
  fotos: string[];
}

export interface Servicio {
  nombre: string;
  descripcion: string;
}

export interface Contenido {
  titular: string;
  subtitulo: string;
  sobre_nosotros: string;
  servicios: Servicio[];
  cta_texto: string;
}

export interface Tema {
  color_primario: string;
  color_acento: string;
  fuente_titulos: string;
  fuente_texto: string;
}

export interface SiteSpec {
  site_id: string;
  lead_ref: string;
  nicho: string;
  hechos: Hechos;
  tema: Tema;
  contenido: Contenido;
}
