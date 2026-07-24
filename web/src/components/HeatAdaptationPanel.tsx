import { useMemo, useState, type ReactNode } from 'react';
import { msg } from '@lingui/core/macro';
import { Trans, useLingui } from '@lingui/react/macro';
import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';

import ScienceNote from '@/components/ScienceNote';
import { Progress } from '@/components/ui/progress';
import type {
  HeatAdaptationAction,
  HeatAdaptationConfidence,
  HeatAdaptationSession,
  HeatAdaptationStage,
  HeatAdaptationStatus,
} from '@/types/api';

const STAGE_LABELS: Record<HeatAdaptationStage, ReturnType<typeof msg>> = {
  insufficient_evidence: msg`Insufficient evidence`,
  building: msg`Building`,
  likely_adapted: msg`Likely adapted`,
  maintaining: msg`Maintaining`,
  decaying: msg`Fading`,
};

const METRIC_STAGE_LABELS: Record<HeatAdaptationStage, ReturnType<typeof msg>> = {
  insufficient_evidence: msg`Not established`,
  building: msg`Developing`,
  likely_adapted: msg`Likely adapted`,
  maintaining: msg`Likely retained`,
  decaying: msg`Fading`,
};

const CONFIDENCE_LABELS: Record<HeatAdaptationConfidence, ReturnType<typeof msg>> = {
  low: msg`Low coverage`,
  moderate: msg`Moderate coverage`,
  high: msg`High coverage`,
};

const ACTION_GUIDANCE: Partial<Record<HeatAdaptationAction, ReturnType<typeof msg>>> = {
  sync_training_data: msg`Sync recent training to start estimating the conditions represented in your heat evidence.`,
  collect_supported_environment_data: msg`Recent activities need supported temperature and humidity data before a condition range can be estimated.`,
  set_power_threshold: msg`Set a power threshold so Praxys can identify sustained work without using diluted activity-average power.`,
  align_power_source: msg`Align the activity and threshold power sources before Praxys uses these sessions in the estimate.`,
  sync_power_provenance: msg`Sync power-source metadata so Praxys can verify that activity and threshold power are comparable.`,
  sync_power_evidence: msg`Sync split or sample power evidence so Praxys can identify sustained work.`,
};

function localDate(value: string): Date {
  return new Date(`${value.slice(0, 10)}T12:00:00`);
}

function formatDate(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' }).format(localDate(value));
}

function formatWeekday(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(localDate(value));
}

function formatDayNumber(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { day: 'numeric' }).format(localDate(value));
}

function formatRange(
  min: number,
  max: number,
  suffix: string,
  locale: string,
): string {
  const formatter = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  const low = formatter.format(min);
  const high = formatter.format(max);
  return low === high ? `${low}${suffix}` : `${low}–${high}${suffix}`;
}

function formatThresholdNumber(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value);
}

function sourceLabel(session: HeatAdaptationSession): ReturnType<typeof msg> {
  if (session.workload_source === 'samples') return msg`Power samples`;
  if (session.workload_source === 'splits') return msg`Activity splits`;
  if (session.workload_source === 'samples_incomplete') return msg`Incomplete power samples`;
  return msg`No supported workload evidence`;
}

function environmentLabel(source: string): ReturnType<typeof msg> {
  if (source === 'split_weighted') return msg`Split-weighted weather`;
  if (source === 'activity_summary' || source.endsWith('_activity_weather')) {
    return msg`Activity-summary weather`;
  }
  return msg`No supported weather evidence`;
}

function powerAlignmentLabel(
  alignment: HeatAdaptationSession['power_source_alignment'],
): ReturnType<typeof msg> {
  if (alignment === 'matched') return msg`Matched`;
  if (alignment === 'mismatch') return msg`Mismatch`;
  if (alignment === 'mixed') return msg`Mixed providers`;
  return msg`Unverified`;
}

function effectiveMinutesLabel(minutes: number): ReturnType<typeof msg> {
  return msg`${minutes} effective min`;
}

function stageLabel(status: HeatAdaptationStatus): ReturnType<typeof msg> {
  return status.is_reacclimating ? msg`Reacclimating` : STAGE_LABELS[status.stage];
}

function metricStageLabel(status: HeatAdaptationStatus): ReturnType<typeof msg> {
  return status.is_reacclimating ? msg`Rebuilding` : METRIC_STAGE_LABELS[status.stage];
}

