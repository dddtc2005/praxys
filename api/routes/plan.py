"""Upcoming training plan endpoint with Stryd push integration."""
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from api.auth import get_data_user_id, require_write_access
from api.deps import get_dashboard_data
from api.etag import CACHE_CONTROL, ENDPOINT_SCOPES, ETagGuard, compute_etag
from api.packs import RequestContext
from db.cache_revision import bump_revisions
from db.session import get_db

router = APIRouter()

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_STRYD_PUSH_STATUS_DIR = os.path.join(_DATA_DIR, "ai", "stryd_push_status")


def _stryd_push_status_path(user_id: str) -> str:
    """Per-user push-status path.

    Must be per-user: a shared file would let the GET /plan response
    include every other user's workout IDs and push timestamps.
    UUID user_ids keep filenames collision-free and filesystem-safe.

    A legacy single-file layout at ``data/ai/stryd_push_status.json`` may
    still exist on older deployments — this code does not read or migrate
    it. Operators should delete that orphan file on deploy; leaving it in
    place only means historical push-state that the UI won't show. No user
    data is lost.
    """
    return os.path.join(_STRYD_PUSH_STATUS_DIR, f"{user_id}.json")


# Hard cap on how wide a window the client can request. Generous enough
# for any UI that wants a few months of plan view, tight enough that an
# abusive ``?end=2099-12-31`` can't force the server to ship years of rows.
_MAX_WINDOW_DAYS = 365
# Default forward offset when no ``end`` is supplied. ``end`` is
# inclusive, so a forward offset of 14 returns 15 calendar days
# ([today, today+14]). Frontend pills mirror this offset semantic
# (1wk = +6, 2wk = +13, 4wk = +27 if exact 7/14/28-day inclusive
# windows are needed; current frontend uses +N which yields N+1 days
# inclusive — accepted for the eyebrow's "≈ N weeks" framing).
_DEFAULT_FORWARD_DAYS = 14


def _resolve_window(start: str | None, end: str | None) -> tuple[date, date]:
    """Parse / default the ?start=&end= query window.

    Accepts ISO ``YYYY-MM-DD`` for both bounds. Either or both may be
    omitted: missing ``start`` defaults to today; missing ``end`` defaults
    to ``start + _DEFAULT_FORWARD_DAYS``. Inverted or oversized windows
    raise 400 — silently clamping would mask bad client input.
    """
    today = date.today()
    try:
        start_d = date.fromisoformat(start) if start else today
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid start date: {start!r}"
        ) from exc
    try:
        end_d = (
            date.fromisoformat(end) if end
            else start_d + timedelta(days=_DEFAULT_FORWARD_DAYS)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid end date: {end!r}"
        ) from exc
    if end_d < start_d:
        raise HTTPException(
            status_code=400, detail="Window end must be on or after start",
        )
    if (end_d - start_d).days > _MAX_WINDOW_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Window cannot exceed {_MAX_WINDOW_DAYS} days",
        )
    return start_d, end_d


def _compute_ai_sync_state(
    date_str: str, push_status: dict, stryd_by_date: dict,
) -> str:
    """Sync state of an AI plan row against the user's Stryd calendar.

    - ``synced``     — Either (a) a Stryd row exists at this date and
                       its ``external_id`` matches the ``workout_id`` we
                       logged on push, or (b) the push log has the
                       workout but the next Stryd sync hasn't pulled
                       the row back in yet. Both cases mean "Praxys's
                       version is on Stryd"; the latter is the brief
                       window after a successful POST /plan/push-stryd
                       and before the user's next Stryd sync, and a
                       consumer that doesn't share the frontend's
                       optimistic ``pushStatus`` map (mini-program,
                       MCP) would otherwise see ``not_synced`` and
                       offer to push again.
    - ``mismatch``   — A Stryd row exists at this date but its
                       ``external_id`` is unknown to us (user-edited on
                       Stryd, or we never pushed). The UI uses this to
                       warn before overwriting.
    - ``not_synced`` — No Stryd row, no push log entry: nothing has
                       ever pushed to Stryd for this date.
    """
    stryd_row = stryd_by_date.get(date_str)
    pushed_id = (push_status.get(date_str) or {}).get("workout_id")

    if stryd_row is None:
        return "synced" if pushed_id else "not_synced"

    stryd_external = stryd_row.get("external_id")
    if (
        pushed_id
        and stryd_external is not None
        and pd.notna(stryd_external)
        and str(stryd_external) == str(pushed_id)
    ):
        return "synced"
    return "mismatch"


