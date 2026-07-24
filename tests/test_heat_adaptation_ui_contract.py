"""Regression contracts for heat-adaptation placement and disclosure."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WEB_TODAY = ROOT / "web" / "src" / "pages" / "Today.tsx"
WEB_TRAINING = ROOT / "web" / "src" / "pages" / "Training.tsx"
WEB_HEAT = ROOT / "web" / "src" / "components" / "HeatAdaptationPanel.tsx"
WEB_METRIC_SHEET = ROOT / "web" / "src" / "components" / "MetricDetailSheet.tsx"
WEB_TSB_CHART = ROOT / "web" / "src" / "components" / "charts" / "FitnessFatigueChart.tsx"
WEB_VOLUME_CHART = ROOT / "web" / "src" / "components" / "charts" / "WeeklyVolumeChart.tsx"
MINI_TODAY = ROOT / "miniapp" / "pages" / "today" / "index.wxml"
MINI_TODAY_TS = ROOT / "miniapp" / "pages" / "today" / "index.ts"
MINI_TRAINING = ROOT / "miniapp" / "pages" / "training" / "index.wxml"
MINI_TRAINING_TS = ROOT / "miniapp" / "pages" / "training" / "index.ts"
MINI_HEAT = ROOT / "miniapp" / "utils" / "heat-adaptation.ts"
WEB_SCIENCE = ROOT / "web" / "src" / "pages" / "Science.tsx"
MINI_SCIENCE = ROOT / "miniapp" / "pages" / "science" / "index.wxml"
MINI_SCIENCE_TS = ROOT / "miniapp" / "pages" / "science" / "index.ts"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_today_does_not_imply_current_weather_is_available() -> None:
    """Heat stays off Today until a real current-weather input exists."""
    web_today = _source(WEB_TODAY)
    web_heat = _source(WEB_HEAT)
    mini_today = _source(MINI_TODAY)
    mini_today_ts = _source(MINI_TODAY_TS)

    assert "data.heat_adaptation.today_restricted" not in web_today
    assert "TodayHeatConstraint" not in web_today
    assert "<HeatAdaptationPanel" not in web_today
    assert "TodayHeatConstraint" not in web_heat

    assert "today-heat" not in mini_today
    assert "HEAT_HISTORY_SCROLL_KEY" not in mini_today_ts
    assert "buildHeatAdaptationView" not in mini_today_ts


def test_training_owns_the_longitudinal_heat_story() -> None:
    """Training should present five aligned peer metrics with bounded details."""
    web_training = _source(WEB_TRAINING)
    web_heat = _source(WEB_HEAT)
    web_metric_sheet = _source(WEB_METRIC_SHEET)
    web_tsb_chart = _source(WEB_TSB_CHART)
    web_volume_chart = _source(WEB_VOLUME_CHART)
    mini_training = _source(MINI_TRAINING)
    mini_training_ts = _source(MINI_TRAINING_TS)
    mini_today_ts = _source(MINI_TODAY_TS)
    mini_heat = _source(MINI_HEAT)

    for metric_id in ("tsb", "distribution", "load", "volume", "heat"):
        assert f"id: '{metric_id}'" in web_training
    assert "<PeerMetricList" in web_training
    assert "<MetricDetailSheet" in web_training
    assert sum(
        line.startswith("      sheetSize:") for line in web_training.splitlines()
    ) == 5
    assert web_training.count("? 'wide' : 'standard'") == 4
    assert web_training.count("sheetSize: 'standard'") == 1
    assert "DiagnosisChartSwitcher" not in web_training
    assert "DIAGNOSIS_CHART_KEY" not in web_training
    assert "Select a metric to inspect its chart or evidence." in web_training
    assert "lg:grid-cols-[minmax(0,0.9fr)_minmax(24rem,1.1fr)]" in web_training
    assert "location.hash !== '#heat-adaptation'" in web_training
    assert "setActiveMetric('heat')" in web_training
    assert "sm:!max-w-[52rem]" in web_metric_sheet
    assert "sm:!max-w-[34rem]" in web_metric_sheet
    assert "data-metric-size={size}" in web_metric_sheet
    assert "side={isMobile ? 'bottom' : 'right'}" in web_metric_sheet
    assert "const targetCount = Math.min(chartData.length, isMobile ? 5 : 10)" in web_tsb_chart
    assert "ticks={xAxisTicks}" in web_tsb_chart
    assert "<SheetTrigger" not in web_heat
    assert "HeatAdaptationMetricValue" in web_heat
    assert "HeatAdaptationSheetDescription" in web_heat
    assert "Current conclusion" in web_heat
    assert 'to="/science#heat"' in web_heat
    assert "label={<Trans>Qualifying days</Trans>}" in web_heat
    assert "label={<Trans>Effective heat</Trans>}" in web_heat
    assert "current >= target" in web_heat
    assert "formatThresholdNumber(status.effective_heat_minutes, locale)" in web_heat
    assert "<ScienceNote embedded>" in web_heat
    assert "<HeatCadence" in web_heat
    assert "<HeatEvidenceForDay" in web_heat
    assert "status.sessions.filter((session) => session.date === selectedDate)" in web_heat
    assert "HeatEvidenceLedger" not in web_heat
    assert "(volume.weeks ?? []).map" in web_volume_chart
    assert "const weeklyKm = volume.weekly_km ?? []" in web_volume_chart
    assert "Weeks with no recorded distance remain in the series and average" in web_volume_chart
    assert "newer half must differ from the older half by more than 10%" in web_volume_chart
    assert "const volumeSummaryAvailable = volumeWeeks === undefined" in web_training
    assert "data.diagnosis.volume.weekly_avg_km > 0" in web_training
    assert "const volumeSeriesPending = volumeWeeks === undefined" in web_training
    assert "const volumeSeriesAvailable = (" in web_training
    assert "unit: volumeSummaryAvailable ? <Trans>km/wk</Trans> : undefined" in web_training
    assert "Weekly chart temporarily unavailable" in web_training

    assert 'class="train-metrics"' in mini_training
    assert 'class="train-metric-row"' in mini_training
    assert 'data-metric="{{item.id}}"' in mini_training
    assert 'bindtap="onOpenMetricDetail"' in mini_training
    assert 'class="train-pills"' not in mini_training
    assert "activePill" not in mini_training_ts
    assert 'class="train-metric-overlay"' in mini_training
    assert 'aria-role="dialog"' in mini_training
    for metric_id in ("tsb", "dist", "load", "volume"):
        assert f"activeMetric === '{metric_id}'" in mini_training
    assert "activeMetric !== 'heat'" in mini_training
    assert 'canvas-id="train-detail-volume"' in mini_training
    assert 'aria-hidden="true"' in mini_training
    assert 'actual="{{volumeKm}}"' in mini_training
    assert 'value-decimals="{{1}}"' in mini_training
    assert 'aria-role="list"' in mini_training
    assert 'wx:for="{{volumePoints}}"' in mini_training
    assert "volumeKm" in mini_training_ts
    assert "volumeHintMessage" in mini_training_ts
    assert "volumeSeriesPending" in mini_training_ts
    assert "weekly_km" in mini_training_ts
    assert "volumeAvailable && weeklyKm != null" in mini_training_ts
    assert "unit: volumeAvailable ? tr.statVolumeUnit : ''" in mini_training_ts
    assert "function hasVolumeSummary(" in mini_training_ts
    assert "volume.weeks === undefined" in mini_training_ts
    assert "volume.weekly_avg_km > 0" in mini_training_ts
    assert "!!diagnosis?.volume?.weekly_avg_km" not in mini_training_ts
    assert "{{tr.tsbMethodology}}" in mini_training
    assert "{{heat.qualifyingDaysValue}}" in mini_training
    assert "{{heat.effectiveHeatValue}}" in mini_training
    assert 'wx:if="{{heat.showCadence}}"' in mini_training
    assert "thresholdProgressPct(status.effective_heat_minutes, thresholdMinutes)" in mini_heat
    assert "formatThresholdNumber(status.effective_heat_minutes)" in mini_heat
    assert "session.dateKey === day.id" in mini_training_ts
    assert 'wx:for="{{selectedHeatSessions}}"' in mini_training
    assert "scrollToHeatIfPending" in mini_training_ts
    assert "activeMetric: 'heat'" in mini_training_ts


def test_science_shows_heat_as_active_fixed_model() -> None:
    """Heat methodology is visible without presenting a fake switch."""
    web_science = _source(WEB_SCIENCE)
    mini_science = _source(MINI_SCIENCE)
    mini_science_ts = _source(MINI_SCIENCE_TS)

    assert "key: 'heat'" in web_science
    assert "fixed_pillars.includes(focused)" in web_science
    assert "Active fixed model" in web_science
    assert "key: 'heat'" in mini_science_ts or "'heat'" in mini_science_ts
    assert "isFixed" in mini_science_ts
    assert "{{tr.fixedModelTag}}" in mini_science


def test_evidence_details_are_localizable_and_explain_mixed_providers() -> None:
    """Evidence detail values should not leak raw API tokens or wrong reasons."""
    web_heat = _source(WEB_HEAT)
    mini_heat = _source(MINI_HEAT)
    mixed_reason = (
        "Observed, but not included because workload evidence mixed power providers."
    )

    assert mixed_reason in web_heat
    assert mixed_reason in mini_heat
    assert "powerAlignmentLabel(session.power_source_alignment)" in web_heat
    assert "{session.power_source_alignment}" not in web_heat
    assert "effectiveMinutesLabel(" in web_heat
    assert "conditions.relative_humidity_pct.min" in web_heat