function stageConclusion(status: HeatAdaptationStatus): ReturnType<typeof msg> {
  if (status.is_reacclimating) return msg`Heat adaptation may be rebuilding.`;
  if (status.stage === 'likely_adapted') {
    return msg`Likely adapted to similar recent conditions.`;
  }
  if (status.stage === 'maintaining') {
    return msg`Prior heat adaptation is likely still retained.`;
  }
  if (status.stage === 'building') return msg`Heat adaptation may be developing.`;
  if (status.stage === 'decaying') return msg`Prior heat adaptation evidence is fading.`;
  return msg`Heat adaptation is not established.`;
}

function stageInterpretation(status: HeatAdaptationStatus): ReturnType<typeof msg> {
  if (status.is_reacclimating) {
    return msg`Qualifying exposure has resumed after a longer gap, but current evidence is still limited.`;
  }
  if (status.stage === 'likely_adapted') {
    return msg`Recent training meets the model's conservative evidence threshold for acclimatization to similar conditions.`;
  }
  if (status.stage === 'maintaining') {
    return status.recent_conditions
      ? msg`A prior qualifying block remains inside the model's operational retention window. The range shown here describes current qualifying evidence, not that retained block.`
      : msg`A prior qualifying block remains inside the model's operational retention window.`;
  }
  if (status.stage === 'building') {
    return msg`Recent training clears the Building threshold but remains below the conservative Likely adapted stage.`;
  }
  if (status.stage === 'decaying') {
    return status.recent_conditions
      ? msg`The last qualifying block is beyond the initial retention window, so retained evidence is declining. The range shown here describes current qualifying evidence, not that prior block.`
      : msg`The last qualifying block is beyond the initial retention window, so retained evidence is declining.`;
  }
  return msg`Recent training remains below the model's Building threshold.`;
}

function lastExposureLabel(days: number | null): ReturnType<typeof msg> {
  if (days == null) return msg`None in the active window`;
  if (days === 0) return msg`Today`;
  if (days === 1) return msg`1 day ago`;
  return msg`${days} days ago`;
}

function exclusionReason(
  session: HeatAdaptationSession,
  thresholdMinutes: number,
): ReturnType<typeof msg> {
  if (session.qualifies) {
    return msg`Included because supported weather and workload evidence reached the session threshold.`;
  }
  if (session.workload_evaluable) {
    return msg`Observed, but not included because it stayed below ${thresholdMinutes} effective heat minutes.`;
  }
  if (session.workload_source === 'samples_incomplete') {
    return msg`Observed, but not included because power-sample coverage was incomplete.`;
  }
  if (session.power_source_alignment === 'mismatch') {
    return msg`Observed, but not included because the activity and threshold power sources did not match.`;
  }
  if (session.power_source_alignment === 'unknown') {
    return msg`Observed, but not included because the power-source match could not be verified.`;
  }
  if (session.power_source_alignment === 'mixed') {
    return msg`Observed, but not included because workload evidence mixed power providers.`;
  }
  return msg`Observed, but not included because supported workload evidence was unavailable.`;
}

function stageToneClass(status: HeatAdaptationStatus): string {
  if (status.stage === 'likely_adapted' || status.stage === 'maintaining') {
    return 'bg-primary/15 text-foreground';
  }
  if (status.stage === 'building' || status.stage === 'decaying' || status.is_reacclimating) {
    return 'bg-accent-amber/15 text-foreground';
  }
  return 'bg-muted text-muted-foreground';
}

function EvidenceProgress({
  label,
  current,
  target,
  valueLabel,
  ariaLabel,
}: {
  label: ReactNode;
  current: number;
  target: number;
  valueLabel: string;
  ariaLabel: string;
}) {
  const value = target <= 0
    ? 0
    : current >= target
      ? 100
      : Math.min(99.9, (current / target) * 100);

  return (
    <div>
      <div className="flex items-center justify-between gap-4 text-xs">
        <span className="font-medium text-foreground">{label}</span>
        <span className="font-data text-muted-foreground">{valueLabel}</span>
      </div>
      <Progress
        value={value}
        aria-label={ariaLabel}
        className="mt-2 gap-0 [&_[data-slot=progress-indicator]]:bg-accent-cobalt [&_[data-slot=progress-track]]:h-1.5"
      />
    </div>
  );
}

