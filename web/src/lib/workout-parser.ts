import type { PlanData } from '@/types/api';

export type Intensity = 'easy' | 'moderate' | 'hard' | 'very_hard' | 'rest';

export type PhaseCode =
  | 'warmup'
  | 'cooldown'
  | 'main'
  | 'run'
  | 'easy_run'
  | 'steady'
  | 'aerobic'
  | 'tempo'
  | 'threshold'
  | 'recovery'
  | 'rest'
  | 'rep';

export interface WorkoutPhase {
  code: PhaseCode;
  duration_min: number;
  intensity: Intensity;
  /** Rep number, set when code === 'rep' (1-indexed). */
  repNumber?: number;
}

const HARD_TYPES = new Set(['interval', 'intervals', 'threshold', 'tempo', 'race', 'race_pace']);

function parseDescription(desc: string, totalMin: number): WorkoutPhase[] | null {
  const phases: WorkoutPhase[] = [];
  const lower = desc.toLowerCase();

  const warmupMatch = lower.match(/warm[\s-]?up\s+(\d+)\s*min/);
  const cooldownMatch = lower.match(/cool[\s-]?down\s+(\d+)\s*min/);
  const intervalMatch = lower.match(/(\d+)\s*[x×]\s*(\d+)\s*min/);
  const restMatch = lower.match(/(?:rest|recovery|jog)\s+(\d+)\s*min|(\d+)\s*min\s+(?:rest|recovery|jog)/);

  if (!intervalMatch && !warmupMatch && !cooldownMatch) return null;

  const warmupMin = warmupMatch ? parseInt(warmupMatch[1]) : 0;
  const cooldownMin = cooldownMatch ? parseInt(cooldownMatch[1]) : 0;

  if (warmupMin > 0) {
    phases.push({ code: 'warmup', duration_min: warmupMin, intensity: 'easy' });
  }

  if (intervalMatch) {
    const reps = parseInt(intervalMatch[1]);
    const repMin = parseInt(intervalMatch[2]);
    const restMin = restMatch ? parseInt(restMatch[1] || restMatch[2]) : Math.max(1, Math.round(repMin * 0.5));

    const isThreshold = lower.includes('threshold') || lower.includes('tempo');
    const isHard = lower.includes('vo2') || lower.includes('hard') || lower.includes('fast');
    const mainIntensity: Intensity = isHard ? 'very_hard' : isThreshold ? 'hard' : 'moderate';

    for (let i = 0; i < reps; i++) {
      phases.push({
        code: 'rep',
        repNumber: i + 1,
        duration_min: repMin,
        intensity: mainIntensity,
      });
      if (i < reps - 1) {
        phases.push({ code: 'rest', duration_min: restMin, intensity: 'rest' });
      }
    }
  }

  if (cooldownMin > 0) {
    phases.push({ code: 'cooldown', duration_min: cooldownMin, intensity: 'easy' });
  }

  if (phases.length > 0) {
    if (totalMin > 0) {
      const parsedTotal = phases.reduce((s, p) => s + p.duration_min, 0);
      const remaining = totalMin - parsedTotal;
      if (remaining > 2 && !warmupMatch && phases.length > 0) {
        phases.unshift({ code: 'warmup', duration_min: Math.round(remaining * 0.6), intensity: 'easy' });
        phases.push({ code: 'cooldown', duration_min: Math.round(remaining * 0.4), intensity: 'easy' });
      }
    }
    return phases;
  }

  return null;
}

