// App shell: navigation, hash router, shared state, global player and status footer.
import { api } from './api.js';
import { $, clear, h, icon, toastError } from './ui.js';
import { state } from './state.js';
import dashboard from './views/dashboard.js';
import spotify from './views/spotify.js';
import library from './views/library.js';
import importer from './views/import.js';
import convert from './views/convert.js';
import history from './views/history.js';
import settings from './views/settings.js';

const ROUTES = [
  { id: 'dashboard', label: 'Dashboard', icon: 'dashboard', view: dashboard },
  { id: 'spotify', label: 'Spotify', icon: 'spotify', view: spotify },
  { id: 'library', label: 'Biblioteca musical', icon: 'library', view: library },
  { id: 'import', label: 'Importar archivos', icon: 'import', view: importer },
  { id: 'convert', label: 'Conversión WAV', icon: 'wave', view: convert },
  { id: 'history', label: 'Historial', icon: 'history', view: history },
  { id: 'settings', label: 'Configuración', icon: 'settings', view: settings },
];

let cleanup = null;
let navBadges = {};

function buildNav() {
  const nav = $('#nav');
  clear(nav, ROUTES.map((r) => {
    const badge = h('span', { class: 'badge green hidden' });
    navBadges[r.id] = badge;
    return h('a', { href: `#/${r.id}`, 'data-route': r.id }, icon(r.icon), r.label, badge);
  }));
  $('#brand-logo').append(icon('logo'));
}

function updateNavBadges() {
  const n = state.selection.size;
  const b = navBadges.convert;
  if (b) { b.textContent = n; b.classList.toggle('hidden', !n); }
}
window.addEventListener('swc:selection', updateNavBadges);

async function render() {
  const [path, query] = (location.hash.replace(/^#\/?/, '') || 'dashboard').split('?');
  const route = ROUTES.find((r) => r.id === path) || ROUTES[0];
  document.querySelectorAll('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.route === route.id));
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  const main = $('#main');
  const page = h('div', { class: 'page', 'data-page': route.id });
  clear(main, page);
  main.scrollTop = 0;
  document.title = `${route.label} · Spotify to WAV Converter`;
  try {
    cleanup = await route.view(page, new URLSearchParams(query || ''));
  } catch (e) {
    toastError(e);
  }
}

// ---- footer status ----
async function refreshStatus() {
  try {
    const d = await api.get('/api/dashboard');
    const sp = $('#foot-spotify');
    clear(sp, h('span', { class: `dot ${d.spotify.connected ? 'on' : ''}` }),
      d.spotify.connected ? `Spotify: ${d.spotify.user?.name || 'conectado'}` : 'Spotify: desconectado');
    clear($('#foot-ffmpeg'), h('span', { class: `dot ${d.ffmpeg ? 'on' : 'off'}` }), d.ffmpeg ? 'FFmpeg listo' : 'FFmpeg no encontrado');
    const active = (d.conversions.queued || 0) + (d.conversions.running || 0);
    $('#foot-queue').textContent = active ? `${active} conversión(es) en curso` : '';
  } catch { /* server unavailable; next tick will retry */ }
}

window.addEventListener('message', (e) => {
  if (e.data?.type === 'swc-spotify') refreshStatus();
});
window.addEventListener('hashchange', render);

(async function init() {
  buildNav();
  updateNavBadges();
  try { state.system = await api.get('/api/system'); } catch (e) { toastError(e); }
  render();
  refreshStatus();
  setInterval(refreshStatus, 4000);
})();
