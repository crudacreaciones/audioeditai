import { api } from '../api.js';
import { navigate, playPreview, state } from '../state.js';
import { clear, confirmDialog, cover, empty, fmtBytes, fmtDuration, fmtRate, h, icon, modal, seg, toast, toastError } from '../ui.js';

const FIELDS = [
  ['title', 'Título'], ['artist', 'Artista'], ['album', 'Álbum'], ['album_artist', 'Artista del álbum'],
  ['genre', 'Género'], ['year', 'Año'], ['track_no', 'Nº de pista'],
];

export default async function libraryView(root, params) {
  const filters = { q: params.get('q') || '', artist: params.get('artist') || '', album: params.get('album') || '', genre: params.get('genre') || '', sort: 'artist' };
  let facetKind = 'artist';
  let items = [];
  const selected = new Set();
  let searchTimer;

  const searchInput = h('input', { class: 'input', id: 'lib-search', placeholder: 'Buscar por título, artista, álbum, género o ruta…', value: filters.q,
    oninput: () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { filters.q = searchInput.value.trim(); load(); }, 250); } });
  const sortSel = h('select', { class: 'input', style: { width: '170px' }, onchange: () => { filters.sort = sortSel.value; load(); } },
    [['artist', 'Artista / álbum'], ['title', 'Título'], ['album', 'Álbum'], ['added', 'Recientes'], ['duration', 'Duración']].map(([v, l]) => h('option', { value: v }, l)));
  const convertBtn = h('button', { class: 'btn primary', id: 'lib-convert', onclick: () => {
    state.addToSelection([...selected]); toast(`${selected.size} pista(s) añadidas a la cola de conversión`); navigate('convert');
  } });
  const removeBtn = h('button', { class: 'btn danger', onclick: removeSelected }, icon('trash'), 'Quitar');
  const chips = h('div', { class: 'row' });
  const tableBox = h('div');
  const facetBox = h('div', { class: 'facet-list' });
  const countLabel = h('span', { class: 'muted' });

  root.append(
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, 'Biblioteca musical'), h('p', {}, 'Tu colección local: busca, clasifica, edita metadatos y escucha una vista previa.')),
      h('div', { class: 'actions' },
        h('button', { class: 'btn', onclick: showDuplicates }, icon('copy'), 'Duplicados'),
        h('button', { class: 'btn', onclick: () => navigate('import') }, icon('import'), 'Importar'))),
    h('div', { class: 'split narrow' },
      h('div', {},
        h('div', { class: 'row mb' }, h('div', { class: 'search', style: { flex: 1, minWidth: '240px' } }, icon('search'), searchInput), sortSel),
        h('div', { class: 'row between mb' }, h('div', { class: 'row' }, countLabel, chips), h('div', { class: 'actions' }, removeBtn, convertBtn)),
        tableBox),
      h('div', { class: 'card' },
        h('h3', {}, 'Clasificar'),
        seg([{ value: 'artist', label: 'Artista' }, { value: 'album', label: 'Álbum' }, { value: 'genre', label: 'Género' }], facetKind,
          (v) => { facetKind = v; loadFacets(); }),
        h('div', { class: 'mt' }, facetBox))));

  function updateButtons() {
    clear(convertBtn, icon('wave'), selected.size ? `Convertir (${selected.size})` : 'Convertir');
    convertBtn.disabled = !selected.size;
    removeBtn.disabled = !selected.size;
  }

  function renderChips() {
    clear(chips, ['artist', 'album', 'genre'].filter((k) => filters[k]).map((k) =>
      h('span', { class: 'badge blue', style: { cursor: 'pointer' }, title: 'Quitar filtro', onclick: () => { filters[k] = ''; load(); loadFacets(); } },
        `${{ artist: 'Artista', album: 'Álbum', genre: 'Género' }[k]}: ${filters[k]}`, icon('x'))));
  }

  async function loadFacets() {
    const f = await api.get('/api/library/facets');
    const list = f[facetKind];
    clear(facetBox, list.length ? list.map((x) => h('div', { class: `facet ${filters[facetKind] === x.value ? 'on' : ''}`,
      onclick: () => { filters[facetKind] = filters[facetKind] === x.value ? '' : x.value; load(); loadFacets(); } },
    h('span', {}, x.value), h('span', { class: 'dim num' }, x.count))) : h('div', { class: 'dim' }, 'Sin datos'));
  }

  async function load() {
    renderChips();
    const r = await api.get('/api/library', { q: filters.q, artist: filters.artist, album: filters.album, genre: filters.genre, sort: filters.sort });
    items = r.items;
    for (const id of [...selected]) if (!items.some((t) => t.id === id)) selected.delete(id);
    countLabel.textContent = `${r.total} pista(s)`;
    renderTable();
    updateButtons();
  }

  function renderTable() {
    if (!items.length) {
      const any = filters.q || filters.artist || filters.album || filters.genre;
      clear(tableBox, h('div', { class: 'card' }, any ? empty('search', 'Sin coincidencias', 'Cambia la búsqueda o quita los filtros.')
        : empty('library', 'Tu biblioteca está vacía', 'Importa archivos MP3, FLAC, M4A, AAC, OGG o WAV para empezar.',
          h('button', { class: 'btn primary', onclick: () => navigate('import') }, icon('import'), 'Importar archivos'))));
      return;
    }
    const all = h('input', { type: 'checkbox', checked: items.length && items.every((t) => selected.has(t.id)),
      onchange: (e) => { items.forEach((t) => (e.target.checked ? selected.add(t.id) : selected.delete(t.id))); renderTable(); updateButtons(); } });
    clear(tableBox, h('div', { class: 'table-wrap', style: { maxHeight: 'calc(100vh - 260px)' } }, h('table', { id: 'lib-table' },
      h('thead', {}, h('tr', {}, h('th', {}, all), h('th', {}, ''), h('th', {}, 'Título'), h('th', {}, 'Álbum'), h('th', {}, 'Género'),
        h('th', {}, 'Formato'), h('th', {}, 'Duración'), h('th', {}, 'Spotify'), h('th', {}, ''))),
      h('tbody', {}, items.map((t) => h('tr', { class: selected.has(t.id) ? 'selected' : '', 'data-id': t.id },
        h('td', {}, h('input', { type: 'checkbox', checked: selected.has(t.id), onchange: (e) => {
          e.target.checked ? selected.add(t.id) : selected.delete(t.id);
          e.target.closest('tr').classList.toggle('selected', e.target.checked); updateButtons();
        } })),
        h('td', {}, h('button', { class: 'btn ghost icon', title: 'Vista previa', onclick: () => playPreview({
          url: `/api/library/${t.id}/stream`, title: t.title, subtitle: t.artist, image: t.spotify_image }) }, icon('play'))),
        h('td', { class: 'trunc' }, h('div', { class: 'track-cell' }, t.spotify_image ? cover(t.spotify_image) : null,
          h('div', { class: 'track-meta' }, h('div', { class: 't' }, t.title || '—'), h('div', { class: 'a' }, t.artist || 'Artista desconocido')))),
        h('td', { class: 'trunc muted' }, t.album),
        h('td', { class: 'muted' }, t.genre),
        h('td', {}, h('span', { class: 'badge' }, t.format.toUpperCase()),
          h('div', { class: 'dim num', style: { fontSize: '12px', marginTop: '2px' } },
            `${fmtRate(t.sample_rate)}${t.bit_depth ? ` · ${t.bit_depth}-bit` : ''} · ${t.channels === 1 ? 'mono' : t.channels === 2 ? 'estéreo' : `${t.channels} can.`}`)),
        h('td', { class: 'num muted' }, fmtDuration(t.duration)),
        h('td', {}, t.spotify_id ? h('span', { class: 'badge green', title: t.spotify_name }, icon('check'), 'Asociada') : h('span', { class: 'dim' }, '—')),
        h('td', {}, h('div', { class: 'row', style: { flexWrap: 'nowrap' } },
          t.wav_count ? h('span', { class: 'badge blue', title: 'Conversiones WAV completadas' }, `WAV ×${t.wav_count}`) : null,
          h('button', { class: 'btn ghost icon', title: 'Editar metadatos', onclick: () => editTrack(t.id) }, icon('edit'))))))))));
  }

  async function removeSelected() {
    if (!(await confirmDialog('Quitar de la biblioteca', `Se quitarán ${selected.size} pista(s) de la biblioteca. Los archivos del disco NO se borran.`, 'Quitar', 'danger'))) return;
    const ids = [...selected];
    await api.post('/api/library/remove', { ids });
    state.setSelection([...state.selection].filter((id) => !ids.includes(id)));
    selected.clear();
    toast('Pistas quitadas de la biblioteca');
    load(); loadFacets();
  }

  async function editTrack(id) {
    const t = await api.get(`/api/library/${id}`);
    const inputs = {};
    const writeFile = h('input', { type: 'checkbox' });
    const linkBox = h('div');
    async function renderLink(track) {
      const cands = await api.get(`/api/library/${id}/candidates`);
      clear(linkBox, h('h3', { style: { fontSize: '14px', margin: '18px 0 8px' } }, 'Canción de Spotify asociada'),
        track.spotify_id
          ? h('div', { class: 'list-item', style: { padding: '8px 0' } }, cover(track.spotify_image), h('div', { class: 'grow track-meta' }, h('div', { class: 't' }, track.spotify_name), h('div', { class: 'a' }, track.spotify_artists)),
            h('button', { class: 'btn sm danger', onclick: async () => { renderLink(await api.put(`/api/library/${id}/spotify`, { spotify_id: null })); load(); } }, 'Desasociar'))
          : cands.length
            ? h('div', { class: 'list' }, cands.slice(0, 4).map((c) => h('div', { class: 'list-item' }, cover(c.image_url),
              h('div', { class: 'grow track-meta' }, h('div', { class: 't' }, c.name), h('div', { class: 'a' }, `${c.artists} · ${fmtDuration(c.duration_ms / 1000)}`)),
              h('span', { class: `badge ${c.score >= 0.78 ? 'green' : 'yellow'}` }, `${Math.round(c.score * 100)}%`),
              h('button', { class: 'btn sm', onclick: async () => { renderLink(await api.put(`/api/library/${id}/spotify`, { spotify_id: c.id })); load(); } }, 'Asociar'))))
            : h('p', { class: 'dim' }, 'Añade canciones a la lista de trabajo de Spotify para poder asociarlas.'));
    }
    const body = h('div', {},
      h('div', { class: 'form-grid' }, FIELDS.map(([k, label]) => h('label', { class: 'field' }, label, inputs[k] = h('input', { class: 'input', name: k, value: t[k] || '' })))),
      h('label', { class: 'check mt' }, writeFile, 'Escribir también las etiquetas en el archivo de audio'),
      h('dl', { class: 'kv mt' },
        h('dt', {}, 'Archivo'), h('dd', { class: 'mono' }, t.path),
        h('dt', {}, 'Códec'), h('dd', {}, `${t.codec} · ${fmtRate(t.sample_rate)} · ${t.bit_depth || '—'} bits · ${t.channels} canal(es)`),
        h('dt', {}, 'Tamaño'), h('dd', {}, `${fmtBytes(t.size)}${t.bitrate ? ` · ${Math.round(t.bitrate / 1000)} kbps` : ''}`),
        h('dt', {}, 'SHA-256'), h('dd', { class: 'mono dim' }, t.file_hash)),
      linkBox);
    renderLink(t);
    modal({ title: 'Editar metadatos', wide: true, body, actions: [
      { label: 'Cancelar' },
      { label: 'Guardar', kind: 'primary', onClick: async () => {
        const values = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value]));
        await api.put(`/api/library/${id}`, { values, write_to_file: writeFile.checked });
        toast('Metadatos guardados');
        load(); loadFacets();
      } }] });
  }

  async function showDuplicates() {
    const groups = await api.get('/api/library/duplicates');
    const body = groups.length ? h('div', {}, groups.map((g) => h('div', { class: 'card mb' },
      h('div', { class: 'row between' }, h('b', {}, g.items[0].title || 'Sin título'), h('span', { class: `badge ${g.kind === 'exact' ? 'red' : 'yellow'}` }, g.kind === 'exact' ? 'Idénticos' : 'Probables')),
      h('div', { class: 'hint' }, g.reason),
      h('div', { class: 'list mt' }, g.items.map((t) => h('div', { class: 'list-item' }, h('span', { class: 'badge' }, t.format.toUpperCase()),
        h('div', { class: 'grow mono', style: { overflow: 'hidden', textOverflow: 'ellipsis' } }, t.path), h('span', { class: 'dim num' }, `${fmtDuration(t.duration)} · ${fmtBytes(t.size)}`)))))))
      : empty('check', 'No hay duplicados', 'No se encontraron archivos repetidos en tu biblioteca.');
    modal({ title: 'Archivos duplicados', body, wide: true });
  }

  await Promise.all([load(), loadFacets()]);
}
