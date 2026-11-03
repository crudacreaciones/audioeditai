import { api } from '../api.js';
import { clear, confirmDialog, empty, fmtBytes, fmtDate, fmtSpec, h, icon, seg, statusBadge, toast } from '../ui.js';

export default async function historyView(root, params) {
  let tab = params.get('tab') || 'conversions';
  let status = '';
  let level = '';
  const content = h('div', { class: 'mt' });
  const tools = h('div', { class: 'actions' });

  root.append(
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Historial'), h('p', {}, 'Conversiones realizadas y registro de operaciones (logs).'))),
    h('div', { class: 'row between' }, seg([{ value: 'conversions', label: 'Conversiones' }, { value: 'logs', label: 'Registro de operaciones' }], tab,
      (v) => { tab = v; render(); }), tools),
    content);

  async function render() {
    if (tab === 'conversions') {
      clear(tools, seg([{ value: '', label: 'Todas' }, { value: 'done', label: 'Completadas' }, { value: 'failed', label: 'Errores' }, { value: 'cancelled', label: 'Canceladas' }], status, (v) => { status = v; render(); }),
        h('button', { class: 'btn danger sm', onclick: async () => {
          if (await confirmDialog('Vaciar historial', 'Se eliminarán los registros de conversiones finalizadas. Los archivos WAV no se borran.', 'Vaciar', 'danger')) {
            const r = await api.del('/api/conversions'); toast(`${r.removed} registros eliminados`); render();
          } } }, icon('trash'), 'Vaciar'));
      const jobs = await api.get('/api/conversions', { status: status || undefined, limit: 500 });
      clear(content, jobs.length ? h('div', { class: 'table-wrap' }, h('table', {},
        h('thead', {}, h('tr', {}, h('th', {}, 'Fecha'), h('th', {}, 'Origen'), h('th', {}, 'Salida'), h('th', {}, 'Formato'), h('th', {}, 'Estado'), h('th', {}, 'Tamaño'))),
        h('tbody', {}, jobs.map((j) => h('tr', {},
          h('td', { class: 'muted' }, fmtDate(j.finished_at || j.created_at)),
          h('td', { class: 'trunc mono', title: j.source_path }, j.source_path.split(/[\\/]/).pop()),
          h('td', { class: 'trunc mono', title: j.output_path }, j.output_path.split(/[\\/]/).pop(), j.status === 'done' && !j.output_exists ? h('span', { class: 'badge red', style: { marginLeft: '6px' } }, 'No encontrado') : null),
          h('td', { class: 'muted' }, fmtSpec(j)),
          h('td', { title: j.error }, statusBadge(j.status), j.verified ? h('span', { class: 'badge green', style: { marginLeft: '6px' } }, 'Verificado') : null),
          h('td', { class: 'muted num' }, j.output_size ? fmtBytes(j.output_size) : '—'))))))
        : h('div', { class: 'card' }, empty('history', 'Sin conversiones', '')));
    } else {
      clear(tools, seg([{ value: '', label: 'Todo' }, { value: 'info', label: 'Info' }, { value: 'warning', label: 'Avisos' }, { value: 'error', label: 'Errores' }], level, (v) => { level = v; render(); }),
        h('button', { class: 'btn danger sm', onclick: async () => {
          if (await confirmDialog('Vaciar registro', 'Se eliminarán las entradas del registro de la base de datos (el archivo de log se conserva).', 'Vaciar', 'danger')) { await api.del('/api/logs'); render(); }
        } }, icon('trash'), 'Vaciar'));
      const logs = await api.get('/api/logs', { level: level || undefined, limit: 500 });
      clear(content, logs.length ? h('div', { class: 'table-wrap' }, h('table', {},
        h('thead', {}, h('tr', {}, h('th', {}, 'Fecha'), h('th', {}, 'Nivel'), h('th', {}, 'Categoría'), h('th', {}, 'Mensaje'))),
        h('tbody', {}, logs.map((l) => h('tr', {},
          h('td', { class: 'muted' }, fmtDate(l.ts)),
          h('td', {}, h('span', { class: `badge ${l.level === 'error' ? 'red' : l.level === 'warning' ? 'yellow' : 'blue'}` }, l.level)),
          h('td', { class: 'muted' }, l.category),
          h('td', { class: 'wrap' }, l.message, l.details ? h('div', { class: 'mono dim', style: { marginTop: '2px', wordBreak: 'break-all' } }, l.details) : null))))))
        : h('div', { class: 'card' }, empty('history', 'El registro está vacío', '')));
    }
  }
  await render();
}
