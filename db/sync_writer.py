"""Write sync data directly to the database, bypassing CSVs.

Each function takes parsed row dicts (same format the sync parse functions
produce) and upserts them into the appropriate DB tables.
"""
import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from db.cache_revision import bump_revisions
from db.models import Activity, ActivitySample, ActivitySplit, RecoveryData, FitnessData, TrainingPlan

logger = logging.getLogger(__name__)


def _parse_date(val) -> date | None:
    if val is None or val == "":
        return None
    if isinstance(val, date):
        return val
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _float(val) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _str(val) -> str | None:
    if val is None or val == "":
        return None
    return str(val)


# Columns that may be missing on pre-existing rows from an older sync (e.g.
# native Garmin running power wasn't parsed before PR #62). A re-sync should
# fill these in without touching columns that were already populated —
# protects against overwriting Stryd-sourced power with Garmin's reading when
# both sources synced the same activity.
_ACTIVITY_FILL_COLUMNS = ("avg_power", "max_power")
_SPLIT_FILL_COLUMNS = ("avg_power",)


def _fill_missing(obj, row: dict, columns: tuple[str, ...]) -> bool:
    """Set listed columns on `obj` from `row` when the column is currently None.

    Returns True if any column was populated. Never overwrites a non-null
    value, so a user who already has Stryd power on a split won't see it
    replaced by the Garmin reading on a subsequent sync.
    """
    touched = False
    for col in columns:
        if getattr(obj, col) is None:
            val = _float(row.get(col))
            if val is not None:
                setattr(obj, col, val)
                touched = True
    return touched


def _pace_min_str(row: dict) -> str | None:
    """Prefer an explicit pace string, else derive one from sec/km."""
    pace_min = _str(row.get("avg_pace_min_km"))
    if pace_min:
        return pace_min

    pace_sec = _float(row.get("avg_pace_sec_km"))
    if pace_sec is None or pace_sec <= 0:
        return None

    total_seconds = int(round(pace_sec))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def write_activities(user_id: str, rows: list[dict], db: Session) -> int:
    """Write activity rows to DB.

    New activity_ids are inserted. Pre-existing rows get their
    ``_ACTIVITY_FILL_COLUMNS`` topped up when those columns are still NULL
    (previous syncs may have missed fields this sync now parses). Returns
    the total number of rows inserted or gap-filled.
    """
    if not rows:
        return 0
    existing = {
        obj.activity_id: obj for obj in db.query(Activity).filter(
            Activity.user_id == user_id
        ).all()
    }
    count = 0
    for row in rows:
        aid = _str(row.get("activity_id"))
        if not aid:
            continue
        existing_obj = existing.get(aid)
        if existing_obj is not None:
            if _fill_missing(existing_obj, row, _ACTIVITY_FILL_COLUMNS):
                count += 1
            continue
        new_obj = Activity(
            user_id=user_id,
            activity_id=aid,
            date=_parse_date(row.get("date")),
            activity_type=_str(row.get("activity_type")) or "running",
            distance_km=_float(row.get("distance_km")),
            duration_sec=_float(row.get("duration_sec")),
            avg_power=_float(row.get("avg_power")),
            max_power=_float(row.get("max_power")),
            avg_hr=_float(row.get("avg_hr")),
            max_hr=_float(row.get("max_hr")),
            avg_pace_min_km=_pace_min_str(row),
            avg_pace_sec_km=_float(row.get("avg_pace_sec_km")),
            elevation_gain_m=_float(row.get("elevation_gain_m")),
            avg_cadence=_float(row.get("avg_cadence")),
            training_effect=_float(row.get("aerobic_te") or row.get("training_effect")),
            rss=_float(row.get("rss")),
            cp_estimate=_float(row.get("cp_estimate")),
            start_time=_str(row.get("start_time")),
            source=_str(row.get("source")) or "garmin",
        )
        db.add(new_obj)
        existing[aid] = new_obj
        count += 1
    if count > 0:
        bump_revisions(db, user_id, ["activities"])
    return count


