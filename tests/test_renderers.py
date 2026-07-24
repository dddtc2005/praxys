"""Regression tests for legacy report and dashboard renderers."""

from analysis.dashboard_renderer import _build_diagnosis_card
from analysis.report_renderer import _render_diagnosis_section


def _zero_volume_diagnosis() -> dict:
    return {
        "lookback_weeks": 4,
        "volume": {
            "weekly_avg_km": 0.0,
            "trend": "stable",
            "weeks": ["2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23"],
            "weekly_km": [0.0, 0.0, 0.0, 0.0],
        },
        "interval_power": {},
        "distribution": {},
        "diagnosis": [{"type": "neutral", "message": "Recorded distance is zero."}],
        "suggestions": [],
    }


def test_markdown_report_preserves_valid_zero_volume() -> None:
    """A non-empty all-zero series should render as 0.0 rather than disappear."""
    report = _render_diagnosis_section(_zero_volume_diagnosis())

    assert "**Volume:** 0.0 km/week avg (stable)" in report


def test_html_dashboard_preserves_valid_zero_volume() -> None:
    """The legacy dashboard should show a valid zero weekly average."""
    card = _build_diagnosis_card(_zero_volume_diagnosis())

    assert '<div class="stat" style="font-size:1.3rem;">0.0</div>' in card
    assert "km/week avg" in card


def test_renderers_hide_unavailable_empty_volume_series() -> None:
    """An empty series should not be presented as a valid 0.0 average."""
    diagnosis = _zero_volume_diagnosis()
    diagnosis["volume"] = {
        "weekly_avg_km": 0.0,
        "trend": "insufficient_data",
        "weeks": [],
        "weekly_km": [],
    }

    assert "**Volume:**" not in _render_diagnosis_section(diagnosis)
    assert "km/week avg" not in _build_diagnosis_card(diagnosis)