def _resolve_sync_target(ctx: RequestContext) -> str | None:
    """Name of the platform AI plan rows get pushed to.

    Today only Stryd is wired up as a write target; surfacing it as a
    derived field (rather than free-form preference) lets the UI decide
    whether to even render sync chrome without sniffing connections.
    """
    return "stryd" if "stryd" in (ctx.config.connections or []) else None


@router.get("/plan")
def get_plan(
    request: Request,
    response: Response,
    start: str | None = Query(
        None,
        description="Window start (YYYY-MM-DD). Defaults to today.",
    ),
    end: str | None = Query(
        None,
        description="Window end (YYYY-MM-DD). Defaults to start + 14 days.",
    ),
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
):
    """Return all plan rows in a window with per-row sync state.

    Each workout carries its ``source`` (``ai`` | ``stryd``). When a date
    has both an AI and a Stryd row, the AI row wins and the Stryd row is
    used purely to derive ``sync_state`` (synced / mismatch / not_synced)
    — that surfaces "did your Praxys-authored plan land on Stryd?" while
    still showing the user every scheduled workout.

    Stryd-only rows surface with ``source='stryd'`` and no ``sync_state``:
    they live natively on Stryd, so the AI-vs-Stryd sync question doesn't
    apply. The UI labels them by source so users who imported a coach's
    plan from Stryd still see something here.

    Window framing is mixed into the ETag salt so two clients hitting
    different windows can't bleed cache into each other. Stryd push
    status comes from a per-user JSON file that lives outside the DB
    revision counters; the push/delete handlers bump ``plans`` so a fresh
    push is never served stale via 304.
    """
    start_d, end_d = _resolve_window(start, end)

    etag = compute_etag(
        db, user_id, ENDPOINT_SCOPES["plan"],
        salt=f"start={start_d.isoformat()}&end={end_d.isoformat()}",
    )
    guard = ETagGuard(etag, request.headers.get("if-none-match"))
    if guard.is_match:
        return guard.not_modified()
    guard.apply(response)

    ctx = RequestContext(user_id=user_id, db=db)
    plan_df = ctx.plan
    push_status = _load_push_status(user_id)
    sync_target = _resolve_sync_target(ctx)

    workouts: list[dict] = []

    if not plan_df.empty and "date" in plan_df.columns:
        windowed = plan_df[
            (plan_df["date"] >= start_d) & (plan_df["date"] <= end_d)
        ]
        has_source = "source" in windowed.columns
        ai_rows = (
            windowed[windowed["source"] == "ai"] if has_source else windowed
        )
        stryd_rows = (
            windowed[windowed["source"] == "stryd"]
            if has_source else windowed.iloc[0:0]
        )

        # Stryd allows multiple workouts on the same date (AM run +
        # PM strides, race + shakeout). Group rows-per-date so the
        # AI sync_state derivation can pick the best match by
        # workout_type instead of arbitrarily collapsing to the
        # last-iterated row.
        stryd_by_date: dict[str, list[pd.Series]] = {}
        for _, srow in stryd_rows.iterrows():
            sd = srow["date"]
            key = sd.isoformat() if hasattr(sd, "isoformat") else str(sd)
            stryd_by_date.setdefault(key, []).append(srow)

        def _best_stryd_match(rows: list[pd.Series], wt: str) -> pd.Series:
            """Pick the Stryd row whose workout_type matches ``wt``,
            falling back to the first row when nothing matches. AI
            plans are typically one-per-date, so a match means we're
            comparing apples to apples."""
            wt_lower = (wt or "").lower()
            for r in rows:
                if str(r.get("workout_type", "")).lower() == wt_lower:
                    return r
            return rows[0]

        ai_dates: set[str] = set()
        for _, row in ai_rows.sort_values("date").iterrows():
            workout = _row_to_workout(row, source="ai")
            ai_wt = workout.get("workout_type", "")
            stryd_match_by_date = {
                d: _best_stryd_match(rows, ai_wt)
                for d, rows in stryd_by_date.items()
            }
            workout["sync_state"] = _compute_ai_sync_state(
                workout["date"], push_status, stryd_match_by_date,
            )
            ai_dates.add(workout["date"])
            workouts.append(workout)

        # Stryd rows on dates the AI plan doesn't cover — show them
        # all (each as its own row) so the user still sees their
        # imported / coach-authored Stryd workouts.
        for date_str, srows in stryd_by_date.items():
            if date_str in ai_dates:
                continue
            for srow in srows:
                workouts.append(_row_to_workout(srow, source="stryd"))

        workouts.sort(key=lambda w: w["date"])

    body = {
        "workouts": workouts,
        "stryd_status": push_status,
        "sync_target": sync_target,
        "window": {"start": start_d.isoformat(), "end": end_d.isoformat()},
    }
    return Response(
        content=json.dumps(body),
        media_type="application/json",
        headers={"ETag": guard.etag, "Cache-Control": CACHE_CONTROL},
    )


