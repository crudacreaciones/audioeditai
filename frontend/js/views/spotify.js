import { api } from '../api.js';
import { navigate, state } from '../state.js';
import { clear, confirmDialog, cover, desktop, empty, fmtDuration, h, icon, modal, seg, toast, toastError } from '../ui.js';

export default async function spotifyView(root, params) {
  let tab = params.get('tab') || 'search';
  let worklistIds = new Set();
  let pollTimer = null;
  let onAuthMessage = null;
  const head = h('div', { class: 'page-head' });
  const body = h('div');
  root.append(head, body);

  async function refreshWorklistIds() {
    const wl = await api.get('/api/worklist');
    worklistIds = new Set(wl.map((t) => t.id));
    return wl;
  }

  async function addTracks(tracks) {
    const fresh = tracks.filter((t) => !worklistIds.has(t.id));
    if (!fresh.length) { toast('Ya están en la lista de trabajo', 'warn'); return; }
    await api.post('/api/worklist', fresh);
    fresh.forEach((t) => worklistIds.add(t.id));
    toast(`${fresh.length} canción(es) añadida(s) a la lista de trabajo`);
  }

  // ---- reusable track list ----
  function trackList(tracks, { showAlbum = true } = {}) {
    if (!tracks.length) return empty('music', 'Sin resultados', 'Prueba con otra búsqueda.');
    return h('div', { class: 'table-wrap' }, h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, 'Título'), showAlbum ? h('th', {}, 'Álbum') : null, h('th', {}, 'Duración'), h('th', { style: { width: '1%' } }, ''))),
      h('tbody', {}, tracks.map((t) => {
        const added = worklistIds.has(t.id);
        const btn = h('button', { class: `btn sm ${added ? 'ghost' : ''}`, disabled: added, title: 'Añadir a la lista de trabajo',
          onclick: async () => { try { await addTracks([t]); btn.disabled = true; btn.className = 'btn sm ghost'; clear(btn, icon('check'), 'Añadida'); } catch (e) { toastError(e); } } },
        added ? [icon('check'), 'Añadida'] : [icon('plus'), 'Añadir']);
        return h('tr', {},
          h('td', {}, h('div', { class: 'track-cell' }, cover(t.thumb_url || t.image_url),
            h('div', { class: 'track-meta' }, h('div', { class: 't' }, t.name, t.explicit ? h('span', { class: 'badge', style: { marginLeft: '6px' } }, 'E') : null), h('div', { class: 'a' }, t.artists)))),
          showAlbum ? h('td', { class: 'trunc muted' }, t.album) : null,
          h('td', { class: 'num muted' }, fmtDuration(t.duration_ms / 1000)),
          h('td', {}, h('div', { class: 'row', style: { flexWrap: 'nowrap' } },
            t.external_url ? h('a', { class: 'btn ghost icon', href: t.external_url, target: '_blank', rel: 'noopener', title: 'Abrir en Spotify', onclick: openExternal }, icon('link')) : null, btn)));
      }))));
  }

  function tracksBlock(title, subtitle, tracks, image, back) {
    const listBox = h('div', {}, trackList(tracks));
    return h('div', {},
      h('div', { class: 'row between mb' },
        h('div', { class: 'row' }, back ? h('button', { class: 'btn ghost icon', onclick: back, title: 'Volver' }, icon('up')) : null,
          image ? cover(image) : null, h('div', {}, h('h2', { style: { margin: 0, fontSize: '18px' } }, title), h('div', { class: 'muted' }, subtitle))),
        tracks.length ? h('button', { class: 'btn primary sm', onclick: async () => {
          try { await addTracks(tracks); clear(listBox, trackList(tracks)); } catch (e) { toastError(e); }
        } }, icon('plus'), `Añadir todas (${tracks.length})`) : null),
      listBox);
  }

  // ---- header & connection states ----
  async function load() {
    const st = await api.get('/api/spotify/status');
    await refreshWorklistIds();
    clear(head, h('div', {}, h('h1', {}, 'Spotify'), h('p', {}, 'Busca canciones, artistas y álbumes, y organiza tu lista de trabajo.')),
      h('div', { class: 'actions' }, st.connected
        ? [h('span', { class: 'badge green' }, icon('user'), st.user?.name || 'Conectado'),
          h('button', { class: 'btn sm', onclick: async () => {
            if (await confirmDialog('Desconectar Spotify', 'Se eliminarán los tokens guardados. Tu lista de trabajo se conserva.', 'Desconectar', 'danger')) {
              await api.post('/api/spotify/logout'); load();
            } } }, 'Desconectar')]
        : []));
    if (!st.configured) {
      clear(body, setupCard(st), worklistSection());
      renderWorklist();
      return;
    }
    if (!st.connected) {
      clear(body, h('div', { class: 'card' },
        h('div', { class: 'row between' }, h('div', {}, h('h2', {}, 'Conecta tu cuenta de Spotify'),
          h('p', { class: 'muted', style: { margin: 0 } }, 'Se abrirá Spotify para autorizar el acceso de solo lectura a tu catálogo y listas (OAuth con PKCE).')),
        h('button', { class: 'btn primary', id: 'connect-spotify', onclick: connect }, icon('spotify'), 'Conectar con Spotify'))),
      worklistSection());
      renderWorklist();
      return;
    }
    clear(body, h('div', { class: 'row between mb' }, seg([
      { value: 'search', label: 'Buscar' }, { value: 'playlists', label: 'Mis playlists' },
      { value: 'saved', label: 'Canciones guardadas' }, { value: 'worklist', label: 'Lista de trabajo' },
    ], tab, (v) => { tab = v; history.replaceState(null, '', `#/spotify?tab=${v}`); renderTabs(); })), h('div', { id: 'sp-content' }));
    renderTabs();
  }

  async function connect() {
    try {
      const { url } = await api.get('/api/spotify/login');
      if (desktop?.openExternal) desktop.openExternal(url); else window.open(url, 'spotify-auth', 'width=520,height=720');
      toast('Autoriza el acceso en la ventana de Spotify…');
      clearInterval(pollTimer);
      let tries = 0;
      const check = async () => {
        const st = await api.get('/api/spotify/status').catch(() => null);
        if (!pollTimer) return; // already handled
        if (st?.connected || ++tries > 150) {
          clearInterval(pollTimer); pollTimer = null;
          if (st?.connected) { toast('Spotify conectado'); load(); }
        }
      };
      onAuthMessage = (e) => { if (e.data?.type === 'swc-spotify') check(); };
      window.addEventListener('message', onAuthMessage);
      pollTimer = setInterval(check, 2000);
    } catch (e) { toastError(e); }
  }

  function setupCard(st) {
    return h('div', { class: 'card mb' }, h('h2', {}, 'Configura tu aplicación de Spotify'),
      h('ol', { class: 'muted', style: { paddingLeft: '18px', lineHeight: 1.9 } },
        h('li', {}, 'Entra en ', h('a', { href: 'https://developer.spotify.com/dashboard', target: '_blank', rel: 'noopener', onclick: openExternal }, 'developer.spotify.com/dashboard'), ' y crea una app (Web API).'),
        h('li', {}, 'Añade esta Redirect URI: ', h('code', { class: 'mono' }, st.redirect_uri)),
        h('li', {}, 'Copia el Client ID en Configuración. No se necesita Client Secret (se usa PKCE).')),
      h('button', { class: 'btn primary', onclick: () => navigate('settings') }, icon('settings'), 'Ir a Configuración'));
  }

  // ---- tabs ----
  function renderTabs() {
    const c = root.querySelector('#sp-content');
    if (!c) { renderWorklist(); return; }
    if (tab === 'search') return renderSearch(c);
    if (tab === 'playlists') return renderPlaylists(c);
    if (tab === 'saved') return renderSaved(c);
    clear(c, worklistSection());
    renderWorklist();
  }

  let search = { q: '', type: 'track', offset: 0, results: null };
  function renderSearch(c) {
    const input = h('input', { class: 'input', id: 'sp-search', placeholder: 'Buscar canciones, artistas o álbumes…', value: search.q,
      onkeydown: (e) => { if (e.key === 'Enter') run(true); } });
    const results = h('div', { class: 'mt' });
    const run = async (reset) => {
      search.q = input.value.trim();
      if (!search.q) return;
      if (reset) { search.offset = 0; search.results = null; }
      clear(results, h('div', { class: 'empty' }, icon('refresh', 'spin')));
      try {
        const r = await api.get('/api/spotify/search', { q: search.q, type: search.type, offset: search.offset });
        const key = { track: 'tracks', album: 'albums', artist: 'artists' }[search.type];
        search.results = search.results ? { ...r, [key]: [...search.results[key], ...r[key]] } : r;
        showResults();
      } catch (e) { clear(results); toastError(e); }
    };
    const showResults = () => {
      const r = search.results;
      if (!r) return;
      const key = { track: 'tracks', album: 'albums', artist: 'artists' }[search.type];
      const items = r[key];
      const more = items.length < r.total ? h('div', { class: 'row mt', style: { justifyContent: 'center' } },
        h('button', { class: 'btn', onclick: () => { search.offset = items.length; run(false); } }, 'Cargar más')) : null;
      if (search.type === 'track') clear(results, tracksBlock(`Resultados para «${search.q}»`, `${r.total} canciones`, items), more);
      else if (search.type === 'album') clear(results, items.length ? h('div', { class: 'tiles' }, items.map((a) =>
        h('div', { class: 'tile', onclick: () => openAlbum(a.id, results, showResults) }, cover(a.image_url, 'lg'), h('div', { class: 't' }, a.name), h('div', { class: 'a' }, `${a.artists} · ${(a.release_date || '').slice(0, 4)}`))))
        : empty('disc', 'Sin álbumes', ''), more);
      else clear(results, items.length ? h('div', { class: 'tiles' }, items.map((a) =>
        h('div', { class: 'tile', onclick: () => openArtist(a.id, results, showResults) }, cover(a.image_url, 'lg round'), h('div', { class: 't' }, a.name), h('div', { class: 'a' }, a.genres.slice(0, 2).join(', ') || 'Artista'))))
        : empty('user', 'Sin artistas', ''), more);
    };
    clear(c, h('div', { class: 'row' }, h('div', { class: 'search', style: { flex: 1, minWidth: '260px' } }, icon('search'), input),
      seg([{ value: 'track', label: 'Canciones' }, { value: 'artist', label: 'Artistas' }, { value: 'album', label: 'Álbumes' }], search.type,
        (v) => { search.type = v; run(true); }),
      h('button', { class: 'btn primary', id: 'sp-search-btn', onclick: () => run(true) }, 'Buscar')), results);
    if (search.results) showResults();
    else clear(results, empty('search', 'Explora el catálogo de Spotify', 'Escribe el nombre de una canción, artista o álbum.'));
    input.focus();
  }

  async function openAlbum(id, container, back) {
    clear(container, h('div', { class: 'empty' }, icon('refresh', 'spin')));
    try {
      const r = await api.get(`/api/spotify/albums/${encodeURIComponent(id)}`);
      clear(container, tracksBlock(r.album.name, `${r.album.artists} · ${(r.album.release_date || '').slice(0, 4)} · ${r.tracks.length} canciones`, r.tracks, r.album.image_url, back));
    } catch (e) { toastError(e); back && back(); }
  }

  async function openArtist(id, container, back) {
    clear(container, h('div', { class: 'empty' }, icon('refresh', 'spin')));
    try {
      const r = await api.get(`/api/spotify/artists/${encodeURIComponent(id)}`);
      const self = () => openArtist(id, container, back);
      clear(container, h('div', { class: 'row mb' }, h('button', { class: 'btn ghost icon', onclick: back, title: 'Volver' }, icon('up')),
        cover(r.artist.image_url), h('div', {}, h('h2', { style: { margin: 0, fontSize: '18px' } }, r.artist.name), h('div', { class: 'muted' }, r.artist.genres.join(', ')))),
      r.albums.length ? h('div', { class: 'tiles' }, r.albums.map((a) => h('div', { class: 'tile', onclick: () => openAlbum(a.id, container, self) },
        cover(a.image_url, 'lg'), h('div', { class: 't' }, a.name), h('div', { class: 'a' }, (a.release_date || '').slice(0, 4))))) : empty('disc', 'Sin álbumes', ''));
    } catch (e) { toastError(e); back && back(); }
  }

  async function renderPlaylists(c) {
    clear(c, h('div', { class: 'empty' }, icon('refresh', 'spin')));
    try {
      const r = await api.get('/api/spotify/playlists');
      const show = () => clear(c, r.items.length ? h('div', { class: 'tiles' }, r.items.map((p) =>
        h('div', { class: 'tile', onclick: async () => {
          clear(c, h('div', { class: 'empty' }, icon('refresh', 'spin')));
          try {
            const tracks = await api.get(`/api/spotify/playlists/${encodeURIComponent(p.id)}`);
            clear(c, tracksBlock(p.name, `${p.owner} · ${tracks.length} canciones`, tracks, p.image_url, show));
          } catch (e) { toastError(e); show(); }
        } }, cover(p.image_url, 'lg'), h('div', { class: 't' }, p.name), h('div', { class: 'a' }, `${p.owner} · ${p.total} canciones`))))
        : empty('music', 'No tienes playlists', ''));
      show();
    } catch (e) { clear(c); toastError(e); }
  }

  async function renderSaved(c) {
    clear(c, h('div', { class: 'empty' }, icon('refresh', 'spin')));
    try {
      const tracks = await api.get('/api/spotify/saved');
      clear(c, tracksBlock('Canciones guardadas', `${tracks.length} canciones`, tracks));
    } catch (e) { clear(c); toastError(e); }
  }

  // ---- work list ----
  function worklistSection() { return h('div', { id: 'worklist', class: 'mt' }); }

  async function renderWorklist() {
    const box = root.querySelector('#worklist');
    if (!box) return;
    const wl = await refreshWorklistIds();
    const available = wl.filter((t) => t.local_track_id);
    clear(box, h('div', { class: 'row between mb' },
      h('div', {}, h('h2', { style: { margin: 0, fontSize: '18px' } }, 'Lista de trabajo'),
        h('div', { class: 'muted' }, `${wl.length} canciones · ${available.length} con archivo local`)),
      h('div', { class: 'actions' },
        h('button', { class: 'btn', disabled: !wl.length, onclick: async () => {
          try { const r = await api.post('/api/worklist/match'); toast(`${r.linked.length} coincidencias encontradas · ${r.unmatched} sin archivo local`); renderWorklist(); } catch (e) { toastError(e); }
        } }, icon('link'), 'Asociar con archivos locales'),
        h('button', { class: 'btn primary', disabled: !available.length, onclick: () => {
          state.addToSelection(available.map((t) => t.local_track_id)); navigate('convert');
        } }, icon('wave'), `Convertir disponibles (${available.length})`))),
    wl.length ? h('div', { class: 'table-wrap' }, h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, 'Canción'), h('th', {}, 'Álbum'), h('th', {}, 'Duración'), h('th', {}, 'Archivo local'), h('th', {}, ''))),
      h('tbody', {}, wl.map((t) => h('tr', {},
        h('td', {}, h('div', { class: 'track-cell' }, cover(t.image_url), h('div', { class: 'track-meta' }, h('div', { class: 't' }, t.name), h('div', { class: 'a' }, t.artists)))),
        h('td', { class: 'trunc muted' }, t.album),
        h('td', { class: 'num muted' }, fmtDuration(t.duration_ms / 1000)),
        h('td', {}, t.local_track_id ? h('span', { class: 'badge green' }, icon('check'), 'Disponible') : h('span', { class: 'badge yellow' }, 'Sin archivo')),
        h('td', {}, h('div', { class: 'row', style: { flexWrap: 'nowrap', justifyContent: 'flex-end' } },
          h('button', { class: 'btn ghost sm', onclick: () => chooseLocal(t) }, icon('link'), 'Asociar'),
          h('button', { class: 'btn ghost icon danger', title: 'Quitar de la lista', onclick: async () => {
            await api.post('/api/worklist/remove', { ids: [t.id] }); renderWorklist();
          } }, icon('trash')))))))))
      : empty('music', 'Tu lista de trabajo está vacía', 'Añade canciones desde la búsqueda o tus playlists. Después podrás asociarlas con tus archivos locales y convertirlas a WAV.'));
  }

  async function chooseLocal(t) {
    const cands = await api.get(`/api/worklist/${encodeURIComponent(t.id)}/candidates`);
    let m;
    const body = cands.length ? h('div', { class: 'list' }, cands.map((c) => h('div', { class: 'list-item' },
      h('div', { class: 'grow track-meta' }, h('div', { class: 't' }, c.title), h('div', { class: 'a' }, `${c.artist} · ${c.album} · ${fmtDuration(c.duration)} · ${c.format.toUpperCase()}`)),
      h('span', { class: `badge ${c.score >= 0.78 ? 'green' : 'yellow'}` }, `${Math.round(c.score * 100)}%`),
      h('button', { class: 'btn sm', onclick: async () => {
        await api.put(`/api/library/${c.id}/spotify`, { spotify_id: t.id }); toast('Asociación guardada'); m.close(); renderWorklist();
      } }, 'Asociar'))))
      : empty('library', 'Sin candidatos', 'Importa el archivo de audio correspondiente para poder asociarlo.');
    m = modal({ title: `Asociar «${t.name}»`, body, wide: true });
  }

  function openExternal(e) {
    if (desktop?.openExternal) { e.preventDefault(); desktop.openExternal(e.currentTarget.href); }
  }

  await load();
  return () => { clearInterval(pollTimer); pollTimer = null; if (onAuthMessage) window.removeEventListener('message', onAuthMessage); };
}