def write_splits(user_id: str, rows: list[dict], db: Session) -> int:
    """Write split rows to DB.

    New (activity_id, split_num) pairs are inserted. Pre-existing rows get
    their ``_SPLIT_FILL_COLUMNS`` topped up when still NULL — the common
    case is native Garmin lap power that older syncs didn't parse.
    """
    if not rows:
        return 0
    existing = {
        (obj.activity_id, obj.split_num): obj
        for obj in db.query(ActivitySplit).filter(
            ActivitySplit.user_id == user_id
        ).all()
    }
    count = 0
    for row in rows:
        aid = _str(row.get("activity_id"))
        snum = row.get("split_num")
        if not aid or snum is None:
            continue
        snum = int(snum)
        existing_obj = existing.get((aid, snum))
        if existing_obj is not None:
            if _fill_missing(existing_obj, row, _SPLIT_FILL_COLUMNS):
                count += 1
            continue
        new_obj = ActivitySplit(
            user_id=user_id,
            activity_id=aid,
            split_num=snum,
            distance_km=_float(row.get("distance_km")),
            duration_sec=_float(row.get("duration_sec")),
            avg_power=_float(row.get("avg_power")),
            avg_hr=_float(row.get("avg_hr")),
            max_hr=_float(row.get("max_hr")),
            avg_pace_min_km=_pace_min_str(row),
            avg_pace_sec_km=_float(row.get("avg_pace_sec_km")),
            avg_cadence=_float(row.get("avg_cadence")),
            elevation_change_m=_float(row.get("elevation_change_m")),
        )
        db.add(new_obj)
        existing[(aid, snum)] = new_obj
        count += 1
    if count > 0:
        bump_revisions(db, user_id, ["splits"])
    return count