def _row_to_workout(row, *, source: str) -> dict:
    """Project a single plan_df row into the JSON shape the UI consumes."""
    row_date = row["date"]
    date_str = (
        row_date.isoformat() if hasattr(row_date, "isoformat") else str(row_date)
    )
    workout: dict = {
        "date": date_str,
        "source": source,
        "workout_type": row.get("workout_type", ""),
    }
    for field, csv_col in (
        ("duration_min", "planned_duration_min"),
        ("distance_km", "planned_distance_km"),
        ("power_min", "target_power_min"),
        ("power_max", "target_power_max"),
        ("description", "workout_description"),
    ):
        val = row.get(csv_col)
        if pd.notna(val) and val != "":
            workout[field] = str(val) if field == "description" else float(val)
    return workout


def _load_push_status(user_id: str) -> dict:
    """Load a user's Stryd push status JSON.

    Returns {} when the file is absent. On corruption, quarantines the file
    (renames to ``*.corrupt-<timestamp>``) and returns {} — the subsequent
    save would otherwise overwrite it with an empty dict and destroy any
    recoverable content.
    """
    path = _stryd_push_status_path(user_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"Expected dict, got {type(data).__name__}")
            return data
    except (json.JSONDecodeError, ValueError, OSError) as e:
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        quarantine = f"{path}.corrupt-{stamp}"
        try:
            os.replace(path, quarantine)
            logger.error(
                "Quarantined corrupt push status file for user=%s at %s: %s",
                user_id, quarantine, e,
            )
        except OSError as rename_err:
            logger.error(
                "Corrupt push status file for user=%s at %s (quarantine failed: %s): %s",
                user_id, path, rename_err, e,
            )
        return {}


