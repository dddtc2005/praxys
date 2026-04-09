import type { PlanData } from '@/types/api';

export type Intensity = 'easy' | 'moderate' | 'hard' | 'very_hard' | 'rest';

export interface WorkoutPhase {
  label: string;
  duration_min: number;
  intensity: Intensity;
}

const HARD_TYPES = new Set(['interval', 'intervals', 'threshold', 'tempo', 'race', 'race_pace']);

/**
 * Try to parse structured intervals from a free-text description.
 * Returns null if parsing fails (caller should fall back to type templates).
 */
function parseDescription(desc: string, totalMin: number): WorkoutPhase[] | null {
  const phases: WorkoutPhase[] = [];
  const lower = desc.toLowerCase();

  // Match warmup: "warm up X min" / "warmup X min" / "warm-up X minutes"
  const warmupMatch = lower.match(/warm[\s-]?up\s+(\d+)\s*min/);
  // Match cooldown: "cool down X min" / "cooldown X min"
  const cooldownMatch = lower.match(/cool[\s-]?down\s+(\d+)\s*min/);
  // Match intervals: "NxM min" / "N x M min" / "N × M min"
  const intervalMatch = lower.match(/(\d+)\s*[x×]\s*(\d+)\s*min/);
  // Match rest between intervals: "rest X min" / "recovery X min" / "X min rest"
  const restMatch = lower.match(/(?:rest|recovery|jog)\s+(\d+)\s*min|(\d+)\s*min\s+(?:rest|recovery|jog)/);

  if (!intervalMatch && !warmupMatch && !cooldownMatch) return null;

  const warmupMin = warmupMatch ? parseInt(warmupMatch[1]) : 0;
  const cooldownMin = cooldownMatch ? parseInt(cooldownMatch[1]) : 0;

  if (warmupMin > 0) {
    phases.push({ label: 'Warmup', duration_min: warmupMin, intensity: 'easy' });
  }

  if (intervalMatch) {
    const reps = parseInt(intervalMatch[1]);
    const repMin = parseInt(intervalMatch[2]);
    const restMin = restMatch ? parseInt(restMatch[1] || restMatch[2]) : Math.max(1, Math.round(repMin * 0.5));

    // Determine intensity from description context
    const isThreshold = lower.includes('threshold') || lower.includes('tempo');
    const isHard = lower.includes('vo2') || lower.includes('hard') || lower.includes('fast');
    const mainIntensity: Intensity = isHard ? 'very_hard' : isThreshold ? 'hard' : 'hard';

    for (let i = 0; i < reps; i++) {
      phases.push({
        label: `Rep ${i + 1}`,
        duration_min: repMin,
        intensity: mainIntensity,
      });
      if (i < reps - 1) {
        phases.push({
          label: 'Rest',
          duration_min: restMin,
          intensity: 'rest',
        });
      }
    }
  }

  if (cooldownMin > 0) {
    phases.push({ label: 'Cooldown', duration_min: cooldownMin, intensity: 'easy' });
  }

  // If we parsed something meaningful, return it
  if (phases.length > 0) {
    // Adjust to fit total duration if we have one
    if (totalMin > 0) {
      const parsedTotal = phases.reduce((s, p) => s + p.duration_min, 0);
      const remaining = totalMin - parsedTotal;
      // If there's unaccounted time and no warmup/cooldown, distribute
      if (remaining > 2 && !warmupMatch && phases.length > 0) {
        phases.unshift({ label: 'Warmup', duration_min: Math.round(remaining * 0.6), intensity: 'easy' });
        phases.push({ label: 'Cooldown', duration_min: Math.round(remaining * 0.4), intensity: 'easy' });
      }
    }
    return phases;
  }

  return null;
}

/**
 * Generate a default phase structure based on workout type.
 */
