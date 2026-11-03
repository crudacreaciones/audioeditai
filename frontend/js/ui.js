// Small DOM toolkit, formatters, icons, toasts, modals and the folder/file picker.
import { api } from './api.js';

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'html') el.innerHTML = v; // only used with trusted static markup (icons)
    else if (k in el && typeof v !== 'string') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export const $ = (sel, root = document) => root.querySelector(sel);
export function clear(el, ...children) { el.replaceChildren(); append(el, children); return el; }

// ---------- icons (inline SVG, stroke-based) ----------
const P = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  spotify: '<circle cx="12" cy="12" r="9"/><path d="M7.5 9.5c3-1 6.5-.8 9 .7M8 12.6c2.5-.7 5.2-.5 7.4.7M8.6 15.5c2-.5 4-.3 5.6.6"/>',
  library: '<path d="M4 4v16M8 4v16"/><path d="m12.5 4.5 3.8 15.2M17 4l3.5 15"/>',
  import: '<path d="M12 3v12m0 0-4-4m4 4 4-4"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  wave: '<path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 7v10M21 12h0"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  play: '<path d="M7 4.5v15l12-7.5z" fill="currentColor"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="m5 12 5 5 9-10"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  file: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  export: '<path d="M12 15V3m0 0 4 4m-4-4-4 4"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  up: '<path d="m6 15 6-6 6 6"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  disc: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/>',
  logo: '<path d="M4 12h1.5M7.5 8v8M11 5v14M14.5 9v6M18 7v10M20.5 12H20" stroke-width="2.4"/>',
};

export function icon(name, cls = '') {
  const span = document.createElement('span');
  span.style.display = 'contents';
  span.innerHTML = `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${P[name] || ''}</svg>`;
  return span.firstElementChild;
}

