import { api } from '../api.js';
import { navigate, playPreview, state } from '../state.js';
import { clear, confirmDialog, empty, fmtBytes, fmtDuration, fmtSpec, h, icon, modal, pickFolder, progressBar, seg, statusBadge, toast, toastError } from '../ui.js';

export default async function convertView(root) {
  const settings = await api.get('/api/settings');
  const opts = { sample_rate: settings.default_sample_rate, bit_depth: settings.default_bit_depth, channels: settings.default_channels };
  let timer = null;
  let tracks = [];
  const exportSel = new Set();

  const queueBox = h('div');
  const jobsBox = h('div');
  const outDir = h('input', { class: 'input mono', value: settings.output_dir });
  const pattern = h('input', { class: 'input mono', value: settings.naming_pattern });
  const estimate = h('div', { class: 'hint' });
  const startBtn = h('button', { class: 'btn primary', id: 'conv-start', onclick: start });
  const exportBtn = h('button', { class: 'btn', id: 'conv-export', onclick: exportSelected });
  const cancelAllBtn = h('button', { class: 'btn danger', onclick: async () => {
    if (await confirmDialog('Cancelar todo', 'Se cancelarán todas las conversiones en cola y en curso.', 'Cancelar todo', 'danger')) {
      const r = await api.post('/api/conversions/cancel-all'); toast(`${r.cancelled} conversión(es) cancelada(s)`); refreshJobs();
    } } }, icon('stop'), 'Cancelar todo');

  const rates = state.system?.options?.sample_rates || [44100, 48000, 88200, 96000, 192000];
  root.append(
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Conversión WAV'),
      h('p', {}, 'Convierte tus archivos a WAV PCM de alta calidad, individualmente o por lotes.'))),
    h('div', { class: 'split' },
      h('div', { class: 'card' },
        h('div', { class: 'card-head' }, h('h2', {}, 'Pistas seleccionadas'),
          h('div', { class: 'actions' },
            h('button', { class: 'btn ghost sm', onclick: () => { state.setSelection([]); loadQueue(); } }, 'Vaciar'),
            h('button', { class: 'btn sm', onclick: () => navigate('library') }, icon('plus'), 'Añadir desde biblioteca'))),
        queueBox),
      h('div', { class: 'card' }, h('h2', {}, 'Formato de salida'),
        h('div', { class: 'opt-group' }, h('div', { class: 'title' }, 'Frecuencia de muestreo'),
          seg(rates.map((r) => ({ value: r, label: `${(r / 1000).toLocaleString('es-ES')} kHz` })), opts.sample_rate, (v) => { opts.sample_rate = Number(v); updateEstimate(); })),
        h('div', { class: 'opt-group mt' }, h('div', { class: 'title' }, 'Profundidad de bits'),
          seg([{ value: '16', label: '16 bits' }, { value: '24', label: '24 bits' }, { value: '32f', label: '32 bits float' }], opts.bit_depth, (v) => { opts.bit_depth = v; updateEstimate(); })),
        h('div', { class: 'opt-group mt' }, h('div', { class: 'title' }, 'Canales'),
          seg([{ value: 2, label: 'Estéreo' }, { value: 1, label: 'Mono' }], opts.channels, (v) => { opts.channels = Number(v); updateEstimate(); })),
        h('label', { class: 'field mt' }, 'Carpeta de salida', h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, outDir,
          h('button', { class: 'btn icon', title: 'Examinar', onclick: async () => { const p = await pickFolder('Carpeta de salida', outDir.value); if (p) outDir.value = p; } }, icon('folder')))),
        h('label', { class: 'field mt' }, 'Nombre de archivo', pattern,
          h('span', { class: 'hint' }, 'Variables: {artist} {title} {album} {album_artist} {genre} {year} {track_no}')),
        h('div', { class: 'mt' }, estimate),
        h('div', { class: 'row mt' }, startBtn))),
    h('div', { class: 'row between mt mb' }, h('h2', { style: { margin: 0, fontSize: '18px' } }, 'Cola y resultados'), h('div', { class: 'actions' }, cancelAllBtn, exportBtn)),
    jobsBox);

  function bytesPerSec() { return opts.sample_rate * opts.channels * (opts.bit_depth === '16' ? 2 : opts.bit_depth === '24' ? 3 : 4); }
  function updateEstimate() {
    const secs = tracks.reduce((a, t) => a + (t.duration || 0), 0);
    estimate.textContent = tracks.length
      ? `${tracks.length} pista(s) · ${fmtDuration(secs)} · tamaño estimado ${fmtBytes(secs * bytesPerSec())} (${fmtBytes(60 * bytesPerSec())}/min)`
      : `${fmtBytes(60 * bytesPerSec())} por minuto de audio`;
    clear(startBtn, icon('wave'), tracks.length > 1 ? `Convertir ${tracks.length} pistas` : 'Convertir');
    startBtn.disabled = !tracks.length;
  }

  async function loadQueue() {
    const ids = [...state.selection];
    tracks = [];
    if (ids.length) {
      const lib = await api.get('/api/library', { limit: 5000 });
      const byId = new Map(lib.items.map((t) => [t.id, t]));
      tracks = ids.map((id) => byId.get(id)).filter(Boolean);
      if (tracks.length !== ids.length) state.setSelection(tracks.map((t) => t.id));
    }
    clear(queueBox, tracks.length ? h('div', { class: 'list', style: { maxHeight: '420px', overflowY: 'auto' } }, tracks.map((t) => h('div', { class: 'list-item' },
      h('span', { class: 'badge' }, t.format.toUpperCase()),
      h('div', { class: 'grow track-meta' }, h('div', { class: 't' }, t.title), h('div', { class: 'a' }, `${t.artist} · ${fmtDuration(t.duration)}`)),
      h('button', { class: 'btn ghost icon', title: 'Quitar', onclick: () => { state.setSelection(tracks.filter((x) => x.id !== t.id).map((x) => x.id)); loadQueue(); } }, icon('x')))))
      : empty('library', 'No hay pistas seleccionadas', 'Elige canciones en la biblioteca o en la lista de trabajo de Spotify.',
        h('button', { class: 'btn', onclick: () => navigate('library') }, 'Ir a la biblioteca')));
    updateEstimate();
  }

  async function start() {
    try {
      const r = await api.post('/api/conversions', { track_ids: tracks.map((t) => t.id), ...opts, output_dir: outDir.value.trim() || null, naming_pattern: pattern.value.trim() || null });
      toast(`${r.job_ids.length} conversión(es) en cola`);
      state.setSelection([]);
      loadQueue();
      refreshJobs();
    } catch (e) { toastError(e); }
  }

  async function exportSelected() {
    const dest = await pickFolder('Exportar WAV a…');
    if (!dest) return;
    try {
      const r = await api.post('/api/export', { conversion_ids: [...exportSel], dest_dir: dest });
      toast(`${r.exported.length} archivo(s) exportado(s)${r.errors.length ? ` · ${r.errors.length} error(es)` : ''}`, r.errors.length ? 'warn' : 'ok');
      exportSel.clear(); refreshJobs();
    } catch (e) { toastError(e); }
  }

  function showReport(j) {
    const rep = j.verify_report;
    modal({ title: 'Verificación de integridad', body: h('div', {},
      h('dl', { class: 'kv' }, h('dt', {}, 'Archivo'), h('dd', { class: 'mono' }, j.output_path),
        h('dt', {}, 'Formato'), h('dd', {}, fmtSpec(j)), h('dt', {}, 'Tamaño'), h('dd', {}, fmtBytes(j.output_size)),
        h('dt', {}, 'SHA-256'), h('dd', { class: 'mono dim' }, j.output_hash || '—')),
      h('div', { class: 'checks mt' }, (rep?.checks || []).map((c) => h('div', { class: 'row' },
        h('span', { class: `badge ${c.ok ? 'green' : 'red'}` }, c.ok ? 'OK' : 'FALLO'), h('b', {}, c.name), h('span', { class: 'dim' }, c.detail))))),
    actions: [{ label: 'Volver a verificar', onClick: async () => {
      const r = await api.post(`/api/conversions/${j.id}/verify`); toast(r.ok ? 'Archivo verificado correctamente' : 'La verificación falló', r.ok ? 'ok' : 'error'); refreshJobs();
    } }, { label: 'Cerrar', kind: 'primary' }] });
  }

  async function refreshJobs() {
    clearTimeout(timer);
    let jobs;
    try { jobs = await api.get('/api/conversions', { limit: 100 }); } catch { timer = setTimeout(refreshJobs, 2000); return; }
    const active = jobs.filter((j) => ['queued', 'running'].includes(j.status));
    cancelAllBtn.disabled = !active.length;
    for (const id of [...exportSel]) if (!jobs.some((j) => j.id === id && j.status === 'done' && j.output_exists)) exportSel.delete(id);
    const updateExport = () => { clear(exportBtn, icon('export'), exportSel.size ? `Exportar (${exportSel.size})` : 'Exportar'); exportBtn.disabled = !exportSel.size; };
    updateExport();
    const exportable = jobs.filter((j) => j.status === 'done' && j.output_exists);
    const all = h('input', { type: 'checkbox', title: 'Seleccionar todos los completados', checked: exportable.length && exportable.every((j) => exportSel.has(j.id)),
      onchange: (e) => { exportable.forEach((j) => (e.target.checked ? exportSel.add(j.id) : exportSel.delete(j.id))); refreshJobs(); } });
    clear(jobsBox, jobs.length ? h('div', { class: 'table-wrap' }, h('table', { id: 'jobs-table' },
      h('thead', {}, h('tr', {}, h('th', {}, all), h('th', {}, 'Archivo'), h('th', {}, 'Formato'), h('th', {}, 'Estado'), h('th', {}, 'Progreso'), h('th', {}, ''))),
      h('tbody', {}, jobs.map((j) => {
        const can = j.status === 'done' && j.output_exists;
        return h('tr', { 'data-status': j.status },
          h('td', {}, can ? h('input', { type: 'checkbox', checked: exportSel.has(j.id), onchange: (e) => { e.target.checked ? exportSel.add(j.id) : exportSel.delete(j.id); updateExport(); } }) : null),
          h('td', { class: 'trunc' }, h('div', { class: 'track-meta' }, h('div', { class: 't' }, j.output_path.split(/[\\/]/).pop()),
            h('div', { class: 'a' }, j.error ? h('span', { style: { color: 'var(--danger)' } }, j.error.slice(0, 120)) : (j.title ? `${j.artist} · ${j.title}` : j.source_path)))),
          h('td', { class: 'muted' }, fmtSpec(j)),
          h('td', {}, statusBadge(j.status), j.verified ? h('span', { class: 'badge green', style: { marginLeft: '6px', cursor: 'pointer' }, onclick: () => showReport(j), title: 'Ver verificación' }, icon('shield'), 'Verificado') : null),
          h('td', {}, j.status === 'running' ? h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, progressBar(j.progress), h('span', { class: 'num dim' }, `${Math.round(j.progress * 100)}%`))
            : j.status === 'done' ? h('span', { class: 'dim' }, fmtBytes(j.output_size)) : j.status === 'queued' ? progressBar(0) : null),
          h('td', {}, h('div', { class: 'row', style: { flexWrap: 'nowrap', justifyContent: 'flex-end' } },
            can ? h('button', { class: 'btn ghost icon', title: 'Escuchar WAV', onclick: () => playPreview({ url: `/api/conversions/${j.id}/stream`, title: j.title || j.output_path.split(/[\\/]/).pop(), subtitle: fmtSpec(j) }) }, icon('play')) : null,
            can ? h('button', { class: 'btn ghost icon', title: 'Verificación', onclick: () => showReport(j) }, icon('shield')) : null,
            ['queued', 'running'].includes(j.status) ? h('button', { class: 'btn sm danger', onclick: () => api.post(`/api/conversions/${j.id}/cancel`).then(refreshJobs) }, 'Cancelar') : null,
            ['failed', 'cancelled'].includes(j.status) ? h('button', { class: 'btn sm', onclick: () => api.post(`/api/conversions/${j.id}/retry`).then(refreshJobs).catch(toastError) }, icon('refresh'), 'Reintentar') : null)));
      }))))
      : h('div', { class: 'card' }, empty('wave', 'Todavía no hay conversiones', 'Selecciona pistas y pulsa Convertir.')));
    timer = setTimeout(refreshJobs, active.length ? 800 : 3000);
  }

  await loadQueue();
  await refreshJobs();
  return () => clearTimeout(timer);
}
