import type { BackendStage } from '../api/types';

export type UiStage = 'initial' | BackendStage;

/** The progress steps shown to the user while working (in order). */
export const STEPS: { stage: BackendStage; label: string }[] = [
  { stage: 'analyzing', label: 'Analizando enlace' },
  { stage: 'identifying', label: 'Identificando canción' },
  { stage: 'searching', label: 'Buscando en fuentes' },
  { stage: 'comparing', label: 'Comparando resultados' },
  { stage: 'checking', label: 'Comprobando permisos' },
  { stage: 'downloading', label: 'Descargando' },
  { stage: 'converting', label: 'Convirtiendo' },
];

export const WORKING: UiStage[] = STEPS.map((s) => s.stage);

export function stepIndex(stage: UiStage): number {
  return STEPS.findIndex((s) => s.stage === stage);
}

export function isWorking(stage: UiStage): boolean {
  return WORKING.includes(stage);
}
