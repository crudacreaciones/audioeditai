import { useCallback, useEffect, useRef, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Bitrate, Job } from '../api/types';
import { checkSpotifyLink, extractLink } from '../lib/spotifyLink';
import type { UiStage } from '../lib/stages';

export interface WavifyState {
  stage: UiStage;
  job: Job | null;
  message: string;      // user-facing message for no_results / error
  retryable: boolean;
  progress: number;
}

const INITIAL: WavifyState = { stage: 'initial', job: null, message: '', retryable: false, progress: 0 };
const POLL_MS = 700;
const MAX_POLL_FAILURES = 5;

export function useWavify() {
  const [state, setState] = useState<WavifyState>(INITIAL);
  const jobId = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const failures = useRef(0);
  const lastRequest = useRef<{ link: string; bitrate: Bitrate } | null>(null);

  const stopPolling = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };

  useEffect(() => stopPolling, []);

  const fail = (message: string, retryable: boolean) =>
    setState((s) => ({ ...s, stage: 'error', message, retryable }));

  const poll = useCallback(async (id: string) => {
    if (jobId.current !== id) return;
    try {
      const job = await api.getJob(id);
      if (jobId.current !== id) return;
      failures.current = 0;
      if (job.stage === 'cancelled') {
        jobId.current = null;
        setState(INITIAL);
        return;
      }
      setState({
        stage: job.stage, job, progress: job.progress,
        message: job.error?.message || (job.stage === 'no_results' ? job.message : ''),
        retryable: job.error?.retryable ?? false,
      });
      if (!job.final) timer.current = setTimeout(() => poll(id), POLL_MS);
    } catch (e) {
      if (jobId.current !== id) return;
      if (++failures.current >= MAX_POLL_FAILURES) {
        fail(e instanceof ApiError ? e.message : 'Se perdió la conexión con el servidor.', true);
      } else {
        timer.current = setTimeout(() => poll(id), POLL_MS * 2);
      }
    }
  }, []);

  const start = useCallback(async (rawLink: string, bitrate: Bitrate) => {
    const link = extractLink(rawLink);
    const check = checkSpotifyLink(link);
    if (!check.ok) {
      setState({ ...INITIAL, stage: 'error', message: check.message, retryable: false });
      return;
    }
    stopPolling();
    lastRequest.current = { link, bitrate };
    failures.current = 0;
    setState({ ...INITIAL, stage: 'analyzing' });
    try {
      const job = await api.createJob(link, bitrate);
      jobId.current = job.id;
      setState((s) => ({ ...s, job, stage: job.stage, progress: job.progress }));
      timer.current = setTimeout(() => poll(job.id), POLL_MS);
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError('No se ha podido iniciar la búsqueda.');
      fail(err.message, err.retryable);
    }
  }, [poll]);

  const cancel = useCallback(async () => {
    const id = jobId.current;
    stopPolling();
    jobId.current = null;
    setState(INITIAL);
    if (id) {
      try { await api.cancelJob(id); } catch { /* the job expires on its own */ }
    }
  }, []);

  const retry = useCallback(() => {
    if (lastRequest.current) start(lastRequest.current.link, lastRequest.current.bitrate);
  }, [start]);

  const reset = useCallback(() => {
    stopPolling();
    jobId.current = null;
    setState(INITIAL);
  }, []);

  return { state, start, cancel, retry, reset };
}
