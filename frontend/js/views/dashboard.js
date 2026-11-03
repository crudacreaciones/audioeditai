import { api } from '../api.js';
import { navigate } from '../state.js';
import { clear, empty, fmtBytes, fmtDate, fmtDuration, fmtSpec, h, icon, progressBar, statusBadge } from '../ui.js';

export default async function dashboard(root) {
  const head = h('div', { class: 'page-head' },
    h('div', {}, h('h1', {}, 'Dashboard'), h('p', {}, 'Resumen de tu biblioteca, conversiones y conexión con Spotify.')),
    h('div', { class: 'actions' },
      h('button', { class: 'btn', onclick: () => navigate('import') }, icon('import'), 'Importar audio'),
      h('button', { class: 'btn primary', onclick: () => navigate('convert') }, icon('wave'), 'Convertir a WAV')));
  const body = h('div');
  root.append(head, body);

  async function load() {
    const d = await api.get('/api/dashboard');
    const lib = d.library, conv = d.conversions;
    const active = (conv.queued || 0) + (conv.running || 0);
    const stats = h('div', { class: 'grid cols-4' },
      statCard('Canciones', lib.tracks, `${lib.artists} artistas · ${lib.albums} álbumes`),
      statCard('Duración total', fmtDuration(lib.duration), fmtBytes(lib.size) + ' en disco'),
      statCard('WAV generados', conv.done || 0, `${fmtBytes(conv.output_bytes)} · ${conv.failed || 0} errores`),
      statCard('En cola', active, active ? 'Conversión en curso' : 'Sin tareas pendientes'));

    const spotifyCard = h('div', { class: 'card' },
      h('div', { class: 'card-head' }, h('h2', {}, 'Spotify'),
        d.spotify.connected ? h('span', { class: 'badge green' }, 'Conectado') : h('span', { class: 'badge' }, 'Desconectado')),
      d.spotify.connected
        ? h('div', {}, h('p', { class: 'muted' }, `Sesión iniciada como `, h('b', {}, d.spotify.user?.name || '—')),
          h('p', { class: 'muted' }, `${d.worklist} canciones en la lista de trabajo · ${lib.linked} asociadas a archivos locales`),
          h('button', { class: 'btn sm', onclick: () => navigate('spotify') }, icon('search'), 'Explorar catálogo'))
        : h('div', {}, h('p', { class: 'muted' }, d.spotify.configured
          ? 'Conecta tu cuenta para buscar canciones y consultar tus listas.'
          : 'Configura el Client ID de tu aplicación de Spotify para empezar.'),
          h('button', { class: 'btn sm primary', onclick: () => navigate(d.spotify.configured ? 'spotify' : 'settings') },
            icon('spotify'), d.spotify.configured ? 'Conectar Spotify' : 'Configurar')));

    const formats = h('div', { class: 'card' }, h('h2', {}, 'Formatos en la biblioteca'),
      lib.formats.length ? h('div', { class: 'list' }, lib.formats.map((f) => {
        const pct = lib.tracks ? f.n / lib.tracks : 0;
        return h('div', { class: 'list-item' }, h('span', { class: 'badge', style: { width: '52px', justifyContent: 'center' } }, (f.format || '?').toUpperCase()),
          h('div', { class: 'grow' }, progressBar(pct)), h('span', { class: 'num muted' }, f.n));
      })) : h('p', { class: 'dim' }, 'Aún no hay archivos importados.'));

    const recent = h('div', { class: 'card' },
      h('div', { class: 'card-head' }, h('h2', {}, 'Conversiones recientes'),
        h('button', { class: 'btn ghost sm', onclick: () => navigate('history') }, 'Ver historial')),
      d.recent_conversions.length ? h('div', { class: 'list' }, d.recent_conversions.map((j) =>
        h('div', { class: 'list-item' }, icon('wave'),
          h('div', { class: 'grow track-meta' }, h('div', { class: 't' }, j.title || j.output_path.split(/[\\/]/).pop()),
            h('div', { class: 'a' }, fmtSpec(j))),
          j.status === 'running' ? progressBar(j.progress) : statusBadge(j.status))))
        : empty('wave', 'Sin conversiones', 'Las conversiones aparecerán aquí.'));

    const activity = h('div', { class: 'card' }, h('h2', {}, 'Actividad'),
      d.recent_logs.length ? h('div', { class: 'list' }, d.recent_logs.map((l) =>
        h('div', { class: 'list-item' },
          h('span', { class: `dot ${l.level === 'error' ? 'off' : l.level === 'warning' ? '' : 'on'}` }),
          h('div', { class: 'grow' }, h('div', {}, l.message), h('div', { class: 'dim', style: { fontSize: '12px' } }, `${l.category} · ${fmtDate(l.ts)}`)))))
        : h('p', { class: 'dim' }, 'Sin actividad.'));

    clear(body, stats, h('div', { class: 'grid cols-3 mt' }, spotifyCard, formats, h('div', { class: 'card' },
      h('h2', {}, 'Privacidad y legalidad'),
      h('div', { class: 'notice' }, icon('shield'), h('div', {},
        'Todo el procesamiento es local: ningún archivo de audio se sube a servidores externos. ',
        'Spotify se usa solo para descubrir y organizar música; la app no descarga ni elude el DRM de Spotify.')))),
    h('div', { class: 'grid cols-2 mt' }, recent, activity));
  }

  await load();
  const timer = setInterval(() => load().catch(() => {}), 3000);
  return () => clearInterval(timer);
}

function statCard(label, value, sub) {
  return h('div', { class: 'card stat' }, h('div', { class: 'label' }, label), h('div', { class: 'value num' }, value), h('div', { class: 'sub' }, sub));
}