def _save_push_status(user_id: str, status: dict) -> None:
    """Save a user's Stryd push status JSON atomically via temp file + rename."""
    path = _stryd_push_status_path(user_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(status, f, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        # Don't leave a half-written tmp file behind on rename failures.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class PushStrydRequest(BaseModel):
    workout_dates: list[str]


@router.post("/plan/push-stryd")
def push_plan_to_stryd(
    request: PushStrydRequest,
    current_user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Push selected AI plan workouts to Stryd calendar.

    Converts AI plan workouts to Stryd structured format and uploads them.
    """
    from sync.stryd_sync import (
        _login_api,
        _STRYD_WORKOUT_TYPES,
        build_workout_blocks,
        create_workout_api,
    )

    # Load Stryd credentials
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "sync", ".env"))
    email = os.environ.get("STRYD_EMAIL")
    password = os.environ.get("STRYD_PASSWORD")
    if not email or not password:
        raise HTTPException(status_code=400, detail="STRYD_EMAIL / STRYD_PASSWORD not configured")

    # Login to Stryd
    try:
        stryd_user_id, token = _login_api(email, password)
    except Exception as e:
        logger.error("Stryd login failed: %s", e)
        raise HTTPException(status_code=502, detail="Stryd login failed. Check your credentials in sync/.env")

    # Load AI plan data
    data = get_dashboard_data(user_id=current_user_id, db=db)
    plan_df: pd.DataFrame = data.get("plan", pd.DataFrame())
    if plan_df.empty:
        raise HTTPException(status_code=404, detail="No training plan found")

    # Get current CP for block building
    cp_watts = None
    latest_cp = data.get("latest_cp")
    if latest_cp and float(latest_cp) > 0:
        cp_watts = float(latest_cp)
    # Fallback: try from latest activities
    if not cp_watts:
        activities = data.get("activities", pd.DataFrame())
        if not isinstance(activities, pd.DataFrame) or activities.empty:
            pass
        else:
            cp_col = "cp_estimate" if "cp_estimate" in activities.columns else None
            if cp_col:
                valid_cp = activities[cp_col].dropna()
                if not valid_cp.empty:
                    cp_watts = float(valid_cp.iloc[-1])
    if not cp_watts:
        raise HTTPException(
            status_code=422,
            detail="Cannot determine Critical Power from your data. Ensure recent activities with power data are synced before pushing to Stryd.",
        )

    push_status = _load_push_status(current_user_id)
    results = []

    for workout_date in request.workout_dates:
        # Skip rest days
        matching = plan_df[plan_df["date"].astype(str) == workout_date]
        if matching.empty:
            results.append({"date": workout_date, "status": "error", "error": "No workout found for this date"})
            continue

        row = matching.iloc[0]
        workout_type = str(row.get("workout_type", ""))

        # Skip rest days
        if workout_type.lower() in ("rest", "off"):
            results.append({"date": workout_date, "status": "error", "error": "Rest day — nothing to push"})
            continue

        workout = row.to_dict()
        # Convert date objects to strings for the dict
        for k, v in workout.items():
            if hasattr(v, "isoformat"):
                workout[k] = v.isoformat()

        try:
            blocks = build_workout_blocks(workout, cp_watts)
            stryd_type = _STRYD_WORKOUT_TYPES.get(workout_type.lower(), "")
            title = f"{workout_type.replace('_', ' ').title()}"
            description = str(row.get("workout_description", ""))

            result = create_workout_api(
                user_id=stryd_user_id,
                token=token,
                workout_date=workout_date,
                title=title,
                blocks=blocks,
                workout_type=stryd_type,
                description=description,
            )

            workout_id = str(result.get("id", ""))
            push_status[workout_date] = {
                "workout_id": workout_id,
                "pushed_at": datetime.now(timezone.utc).isoformat(),
                "status": "pushed",
            }
            results.append({"date": workout_date, "status": "success", "workout_id": workout_id})

        except requests.HTTPError as e:
            detail = str(e)
            if e.response is not None:
                try:
                    detail = e.response.json().get("message", detail)
                except (ValueError, AttributeError):
                    pass
            results.append({"date": workout_date, "status": "error", "error": f"Stryd API error: {detail}"})
        except Exception as e:
            logger.error("Failed to push workout for %s: %s: %s", workout_date, type(e).__name__, e)
            results.append({"date": workout_date, "status": "error", "error": str(e)})

    try:
        _save_push_status(current_user_id, push_status)
    except OSError as e:
        logger.warning("Failed to save push status: %s", e)
    else:
        # Bump ``plans`` so /api/plan's ETag flips and the new push status is
        # served on the next read instead of a stale 304. ``stryd_status``
        # lives in a JSON file outside the DB scopes, so without this bump
        # the L2 cache layer would have no signal that the response changed.
        try:
            bump_revisions(db, current_user_id, ["plans"])
            db.commit()
        except Exception as e:
            logger.warning("Failed to bump cache revision after push: %s", e)
            db.rollback()

    return {"results": results}


@router.delete("/plan/stryd-workout/{workout_id}")
def delete_stryd_workout(
    workout_id: str,
    current_user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a previously pushed workout from Stryd."""
    from sync.stryd_sync import _login_api, delete_workout_api

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "sync", ".env"))
    email = os.environ.get("STRYD_EMAIL")
    password = os.environ.get("STRYD_PASSWORD")
    if not email or not password:
        raise HTTPException(status_code=400, detail="STRYD_EMAIL / STRYD_PASSWORD not configured")

    try:
        stryd_user_id, token = _login_api(email, password)
    except Exception as e:
        logger.error("Stryd login failed: %s", e)
        raise HTTPException(status_code=502, detail="Stryd login failed. Check your credentials in sync/.env")

    try:
        delete_workout_api(stryd_user_id, token, workout_id)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            pass  # Already deleted on Stryd — proceed to clean local status
        else:
            raise HTTPException(status_code=502, detail=f"Stryd delete failed: {e}")
    except Exception as e:
        logger.error("Stryd delete failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to delete from Stryd")

    # Remove from push status
    push_status = _load_push_status(current_user_id)
    to_remove = [d for d, info in push_status.items() if info.get("workout_id") == workout_id]
    for d in to_remove:
        del push_status[d]
    _save_push_status(current_user_id, push_status)

    # Bump ``plans`` so /api/plan's ETag flips and the cleared push status is
    # served on the next read instead of a stale 304. Mirror the bump in
    # push_plan_to_stryd — ``stryd_status`` lives outside the DB scopes.
    if to_remove:
        try:
            bump_revisions(db, current_user_id, ["plans"])
            db.commit()
        except Exception as e:
            logger.warning("Failed to bump cache revision after delete: %s", e)
            db.rollback()

    return {"deleted": True, "workout_id": workout_id}
