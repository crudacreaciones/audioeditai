import { apiBaseUrl } from '../lib/config';
import type { Bitrate, Job } from './types';

export class ApiError extends Error {
  constructor(message: string, public status = 0, public retryable = true) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = 15000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(apiBaseUrl() + path, { ...init, signal: ctrl.signal,
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } });
  } catch {
    throw new ApiError('No se puede conectar con el servidor de WAVIFY. Revisa tu conexión.');
  } finally {
    clearTimeout(timer);
  }
  let body: any = null;
  try { body = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const detail = typeof body?.detail === 'string' ? body.detail : 'El servidor no ha podido procesar la petición.';
    throw new ApiError(detail, res.status, res.status === 429 || res.status >= 500);
  }
  return body as T;
}

export const api = {
  createJob: (url: string, bitrate: Bitrate) =>
    request<Job>('/api/v1/jobs', { method: 'POST', body: JSON.stringify({ url, bitrate }) }),
  getJob: (id: string) => request<Job>(`/api/v1/jobs/${encodeURIComponent(id)}`),
  cancelJob: (id: string) => request<{ cancelled: boolean }>(`/api/v1/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  fileUrl: (downloadPath: string) => apiBaseUrl() + downloadPath,
};
