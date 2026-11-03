// Quick client-side check for instant feedback. The server validates again (and is the source of truth).
const ID = '[A-Za-z0-9]{22}';
const WEB = new RegExp(`^(https?://)?(open|play)\\.spotify\\.com/(intl-[a-z]{2}(-[a-z]{2})?/)?(embed/)?(track|album|playlist|artist|episode|show)/(${ID})`, 'i');
const URI = new RegExp(`^spotify:(track|album|playlist|artist|episode|show):(${ID})$`);
const SHORT = /^(https?:\/\/)?(spotify\.link|spoti\.fi)\/[A-Za-z0-9_-]{4,40}\/?$/i;

export type LinkCheck = { ok: true } | { ok: false; message: string };

export function checkSpotifyLink(raw: string): LinkCheck {
  const text = raw.trim();
  if (!text) return { ok: false, message: 'Pega un enlace de Spotify.' };
  if (SHORT.test(text)) return { ok: true };
  const m = WEB.exec(text) || URI.exec(text);
  if (!m) return { ok: false, message: 'Eso no parece un enlace de canción de Spotify.' };
  const kind = (m.length > 3 ? m[6] : m[1]).toLowerCase();
  if (kind !== 'track') return { ok: false, message: 'Pega el enlace de una canción (no de un álbum, playlist o artista).' };
  return { ok: true };
}

/** Extract the first Spotify-looking link from shared text like "Escucha X en Spotify: https://…". */
export function extractLink(text: string): string {
  const m = /(https?:\/\/(open\.spotify\.com|spotify\.link|spoti\.fi)\/\S+|spotify:track:[A-Za-z0-9]{22})/i.exec(text);
  return m ? m[0] : text.trim();
}
