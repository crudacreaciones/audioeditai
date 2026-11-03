import { api } from '../api.js';
import { state } from '../state.js';
import { h, icon, pickFolder, toast, toastError } from '../ui.js';

export default async function settingsView(root) {
  const [s, sys] = await Promise.all([api.get('/api/settings'), api.get('/api/system')]);
  const f = {
    spotify_client_id: h('input', { class: 'input mono', id: 'set-client-id', value: s.spotify_client_id, placeholder: 'p. ej. 0a1b2c3d4e5f…' }),
    spotify_redirect_uri: h('input', { class: 'input mono', value: s.spotify_redirect_uri }),
    output_dir: h('input', { class: 'input mono', value: s.output_dir }),
    naming_pattern: h('input', { class: 'input mono', value: s.naming_pattern }),
    default_sample_rate: h('select', { class: 'input' }, sys.options.sample_rates.map((r) => h('option', { value: r, selected: r === s.default_sample_rate }, `${(r / 1000).toLocaleString('es-ES')} kHz`))),
    default_bit_depth: h('select', { class: 'input' }, sys.options.bit_depths.map((b) => h('option', { value: b.value, selected: b.value === s.default_bit_depth }, b.label))),
    default_channels: h('select', { class: 'input' }, sys.options.channels.map((c) => h('option', { value: c.value, selected: c.value === s.default_channels }, c.label))),
    concurrency: h('input', { class: 'input', type: 'number', min: 1, max: 8, value: s.concurrency }),
    verify_after_convert: h('input', { type: 'checkbox', checked: s.verify_after_convert }),
    skip_exact_duplicates: h('input', { type: 'checkbox', checked: s.skip_exact_duplicates }),
  };

  async function save() {
    try {
      const values = {
        spotify_client_id: f.spotify_client_id.value.trim(),
        spotify_redirect_uri: f.spotify_redirect_uri.value.trim(),
        output_dir: f.output_dir.value.trim(),
        naming_pattern: f.naming_pattern.value.trim() || '{artist} - {title}',
        default_sample_rate: Number(f.default_sample_rate.value),
        default_bit_depth: f.default_bit_depth.value,
        default_channels: Number(f.default_channels.value),
        concurrency: Number(f.concurrency.value) || 2,
        verify_after_convert: f.verify_after_convert.checked,
        skip_exact_duplicates: f.skip_exact_duplicates.checked,
      };
      await api.put('/api/settings', values);
      toast(values.concurrency !== s.concurrency ? 'Configuración guardada. El cambio de conversiones simultáneas se aplica al reiniciar.' : 'Configuración guardada');
      s.concurrency = values.concurrency;
    } catch (e) { toastError(e); }
  }

  const ff = sys.ffmpeg;
  root.append(
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Configuración'), h('p', {}, 'Spotify, formato por defecto, carpetas y sistema.')),
      h('div', { class: 'actions' }, h('button', { class: 'btn primary', id: 'set-save', onclick: save }, icon('check'), 'Guardar cambios'))),
    h('div', { class: 'grid cols-2' },
      h('div', { class: 'card' }, h('h2', {}, 'Spotify'),
        h('div', { class: 'notice mb' }, icon('info'), h('div', {}, 'Crea una app en developer.spotify.com, añade la Redirect URI indicada abajo y pega aquí el Client ID. Se usa OAuth con PKCE: no hace falta Client Secret.')),
        h('label', { class: 'field' }, 'Client ID', f.spotify_client_id),
        h('label', { class: 'field mt' }, 'Redirect URI', f.spotify_redirect_uri,
          h('span', { class: 'hint' }, 'Debe coincidir exactamente con la registrada en tu app de Spotify (usa 127.0.0.1, no «localhost»).'))),
      h('div', { class: 'card' }, h('h2', {}, 'Conversión por defecto'),
        h('div', { class: 'form-grid' },
          h('label', { class: 'field' }, 'Frecuencia', f.default_sample_rate),
          h('label', { class: 'field' }, 'Profundidad', f.default_bit_depth),
          h('label', { class: 'field' }, 'Canales', f.default_channels),
          h('label', { class: 'field' }, 'Conversiones simultáneas', f.concurrency)),
        h('label', { class: 'check mt' }, f.verify_after_convert, 'Verificar la integridad de cada WAV tras convertirlo'),
        h('br'),
        h('label', { class: 'check mt' }, f.skip_exact_duplicates, 'Omitir duplicados exactos al importar')),
      h('div', { class: 'card' }, h('h2', {}, 'Archivos'),
        h('label', { class: 'field' }, 'Carpeta de salida WAV', h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, f.output_dir,
          h('button', { class: 'btn icon', title: 'Examinar', onclick: async () => { const p = await pickFolder('Carpeta de salida', f.output_dir.value); if (p) f.output_dir.value = p; } }, icon('folder')))),
        h('label', { class: 'field mt' }, 'Patrón de nombre', f.naming_pattern,
          h('span', { class: 'hint' }, 'Variables: {artist} {title} {album} {album_artist} {genre} {year} {track_no}'))),
      h('div', { class: 'card' }, h('h2', {}, 'Sistema'),
        h('dl', { class: 'kv' },
          h('dt', {}, 'Versión'), h('dd', {}, `${sys.app} ${sys.version}`),
          h('dt', {}, 'FFmpeg'), h('dd', {}, ff.ffmpeg || h('span', { class: 'badge red' }, 'No encontrado')),
          h('dt', {}, 'FFprobe'), h('dd', {}, ff.ffprobe || h('span', { class: 'badge red' }, 'No encontrado')),
          h('dt', {}, 'Remuestreo'), h('dd', {}, ff.soxr ? 'SoX Resampler (soxr, precisión 28 bits)' : 'swresample (por defecto)'),
          h('dt', {}, 'Python'), h('dd', {}, `${sys.python} · ${sys.platform}`),
          h('dt', {}, 'Datos'), h('dd', { class: 'mono' }, sys.data_dir),
          h('dt', {}, 'Base de datos'), h('dd', { class: 'mono' }, sys.db_path),
          h('dt', {}, 'Log'), h('dd', { class: 'mono' }, sys.log_file)))));
  state.system = sys;
}
