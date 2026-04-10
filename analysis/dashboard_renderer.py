# trail-running/analysis/dashboard_renderer.py
"""Generate self-contained HTML dashboard from computed training data."""
import json
import os
from datetime import date


def render_dashboard(
    output_path: str,
    training_signal: dict,
    race_countdown: dict,
    fitness_fatigue: dict,
    weekly_review: dict,
    insights: dict,
    diagnosis: dict | None = None,
) -> None:
    """Generate dashboard.html with all panels.

    Args:
        output_path: where to write dashboard.html
        training_signal: dict with recommendation/reason for today
        race_countdown: dict with race_date, predicted_time, target_time, cp_trend
        fitness_fatigue: dict with dates, ctl, atl, tsb arrays
        weekly_review: dict with compliance data, good/bad workouts
        insights: dict with sleep_perf correlation, fatigue warnings
    """
    html = _build_html(training_signal, race_countdown, fitness_fatigue, weekly_review, insights, diagnosis or {})
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


def _signal_color(recommendation: str) -> str:
    colors = {
        "follow_plan": "#22c55e",
        "easy": "#f59e0b",
        "modify": "#f59e0b",
        "reduce_intensity": "#f59e0b",
        "rest": "#ef4444",
    }
    return colors.get(recommendation, "#6b7280")


def _signal_label(recommendation: str) -> str:
    labels = {
        "follow_plan": "GO — Follow Plan",
        "easy": "CAUTION — Go Easy",
        "modify": "MODIFY — Adjust Today's Workout",
        "reduce_intensity": "CAUTION — Reduce Intensity",
        "rest": "REST — Recovery Day",
    }
    return labels.get(recommendation, recommendation.upper())


def _format_time(seconds: float | None) -> str:
    if not seconds:
        return "N/A"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}"


def _build_race_card(race_countdown: dict, gap_status: str, gap_color: str) -> str:
    """Build the Race Reality Check / CP Progress card HTML."""
    dashboard_mode = race_countdown.get("mode", "race_date")
    card_title = "Race Reality Check" if dashboard_mode == "race_date" else "CP Progress"

    if dashboard_mode == "cp_milestone":
        current_cp = race_countdown.get("current_cp")
        target_cp = race_countdown.get("target_cp")
        cp_cur = f"{current_cp:.0f}" if current_cp is not None else "?"
        cp_tgt = f"{target_cp:.0f}" if target_cp is not None else "?"
        cp_cur_v = current_cp or 0
        cp_tgt_v = target_cp or 1
        pct = min(100, (cp_cur_v / cp_tgt_v) * 100)
        stats_html = f"""<div style="display: flex; gap: 24px; align-items: baseline;">
      <div>
        <div class="stat">{cp_cur}W</div>
        <div class="stat-label">current CP</div>
      </div>
      <div>
        <div class="stat" style="font-size: 1.5rem; color: #94a3b8;">&rarr;</div>
      </div>
      <div>
        <div class="stat">{cp_tgt}W</div>
        <div class="stat-label">target CP</div>
      </div>
    </div>
    <div style="margin-top: 12px;">
      <div style="background: #334155; border-radius: 8px; height: 12px; overflow: hidden;">
        <div style="background: {gap_color}; height: 100%; width: {pct:.0f}%; border-radius: 8px; transition: width 0.3s;"></div>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: #94a3b8; margin-top: 4px;">
        <span>{cp_cur}W</span>
        <span>{cp_tgt}W</span>
      </div>
    </div>"""
    else:
        days_left = race_countdown.get("days_left", "?")
        predicted = _format_time(race_countdown.get("predicted_time_sec"))
        target = _format_time(race_countdown.get("target_time_sec"))
        stats_html = f"""<div style="display: flex; gap: 24px; align-items: baseline;">
      <div>
        <div class="stat">{days_left}</div>
        <div class="stat-label">days to race</div>
      </div>
      <div>
        <div class="stat" style="font-size: 1.5rem;">{predicted}</div>
        <div class="stat-label">predicted</div>
      </div>
      <div>
        <div class="stat" style="font-size: 1.5rem;">{target}</div>
        <div class="stat-label">target</div>
      </div>
    </div>"""

    return f"""<div class="card">
    <h2>{card_title}</h2>
    {stats_html}
    <div style="margin-top: 12px;">
      <span class="status-badge" style="background: {gap_color}20; color: {gap_color}">{gap_status.upper()}</span>
    </div>
    <div id="raceReality" style="margin-top: 16px; font-size: 0.85rem; color: #cbd5e1;"></div>
  </div>"""


