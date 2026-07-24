import type {
  HeatAdaptationAction,
  HeatAdaptationConfidence,
  HeatAdaptationSession,
  HeatAdaptationStage,
  HeatAdaptationStatus,
} from '../types/api';
import { detectLocale, t, tFmt, tNamed } from './i18n';

export type HeatTone = 'neutral' | 'amber' | 'green';

export const HEAT_HISTORY_SCROLL_KEY = 'praxys.training_scroll_target';
export const HEAT_HISTORY_SCROLL_TARGET = 'heat-adaptation';

export interface HeatCadenceDay {
  id: string;
  weekday: string;
  dayNumber: string;
  state: 'included' | 'observed' | 'empty';
  stateLabel: string;
  hasEvidence: boolean;
  detail: string;
}

export interface HeatEvidenceRow {
  id: string;
  label: string;
  value: string;
}

export interface HeatSessionRow {
  id: string;
  dateKey: string;
  date: string;
  environment: string;
  effective: string;
  workloadMethod: string;
  weatherEvidence: string;
  powerAlignment: string;
  status: string;
  reason: string;
  tone: 'included' | 'muted';
}

export interface HeatAdaptationView {
  label: string;
  closeLabel: string;
  metricValue: string;
  metricAction: string;
  stage: string;
  tone: HeatTone;
  conditionRange: string;
  conclusionLabel: string;
  conclusion: string;
  conclusionDetail: string;
  interpretation: string;
  basis: string;
  guidance: string;
  safetyText: string;

  showThresholdProgress: boolean;
  thresholdLabel: string;
  thresholdDescription: string;
  qualifyingDaysLabel: string;
  qualifyingDaysValue: string;
  qualifyingDaysPct: number;
  effectiveHeatLabel: string;
  effectiveHeatValue: string;
  effectiveHeatPct: number;

  evidenceDisclosureLabel: string;
  evidenceDisclosureMeta: string;
  evidenceRows: HeatEvidenceRow[];

  cadenceLabel: string;
  cadenceDescription: string;
  includedLegend: string;
  observedLegend: string;
  noSessionLegend: string;
  showCadence: boolean;
  cadenceDays: HeatCadenceDay[];
  defaultCadenceId: string;
  defaultCadenceDetail: string;

  sessionsLabel: string;
  sessionsDescription: string;
  emptySessionsText: string;
  missingSessionsText: string;
  hasSessions: boolean;
  sessions: HeatSessionRow[];

  scienceNote: string;
  scienceLinkLabel: string;
}

function localeName(): string {
  return detectLocale() === 'zh' ? 'zh-CN' : 'en-US';
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const [year, month, day] = value.slice(0, 10).split('-').map(Number);
  if (!year || !month || !day) return null;
  return new Date(year, month - 1, day, 12);
}

function formatDate(value: string): string {
  const parsed = parseDate(value);
  if (!parsed) return value;
  return parsed.toLocaleDateString(localeName(), { month: 'short', day: 'numeric' });
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(localeName(), { maximumFractionDigits: 0 }).format(value);
}

function formatThresholdNumber(value: number): string {
  return new Intl.NumberFormat(localeName(), { maximumFractionDigits: 1 }).format(value);
}

function thresholdProgressPct(current: number, target: number): number {
  if (target <= 0) return 0;
  if (current >= target) return 100;
  return Math.min(99.9, Math.round((current / target) * 1000) / 10);
}

function formatRange(min: number, max: number, suffix: string): string {
  const formatter = new Intl.NumberFormat(localeName(), { maximumFractionDigits: 1 });
  const low = formatter.format(min);
  const high = formatter.format(max);
  return low === high ? `${low}${suffix}` : `${low}–${high}${suffix}`;
}

function stageLabel(status: HeatAdaptationStatus): string {
  if (status.is_reacclimating) return t('Reacclimating');
  switch (status.stage) {
    case 'building': return t('Building');
    case 'likely_adapted': return t('Likely adapted');
    case 'maintaining': return t('Maintaining');
    case 'decaying': return t('Fading');
    default: return t('Insufficient evidence');
  }
}

