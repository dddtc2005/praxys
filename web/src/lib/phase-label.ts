import { msg } from '@lingui/core/macro';
import type { MessageDescriptor, I18n } from '@lingui/core';
import type { PhaseCode, WorkoutPhase } from './workout-parser';

/** One message descriptor per phase code — extractable by Lingui. */
const PHASE_LABELS: Record<PhaseCode, MessageDescriptor> = {
  warmup: msg`Warmup`,
  cooldown: msg`Cooldown`,
  main: msg`Main`,
  run: msg`Run`,
  easy_run: msg`Easy Run`,
  steady: msg`Steady`,
  aerobic: msg`Aerobic`,
  tempo: msg`Tempo`,
  threshold: msg`Threshold`,
  recovery: msg`Recovery`,
  rest: msg`Rest`,
  rep: msg`Rep`,
};

/**
 * Render a workout phase's user-facing label for the active locale.
 * Pass the i18n instance from useLingui() so this stays a pure helper.
 */
export function phaseLabel(phase: WorkoutPhase, i18n: I18n): string {
  const base = i18n._(PHASE_LABELS[phase.code]);
  if (phase.code === 'rep' && phase.repNumber != null) {
    return `${base} ${phase.repNumber}`;
  }
  return base;
}