def _build_diagnosis_card(diagnosis: dict) -> str:
    """Build the Training Diagnosis card HTML."""
    if not diagnosis or not diagnosis.get("diagnosis"):
        return ""

    interval = diagnosis.get("interval_power", {})
    volume = diagnosis.get("volume", {})
    dist = diagnosis.get("distribution", {})
    findings = diagnosis.get("diagnosis", [])
    suggestions = diagnosis.get("suggestions", [])
    lookback = diagnosis.get("lookback_weeks", 6)

    # Stats row
    max_p = interval.get("max")
    avg_p = interval.get("avg_work")
    supra = interval.get("supra_cp_sessions", 0)
    quality = interval.get("total_quality_sessions", 0)
    avg_km = volume.get("weekly_avg_km", 0)

    stats_parts = []
    if avg_km:
        stats_parts.append(f'<div><div class="stat" style="font-size:1.3rem;">{avg_km}</div><div class="stat-label">km/week avg</div></div>')
    if max_p:
        stats_parts.append(f'<div><div class="stat" style="font-size:1.3rem;">{max_p:.0f}W</div><div class="stat-label">peak interval</div></div>')
    if avg_p:
        stats_parts.append(f'<div><div class="stat" style="font-size:1.3rem;">{avg_p:.0f}W</div><div class="stat-label">avg work power</div></div>')
    stats_parts.append(f'<div><div class="stat" style="font-size:1.3rem;">{supra}/{quality}</div><div class="stat-label">supra-CP / quality</div></div>')

    stats_html = '<div style="display:flex;gap:24px;align-items:baseline;margin-bottom:16px;">' + "".join(stats_parts) + '</div>'

    # Distribution bar
    s_pct = dist.get("supra_cp", 0)
    t_pct = dist.get("threshold", 0)
    m_pct = dist.get("tempo", 0)
    e_pct = dist.get("easy", 0)
    dist_html = f"""<div style="margin-bottom:12px;">
      <div style="font-size:0.8rem;color:#94a3b8;margin-bottom:4px;">Training Distribution</div>
      <div style="display:flex;height:16px;border-radius:8px;overflow:hidden;">
        <div style="width:{s_pct}%;background:#ef4444;" title="Threshold {s_pct}%"></div>
        <div style="width:{t_pct}%;background:#f59e0b;" title="Tempo {t_pct}%"></div>
        <div style="width:{m_pct}%;background:#3b82f6;" title="Endurance {m_pct}%"></div>
        <div style="width:{e_pct}%;background:#334155;" title="Recovery {e_pct}%"></div>
      </div>
      <div style="display:flex;gap:12px;font-size:0.7rem;color:#94a3b8;margin-top:4px;">
        <span style="color:#ef4444;">&#9632; Threshold {s_pct}%</span>
        <span style="color:#f59e0b;">&#9632; Tempo {t_pct}%</span>
        <span style="color:#3b82f6;">&#9632; Endurance {m_pct}%</span>
        <span style="color:#64748b;">&#9632; Recovery {e_pct}%</span>
      </div>
    </div>"""

    # Findings
    findings_html = ""
    for f in findings:
        color = {"positive": "#22c55e", "warning": "#f59e0b", "neutral": "#94a3b8"}.get(f["type"], "#94a3b8")
        icon = {"positive": "+", "warning": "!", "neutral": "-"}.get(f["type"], "-")
        findings_html += f'<div style="margin-bottom:4px;font-size:0.85rem;"><span style="color:{color};font-weight:700;margin-right:6px;">{icon}</span>{f["message"]}</div>'

    # Suggestions
    suggestions_html = ""
    if suggestions:
        suggestions_html = '<div style="margin-top:12px;padding-top:12px;border-top:1px solid #334155;">'
        suggestions_html += '<div style="font-size:0.8rem;color:#94a3b8;margin-bottom:4px;font-weight:600;">Suggestions</div>'
        for s in suggestions:
            suggestions_html += f'<div style="margin-bottom:4px;font-size:0.85rem;color:#cbd5e1;">&#8226; {s}</div>'
        suggestions_html += '</div>'

    return f"""<div class="card full-width">
    <h2>Training Diagnosis (last {lookback} weeks)</h2>
    {stats_html}
    {dist_html}
    {findings_html}
    {suggestions_html}
  </div>"""