function metricStageLabel(status: HeatAdaptationStatus): string {
  if (status.is_reacclimating) return t('Rebuilding');
  switch (status.stage) {
    case 'building': return t('Developing');
    case 'likely_adapted': return t('Likely adapted');
    case 'maintaining': return t('Likely retained');
    case 'decaying': return t('Fading');
    default: return t('Not established');
  }
}

function stageTone(stage: HeatAdaptationStage): HeatTone {
  if (stage === 'likely_adapted' || stage === 'maintaining') return 'green';
  if (stage === 'building' || stage === 'decaying') return 'amber';
  return 'neutral';
}

function stageConclusion(status: HeatAdaptationStatus): string {
  if (status.is_reacclimating) return t('Heat adaptation may be rebuilding.');
  switch (status.stage) {
    case 'likely_adapted':
      return t('Likely adapted to similar recent conditions.');
    case 'maintaining':
      return t('Prior heat adaptation is likely still retained.');
    case 'building':
      return t('Heat adaptation may be developing.');
    case 'decaying':
      return t('Prior heat adaptation evidence is fading.');
    default:
      return t('Heat adaptation is not established.');
  }
}

function stageInterpretation(status: HeatAdaptationStatus): string {
  if (status.is_reacclimating) {
    return t('Qualifying exposure has resumed after a longer gap, but current evidence is still limited.');
  }
  switch (status.stage) {
    case 'likely_adapted':
      return t("Recent training meets the model's conservative evidence threshold for acclimatization to similar conditions.");
    case 'maintaining':
      return status.recent_conditions
        ? t("A prior qualifying block remains inside the model's operational retention window. The range shown here describes current qualifying evidence, not that retained block.")
        : t("A prior qualifying block remains inside the model's operational retention window.");
    case 'building':
      return t('Recent training clears the Building threshold but remains below the conservative Likely adapted stage.');
    case 'decaying':
      return status.recent_conditions
        ? t('The last qualifying block is beyond the initial retention window, so retained evidence is declining. The range shown here describes current qualifying evidence, not that prior block.')
        : t('The last qualifying block is beyond the initial retention window, so retained evidence is declining.');
    default:
      return t("Recent training remains below the model's Building threshold.");
  }
}

function setupGuidance(action: HeatAdaptationAction): string {
  switch (action) {
    case 'sync_training_data':
      return t('Sync recent training to start estimating the conditions represented in your heat evidence.');
    case 'collect_supported_environment_data':
      return t('Recent activities need supported temperature and humidity data before a condition range can be estimated.');
    case 'set_power_threshold':
      return t('Set a power threshold so Praxys can identify sustained work without using diluted activity-average power.');
    case 'align_power_source':
      return t('Align the activity and threshold power sources before Praxys uses these sessions in the estimate.');
    case 'sync_power_provenance':
      return t('Sync power-source metadata so Praxys can verify that activity and threshold power are comparable.');
    case 'sync_power_evidence':
      return t('Sync split or sample power evidence so Praxys can identify sustained work.');
    default:
      return '';
  }
}

function confidenceLabel(confidence: HeatAdaptationConfidence): string {
  switch (confidence) {
    case 'high': return t('High coverage');
    case 'moderate': return t('Moderate coverage');
    default: return t('Low coverage');
  }
}

function lastExposureLabel(days: number | null): string {
  if (days == null) return t('None in the active window');
  if (days === 0) return t('Today');
  if (days === 1) return t('1 day ago');
  return tFmt('{0} days ago', days);
}