function typeTemplate(workoutType: string, totalMin: number): WorkoutPhase[] {
  const t = workoutType.toLowerCase().replace(/[\s_-]+/g, '_');

  if (t === 'recovery' || t === 'easy' || t === 'easy_run') {
    return [{ label: 'Easy Run', duration_min: totalMin, intensity: 'easy' }];
  }

  if (t === 'long' || t === 'long_run') {
    const warmup = Math.round(totalMin * 0.1);
    const cooldown = Math.round(totalMin * 0.1);
    return [
      { label: 'Warmup', duration_min: warmup, intensity: 'easy' },
      { label: 'Steady', duration_min: totalMin - warmup - cooldown, intensity: 'moderate' },
      { label: 'Cooldown', duration_min: cooldown, intensity: 'easy' },
    ];
  }

  if (t === 'steady_aerobic' || t === 'steady' || t === 'aerobic') {
    const warmup = Math.round(totalMin * 0.12);
    const cooldown = Math.round(totalMin * 0.08);
    return [
      { label: 'Warmup', duration_min: warmup, intensity: 'easy' },
      { label: 'Aerobic', duration_min: totalMin - warmup - cooldown, intensity: 'moderate' },
      { label: 'Cooldown', duration_min: cooldown, intensity: 'easy' },
    ];
  }

  if (t === 'tempo') {
    const warmup = Math.round(totalMin * 0.15);
    const cooldown = Math.round(totalMin * 0.15);
    return [
      { label: 'Warmup', duration_min: warmup, intensity: 'easy' },
      { label: 'Tempo', duration_min: totalMin - warmup - cooldown, intensity: 'hard' },
      { label: 'Cooldown', duration_min: cooldown, intensity: 'easy' },
    ];
  }

  if (t === 'threshold') {
    const warmup = Math.round(totalMin * 0.15);
    const cooldown = Math.round(totalMin * 0.15);
    const main = totalMin - warmup - cooldown;
    const repMin = Math.round(main / 2);
    const restMin = main - repMin * 2 > 0 ? main - repMin * 2 : Math.round(repMin * 0.25);
    return [
      { label: 'Warmup', duration_min: warmup, intensity: 'easy' },
      { label: 'Threshold', duration_min: repMin, intensity: 'hard' },
      { label: 'Recovery', duration_min: restMin, intensity: 'rest' },
      { label: 'Threshold', duration_min: repMin, intensity: 'hard' },
      { label: 'Cooldown', duration_min: cooldown, intensity: 'easy' },
    ];
  }

  if (HARD_TYPES.has(t) || t === 'interval') {
    const warmup = Math.round(totalMin * 0.15);
    const cooldown = Math.round(totalMin * 0.15);
    const main = totalMin - warmup - cooldown;
    const reps = 4;
    const restFrac = 0.35;
    const totalRest = Math.round(main * restFrac);
    const restPer = Math.round(totalRest / (reps - 1));
    const repDur = Math.round((main - totalRest) / reps);
    const phases: WorkoutPhase[] = [{ label: 'Warmup', duration_min: warmup, intensity: 'easy' }];
    for (let i = 0; i < reps; i++) {
      phases.push({ label: `Rep ${i + 1}`, duration_min: repDur, intensity: 'very_hard' });
      if (i < reps - 1) {
        phases.push({ label: 'Rest', duration_min: restPer, intensity: 'rest' });
      }
    }
    phases.push({ label: 'Cooldown', duration_min: cooldown, intensity: 'easy' });
    return phases;
  }

  // Default: simple structured run
  const warmup = Math.round(totalMin * 0.15);
  const cooldown = Math.round(totalMin * 0.1);
  return [
    { label: 'Warmup', duration_min: warmup, intensity: 'easy' },
    { label: 'Main', duration_min: totalMin - warmup - cooldown, intensity: 'moderate' },
    { label: 'Cooldown', duration_min: cooldown, intensity: 'easy' },
  ];
}

/**
 * Parse a planned workout into visualizable phases.
 * Tries description parsing first, falls back to type templates.
 */
export function parseWorkoutStructure(plan: PlanData): WorkoutPhase[] {
  const totalMin = plan.duration_min ?? 45; // reasonable default

  // Try parsing description first
  if (plan.description) {
    const parsed = parseDescription(plan.description, totalMin);
    if (parsed && parsed.length > 0) return parsed;
  }

  // Fall back to type-based template
  if (plan.workout_type) {
    return typeTemplate(plan.workout_type, totalMin);
  }

  // Final fallback: single block
  return [{ label: 'Run', duration_min: totalMin, intensity: 'moderate' }];
}
