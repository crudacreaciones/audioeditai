import { act, fireEvent, render, screen } from '@testing-library/react-native';

import Home from '../src/app/index';
import { READY, TRACK, job, mockBackend, sequence } from '../test-support/fakeBackend';

jest.mock('../src/lib/save', () => ({ saveMp3: jest.fn(async () => ({ saved: true, location: 'Descargas' })) }));
jest.mock('expo-clipboard', () => ({ getStringAsync: jest.fn(async () => 'https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC') }));
import { saveMp3 } from '../src/lib/save';

const LINK = 'https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC';

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

async function tick(ms = 800) {
  await act(async () => { jest.advanceTimersByTime(ms); });
}

async function submit(link = LINK) {
  await fireEvent.changeText(screen.getByTestId('link-input'), link);
  await fireEvent.press(screen.getByTestId('go'));
}

test('initial state', async () => {
  mockBackend([]);
  await render(<Home />);
  expect(screen.getByText('WAVIFY')).toBeTruthy();
  expect(screen.getByText('Tu música, lista para llevar')).toBeTruthy();
  expect(screen.getByText('BUSCAR Y CONVERTIR')).toBeTruthy();
  expect(screen.getByTestId('go')).toBeDisabled();
});

test('paste button fills the link', async () => {
  mockBackend([]);
  await render(<Home />);
  await fireEvent.press(screen.getByTestId('paste'));
  expect(screen.getByTestId('link-input').props.value).toBe(LINK);
});

test('full flow: stages → ready → save', async () => {
  const { calls } = mockBackend([
    { method: 'POST', path: /\/api\/v1\/jobs$/, reply: () => ({ status: 202, body: job({}) }) },
    { method: 'GET', path: /\/api\/v1\/jobs\/j1$/, reply: sequence([
      job({ stage: 'identifying', progress: 0.1 }),
      job({ stage: 'searching', progress: 0.2, track: TRACK }),
      job({ stage: 'converting', progress: 0.85, track: TRACK }),
      READY,
    ]) },
  ]);
  await render(<Home />);
  await fireEvent.press(screen.getByTestId('quality-256'));
  await submit();
  expect(calls[0]).toBe('POST /api/v1/jobs');
  expect(JSON.parse((globalThis.fetch as jest.Mock).mock.calls[0][1].body)).toEqual({ url: LINK, bitrate: 256 });
  expect(screen.getByTestId('current-step')).toHaveTextContent('Analizando enlace…', { exact: false });
  await tick();
  expect(screen.getByTestId('current-step')).toHaveTextContent('Identificando canción…', { exact: false });
  await tick();
  expect(screen.getByTestId('current-step')).toHaveTextContent('Buscando en fuentes…', { exact: false });
  expect(screen.getByText('Luz de Mañana')).toBeTruthy();
  await tick();
  expect(screen.getByTestId('current-step')).toHaveTextContent('Convirtiendo…', { exact: false });
  await tick();
  expect(screen.getByTestId('availability')).toHaveTextContent('✓ Descargable', { exact: false });
  expect(screen.getByTestId('quality')).toHaveTextContent('MP3 · 320 kbps', { exact: false });
  expect(screen.getByText(/CC BY-SA 4.0/)).toBeTruthy();
  await fireEvent.press(screen.getByTestId('save'));
  await act(async () => { await Promise.resolve(); });
  expect(saveMp3).toHaveBeenCalledWith(expect.stringMatching(/^http:\/\/(localhost|127\.0\.0\.1):8000\/api\/v1\/jobs\/j1\/file\?token=t$/), 'Aurora Libre - Luz de Mañana.mp3');
  expect(screen.getByTestId('saved')).toHaveTextContent('Guardado en Descargas', { exact: false });
});

test('quality note when the source does not justify the bitrate', async () => {
  mockBackend([
    { method: 'POST', path: /jobs$/, reply: () => ({ body: job({}) }) },
    { method: 'GET', path: /jobs\/j1$/, reply: () => ({ body: { ...READY, file: { ...READY.file!, bitrate_kbps: 128,
      note: 'El original ya es MP3 a 128 kbps: se conserva sin recodificar.' } } }) },
  ]);
  await render(<Home />);
  await submit();
  await tick();
  expect(screen.getByTestId('quality')).toHaveTextContent('128 kbps', { exact: false });
  expect(screen.getByTestId('quality-note')).toHaveTextContent('sin recodificar', { exact: false });
});

test('no authorized version available', async () => {
  mockBackend([
    { method: 'POST', path: /jobs$/, reply: () => ({ body: job({}) }) },
    { method: 'GET', path: /jobs\/j1$/, reply: () => ({ body: job({ stage: 'no_results', final: true, track: TRACK,
      message: 'No hemos encontrado esta canción en ninguna fuente de descarga autorizada.' }) }) },
  ]);
  await render(<Home />);
  await submit();
  await tick();
  expect(screen.getByTestId('no-results')).toHaveTextContent(/Sin versión descargable autorizada.*ninguna fuente/);
  expect(screen.queryByTestId('save')).toBeNull();
});

test('invalid link is rejected locally without calling the server', async () => {
  const { calls } = mockBackend([]);
  await render(<Home />);
  await submit('https://open.spotify.com/album/4uLU6hMCjMI75M1A2tKUQC');
  expect(screen.getByTestId('error')).toHaveTextContent('Pega el enlace de una canción', { exact: false });
  expect(screen.queryByTestId('retry')).toBeNull();
  expect(calls).toEqual([]);
});

test('recoverable error offers retry', async () => {
  let fail = true;
  mockBackend([
    { method: 'POST', path: /jobs$/, reply: () => (fail ? { status: 503, body: { detail: 'Servicio no disponible' } } : { body: job({}) }) },
    { method: 'GET', path: /jobs\/j1$/, reply: () => ({ body: READY }) },
  ]);
  await render(<Home />);
  await submit();
  expect(screen.getByTestId('error')).toHaveTextContent('Servicio no disponible', { exact: false });
  fail = false;
  await fireEvent.press(screen.getByTestId('retry'));
  await tick();
  expect(screen.getByTestId('availability')).toBeTruthy();
});

test('server unreachable', async () => {
  mockBackend([]);
  await render(<Home />);
  await submit();
  expect(screen.getByTestId('error')).toHaveTextContent('No se puede conectar con el servidor', { exact: false });
  expect(screen.getByTestId('retry')).toBeTruthy();
});

test('cancel stops polling and calls the API', async () => {
  const { calls } = mockBackend([
    { method: 'POST', path: /jobs$/, reply: () => ({ body: job({}) }) },
    { method: 'GET', path: /jobs\/j1$/, reply: () => ({ body: job({ stage: 'downloading', progress: 0.6, track: TRACK }) }) },
    { method: 'POST', path: /jobs\/j1\/cancel$/, reply: () => ({ body: { cancelled: true } }) },
  ]);
  await render(<Home />);
  await submit();
  await tick();
  expect(screen.getByTestId('current-step')).toHaveTextContent('Descargando…', { exact: false });
  await fireEvent.press(screen.getByTestId('cancel'));
  expect(calls).toContain('POST /api/v1/jobs/j1/cancel');
  const before = calls.length;
  await tick(3000);
  expect(calls.length).toBe(before);
  expect(screen.queryByTestId('progress')).toBeNull();
});