// ---------- formatters ----------
export function fmtDuration(sec) {
  sec = Math.round(Number(sec) || 0);
  const hh = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return hh ? `${hh}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}
export function fmtBytes(n) {
  n = Number(n) || 0;
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}
export function fmtDate(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleString('es-ES', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}
export function fmtRate(hz) { return hz ? `${(hz / 1000).toLocaleString('es-ES', { maximumFractionDigits: 1 })} kHz` : '—'; }
export const DEPTH_LABEL = { '16': '16 bits', '24': '24 bits', '32f': '32 bits float' };
export function fmtSpec(j) { return `${fmtRate(j.sample_rate)} · ${DEPTH_LABEL[j.bit_depth] || j.bit_depth} · ${j.channels === 1 ? 'Mono' : 'Estéreo'}`; }

export const STATUS = {
  queued: ['En cola', 'blue'], running: ['Convirtiendo', 'yellow'], done: ['Completado', 'green'],
  failed: ['Error', 'red'], cancelled: ['Cancelado', ''],
};
export function statusBadge(s) { const [t, c] = STATUS[s] || [s, '']; return h('span', { class: `badge ${c}` }, t); }

export function cover(url, cls = '') {
  if (url) return h('img', { class: `cover ${cls}`, src: url, alt: '', loading: 'lazy' });
  return h('div', { class: `cover ${cls}` }, icon('music'));
}

export function empty(iconName, title, text, ...actions) {
  return h('div', { class: 'empty' }, icon(iconName), h('h3', {}, title), text ? h('p', {}, text) : null,
    actions.length ? h('div', { class: 'row', style: { justifyContent: 'center' } }, actions) : null);
}

export function progressBar(p, indeterminate = false) {
  return h('div', { class: `progress ${indeterminate ? 'indet' : ''}` }, h('div', { style: { width: `${Math.round((p || 0) * 100)}%` } }));
}

export function seg(options, value, onChange) {
  const wrap = h('div', { class: 'seg', role: 'tablist' });
  const render = (val) => clear(wrap, options.map((o) =>
    h('button', { class: String(o.value) === String(val) ? 'on' : '', type: 'button', 'data-value': o.value,
      onclick: () => { render(o.value); onChange(o.value); } }, o.label)));
  render(value);
  return wrap;
}

// ---------- toast ----------
export function toast(msg, kind = 'ok', ms = 3800) {
  const t = h('div', { class: `toast ${kind}` }, msg);
  const box = $('#toasts');
  box.append(t);
  while (box.children.length > 3) box.firstElementChild.remove();
  setTimeout(() => t.remove(), ms);
}
export function toastError(e) { toast(e?.message || String(e), 'error', 6000); }

// ---------- modal ----------
export function modal({ title, body, actions = [], wide = false, onClose }) {
  const close = () => { overlay.remove(); document.removeEventListener('keydown', esc); onClose && onClose(); };
  const esc = (e) => { if (e.key === 'Escape') close(); };
  const overlay = h('div', { class: 'overlay', onmousedown: (e) => { if (e.target === overlay) close(); } },
    h('div', { class: `modal ${wide ? 'wide' : ''}`, role: 'dialog', 'aria-label': title },
      h('div', { class: 'modal-head' }, h('h2', {}, title),
        h('button', { class: 'btn ghost icon', onclick: close, title: 'Cerrar' }, icon('x'))),
      h('div', { class: 'modal-body' }, body),
      actions.length ? h('div', { class: 'modal-foot' }, actions.map((a) =>
        h('button', { class: `btn ${a.kind || ''}`, onclick: async (e) => {
          if (!a.onClick) return close();
          const btn = e.currentTarget;
          btn.disabled = true;
          try { if ((await a.onClick()) !== false) close(); } catch (err) { toastError(err); }
          finally { btn.disabled = false; }
        } }, a.label))) : null));
  document.body.append(overlay);
  document.addEventListener('keydown', esc);
  return { close, overlay };
}

export function confirmDialog(title, text, okLabel = 'Aceptar', kind = 'primary') {
  return new Promise((resolve) => {
    let answered = false;
    modal({ title, body: h('p', { class: 'muted' }, text),
      onClose: () => { if (!answered) resolve(false); },
      actions: [{ label: 'Cancelar' }, { label: okLabel, kind, onClick: () => { answered = true; resolve(true); } }] });
  });
}

// ---------- folder / file picker ----------
// Uses the native dialog in the desktop (Electron) shell; falls back to a local file browser in the browser.
export const desktop = window.swcDesktop || null;

export async function pickFolder(title = 'Seleccionar carpeta', start = '') {
  if (desktop?.pickFolder) return desktop.pickFolder(title);
  return browseDialog({ title, start, mode: 'folder' });
}

export async function pickPaths(title = 'Seleccionar archivos o carpetas') {
  if (desktop?.pickFiles) return desktop.pickFiles(title);
  return browseDialog({ title, mode: 'multi' });
}

function browseDialog({ title, start = '', mode }) {
  return new Promise((resolve) => {
    let current = start, selected = new Set(), result = null;
    const pathInput = h('input', { class: 'input mono', value: start, onkeydown: (e) => { if (e.key === 'Enter') load(pathInput.value); } });
    const list = h('div', { class: 'browser-list' });
    const info = h('div', { class: 'hint mt' });
    async function load(path) {
      try {
        const r = await api.get('/api/fs/list', { path, files: mode !== 'folder' });
        current = r.path; pathInput.value = r.path;
        const rows = [];
        if (r.parent !== null && r.parent !== undefined) rows.push(h('div', { class: 'browser-row', onclick: () => load(r.parent) }, icon('up'), '..'));
        for (const d of r.dirs) {
          const cb = mode === 'multi' ? h('input', { type: 'checkbox', checked: selected.has(d.path), onclick: (e) => { e.stopPropagation(); toggle(d.path, e.target.checked); } }) : null;
          rows.push(h('div', { class: 'browser-row', ondblclick: () => load(d.path), onclick: () => load(d.path) }, cb, icon('folder'), d.name));
        }
        for (const f of r.files) {
          const cb = h('input', { type: 'checkbox', checked: selected.has(f.path), onclick: (e) => e.stopPropagation(), onchange: (e) => toggle(f.path, e.target.checked) });
          rows.push(h('label', { class: 'browser-row file' }, cb, icon('file'), h('span', { style: { flex: 1 } }, f.name), h('span', { class: 'dim' }, fmtBytes(f.size))));
        }
        if (!rows.length) rows.push(h('div', { class: 'browser-row dim' }, 'Carpeta vacía'));
        clear(list, rows);
        updateInfo();
      } catch (e) { toastError(e); }
    }
    function toggle(p, on) { on ? selected.add(p) : selected.delete(p); updateInfo(); }
    function updateInfo() {
      info.textContent = mode === 'folder' ? `Carpeta: ${current}`
        : selected.size ? `${selected.size} elemento(s) seleccionado(s)` : 'Marca archivos o carpetas, o usa «Esta carpeta».';
    }
    const actions = [{ label: 'Cancelar' }];
    if (mode === 'multi') {
      actions.push({ label: 'Esta carpeta', onClick: () => { result = [pathInput.value.trim() || current]; } });
      actions.push({ label: 'Añadir selección', kind: 'primary', onClick: () => { if (!selected.size) { toast('No hay nada seleccionado', 'warn'); return false; } result = [...selected]; } });
    } else {
      // the typed path wins: it may be a new folder that will be created on use
      actions.push({ label: 'Seleccionar esta carpeta', kind: 'primary', onClick: () => { result = pathInput.value.trim() || current; } });
    }
    modal({ title, wide: true, body: h('div', {}, h('div', { class: 'browser-path' }, pathInput,
      h('button', { class: 'btn', onclick: () => load(pathInput.value) }, 'Ir')), list, info),
      actions, onClose: () => resolve(result) });
    load(start);
  });
}