function buildCadence(status: HeatAdaptationStatus): HeatCadenceDay[] {
  return (status.cadence ?? []).flatMap((cadenceDay) => {
    const date = parseDate(cadenceDay.date);
    if (!date) return [];
    const formatted = date.toLocaleDateString(localeName(), { month: 'short', day: 'numeric' });
    const state = cadenceDay.counted_session_count > 0
      ? 'included' as const
      : cadenceDay.session_count > 0
        ? 'observed' as const
        : 'empty' as const;
    const excluded = cadenceDay.session_count - cadenceDay.counted_session_count;
    const detail = tNamed(
      '{formatted}: {included} included, {excluded} observed but not included, {minutes} effective min',
      {
        formatted,
        included: cadenceDay.counted_session_count,
        excluded,
        minutes: Math.round(cadenceDay.effective_heat_minutes),
      },
    );

    return {
      id: cadenceDay.date,
      weekday: date.toLocaleDateString(localeName(), { weekday: 'narrow' }),
      dayNumber: `${date.getDate()}`,
      state,
      stateLabel: state === 'included'
        ? t('Included')
        : state === 'observed'
          ? t('Not included')
          : t('No evidence'),
      hasEvidence: cadenceDay.session_count > 0,
      detail,
    };
  });
}

function workloadMethodSummary(session: HeatAdaptationSession): string {
  const coverage = session.sample_coverage_ratio == null
    ? null
    : Math.round(session.sample_coverage_ratio * 100);
  switch (session.workload_source) {
    case 'samples':
      return coverage == null
        ? t('Power samples')
        : tFmt('Power samples · {0}% coverage', coverage);
    case 'splits':
      return t('Activity splits');
    case 'samples_incomplete':
      return coverage == null
        ? t('Incomplete power samples')
        : tFmt('Incomplete power samples · {0}% coverage', coverage);
    default:
      return t('No supported workload evidence');
  }
}

function weatherEvidenceLabel(source: string): string {
  if (source === 'split_weighted') return t('Split-weighted weather');
  return t('Activity-summary weather');
}

function powerAlignmentLabel(alignment: HeatAdaptationSession['power_source_alignment']): string {
  switch (alignment) {
    case 'matched': return t('Matched');
    case 'mismatch': return t('Mismatch');
    case 'mixed': return t('Mixed providers');
    default: return t('Unverified');
  }
}

function sessionReason(session: HeatAdaptationSession, threshold: number): string {
  if (session.qualifies) {
    return t('Included because supported weather and workload evidence reached the session threshold.');
  }
  if (session.workload_evaluable) {
    return tFmt(
      'Observed, but not included because it stayed below {0} effective heat minutes.',
      threshold,
    );
  }
  if (session.workload_source === 'samples_incomplete') {
    return t('Observed, but not included because power-sample coverage was incomplete.');
  }
  if (session.power_source_alignment === 'mismatch') {
    return t('Observed, but not included because the activity and threshold power sources did not match.');
  }
  if (session.power_source_alignment === 'unknown') {
    return t('Observed, but not included because the power-source match could not be verified.');
  }
  if (session.power_source_alignment === 'mixed') {
    return t('Observed, but not included because workload evidence mixed power providers.');
  }
  return t('Observed, but not included because supported workload evidence was unavailable.');
}

function buildSessions(status: HeatAdaptationStatus): HeatSessionRow[] {
  const threshold = status.evidence_thresholds.qualifying_effective_minutes;
  return (status.cadence ?? []).flatMap((day) =>
    status.sessions
      .filter((session) => session.date === day.date)
      .map((session) => ({
        id: `${session.activity_id}-${session.date}`,
        dateKey: session.date,
        date: formatDate(session.date),
        environment: tFmt(
          '{0}°C · {1}% humidity',
          formatNumber(session.temperature_c),
          formatNumber(session.relative_humidity_pct),
        ),
        effective: tFmt(
          '{0} effective min',
          formatNumber(session.effective_heat_minutes),
        ),
        workloadMethod: workloadMethodSummary(session),
        weatherEvidence: weatherEvidenceLabel(session.environment_source),
        powerAlignment: powerAlignmentLabel(session.power_source_alignment),
        status: session.qualifies ? t('Included in estimate') : t('Observed, not included'),
        reason: sessionReason(session, threshold),
        tone: session.qualifies ? 'included' as const : 'muted' as const,
      })),
  ).reverse();
}