def write_recovery(user_id: str, readiness_rows: list[dict],
                   sleep_rows: list[dict], hrv_by_date: dict,
                   db: Session,
                   garmin_recovery: list[dict] | None = None,
                   recovery_source: str = "garmin") -> int:
    """Write recovery data (readiness + sleep merged) to DB. Returns count of new.

    Supports both Oura (readiness_rows + sleep_rows + hrv_by_date) and
    Garmin-style (garmin_recovery list with pre-parsed fields).
    ``recovery_source`` controls the source tag for garmin_recovery rows
    (default "garmin"; pass "coros" etc. for other platforms).
    """
    count = 0

    # --- Oura recovery ---
    existing_oura = {
        r[0] for r in db.query(RecoveryData.date).filter(
            RecoveryData.user_id == user_id, RecoveryData.source == "oura"
        ).all()
    }

    sleep_by_date = {}
    for row in sleep_rows:
        d = row.get("date", "")
        if d:
            sleep_by_date[d] = row

    for row in readiness_rows:
        d = _parse_date(row.get("date"))
        if not d:
            continue
        sleep = sleep_by_date.get(row.get("date", ""), {})
        hrv = hrv_by_date.get(row.get("date", ""), {})

        readiness_score = _float(row.get("readiness_score"))
        hrv_avg = _float(hrv.get("hrv_avg") or row.get("hrv_avg"))
        resting_hr = _float(hrv.get("resting_hr") or row.get("resting_hr"))
        sleep_score = _float(sleep.get("sleep_score"))
        total_sleep_sec = _float(sleep.get("total_sleep_sec"))
        deep_sleep_sec = _float(sleep.get("deep_sleep_sec"))
        rem_sleep_sec = _float(sleep.get("rem_sleep_sec"))
        body_temp_delta = _float(
            row.get("body_temperature_delta") or row.get("body_temp_delta")
        )

        if d in existing_oura:
            # Backfill empty fields on existing rows. The original write may
            # have happened before HRV extraction landed in the row builder,
            # or before multi-record-per-day overwrites were handled — without
            # this, those rows would stay null forever because the loop used
            # to skip existing dates, leaving recovery analysis stuck on
            # "insufficient HRV data" even though Oura returns the value on
            # every subsequent sync.
            existing = db.query(RecoveryData).filter(
                RecoveryData.user_id == user_id,
                RecoveryData.date == d,
                RecoveryData.source == "oura",
            ).first()
            if existing is None:
                continue
            updated = False
            if (existing.hrv_avg is None or existing.hrv_avg <= 0) and hrv_avg and hrv_avg > 0:
                existing.hrv_avg = hrv_avg
                updated = True
            if (existing.resting_hr is None or existing.resting_hr <= 0) and resting_hr and resting_hr > 0:
                existing.resting_hr = resting_hr
                updated = True
            # Sleep score: overwrite on difference, not just on null.
            # Self-heals rows from before the daily_sleep fix where
            # parse_sleep_records put readiness.score into sleep_score —
            # the canonical daily_sleep value should win every time it
            # disagrees with what's stored. Skipping the update when
            # values match preserves write-amplification benefits of
            # the dedup branch.
            if sleep_score is not None and existing.sleep_score != sleep_score:
                existing.sleep_score = sleep_score
                updated = True
            if existing.readiness_score is None and readiness_score is not None:
                existing.readiness_score = readiness_score
                updated = True
            if existing.total_sleep_sec is None and total_sleep_sec is not None:
                existing.total_sleep_sec = total_sleep_sec
                updated = True
            if existing.deep_sleep_sec is None and deep_sleep_sec is not None:
                existing.deep_sleep_sec = deep_sleep_sec
                updated = True
            if existing.rem_sleep_sec is None and rem_sleep_sec is not None:
                existing.rem_sleep_sec = rem_sleep_sec
                updated = True
            if existing.body_temp_delta is None and body_temp_delta is not None:
                existing.body_temp_delta = body_temp_delta
                updated = True
            if updated:
                count += 1
            continue

        db.add(RecoveryData(
            user_id=user_id, date=d, source="oura",
            readiness_score=readiness_score,
            hrv_avg=hrv_avg,
            resting_hr=resting_hr,
            sleep_score=sleep_score,
            total_sleep_sec=total_sleep_sec,
            deep_sleep_sec=deep_sleep_sec,
            rem_sleep_sec=rem_sleep_sec,
            body_temp_delta=body_temp_delta,
        ))
        existing_oura.add(d)
        count += 1

    # --- Garmin-style recovery ---
    if garmin_recovery:
        existing_src = {
            r[0] for r in db.query(RecoveryData.date).filter(
                RecoveryData.user_id == user_id, RecoveryData.source == recovery_source
            ).all()
        }
        for row in garmin_recovery:
            d = _parse_date(row.get("date"))
            if not d:
                continue
            if d in existing_src:
                # Update existing
                existing = db.query(RecoveryData).filter(
                    RecoveryData.user_id == user_id,
                    RecoveryData.date == d,
                    RecoveryData.source == recovery_source,
                ).first()
                if existing:
                    if row.get("readiness_score"):
                        existing.readiness_score = _float(row["readiness_score"])
                    if row.get("hrv_ms"):
                        existing.hrv_avg = _float(row["hrv_ms"])
                    if row.get("resting_hr"):
                        existing.resting_hr = _float(row["resting_hr"])
                    if row.get("sleep_score"):
                        existing.sleep_score = _float(row["sleep_score"])
                    if row.get("total_sleep_hours"):
                        existing.total_sleep_sec = _float(row["total_sleep_hours"]) * 3600 if _float(row["total_sleep_hours"]) else None
                    if row.get("deep_sleep_sec"):
                        existing.deep_sleep_sec = _float(row["deep_sleep_sec"])
                    if row.get("rem_sleep_sec"):
                        existing.rem_sleep_sec = _float(row["rem_sleep_sec"])
                    count += 1
            else:
                total_sleep_sec = None
                if row.get("total_sleep_hours"):
                    h = _float(row["total_sleep_hours"])
                    total_sleep_sec = h * 3600 if h else None
                db.add(RecoveryData(
                    user_id=user_id, date=d, source=recovery_source,
                    readiness_score=_float(row.get("readiness_score")),
                    hrv_avg=_float(row.get("hrv_ms")),
                    resting_hr=_float(row.get("resting_hr")),
                    sleep_score=_float(row.get("sleep_score")),
                    total_sleep_sec=total_sleep_sec,
                    deep_sleep_sec=_float(row.get("deep_sleep_sec")),
                    rem_sleep_sec=_float(row.get("rem_sleep_sec")),
                ))
                existing_src.add(d)
                count += 1

    if count > 0:
        bump_revisions(db, user_id, ["recovery"])
    return count


