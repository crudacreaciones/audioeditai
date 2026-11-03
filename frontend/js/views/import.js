import { api } from '../api.js';
import { navigate, state } from '../state.js';
import { clear, desktop, empty, fmtDate, h, icon, pickFolder, pickPaths, progressBar, toast, toastError } from '../ui.js';

export default async function importView(root) {
  const paths = new Set();
  let timer = null;
  const pathList = h('div', { class: 'list' });
  const manual = h('input', { class: 'input mono', id: 'imp-path', placeholder: 'Pega una ruta de archivo o carpeta y pulsa Intro…',
    onkeydown: (e) => { if (e.key === 'Enter' && manual.value.trim()) { paths.add(manual.value.trim()); manual.value = ''; renderPaths(); } } });
  const recursive = h('input', { type: 'checkbox', checked: true });
  const skipDup = h('input', { type: 'checkbox', checked: true });
  const startBtn = h('button', { class: 'btn primary', id: 'imp-start', onclick: start }, icon('import'), 'Importar');
  const jobsBox = h('div');
  const exts = (state.system?.options?.extensions || ['.mp3', '.flac', '.m4a', '.aac', '.ogg', '.wav']).map((e) => e.slice(1).toUpperCase());

  const drop = h('div', { class: 'dropzone' }, icon('import'),
    h('h3', { style: { margin: '10px 0 4px' } }, desktop ? 'Arrastra aquí archivos o carpetas' : 'Selecciona archivos o carpetas'),
    h('p', { class: 'muted', style: { margin: '0 0 14px' } }, `Formatos admitidos: ${[...new Set(exts)].join(', ')}`),
    h('div', { class: 'row', style: { justifyContent: 'center' } },
      h('button', { class: 'btn', id: 'imp-browse', onclick: async () => {
        const r = await pickPaths();
        if (r && r.length) { r.forEach((p) => paths.add(p)); renderPaths(); }
      } }, icon('file'), desktop ? 'Archivos…' : 'Examinar…'),
      desktop ? h('button', { class: 'btn', onclick: async () => {
        const r = await pickFolder('Importar carpeta');
        if (r) { paths.add(r); renderPaths(); }
      } }, icon('folder'), 'Carpeta…') : null));
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault(); drop.classList.remove('over');
    const files = [...(e.dataTransfer?.files || [])];
    const got = files.map((f) => desktop?.getPathForFile?.(f) || f.path).filter(Boolean);
    if (got.length) { got.forEach((p) => paths.add(p)); renderPaths(); }
    else toast('El navegador no expone rutas locales al arrastrar. Usa «Examinar…» o pega la ruta.', 'warn', 6000);
  });

  root.append(
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Importar archivos'),
      h('p', {}, 'Añade archivos o carpetas completas. Se leen los metadatos y se detectan duplicados automáticamente.'))),
    h('div', { class: 'split' },
      h('div', {}, drop,
        h('div', { class: 'card mt' },
          h('div', { class: 'card-head' }, h('h3', {}, 'Rutas a importar'), h('button', { class: 'btn ghost sm', onclick: () => { paths.clear(); renderPaths(); } }, 'Limpiar')),
          manual, h('div', { class: 'mt' }, pathList),
          h('div', { class: 'row between mt' },
            h('div', { class: 'row' }, h('label', { class: 'check' }, recursive, 'Incluir subcarpetas'), h('label', { class: 'check' }, skipDup, 'Omitir duplicados exactos')),
            startBtn))),
      h('div', { class: 'card' }, h('h3', {}, 'Cómo funciona'),
        h('ul', { class: 'muted', style: { paddingLeft: '18px', margin: 0, lineHeight: 1.8 } },
          h('li', {}, 'Los archivos se quedan donde están; la biblioteca solo guarda su ruta.'),
          h('li', {}, 'Se analizan con FFprobe: códec, frecuencia, bits, canales y duración.'),
          h('li', {}, 'Las etiquetas (título, artista, álbum, género…) se leen del archivo o se deducen del nombre.'),
          h('li', {}, 'Los duplicados exactos se detectan por huella SHA-256.'),
          h('li', {}, 'Los archivos dañados se rechazan y quedan registrados en el historial.')))),
    h('h2', { class: 'mt', style: { fontSize: '18px' } }, 'Importaciones'), jobsBox);

  function renderPaths() {
    startBtn.disabled = !paths.size;
    clear(pathList, paths.size ? [...paths].map((p) => h('div', { class: 'list-item' }, icon('folder'), h('div', { class: 'grow mono' }, p),
      h('button', { class: 'btn ghost icon', title: 'Quitar', onclick: () => { paths.delete(p); renderPaths(); } }, icon('x'))))
      : h('div', { class: 'dim' }, 'No hay rutas seleccionadas.'));
  }

  async function start() {
    try {
      await api.post('/api/import', { paths: [...paths], recursive: recursive.checked, skip_duplicates: skipDup.checked });
      paths.clear(); renderPaths();
      toast('Importación iniciada');
      poll();
    } catch (e) { toastError(e); }
  }

  async function poll() {
    clearTimeout(timer);
    const jobs = await api.get('/api/import').catch(() => []);
    renderJobs(jobs);
    if (jobs.some((j) => ['scanning', 'importing'].includes(j.status))) timer = setTimeout(poll, 600);
  }

  function renderJobs(jobs) {
    if (!jobs.length) { clear(jobsBox, h('div', { class: 'card' }, empty('import', 'Sin importaciones en esta sesión', 'Selecciona archivos o carpetas y pulsa Importar.'))); return; }
    clear(jobsBox, jobs.map((j) => {
      const running = ['scanning', 'importing'].includes(j.status);
      const statusLabel = { scanning: 'Analizando…', importing: 'Importando…', done: 'Completada', cancelled: 'Cancelada', failed: 'Error' }[j.status];
      return h('div', { class: 'card mb', 'data-job': j.id },
        h('div', { class: 'row between' },
          h('div', {}, h('b', {}, statusLabel), h('span', { class: 'dim' }, ` · ${fmtDate(j.started_at)} · ${j.paths.length} ruta(s)`)),
          running ? h('button', { class: 'btn sm danger', onclick: () => api.post(`/api/import/${j.id}/cancel`).then(poll) }, icon('stop'), 'Cancelar')
            : h('button', { class: 'btn sm', onclick: () => navigate('library') }, 'Ver biblioteca')),
        h('div', { class: 'row mt' }, h('div', { style: { flex: 1 } }, progressBar(j.total ? j.processed / j.total : running ? 0 : 1, j.status === 'scanning')),
          h('span', { class: 'num muted' }, `${j.processed}/${j.total}`)),
        running && j.current ? h('div', { class: 'hint mono mt' }, j.current) : null,
        h('div', { class: 'row mt' },
          h('span', { class: 'badge green' }, `${j.imported.length} importados`),
          j.updated.length ? h('span', { class: 'badge blue' }, `${j.updated.length} actualizados`) : null,
          h('span', { class: `badge ${j.duplicates.length ? 'yellow' : ''}` }, `${j.duplicates.length} duplicados`),
          h('span', { class: `badge ${j.errors.length ? 'red' : ''}` }, `${j.errors.length} errores`)),
        j.duplicates.length || j.errors.length ? h('details', { class: 'mt' }, h('summary', { class: 'muted', style: { cursor: 'pointer' } }, 'Ver detalles'),
          h('div', { class: 'list mt' },
            j.duplicates.map((d) => h('div', { class: 'list-item' }, h('span', { class: 'badge yellow' }, 'Duplicado'), h('div', { class: 'grow mono' }, d.path, h('div', { class: 'dim' }, `= ${d.duplicate_of.path}`)))),
            j.errors.map((d) => h('div', { class: 'list-item' }, h('span', { class: 'badge red' }, 'Error'), h('div', { class: 'grow' }, h('div', { class: 'mono' }, d.path), h('div', { class: 'dim' }, d.error))))))
          : null);
    }));
  }

  renderPaths();
  await poll();
  return () => clearTimeout(timer);
}