export function emptyHeatAdaptationView(): HeatAdaptationView {
  return {
    label: t('Heat adaptation'),
    closeLabel: t('Close'),
    metricValue: t('Not established'),
    metricAction: t('Open evidence'),
    stage: '',
    tone: 'neutral',
    conditionRange: t('No current qualifying condition range yet'),
    conclusionLabel: t('Current conclusion'),
    conclusion: t('Heat adaptation is not established.'),
    conclusionDetail: t("Recent training remains below the model's Building threshold."),
    interpretation: '',
    basis: '',
    guidance: '',
    safetyText: t("Past training only. This does not assess today's weather, guarantee adaptation, or replace medical guidance."),
    showThresholdProgress: false,
    thresholdLabel: t('Evidence toward Likely adapted'),
    thresholdDescription: t('Both thresholds must be met. The bars describe model evidence, not a biological adaptation percentage.'),
    qualifyingDaysLabel: t('Qualifying days'),
    qualifyingDaysValue: '',
    qualifyingDaysPct: 0,
    effectiveHeatLabel: t('Effective heat'),
    effectiveHeatValue: '',
    effectiveHeatPct: 0,
    evidenceDisclosureLabel: t('Open evidence'),
    evidenceDisclosureMeta: '',
    evidenceRows: [],
    cadenceLabel: t('Fourteen-day activity record'),
    cadenceDescription: t('Select a day to inspect what entered the estimate.'),
    includedLegend: t('Included'),
    observedLegend: t('Observed, not included'),
    noSessionLegend: t('No heat evidence'),
    showCadence: false,
    cadenceDays: [],
    defaultCadenceId: '',
    defaultCadenceDetail: '',
    sessionsLabel: t('Activity evidence'),
    sessionsDescription: t("The selected day's activities show why each session entered or stayed outside the estimate."),
    emptySessionsText: t('No supported heat evidence for this day.'),
    missingSessionsText: t('Detailed activity evidence is unavailable for this day.'),
    hasSessions: false,
    sessions: [],
    scienceNote: t('The thresholds are Praxys operational estimates grounded in heat-acclimatization research, not a direct physiological measurement.'),
    scienceLinkLabel: t('Read the active heat model'),
  };
}

