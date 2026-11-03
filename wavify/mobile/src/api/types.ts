// Mirrors the WAVIFY backend responses (backend/wavify/jobs.py).
export type BackendStage =
  | 'analyzing' | 'identifying' | 'searching' | 'comparing' | 'checking'
  | 'downloading' | 'converting' | 'ready' | 'no_results' | 'error' | 'cancelled';

export type Availability =
  | 'downloadable' | 'purchase_required' | 'stream_only' | 'license_incompatible' | 'unavailable' | 'unverified_match';

export interface Track {
  id: string;
  title: string;
  artists: string[];
  album: string;
  cover_url: string;
  duration: number;
  isrc: string;
  url: string;
  release_date: string;
}

export interface Selected {
  provider: string;
  provider_name: string;
  title: string;
  artist: string;
  page_url: string;
  availability: Availability;
  availability_label: string;
  lossless: boolean;
  license: { name: string; url: string; requires_attribution: boolean; notes: string } | null;
}

export interface JobFile {
  name: string;
  size: number;
  bitrate_kbps: number;
  note: string;
  duration: number;
  source_lossless: boolean;
  download_path: string;
  expires_at: number;
}

export interface Job {
  id: string;
  stage: BackendStage;
  progress: number;
  message: string;
  bitrate: number;
  track: Track | null;
  selected: Selected | null;
  summary: { reason?: string };
  error: { code: string; message: string; retryable: boolean } | null;
  file: JobFile | null;
  final: boolean;
}

export const BITRATES = [128, 192, 256, 320] as const;
export type Bitrate = (typeof BITRATES)[number];
