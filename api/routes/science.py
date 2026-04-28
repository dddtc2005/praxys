"""Science framework endpoint — active theories, available options, recommendations."""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from api.auth import get_data_user_id, require_write_access
from api.etag import ENDPOINT_SCOPES, ETagGuard, compute_etag
from analysis.config import (
    load_config_from_db,
    save_config_to_db,
)
from analysis.metrics import get_distance_config
from analysis.science import (
    PILLARS,
    list_theories,
    list_label_sets,
    load_active_science,
    load_theory,
    recommend_science,
)
from db.session import get_db

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
        "params": theory.params,
    }


SUPPORTED_SCIENCE_LOCALES = {"en", "zh"}


def _resolve_locale(config_language: str | None, request: Request | None) -> str | None:
    """Pick the locale used for science text.

    Preference order: explicit user config → `Accept-Language` header's first
    supported prefix → English (None).
    """
    if config_language and config_language in SUPPORTED_SCIENCE_LOCALES:
        return config_language
    if request is not None:
        header = request.headers.get("accept-language", "")
        for raw in header.split(","):
            prefix = raw.strip().split(";", 1)[0].split("-", 1)[0].lower()
            if prefix in SUPPORTED_SCIENCE_LOCALES:
                return prefix
    return None


@router.get("/science")
def get_science(
    request: Request,
    response: Response,
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
):
    """Return active theories, all available options, and recommendations.

    Doesn't go through the full dashboard pipeline: loading config + science
    is enough. The legacy `recommend_science` call only inspects DataFrame
    inputs (the previous code passed a list[dict], which never matched the
    isinstance check), so passing ``None`` here produces byte-identical
    recommendations while skipping the activity / split / threshold load.
    """
    config = load_config_from_db(user_id, db)
    locale = _resolve_locale(config.language, request)
    # Salt with the resolved locale because /api/science varies on
    # Accept-Language even when no config field changed.
    etag = compute_etag(
        db, user_id, ENDPOINT_SCOPES["science"], salt=f"locale={locale or ''}",
    )
    guard = ETagGuard(etag, request.headers.get("if-none-match"))
    if guard.is_match:
        return guard.not_modified()
    guard.apply(response)

    # Active theories — loaded in the requested locale so the user sees
    # translated prose without the dashboard loader needing to know about
    # locales.
    science = load_active_science(
        config.science, config.zone_labels, locale=locale,
    )

    active = {}
    for pillar in PILLARS:
        theory = science.get(pillar)
        if theory:
            summary = _theory_summary(theory)
            if theory.tsb_zones_labeled:
                summary["tsb_zones"] = [
                    {"key": z.key, "min": z.min, "max": z.max, "label": z.label, "color": z.color}
                    for z in theory.tsb_zones_labeled
                ]
            active[pillar] = summary

    # Available theories per pillar
    available = {}
    for pillar in PILLARS:
        available[pillar] = [
            _theory_summary(t) for t in list_theories(pillar, locale=locale)
        ]

    # Available label sets
    label_sets = [{"id": ls.id, "name": ls.name} for ls in list_label_sets()]

    # Recommendations
    dist_key = str(config.goal.get("distance", "marathon"))
    goal_km = get_distance_config(dist_key).get("km")

    recs = recommend_science(
        activities=None,
        recovery=None,
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
def update_science(
    body: dict,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Update science theory selections and/or label preference."""
    config = load_config_from_db(user_id, db)

    if "science" in body:
        for pillar, theory_id in body["science"].items():
            if pillar in PILLARS and isinstance(theory_id, str):
                # When changing zone theory, validate first and apply boundaries
                if pillar == "zones":
                    try:
                        theory = load_theory("zones", theory_id)
                        config.science[pillar] = theory_id
                        if theory.zone_boundaries:
                            for base_key, bounds in theory.zone_boundaries.items():
                                config.zones[base_key] = bounds
                    except FileNotFoundError:
                        continue  # Don't save invalid theory_id
                else:
                    config.science[pillar] = theory_id

    if "zone_labels" in body:
        config.zone_labels = str(body["zone_labels"])

    from db.cache_revision import bump_revisions
    bump_revisions(db, user_id, ["config"])
    save_config_to_db(user_id, config, db)

    return {"status": "ok"}