function HeatCadence({
  status,
  selectedDate,
  onSelect,
}: {
  status: HeatAdaptationStatus;
  selectedDate: string | null;
  onSelect: (date: string) => void;
}) {
  const { i18n } = useLingui();
  const locale = i18n.locale || 'en';
  const selected = status.cadence.find((day) => day.date === selectedDate) ?? null;

  return (
    <section className="mt-7" aria-labelledby="heat-cadence-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="heat-cadence-title" className="text-sm font-semibold text-foreground">
            <Trans>Fourteen-day activity record</Trans>
          </h3>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted-foreground">
            <Trans>Select a day to inspect what entered the estimate.</Trans>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm border border-primary/50 bg-primary/20" aria-hidden="true" />
            <Trans>Included</Trans>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm border border-accent-amber/60 bg-accent-amber/15" aria-hidden="true" />
            <Trans>Observed</Trans>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm border border-border bg-muted/35" aria-hidden="true" />
            <Trans>No heat evidence</Trans>
          </span>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-7 gap-1 sm:gap-2">
        {status.cadence.map((day) => {
          const isSelected = selected?.date === day.date;
          const hasIncluded = day.counted_session_count > 0;
          const hasObserved = day.session_count > 0;
          const excluded = day.session_count - day.counted_session_count;
          const stateClass = hasIncluded
            ? 'border-primary/45 bg-primary/10 hover:bg-primary/15'
            : hasObserved
              ? 'border-accent-amber/55 bg-accent-amber/10 hover:bg-accent-amber/15'
              : 'border-border bg-muted/30 hover:bg-muted/50';
          const label = i18n._(
            msg`${formatDate(day.date, locale)}: ${day.counted_session_count} included, ${excluded} observed but not included`,
          );

          return (
            <button
              key={day.date}
              type="button"
              aria-label={label}
              aria-pressed={isSelected}
              onClick={() => onSelect(day.date)}
              className={`h-12 min-w-0 rounded-md border p-1 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:h-[4.6rem] sm:p-2 ${stateClass} ${
                isSelected ? 'ring-2 ring-foreground/80 ring-offset-2 ring-offset-background' : ''
              }`}
            >
              <span className="flex items-baseline justify-between gap-1">
                <span className="hidden text-[11px] uppercase tracking-wide text-muted-foreground sm:inline">
                  {formatWeekday(day.date, locale)}
                </span>
                <span className="font-data text-[11px] font-semibold text-foreground sm:text-xs">
                  {formatDayNumber(day.date, locale)}
                </span>
              </span>
              <span className="mt-0.5 block truncate font-data text-[11px] font-semibold text-foreground sm:mt-2">
                {hasObserved ? `${Math.round(day.effective_heat_minutes)}m` : '—'}
              </span>
              <span className="mt-0.5 hidden text-[11px] font-medium text-muted-foreground sm:block">
                {hasIncluded
                  ? i18n._(msg`Included`)
                  : hasObserved
                    ? i18n._(msg`Observed`)
                    : i18n._(msg`No evidence`)}
              </span>
            </button>
          );
        })}
      </div>

      {selected && (
        <div className="mt-4 rounded-lg bg-muted/35 p-4" aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-data text-sm font-semibold text-foreground">
              {formatDate(selected.date, locale)}
            </p>
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
              selected.counted_session_count > 0
                ? 'bg-primary/15 text-foreground'
                : selected.session_count > 0
                  ? 'bg-accent-amber/15 text-foreground'
                  : 'bg-muted text-muted-foreground'
            }`}>
              {selected.counted_session_count > 0
                ? i18n._(msg`Included in estimate`)
                : selected.session_count > 0
                  ? i18n._(msg`Observed, not included`)
                  : i18n._(msg`No heat evidence`)}
            </span>
          </div>
          <p className="mt-2 font-data text-xs text-foreground">
            <Trans>
              {selected.counted_session_count} included · {selected.session_count - selected.counted_session_count} observed, not included · {Math.round(selected.effective_heat_minutes)} effective min
            </Trans>
          </p>
        </div>
      )}
    </section>
  );
}

function HeatEvidenceForDay({
  status,
  selectedDate,
}: {
  status: HeatAdaptationStatus;
  selectedDate: string | null;
}) {
  const { i18n } = useLingui();
  const locale = i18n.locale || 'en';
  const threshold = status.evidence_thresholds.qualifying_effective_minutes;
  const sessions = selectedDate
    ? status.sessions.filter((session) => session.date === selectedDate)
    : [];
  const selectedDay = selectedDate
    ? status.cadence.find((day) => day.date === selectedDate)
    : null;

  return (
    <section className="mt-7" aria-labelledby="heat-activity-evidence-title">
      <h3 id="heat-activity-evidence-title" className="text-sm font-semibold text-foreground">
        <Trans>Activity evidence</Trans>
      </h3>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
        <Trans>
          The selected day's activities show why each session entered or stayed outside the estimate.
        </Trans>
      </p>

      {sessions.length === 0 ? (
        <div className="mt-3 rounded-lg bg-muted/35 p-4 text-sm text-muted-foreground">
          {selectedDay && selectedDay.session_count > 0 ? (
            <Trans>Detailed activity evidence is unavailable for this day.</Trans>
          ) : (
            <Trans>No supported heat evidence for this day.</Trans>
          )}
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          {sessions.map((session) => (
            <article key={`${session.date}-${session.activity_id}`} className="rounded-lg border border-border p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-data text-sm font-semibold text-foreground">
                    {formatDate(session.date, locale)}
                  </p>
                  <p className="mt-1 font-data text-xs text-muted-foreground">
                    {Math.round(session.temperature_c)}°C · {Math.round(session.relative_humidity_pct)}%
                  </p>
                </div>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                  session.qualifies
                    ? 'bg-primary/15 text-foreground'
                    : 'bg-accent-amber/15 text-foreground'
                }`}>
                  {session.qualifies
                    ? i18n._(msg`Included in estimate`)
                    : i18n._(msg`Observed, not included`)}
                </span>
              </div>

              <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                {i18n._(exclusionReason(session, threshold))}
              </p>

              <dl className="mt-4 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-2">
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground"><Trans>Workload evidence</Trans></dt>
                  <dd className="text-right text-foreground">{i18n._(sourceLabel(session))}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground"><Trans>Weather evidence</Trans></dt>
                  <dd className="text-right text-foreground">{i18n._(environmentLabel(session.environment_source))}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground"><Trans>Effective heat time</Trans></dt>
                  <dd className="font-data text-foreground">
                    {i18n._(effectiveMinutesLabel(Math.round(session.effective_heat_minutes)))}
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground"><Trans>Power-source match</Trans></dt>
                  <dd className="text-right text-foreground">
                    {i18n._(powerAlignmentLabel(session.power_source_alignment))}
                  </dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export function HeatAdaptationMetricValue({ status }: { status: HeatAdaptationStatus }) {
  const { i18n } = useLingui();
  return <>{i18n._(metricStageLabel(status))}</>;
}

export function HeatAdaptationMetricContext({ status }: { status: HeatAdaptationStatus }) {
  const { i18n } = useLingui();
  const locale = i18n.locale || 'en';
  const temperatureRange = status.recent_conditions
    ? formatRange(
        status.recent_conditions.temperature_c.min,
        status.recent_conditions.temperature_c.max,
        '°C',
        locale,
      )
    : null;

  if (status.stage === 'maintaining' || status.stage === 'decaying') {
    return <Trans>Current evidence</Trans>;
  }
  if (temperatureRange) {
    return <>{temperatureRange} <span aria-hidden="true">·</span> <Trans>evidence</Trans></>;
  }
  return <Trans>Open evidence</Trans>;
}

export function HeatAdaptationSheetDescription({ status }: { status: HeatAdaptationStatus }) {
  const { i18n } = useLingui();
  const locale = i18n.locale || 'en';
  const conditions = status.recent_conditions;
  const temperatureRange = conditions
    ? formatRange(conditions.temperature_c.min, conditions.temperature_c.max, '°C', locale)
    : null;
  const humidityRange = conditions
    ? i18n._(
        msg`${formatRange(
          conditions.relative_humidity_pct.min,
          conditions.relative_humidity_pct.max,
          '%',
          locale,
        )} humidity`,
      )
    : null;

  return temperatureRange && humidityRange ? (
    <>
      <Trans>Current qualifying evidence</Trans>{' '}
      <span aria-hidden="true">·</span> {temperatureRange}{' '}
      <span aria-hidden="true">·</span> {humidityRange}
    </>
  ) : (
    <Trans>No current qualifying condition range yet</Trans>
  );
}

export default function HeatAdaptationDetail({ status }: { status: HeatAdaptationStatus }) {
  const { i18n } = useLingui();
  const locale = i18n.locale || 'en';
  const conditions = status.recent_conditions;
  const included = status.cadence.reduce((sum, day) => sum + day.counted_session_count, 0);
  const observed = status.cadence.reduce((sum, day) => sum + day.session_count, 0);
  const excluded = Math.max(0, observed - included);
  const actionGuidance = ACTION_GUIDANCE[status.next_action];
  const defaultDay = useMemo(
    () =>
      [...status.cadence].reverse().find((day) => day.session_count > 0)
      ?? status.cadence.at(-1)
      ?? null,
    [status.cadence],
  );
  const [selectedDate, setSelectedDate] = useState<string | null>(defaultDay?.date ?? null);
  const activeSelectedDate = status.cadence.some((day) => day.date === selectedDate)
    ? selectedDate
    : defaultDay?.date ?? null;
  const thresholdDays = status.evidence_thresholds.likely_adapted_days;
  const thresholdMinutes = status.evidence_thresholds.likely_adapted_effective_minutes;
  const showThresholdProgress = status.stage !== 'maintaining' && status.stage !== 'decaying';

  return (
    <>
      <div className="flex flex-wrap items-center gap-3 rounded-lg bg-muted/35 p-4">
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${stageToneClass(status)}`}>
              {i18n._(stageLabel(status))}
            </span>
            <p className="font-data text-xs text-muted-foreground">
              <Trans>{included} included · {excluded} observed, not included</Trans>
            </p>
          </div>

          <section className="mt-6" aria-labelledby="heat-conclusion-title">
            <p className="font-data text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              <Trans>Current conclusion</Trans>
            </p>
            <h3 id="heat-conclusion-title" className="mt-2 text-lg font-semibold tracking-[-0.015em] text-foreground">
              {i18n._(stageConclusion(status))}
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
              {i18n._(stageInterpretation(status))}
            </p>
            {!conditions && actionGuidance && (
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {i18n._(actionGuidance)}
              </p>
            )}
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              <Trans>
                This is an inference from training evidence in similar conditions, not a direct physiological measurement.
              </Trans>
            </p>
          </section>

          {showThresholdProgress && (
            <section className="mt-7" aria-labelledby="heat-threshold-title">
              <h3 id="heat-threshold-title" className="text-sm font-semibold text-foreground">
                <Trans>Evidence toward Likely adapted</Trans>
              </h3>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                <Trans>
                  Both thresholds must be met. The bars describe model evidence, not a biological adaptation percentage.
                </Trans>
              </p>
              <div className="mt-4 space-y-4">
                <EvidenceProgress
                  label={<Trans>Qualifying days</Trans>}
                  current={status.exposure_days}
                  target={thresholdDays}
                  valueLabel={i18n._(msg`${status.exposure_days} / ${thresholdDays} days`)}
                  ariaLabel={i18n._(msg`Qualifying days: ${status.exposure_days} of ${thresholdDays}`)}
                />
                <EvidenceProgress
                  label={<Trans>Effective heat</Trans>}
                  current={status.effective_heat_minutes}
                  target={thresholdMinutes}
                  valueLabel={i18n._(msg`${formatThresholdNumber(status.effective_heat_minutes, locale)} / ${thresholdMinutes} min`)}
                  ariaLabel={i18n._(msg`Effective heat: ${formatThresholdNumber(status.effective_heat_minutes, locale)} of ${thresholdMinutes} minutes`)}
                />
              </div>
            </section>
          )}

          <dl className="mt-7 grid gap-x-8 gap-y-4 rounded-lg bg-muted/35 p-4 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted-foreground"><Trans>Data coverage</Trans></dt>
              <dd className="mt-1 text-foreground">{i18n._(CONFIDENCE_LABELS[status.confidence])}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground"><Trans>Last included session</Trans></dt>
              <dd className="mt-1 font-data text-foreground">
                {i18n._(lastExposureLabel(status.days_since_last_exposure))}
              </dd>
            </div>
          </dl>

          <HeatCadence
            status={status}
            selectedDate={activeSelectedDate}
            onSelect={setSelectedDate}
          />
          <HeatEvidenceForDay status={status} selectedDate={activeSelectedDate} />

          <div className="mt-7">
            <ScienceNote embedded>
              <p>
                <Trans>
                  The thresholds are Praxys operational estimates grounded in heat-acclimatization research, not a direct physiological measurement.
                </Trans>
              </p>
              <p className="mt-2">
                <Trans>
                  Past training only. This does not assess today's weather, guarantee adaptation, or replace medical guidance.
                </Trans>
              </p>
              <Link
                to="/science#heat"
                className="mt-3 inline-flex items-center gap-2 text-sm font-medium text-[var(--accent-cobalt-val)] hover:underline hover:underline-offset-4"
              >
                <Trans>Read the active heat model</Trans>
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </ScienceNote>
      </div>
    </>
  );
}