function typeTemplate(workoutType: string, totalMin: number): WorkoutPhase[] {
  const t = workoutType.toLowerCase().replace(/[\s_-]+/g, '_');

  if (t === 'recovery' || t === 'easy' || t === 'easy_run') {
    return [{ code: 'easy_run', duration_min: totalMin, intensity: 'easy' }];
  }

  if (t === 'long' || t === 'long_run') {
    const warmup = Math.round(totalMin * 0.1);
    const cooldown = Math.round(totalMin * 0.1);
    return [
      { code: 'warmup', duration_min: warmup, intensity: 'easy' },
      { code: 'steady', duration_min: totalMin - warmup - cooldown, intensity: 'moderate' },
      { code: 'cooldown', duration_min: cooldown, intensity: 'easy' },
    ];
  }

  if (t === 'steady_aerobic' || t === 'steady' || t === 'aerobic') {
    const warmup = Math.round(totalMin * 0.12);
    const cooldown = Math.round(totalMin * 0.08);
    return [
      { code: 'warmup', duration_min: warmup, intensity: 'easy' },
      { code: 'aerobic', duration_min: totalMin - warmup - cooldown, intensity: 'moderate' },
      { code: 'cooldown', duration_min: cooldown, intensity: 'easy' },
    ];
  }

  if (t === 'tempo') {
    const warmup = Math.round(totalMin * 0.15);
    const cooldown = Math.round(totalMin * 0.15);
    return [
      { code: 'warmup', duration_min: warmup, intensity: 'easy' },
      { code: 'tempo', duration_min: totalMin - warmup - cooldown, intensity: 'hard' },
      { code: 'cooldown', duration_min: cooldown, intensity: 'easy' },
    ];
  }

  if (t === 'threshold') {
    const warmup = Math.round(totalMin * 0.15);
    const cooldown = Math.round(totalMin * 0.15);
    const main = totalMin - warmup - cooldown;
    const repMin = Math.floor(main / 2);
    const restMin = main - repMin * 2;
    return [
      { code: 'warmup', duration_min: warmup, intensity: 'easy' },
      { code: 'threshold', duration_min: repMin, intensity: 'hard' },
      ...(restMin > 0 ? [{ code: 'recovery' as PhaseCode, duration_min: restMin, intensity: 'rest' as Intensity }] : []),
      { code: 'threshold', duration_min: repMin, intensity: 'hard' },
      { code: 'cooldown', duration_min: cooldown, intensity: 'easy' },
    ];
  }

  if (HARD_TYPES.has(t)) {
    const warmup = Math.round(totalMin * 0.15);
    const cooldown = Math.round(totalMin * 0.15);
    const main = totalMin - warmup - cooldown;
    const reps = 4;
    const restFrac = 0.35;
    const totalRest = Math.round(main * restFrac);
    const restPer = Math.round(totalRest / (reps - 1));
    const repDur = Math.round((main - totalRest) / reps);
    const phases: WorkoutPhase[] = [{ code: 'warmup', duration_min: warmup, intensity: 'easy' }];
    for (let i = 0; i < reps; i++) {
      phases.push({ code: 'rep', repNumber: i + 1, duration_min: repDur, intensity: 'very_hard' });
      if (i < reps - 1) {
        phases.push({ code: 'rest', duration_min: restPer, intensity: 'rest' });
      }
    }
    phases.push({ code: 'cooldown', duration_min: cooldown, intensity: 'easy' });
    return phases;
  }

  const warmup = Math.round(totalMin * 0.15);
  const cooldown = Math.round(totalMin * 0.1);
  return [
    { code: 'warmup', duration_min: warmup, intensity: 'easy' },
    { code: 'main', duration_min: totalMin - warmup - cooldown, intensity: 'moderate' },
    { code: 'cooldown', duration_min: cooldown, intensity: 'easy' },
  ];
}

export function parseWorkoutStructure(plan: PlanData): WorkoutPhase[] {
  // Rest days have no structure to render — falling through to the default
  // duration template would synthesize a fake 33-min "main set" and mislead
  // the user (#129). The backend treats both "rest" and "off" as rest types
  // (api/routes/plan.py, api/ai.py), so match the same set here.
  const wt = plan.workout_type?.toLowerCase();
  if (wt === 'rest' || wt === 'off') return [];
  if (plan.duration_min === 0) return [];

  // If duration is missing, only render structure when the description has
  // explicit phase durations to parse — never synthesize from a default.
  if (plan.duration_min == null) {
    if (plan.description) {
      const parsed = parseDescription(plan.description, 0);
      if (parsed && parsed.length > 0) return parsed;
    }
    return [];
  }

  const totalMin = plan.duration_min;

  if (plan.description) {
    const parsed = parseDescription(plan.description, totalMin);
    if (parsed && parsed.length > 0) return parsed;
  }

  if (plan.workout_type) {
    return typeTemplate(plan.workout_type, totalMin);
  }

  return [{ code: 'run', duration_min: totalMin, intensity: 'moderate' }];
}