def write_daily_metrics(user_id: str, rows: list[dict], db: Session) -> int:
    """Write Garmin daily metrics to fitness_data table. Returns count of new."""
    count = 0
    metrics = [
        ("vo2max", "vo2max", False),
        ("training_status", "training_status", True),
        ("resting_hr", "rest_hr_bpm", False),
        ("training_readiness", "training_readiness", False),
    ]
    for row in rows:
        d = _parse_date(row.get("date"))
        if not d:
            continue
        for csv_col, metric_type, is_str in metrics:
            val = row.get(csv_col)
            if val is None or val == "":
                continue
            exists = db.query(FitnessData.id).filter(
                FitnessData.user_id == user_id,
                FitnessData.date == d,
                FitnessData.metric_type == metric_type,
            ).first()
            if exists:
                continue
            db.add(FitnessData(
                user_id=user_id, date=d, metric_type=metric_type, source="garmin",
                value=None if is_str else _float(val),
                value_str=_str(val) if is_str else None,
            ))
            count += 1
    if count > 0:
        bump_revisions(db, user_id, ["fitness"])
    return count


def write_profile_thresholds(
    user_id: str,
    profile: dict,
    db: Session,
    source: str = "garmin",
    as_of: date | None = None,
) -> int:
    """Write configured max/resting HR from a user-profile parse into fitness_data.

    Keeps the user's configured Garmin HR thresholds authoritative over the
    activity-max fallback in api.deps._resolve_thresholds.
    """
    if not profile:
        return 0
    when = as_of or date.today()
    count = 0
    # cp_watts is intentionally stored under the same `cp_estimate` metric
    # type that Stryd uses, so the existing _resolve_thresholds logic picks
    # the most recent value regardless of which source wrote it.
    # Mixing Garmin and Stryd CP in the same account is documented as
    # unreliable (~30% gap between the two systems); see docs/dev/gotchas.md.
    _FITNESS_METRIC_KEY = {
        "max_hr_bpm": "max_hr_bpm",
        "rest_hr_bpm": "rest_hr_bpm",
        "lthr_bpm": "lthr_bpm",
        "cp_watts": "cp_estimate",
    }
    for key in ("max_hr_bpm", "rest_hr_bpm", "lthr_bpm", "cp_watts"):
        val = profile.get(key)
        if val is None:
            continue
        metric_type = _FITNESS_METRIC_KEY[key]
        exists = db.query(FitnessData.id).filter(
            FitnessData.user_id == user_id,
            FitnessData.date == when,
            FitnessData.metric_type == metric_type,
        ).first()
        if exists:
            db.query(FitnessData).filter(
                FitnessData.user_id == user_id,
                FitnessData.date == when,
                FitnessData.metric_type == metric_type,
            ).update({"value": float(val), "source": source})
        else:
            db.add(FitnessData(
                user_id=user_id, date=when,
                metric_type=metric_type, value=float(val), source=source,
            ))
        count += 1
    if count > 0:
        bump_revisions(db, user_id, ["fitness"])
    return count


def update_cp_from_activities(user_id: str, db: Session, **kwargs) -> dict | None:
    """Derive CP from the user's recent activity power and upsert a row.

    Runs the 2-parameter hyperbolic fit (see
    ``analysis.cp_from_activities.estimate_cp_from_activities``) on the
    user's own best-effort power-vs-duration observations and writes the
    resulting CP as a ``FitnessData`` row with ``source="activities"``.

    Upserts on ``(user_id, date=as_of, metric_type="cp_estimate",
    source="activities")`` so same-day re-runs (e.g. two syncs in an hour)
    don't create duplicates. Never touches rows from other sources — the
    user can still pick Stryd, Garmin, or Activities in the Settings
    source selector; this just keeps the Activities option populated.

    Returns the fit as a ``dict`` when successful, ``None`` when there
    isn't enough data. ``None`` is not an error: a missing CP is always
    better than a wrong CP, and any previous good row stays in place until
    a future fit replaces it.
    """
    from analysis.cp_from_activities import estimate_cp_from_activities

    result = estimate_cp_from_activities(user_id, db, **kwargs)
    if result is None:
        return None

    existing = db.query(FitnessData).filter(
        FitnessData.user_id == user_id,
        FitnessData.date == result.as_of,
        FitnessData.metric_type == "cp_estimate",
        FitnessData.source == "activities",
    ).first()
    # An idempotent re-sync of the same activity window produces the same CP;
    # skipping the bump in that case lets warm visits keep returning 304.
    changed = True
    if existing:
        if existing.value == result.cp_watts:
            changed = False
        else:
            existing.value = result.cp_watts
    else:
        db.add(FitnessData(
            user_id=user_id,
            date=result.as_of,
            metric_type="cp_estimate",
            source="activities",
            value=result.cp_watts,
        ))
    if changed:
        bump_revisions(db, user_id, ["fitness"])
    return result.to_dict()


