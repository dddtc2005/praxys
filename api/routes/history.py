"""Activity history endpoint."""
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from api.auth import get_data_user_id
from api.etag import ENDPOINT_SCOPES, ETagGuard, compute_etag
from api.packs import RequestContext, get_history_pack
from db.session import get_db

router = APIRouter()


@router.get("/history")
def get_history(
    request: Request,
    response: Response,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    source: str = Query(None, description="Filter by source (garmin, stryd). Defaults to primary activities source."),
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
):
    # Pagination changes the body, so query params must be salted into the
    # ETag. Otherwise ?offset=0 and ?offset=20 would share an ETag and the
    # browser would replay the wrong cached page on a matching 304.
    etag = compute_etag(
        db, user_id, ENDPOINT_SCOPES["history"],
        salt=f"limit={limit}&offset={offset}&source={source or ''}",
    )
    guard = ETagGuard(etag, request.headers.get("if-none-match"))
    if guard.is_match:
        return guard.not_modified()
    guard.apply(response)
    ctx = RequestContext(user_id=user_id, db=db)
    activities = get_history_pack(ctx)["activities"]

    # Smart dedup: when multiple sources have the same activity (same date +
    # similar duration), keep the primary source version. Activities that only
    # exist in one source are always shown.
    primary_source = source or ctx.config.preferences.get("activities")

    if primary_source:
        # Group by date
        by_date: dict[str, list[dict]] = {}
        for a in activities:
            by_date.setdefault(a.get("date", ""), []).append(a)

        deduped: list[dict] = []
        for date_str, day_acts in by_date.items():
            if len(day_acts) <= 1:
                deduped.extend(day_acts)
                continue

            # Multiple activities on same date — check for duplicates
            primary_acts = [a for a in day_acts if a.get("source") == primary_source]
            other_acts = [a for a in day_acts if a.get("source") != primary_source]

            deduped.extend(primary_acts)

            # For each non-primary activity, check if a matching primary exists
            # (same date + duration within 10%)
            for other in other_acts:
                other_dur = other.get("duration_sec") or 0
                is_duplicate = False
                for primary in primary_acts:
                    primary_dur = primary.get("duration_sec") or 0
                    if primary_dur > 0 and other_dur > 0:
                        ratio = abs(primary_dur - other_dur) / max(primary_dur, other_dur)
                        if ratio < 0.10:  # Within 10% duration = same activity
                            is_duplicate = True
                            break
                if not is_duplicate:
                    deduped.append(other)

        # Re-sort by date descending
        activities = sorted(deduped, key=lambda a: a.get("date", ""), reverse=True)

    total = len(activities)
    page = activities[offset : offset + limit]
    return {
        "activities": page,
        "total": total,
        "limit": limit,
        "offset": offset,
        "source_filter": primary_source,
        "training_base": ctx.config.training_base,
        "display": ctx.display,
    }
