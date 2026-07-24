# trail-running/analysis/report_renderer.py
"""Generate weekly markdown training report."""
import os
from datetime import date


def _render_diagnosis_section(diagnosis: dict | None) -> str:
    """Render training diagnosis as markdown section."""
    if not diagnosis or not diagnosis.get("diagnosis"):
        return ""

    interval = diagnosis.get("interval_power", {})
    volume = diagnosis.get("volume", {})
    dist = diagnosis.get("distribution", {})
    findings = diagnosis.get("diagnosis", [])
    suggestions = diagnosis.get("suggestions", [])
    lookback = diagnosis.get("lookback_weeks", 6)

    lines = [f"## Training Diagnosis (last {lookback} weeks)", ""]

    # Stats
    stats = []
    weekly_avg_km = volume.get("weekly_avg_km")
    weeks = volume.get("weeks")
    volume_available = bool(weeks) if weeks is not None else bool(weekly_avg_km)
    if volume_available and weekly_avg_km is not None:
        stats.append(
            f"**Volume:** {weekly_avg_km} km/week avg "
            f"({volume.get('trend', '?')})"
        )
    if interval.get("max"):
        stats.append(f"**Peak interval power:** {interval['max']:.0f}W")
    if interval.get("avg_work"):
        stats.append(f"**Avg work interval:** {interval['avg_work']:.0f}W")
    stats.append(f"**Supra-CP sessions:** {interval.get('supra_cp_sessions', 0)} / {interval.get('total_quality_sessions', 0)} quality")
    for s in stats:
        lines.append(f"- {s}")

    # Distribution
    lines.append("")
    lines.append(f"**Distribution:** {dist.get('supra_cp', 0)}% supra-CP | {dist.get('threshold', 0)}% threshold | {dist.get('tempo', 0)}% tempo | {dist.get('easy', 0)}% easy")

    # Findings
    lines.append("")
    lines.append("### Findings")
    lines.append("")
    for f in findings:
        icon = {"positive": "+", "warning": "!", "neutral": "-"}.get(f["type"], "-")
        lines.append(f"- **{icon}** {f['message']}")

    # Suggestions
    if suggestions:
        lines.append("")
        lines.append("### Suggestions")
        lines.append("")
        for s in suggestions:
            lines.append(f"- {s}")

    return "\n".join(lines)


def render_weekly_report(
    output_dir: str,
    report_date: date,
    summary: dict,
    training_signal: dict,
    race_countdown: dict,
    insights: dict,
    diagnosis: dict | None = None,
) -> str:
    """Generate weekly markdown report.

    Args:
        output_dir: directory to write report
        report_date: date for the report filename
        summary: dict with volume_km, total_rss, planned_rss, num_activities
        training_signal: today's recommendation
        race_countdown: race readiness info
        insights: fatigue warnings, sleep-perf findings
        diagnosis: training diagnosis findings and suggestions

    Returns:
        Path to the generated report file
    """
    filename = f"{report_date.isoformat()}-weekly.md"
    path = os.path.join(output_dir, filename)

    def fmt_time(sec):
        if not sec:
            return "N/A"
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        return f"{h}:{m:02d}"

    compliance_pct = ""
    if summary.get("planned_rss") and summary["planned_rss"] > 0:
        pct = (summary.get("total_rss", 0) / summary["planned_rss"]) * 100
        compliance_pct = f" ({pct:.0f}% of plan)"

    warnings = insights.get("warnings", [])
    warnings_md = "\n".join(f"- {w}" for w in warnings) if warnings else "- No warnings this week."

    mode = race_countdown.get("mode", "race_date")

    if mode == "cp_milestone":
        reality = race_countdown.get("reality_check", {})
        current_cp = race_countdown.get("current_cp", "?")
        target_cp = race_countdown.get("target_cp", "?")
        gap_w = reality.get("cp_gap_watts", "?")
        gap_pct = reality.get("cp_gap_pct", "?")
        trend_note = reality.get("trend_note", "")
        est_months = race_countdown.get("estimated_months")
        est_str = f"~{est_months:.0f} months (at current trend)" if est_months and est_months > 0 else "unknown (trend flat or declining)"
        milestones = reality.get("milestones", [])
        ms_lines = "\n".join(
            f"- {'[x]' if m['reached'] else '[ ]'} **{m['cp']}W** — {m['marathon']}"
            for m in milestones
        ) if milestones else "- No milestones in range"

        readiness_section = f"""## CP Progress

- **Current CP:** {current_cp:.0f}W
- **Target CP:** {target_cp:.0f}W (sub-3 marathon territory)
- **Gap:** {gap_w:.0f}W ({gap_pct:.0f}%)
- **Trend:** {trend_note}
- **Estimated time to target:** {est_str}
- **Status:** {race_countdown.get('status', 'unknown').upper()}

### Milestones

{ms_lines}"""
    else:
        readiness_section = f"""## Race Readiness

- **Target:** {race_countdown.get('race_date', 'N/A')} — {fmt_time(race_countdown.get('target_time_sec'))}
- **Predicted:** {fmt_time(race_countdown.get('predicted_time_sec'))}
- **Days remaining:** {race_countdown.get('days_left', '?')}
- **Status:** {race_countdown.get('status', 'unknown').upper()}"""

    if mode == "cp_milestone":
        next_week = "focus on threshold sessions to push CP" if race_countdown.get("status") != "on_track" else "maintain current training — CP is trending well"
    else:
        next_week = "maintain current load" if race_countdown.get("status") == "on_track" else "consider adjusting training load to close the gap"

    content = f"""# Weekly Training Report — {report_date.isoformat()}

## Week Summary

| Metric | Value |
|--------|-------|
| Activities | {summary.get('num_activities', 0)} |
| Volume | {summary.get('volume_km', 0):.1f} km |
| Total RSS | {summary.get('total_rss', 0):.0f}{compliance_pct} |
| Planned RSS | {summary.get('planned_rss', 'N/A')} |

{readiness_section}

## Key Insights

{warnings_md}

## Today's Signal

**{training_signal.get('recommendation', 'N/A').upper()}** — {training_signal.get('reason', '')}

## Next Week Suggestion

Based on current trends: {next_week}.

{_render_diagnosis_section(diagnosis)}"""

    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return path