def write_lactate_threshold(user_id: str, rows: list[dict], db: Session) -> int:
    """Write lactate threshold data to fitness_data table. Returns count of new."""
    count = 0
    for row in rows:
        d = _parse_date(row.get("date"))
        if not d:
            continue
        for csv_col, metric_type in [
            ("lthr_bpm", "lthr_bpm"),
            ("lt_power_watts", "lt_power_watts"),
            ("lt_pace_sec_km", "lt_pace_sec_km"),
        ]:
            val = row.get(csv_col)
            if val is None or val == "":
                continue
            exists = db.query(FitnessData.id).filter(
                FitnessData.user_id == user_id,
                FitnessData.date == d,
                FitnessData.metric_type == metric_type,
            ).first()
            if exists:
                continue
            db.add(FitnessData(
                user_id=user_id, date=d, metric_type=metric_type,
                value=_float(val), source="garmin",
            ))
            count += 1
    if count > 0:
        bump_revisions(db, user_id, ["fitness"])
    return count


_SAMPLE_BATCH_SIZE = 500


def write_samples(user_id: str, rows: list[dict], db: Session) -> int:
    """Upsert per-second activity samples. Returns count of rows written.

    Uses INSERT OR IGNORE keyed on (user_id, activity_id, t_sec) so re-syncing an
    activity is idempotent — existing rows are left untouched. Inserts are
    batched to avoid oversized transactions for long activities.
    """
    if not rows:
        return 0

    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    total = 0
    for batch_start in range(0, len(rows), _SAMPLE_BATCH_SIZE):
        batch = rows[batch_start : batch_start + _SAMPLE_BATCH_SIZE]
        records = []
        for row in batch:
            t = row.get("t_sec")
            aid = row.get("activity_id")
            if t is None or not aid:
                continue
            speed = _float(row.get("speed_ms"))
            records.append({
                "user_id": user_id,
                "activity_id": str(aid),
                "source": str(row.get("source", "")),
                "t_sec": int(t),
                "power_watts": _float(row.get("power_watts")),
                "hr_bpm": _float(row.get("hr_bpm")),
                "speed_ms": speed,
                "pace_sec_km": round(1000.0 / speed, 2) if speed and speed > 0 else _float(row.get("pace_sec_km")),
                "cadence_spm": _float(row.get("cadence_spm")),
                "altitude_m": _float(row.get("altitude_m")),
                "distance_m": _float(row.get("distance_m")),
                "lat": _float(row.get("lat")),
                "lng": _float(row.get("lng")),
                "grade_pct": _float(row.get("grade_pct")),
                "temperature_c": _float(row.get("temperature_c")),
                "ground_time_ms": _float(row.get("ground_time_ms")),
                "oscillation_mm": _float(row.get("oscillation_mm")),
                "leg_spring_kn_m": _float(row.get("leg_spring_kn_m")),
                "vertical_ratio": _float(row.get("vertical_ratio")),
                "form_power_watts": _float(row.get("form_power_watts")),
                "respiration_rate": _float(row.get("respiration_rate")),
            })
        if not records:
            continue
        stmt = sqlite_insert(ActivitySample).values(records)
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "activity_id", "t_sec"])
        result = db.execute(stmt)
        total += result.rowcount
    return total


def write_training_plan(user_id: str, rows: list[dict], source: str,
                        db: Session) -> int:
    """Write training plan rows to DB. Returns count of new."""
    if not rows:
        return 0
    count = 0
    for row in rows:
        d = _parse_date(row.get("date"))
        if not d:
            continue
        wt = _str(row.get("workout_type"))
        exists = db.query(TrainingPlan.id).filter(
            TrainingPlan.user_id == user_id,
            TrainingPlan.date == d,
            TrainingPlan.source == source,
            TrainingPlan.workout_type == wt,
        ).first()
        if exists:
            continue
        db.add(TrainingPlan(
            user_id=user_id, date=d, source=source,
            workout_type=wt,
            planned_duration_min=_float(row.get("planned_duration_min")),
            planned_distance_km=_float(row.get("planned_distance_km")),
            target_power_min=_float(row.get("target_power_min")),
            target_power_max=_float(row.get("target_power_max")),
            workout_description=_str(row.get("workout_description")),
        ))
        count += 1
    if count > 0:
        bump_revisions(db, user_id, ["plans"])
    return count