def _build_html(
    training_signal: dict,
    race_countdown: dict,
    fitness_fatigue: dict,
    weekly_review: dict,
    insights: dict,
    diagnosis: dict = None,
) -> str:
    signal_color = _signal_color(training_signal.get("recommendation", ""))
    signal_label = _signal_label(training_signal.get("recommendation", ""))
    signal_reason = training_signal.get("reason", "")
    signal_recovery = training_signal.get("recovery", {})
    signal_plan = training_signal.get("plan", {})
    signal_alternatives = training_signal.get("alternatives", [])

    dashboard_mode = race_countdown.get("mode", "race_date")
    days_left = race_countdown.get("days_left", "?")
    gap_status = race_countdown.get("status", "unknown")
    gap_color = {"on_track": "#22c55e", "behind": "#ef4444", "close": "#f59e0b", "unlikely": "#ef4444", "ahead": "#22c55e"}.get(gap_status, "#6b7280")
    race_reality = race_countdown.get("reality_check", {})

    race_card_html = _build_race_card(race_countdown, gap_status, gap_color)
    diagnosis_card_html = _build_diagnosis_card(diagnosis or {})

    ff_data = json.dumps(fitness_fatigue)
    weekly_data = json.dumps(weekly_review)
    insights_data = json.dumps(insights)
    signal_data = json.dumps({"recovery": signal_recovery, "plan": signal_plan, "alternatives": signal_alternatives})
    reality_data = json.dumps(race_reality)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Training Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; padding: 24px; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 8px; }}
  .subtitle {{ color: #94a3b8; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border-radius: 12px; padding: 20px; }}
  .card h2 {{ font-size: 1rem; color: #94a3b8; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .signal {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 8px; }}
  .reason {{ color: #94a3b8; font-size: 0.9rem; }}
  .stat {{ font-size: 2rem; font-weight: 700; }}
  .stat-label {{ color: #94a3b8; font-size: 0.85rem; }}
  .status-badge {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 0.8rem; font-weight: 600; }}
  .chart-container {{ position: relative; height: 300px; }}
  .full-width {{ grid-column: 1 / -1; }}
  .weekly-table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  .weekly-table th, .weekly-table td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #334155; }}
  .weekly-table th {{ color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; }}
</style>
</head>
<body>
<h1>Training Dashboard</h1>
<p class="subtitle">Generated {date.today().isoformat()} &mdash; Power-based training insights</p>

<div class="grid">
  <!-- Daily Signal -->
  <div class="card">
    <h2>Today's Signal</h2>
    <div class="signal" style="color: {signal_color}">{signal_label}</div>
    <div class="reason" style="margin-bottom: 12px;">{signal_reason}</div>
    <div id="signalDetail" style="font-size: 0.85rem; color: #cbd5e1;"></div>
  </div>

  <!-- Race / CP Progress -->
  {race_card_html}

  <!-- Fitness/Fatigue Chart -->
  <div class="card full-width">
    <h2>Fitness & Fatigue (CTL / ATL / TSB)</h2>
    <div class="chart-container">
      <canvas id="ffChart"></canvas>
    </div>
  </div>

  <!-- CP Trend -->
  <div class="card full-width">
    <h2>Critical Power Trend</h2>
    <div class="chart-container">
      <canvas id="cpTrendChart"></canvas>
    </div>
  </div>

  <!-- Training Diagnosis -->
  {diagnosis_card_html}

  <!-- Load Compliance -->
  <div class="card">
    <h2>Weekly Load Compliance</h2>
    <div class="chart-container">
      <canvas id="complianceChart"></canvas>
    </div>
  </div>

  <!-- What Worked / What Didn't -->
  <div class="card">
    <h2>What Worked / What Didn't</h2>
    <div id="workoutFlags"></div>
  </div>

  <!-- Sleep-Performance Correlation -->
  <div class="card">
    <h2>Sleep &rarr; Performance</h2>
    <div class="chart-container">
      <canvas id="sleepPerfChart"></canvas>
    </div>
  </div>

  <!-- Fatigue Warnings -->
  <div class="card">
    <h2>Fatigue Warnings</h2>
    <div id="fatigueWarnings"></div>
  </div>

  <!-- Taper Readiness (shown only in final weeks) -->
  <div class="card" id="taperCard" style="display:none;">
    <h2>Taper Readiness</h2>
    <div class="chart-container">
      <canvas id="taperChart"></canvas>
    </div>
  </div>
</div>

<script>
const dashboardMode = '{dashboard_mode}';
const ffData = {ff_data};
const weeklyData = {weekly_data};
const insightsData = {insights_data};
const signalExtra = {signal_data};
const raceReality = {reality_data};

// Helper: create a styled div with text
function mkDiv(text, style) {{
  const d = document.createElement('div');
  d.textContent = text;
  Object.assign(d.style, style || {{}});
  return d;
}}

// Signal Detail — recovery metrics + planned workout
(function() {{
  const el = document.getElementById('signalDetail');
  if (!el) return;
  const r = signalExtra.recovery || {{}};
  const p = signalExtra.plan || {{}};
  const alts = signalExtra.alternatives || [];

  // Recovery line
  const recoveryParts = [];
  if (r.readiness != null) recoveryParts.push('Readiness ' + Math.round(r.readiness));
  if (r.hrv_ms != null) {{
    let hrvStr = 'HRV ' + Math.round(r.hrv_ms) + 'ms';
    if (r.hrv_trend_pct != null && r.hrv_trend_pct !== 0) hrvStr += ' (' + (r.hrv_trend_pct > 0 ? '+' : '') + r.hrv_trend_pct.toFixed(0) + '%)';
    recoveryParts.push(hrvStr);
  }}
  if (r.sleep_score != null) recoveryParts.push('Sleep ' + Math.round(r.sleep_score));
  if (r.tsb != null) recoveryParts.push('TSB ' + r.tsb.toFixed(1));
  if (recoveryParts.length > 0) {{
    el.appendChild(mkDiv('Recovery: ' + recoveryParts.join(' \u00b7 '), {{marginBottom: '8px', color: '#94a3b8'}}));
  }}

  // Planned workout
  if (p.workout_type) {{
    const nameDiv = document.createElement('div');
    nameDiv.style.marginBottom = '4px';
    const nameStrong = document.createElement('strong');
    nameStrong.textContent = p.workout_type;
    nameStrong.style.color = '#e2e8f0';
    nameStrong.style.textTransform = 'capitalize';
    nameDiv.appendChild(nameStrong);
    el.appendChild(nameDiv);

    const details = [];
    if (p.duration_min) {{
      const mins = parseFloat(p.duration_min);
      const h = Math.floor(mins / 60);
      const m = Math.round(mins % 60);
      details.push(h > 0 ? h + 'h' + (m > 0 ? m + 'min' : '') : m + 'min');
    }}
    if (p.distance_km) details.push(parseFloat(p.distance_km).toFixed(1) + 'km');
    if (p.power_min && p.power_max) details.push(Math.round(parseFloat(p.power_min)) + '\u2013' + Math.round(parseFloat(p.power_max)) + 'W');
    if (details.length > 0) {{
      el.appendChild(mkDiv(details.join(' \u00b7 '), {{color: '#94a3b8'}}));
    }}
    if (p.description) {{
      el.appendChild(mkDiv(p.description, {{color: '#94a3b8', marginTop: '4px', fontSize: '0.8rem'}}));
    }}
  }} else {{
    el.appendChild(mkDiv('No planned workout today (rest day)', {{color: '#64748b'}}));
  }}

  // Alternatives
  if (alts.length > 0) {{
    const altContainer = document.createElement('div');
    altContainer.style.cssText = 'margin-top: 8px; padding-top: 8px; border-top: 1px solid #334155;';
    altContainer.appendChild(mkDiv('Options:', {{color: '#94a3b8', fontSize: '0.8rem', marginBottom: '4px'}}));
    alts.forEach((a, i) => {{
      altContainer.appendChild(mkDiv(String.fromCharCode(65 + i) + '. ' + a, {{color: '#cbd5e1', fontSize: '0.8rem', marginLeft: '8px'}}));
    }});
    el.appendChild(altContainer);
  }}
}})();

// Race Reality Check / CP Progress — honest assessment
(function() {{
  const el = document.getElementById('raceReality');
  if (!el || !raceReality) return;

  if (dashboardMode === 'cp_milestone') {{
    // CP milestone mode
    if (raceReality.assessment) {{
      const sevColor = {{'on_track': '#22c55e', 'close': '#f59e0b', 'behind': '#ef4444', 'unlikely': '#ef4444'}}[raceReality.severity] || '#94a3b8';
      el.appendChild(mkDiv(raceReality.assessment, {{marginBottom: '8px', color: sevColor}}));
    }}
    if (raceReality.trend_note) {{
      el.appendChild(mkDiv(raceReality.trend_note, {{color: '#94a3b8', fontSize: '0.8rem', marginBottom: '8px'}}));
    }}
    if (raceReality.estimated_months != null && raceReality.estimated_months > 0) {{
      el.appendChild(mkDiv('Estimated time to target: ~' + Math.round(raceReality.estimated_months) + ' months (at current trend)', {{color: '#94a3b8', fontSize: '0.8rem', marginBottom: '8px'}}));
    }}
    // Milestones
    const milestones = raceReality.milestones || [];
    if (milestones.length > 0) {{
      const msDiv = document.createElement('div');
      msDiv.style.cssText = 'margin-top: 8px; padding-top: 8px; border-top: 1px solid #334155;';
      msDiv.appendChild(mkDiv('Milestones:', {{color: '#94a3b8', fontSize: '0.8rem', marginBottom: '4px', fontWeight: '600'}}));
      milestones.forEach(ms => {{
        const row = document.createElement('div');
        row.style.cssText = 'display: flex; gap: 8px; align-items: center; font-size: 0.8rem; margin-bottom: 2px;';
        const icon = document.createElement('span');
        icon.textContent = ms.reached ? '\u2713' : '\u25cb';
        icon.style.color = ms.reached ? '#22c55e' : '#64748b';
        icon.style.width = '16px';
        row.appendChild(icon);
        row.appendChild(document.createTextNode(ms.cp + 'W \u2014 ' + ms.marathon));
        row.style.color = ms.reached ? '#22c55e' : '#cbd5e1';
        msDiv.appendChild(row);
      }});
      el.appendChild(msDiv);
    }}
  }} else {{
    // Race-date mode (existing)
    if (raceReality.current_cp && raceReality.needed_cp) {{
      const gapColor = raceReality.cp_gap_watts <= 0 ? '#22c55e' : raceReality.cp_gap_watts <= 5 ? '#f59e0b' : '#ef4444';
      const cpDiv = document.createElement('div');
      cpDiv.style.marginBottom = '8px';
      cpDiv.textContent = 'CP: ' + Math.round(raceReality.current_cp) + 'W current \u00b7 ' + Math.round(raceReality.needed_cp) + 'W needed ';
      const gapSpan = document.createElement('span');
      gapSpan.style.color = gapColor;
      gapSpan.textContent = '(gap: ' + (raceReality.cp_gap_watts > 0 ? '+' : '') + Math.round(raceReality.cp_gap_watts) + 'W)';
      cpDiv.appendChild(gapSpan);
      el.appendChild(cpDiv);
    }}

    if (raceReality.assessment) {{
      const sevColor = {{'on_track': '#22c55e', 'close': '#f59e0b', 'behind': '#ef4444', 'unlikely': '#ef4444'}}[raceReality.severity] || '#94a3b8';
      el.appendChild(mkDiv(raceReality.assessment, {{marginBottom: '8px', color: sevColor}}));
    }}

    if (raceReality.trend_note) {{
      el.appendChild(mkDiv(raceReality.trend_note, {{color: '#94a3b8', fontSize: '0.8rem'}}));
    }}

    if (raceReality.realistic_targets) {{
      const fmt = (s) => {{
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        return h + ':' + String(m).padStart(2, '0');
      }};
      const rt = raceReality.realistic_targets;
      const altDiv = document.createElement('div');
      altDiv.style.cssText = 'margin-top: 8px; padding-top: 8px; border-top: 1px solid #334155; font-size: 0.8rem; color: #94a3b8;';
      altDiv.textContent = 'Realistic targets: ' + fmt(rt.stretch) + ' (stretch) \u00b7 ' + fmt(rt.comfortable) + ' (comfortable)';
      el.appendChild(altDiv);
    }}
  }}
}})();

// Fitness/Fatigue Chart
if (ffData.dates && ffData.dates.length > 0) {{
  new Chart(document.getElementById('ffChart'), {{
    type: 'line',
    data: {{
      labels: ffData.dates,
      datasets: [
        {{ label: 'CTL (Fitness)', data: ffData.ctl, borderColor: '#22c55e', fill: false, tension: 0.3 }},
        {{ label: 'ATL (Fatigue)', data: ffData.atl, borderColor: '#ef4444', fill: false, tension: 0.3 }},
        {{ label: 'TSB (Form)', data: ffData.tsb, borderColor: '#3b82f6', fill: true, backgroundColor: 'rgba(59,130,246,0.1)', tension: 0.3 }},
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      scales: {{ y: {{ grid: {{ color: '#334155' }} }}, x: {{ grid: {{ color: '#334155' }} }} }},
      plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }}
    }}
  }});
}}

// Compliance Chart
if (weeklyData.weeks && weeklyData.weeks.length > 0) {{
  new Chart(document.getElementById('complianceChart'), {{
    type: 'bar',
    data: {{
      labels: weeklyData.weeks,
      datasets: [
        {{ label: 'Planned RSS', data: weeklyData.planned_rss, backgroundColor: '#475569' }},
        {{ label: 'Actual RSS', data: weeklyData.actual_rss, backgroundColor: '#3b82f6' }},
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      scales: {{ y: {{ grid: {{ color: '#334155' }} }}, x: {{ grid: {{ color: '#334155' }} }} }},
      plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }}
    }}
  }});
}}

// CP Trend Chart
if (insightsData.cp_trend && insightsData.cp_trend.dates.length > 0) {{
  new Chart(document.getElementById('cpTrendChart'), {{
    type: 'line',
    data: {{
      labels: insightsData.cp_trend.dates,
      datasets: [{{ label: 'Critical Power (W)', data: insightsData.cp_trend.values, borderColor: '#f59e0b', fill: false, tension: 0.3 }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      scales: {{ y: {{ grid: {{ color: '#334155' }} }}, x: {{ grid: {{ color: '#334155' }} }} }},
      plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }}
    }}
  }});
}}

// What Worked / What Didn't
const flagsEl = document.getElementById('workoutFlags');
if (insightsData.workout_flags && insightsData.workout_flags.length > 0) {{
  // Note: data is generated server-side from trusted CSV data, not user input
  insightsData.workout_flags.forEach(f => {{
    const div = document.createElement('div');
    div.style.marginBottom = '8px';
    const span = document.createElement('span');
    span.style.color = f.type === 'good' ? '#22c55e' : '#ef4444';
    span.style.fontWeight = '700';
    span.textContent = f.type === 'good' ? '+' : '-';
    div.appendChild(span);
    div.appendChild(document.createTextNode(` ${{f.date}}: ${{f.description}}`));
    flagsEl.appendChild(div);
  }});
}} else {{
  flagsEl.textContent = 'No notable workout flags this period.';
  flagsEl.style.color = '#94a3b8';
}}

// Sleep-Performance Scatter
if (insightsData.sleep_perf && insightsData.sleep_perf.length > 0) {{
  new Chart(document.getElementById('sleepPerfChart'), {{
    type: 'scatter',
    data: {{
      datasets: [{{
        label: 'Sleep Score vs Power',
        data: insightsData.sleep_perf.map(p => ({{ x: p[0], y: p[1] }})),
        backgroundColor: '#8b5cf6',
      }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      scales: {{
        x: {{ title: {{ display: true, text: 'Sleep Score', color: '#94a3b8' }}, grid: {{ color: '#334155' }} }},
        y: {{ title: {{ display: true, text: 'Avg Power (W)', color: '#94a3b8' }}, grid: {{ color: '#334155' }} }},
      }},
      plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }}
    }}
  }});
}}

// Fatigue Warnings
const warningsEl = document.getElementById('fatigueWarnings');
if (insightsData.warnings && insightsData.warnings.length > 0) {{
  insightsData.warnings.forEach(w => {{
    const div = document.createElement('div');
    div.style.marginBottom = '8px';
    div.style.color = '#f59e0b';
    div.textContent = '\u26a0 ' + w;
    warningsEl.appendChild(div);
  }});
}} else {{
  warningsEl.textContent = 'No fatigue warnings. Recovery looks good.';
  warningsEl.style.color = '#22c55e';
}}

// Taper Readiness (show only in race-date mode, if <= 21 days to race)
const daysLeft = dashboardMode === 'race_date' ? ({days_left} || 999) : 999;
if (daysLeft <= 21 && ffData.dates && ffData.dates.length > 0) {{
  document.getElementById('taperCard').style.display = 'block';
  const taperDays = Math.min(21, ffData.dates.length);
  new Chart(document.getElementById('taperChart'), {{
    type: 'line',
    data: {{
      labels: ffData.dates.slice(-taperDays),
      datasets: [
        {{ label: 'CTL (Fitness)', data: ffData.ctl.slice(-taperDays), borderColor: '#22c55e', fill: false, tension: 0.3 }},
        {{ label: 'ATL (Fatigue)', data: ffData.atl.slice(-taperDays), borderColor: '#ef4444', fill: false, tension: 0.3 }},
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      scales: {{ y: {{ grid: {{ color: '#334155' }} }}, x: {{ grid: {{ color: '#334155' }} }} }},
      plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }}
    }}
  }});
}}
</script>
</body>
</html>"""
