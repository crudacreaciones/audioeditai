// TEST-ONLY fake of the WAVIFY backend, served through a mocked global fetch.
import type { Job } from '../src/api/types';

export const TRACK = {
  id: '4uLU6hMCjMI75M1A2tKUQC', title: 'Luz de Mañana', artists: ['Aurora Libre'], album: 'Cielos Abiertos',
  cover_url: '', duration: 214, isrc: '', url: 'https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC', release_date: '2024',
};

export function job(over: Partial<Job>): Job {
  return { id: 'j1', stage: 'analyzing', progress: 0, message: '', bitrate: 320, track: null, selected: null, summary: {},
    error: null, file: null, final: false, ...over };
}

export const READY = job({
  stage: 'ready', progress: 1, final: true, track: TRACK,
  selected: { provider: 'internet_archive', provider_name: 'Internet Archive', title: 'Luz de Mañana', artist: 'Aurora Libre',
    page_url: '', availability: 'downloadable', availability_label: 'Descargable', lossless: true,
    license: { name: 'CC BY-SA 4.0', url: 'https://creativecommons.org/licenses/by-sa/4.0/', requires_attribution: true, notes: '' } },
  file: { name: 'Aurora Libre - Luz de Mañana.mp3', size: 8_600_000, bitrate_kbps: 320, note: '', duration: 214,
    source_lossless: true, download_path: '/api/v1/jobs/j1/file?token=t', expires_at: 0 },
});

type Route = { method: string; path: RegExp; reply: () => { status?: number; body: unknown } };

export function mockBackend(routes: Route[]) {
  const calls: string[] = [];
  const fetchMock = jest.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method || 'GET';
    const path = url.replace(/^https?:\/\/[^/]+/, '');
    calls.push(`${method} ${path}`);
    const r = routes.find((x) => x.method === method && x.path.test(path));
    if (!r) throw new TypeError('Network request failed');
    const { status = 200, body } = r.reply();
    return { ok: status < 400, status, json: async () => body } as Response;
  });
  (globalThis as any).fetch = fetchMock;
  return { calls, fetchMock };
}

/** Returns the given jobs one after another for each GET /jobs/:id. */
export function sequence(jobs: Job[]) {
  let i = 0;
  return () => ({ body: jobs[Math.min(i++, jobs.length - 1)] });
}
