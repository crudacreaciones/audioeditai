// Shared client state + helpers used by several views.
import { $, clear, h, icon, toastError } from './ui.js';

const SEL_KEY = 'swc.convertSelection';

export const state = {
  system: null,
  get selection() {
    try { return new Set(JSON.parse(sessionStorage.getItem(SEL_KEY) || '[]')); } catch { return new Set(); }
  },
  setSelection(ids) {
    try { sessionStorage.setItem(SEL_KEY, JSON.stringify([...new Set(ids)])); } catch { /* storage unavailable */ }
    window.dispatchEvent(new CustomEvent('swc:selection'));
  },
  addToSelection(ids) { this.setSelection([...this.selection, ...ids]); },
};

export function navigate(route, params) {
  const qs = params ? '?' + new URLSearchParams(params) : '';
  location.hash = `#/${route}${qs}`;
}

// Global preview player (bottom bar).
export function playPreview({ url, title, subtitle, image }) {
  const p = $('#player');
  const audio = h('audio', { controls: true, autoplay: true, src: url });
  audio.addEventListener('error', () => toastError(new Error('No se puede reproducir este archivo en la vista previa')));
  clear(p,
    h('div', { class: 'track-cell' },
      image ? h('img', { class: 'cover', src: image, alt: '' }) : h('div', { class: 'cover' }, icon('music')),
      h('div', { class: 'track-meta' }, h('div', { class: 't' }, title || 'Vista previa'), h('div', { class: 'a' }, subtitle || ''))),
    audio,
    h('button', { class: 'btn ghost icon', title: 'Cerrar reproductor', onclick: () => { audio.pause(); p.classList.remove('show'); } }, icon('x')));
  p.classList.add('show');
}
