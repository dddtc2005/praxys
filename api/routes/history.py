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
    pack = get_history_pack(ctx, limit=limit, offset=offset, source=source)
    return {
        "activities": pack["activities"],
        "total": pack["total"],
        "limit": limit,
        "offset": offset,
        "source_filter": pack["source_filter"],
        "training_base": ctx.config.training_base,
        "display": ctx.display,
    }
