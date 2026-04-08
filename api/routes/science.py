"""Science framework endpoint — active theories, available options, recommendations."""
from fastapi import APIRouter

from api.deps import get_dashboard_data
from analysis.config import load_config, save_config
from analysis.science import (
    PILLARS,
    list_theories,
    list_label_sets,
    load_active_science,
    recommend_science,
)

router = APIRouter()


def _theory_summary(theory) -> dict:
    """Serialize a Theory to a JSON-safe summary."""
    return {
        "id": theory.id,
        "name": theory.name,
        "description": theory.description,
        "simple_description": theory.simple_description,
        "advanced_description": theory.advanced_description,
        "author": theory.author,
        "citations": [
            {k: v for k, v in c.__dict__.items() if v is not None}
            for c in theory.citations
        ],
    }


@router.get("/science")
def get_science() -> dict:
    """Return active theories, all available options, and recommendations."""
    data = get_dashboard_data()
    config = load_config()
    science = data.get("science", {})

    # Active theories
    active = {}
    for pillar in PILLARS:
        theory = science.get(pillar)
        if theory:
            summary = _theory_summary(theory)
            if theory.tsb_zones_labeled:
                summary["tsb_zones"] = [
                    {"min": z.min, "max": z.max, "label": z.label, "color": z.color}
                    for z in theory.tsb_zones_labeled
                ]
            active[pillar] = summary

    # Available theories per pillar
    available = {}
    for pillar in PILLARS:
        available[pillar] = [
            _theory_summary(t) for t in list_theories(pillar)
        ]

    # Available label sets
    label_sets = [{"id": ls.id, "name": ls.name} for ls in list_label_sets()]

    # Recommendations
    activities = data.get("activities", None)
    recovery_df = data.get("recovery", None)
    # Extract goal distance from config
    from analysis.metrics import get_distance_config
    dist_key = str(config.goal.get("distance", "marathon"))
    goal_km = get_distance_config(dist_key).get("km")

    recs = recommend_science(
        activities=activities,
        recovery=recovery_df,
        goal_distance_km=goal_km,
        connected_platforms=config.connections,
        training_base=config.training_base,
    )

    return {
        "active": active,
        "active_labels": config.zone_labels,
        "available": available,
        "label_sets": label_sets,
        "recommendations": [
            {
                "pillar": r.pillar,
                "recommended_id": r.recommended_id,
                "reason": r.reason,
                "confidence": r.confidence,
            }
            for r in recs
        ],
    }


@router.put("/science")
def update_science(body: dict) -> dict:
    """Update science theory selections and/or label preference."""
    config = load_config()

    if "science" in body:
        for pillar, theory_id in body["science"].items():
            if pillar in PILLARS and isinstance(theory_id, str):
                config.science[pillar] = theory_id

    if "zone_labels" in body:
        config.zone_labels = str(body["zone_labels"])

    save_config(config)

    # Clear cache so next request uses new theories
    from api.deps import _clear_cache
    _clear_cache()

    return {"status": "ok"}