export function buildHeatAdaptationView(status: HeatAdaptationStatus): HeatAdaptationView {
  const conditions = status.recent_conditions;
  const included = (status.cadence ?? []).reduce(
    (sum, day) => sum + day.counted_session_count,
    0,
  );
  const observed = (status.cadence ?? []).reduce(
    (sum, day) => sum + day.session_count,
    0,
  );
  const excluded = Math.max(0, observed - included);
  const temperatureRange = conditions
    ? formatRange(conditions.temperature_c.min, conditions.temperature_c.max, '°C')
    : '';
  const conditionRange = conditions
    ? `${t('Current qualifying evidence')} · ${tFmt(
        '{0} · {1} humidity',
        temperatureRange,
        formatRange(
          conditions.relative_humidity_pct.min,
          conditions.relative_humidity_pct.max,
          '%',
        ),
      )}`
    : t('No current qualifying condition range yet');
  const guidance = conditions ? '' : setupGuidance(status.next_action);
  const basis = conditions
    ? tNamed(
        'Based on {sessions} included sessions across {days} days in the last {window} days.',
        {
          sessions: conditions.qualifying_session_count,
          days: status.exposure_days,
          window: status.evidence_thresholds.active_window_days,
        },
      )
    : guidance
      ? ''
      : tFmt(
          "No recent activity reached the model's {0}-minute inclusion threshold.",
          status.evidence_thresholds.qualifying_effective_minutes,
        );
  const cadenceDays = buildCadence(status);
  const defaultCadence = [...cadenceDays].reverse().find((day) => day.state !== 'empty')
    ?? cadenceDays[cadenceDays.length - 1];
  const sessions = buildSessions(status);
  const thresholdDays = status.evidence_thresholds.likely_adapted_days;
  const thresholdMinutes = status.evidence_thresholds.likely_adapted_effective_minutes;
  const qualifyingDaysPct = thresholdProgressPct(status.exposure_days, thresholdDays);
  const effectiveHeatPct = thresholdProgressPct(status.effective_heat_minutes, thresholdMinutes);

  return {
    label: t('Heat adaptation'),
    closeLabel: t('Close'),
    metricValue: metricStageLabel(status),
    metricAction: status.stage === 'maintaining' || status.stage === 'decaying'
      ? t('Current evidence')
      : conditions
        ? tFmt('{0} · evidence', temperatureRange)
        : t('Open evidence'),
    stage: stageLabel(status),
    tone: stageTone(status.stage),
    conditionRange,
    conclusionLabel: t('Current conclusion'),
    conclusion: stageConclusion(status),
    conclusionDetail: stageInterpretation(status),
    interpretation: stageInterpretation(status),
    basis,
    guidance,
    safetyText: t("Past training only. This does not assess today's weather, guarantee adaptation, or replace medical guidance."),
    showThresholdProgress: status.stage !== 'maintaining' && status.stage !== 'decaying',
    thresholdLabel: t('Evidence toward Likely adapted'),
    thresholdDescription: t('Both thresholds must be met. The bars describe model evidence, not a biological adaptation percentage.'),
    qualifyingDaysLabel: t('Qualifying days'),
    qualifyingDaysValue: tNamed(
      '{current} / {target} days',
      { current: status.exposure_days, target: thresholdDays },
    ),
    qualifyingDaysPct,
    effectiveHeatLabel: t('Effective heat'),
    effectiveHeatValue: tNamed(
      '{current} / {target} min',
      {
        current: formatThresholdNumber(status.effective_heat_minutes),
        target: thresholdMinutes,
      },
    ),
    effectiveHeatPct,
    evidenceDisclosureLabel: t('Open evidence'),
    evidenceDisclosureMeta: tFmt(
      '{0} included · {1} observed, not included',
      included,
      excluded,
    ),
    evidenceRows: [
      {
        id: 'current',
        label: t('Current evidence'),
        value: tFmt(
          '{0} days · {1} effective min',
          status.exposure_days,
          Math.round(status.effective_heat_minutes),
        ),
      },
      {
        id: 'coverage',
        label: t('Data coverage'),
        value: confidenceLabel(status.confidence),
      },
      {
        id: 'threshold',
        label: t('Likely-adapted threshold'),
        value: tFmt(
          '{0} days · {1} effective min',
          status.evidence_thresholds.likely_adapted_days,
          status.evidence_thresholds.likely_adapted_effective_minutes,
        ),
      },
      {
        id: 'recency',
        label: t('Last included session'),
        value: lastExposureLabel(status.days_since_last_exposure),
      },
    ],
    cadenceLabel: t('Fourteen-day activity record'),
    cadenceDescription: t('Select a day to inspect what entered the estimate.'),
    includedLegend: t('Included'),
    observedLegend: t('Observed, not included'),
    noSessionLegend: t('No heat evidence'),
    showCadence: cadenceDays.length > 0,
    cadenceDays,
    defaultCadenceId: defaultCadence?.id ?? '',
    defaultCadenceDetail: defaultCadence?.detail ?? '',
    sessionsLabel: t('Activity evidence'),
    sessionsDescription: t("The selected day's activities show why each session entered or stayed outside the estimate."),
    emptySessionsText: t('No supported heat evidence for this day.'),
    missingSessionsText: t('Detailed activity evidence is unavailable for this day.'),
    hasSessions: sessions.length > 0,
    sessions,
    scienceNote: t('The thresholds are Praxys operational estimates grounded in heat-acclimatization research, not a direct physiological measurement.'),
    scienceLinkLabel: t('Read the active heat model'),
  };
}
