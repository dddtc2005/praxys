#!/usr/bin/env python3
"""One-shot cleanup for the shared-Garmin-token bug (issue #56).

Background
----------
Before the fix, every user's Garmin sync wrote OAuth tokens to a shared
``sync/.garmin_tokens/`` directory. `garminconnect.Garmin.login()` reuses
tokens from its tokenstore and only falls back to username/password if
loading fails — so after the first user authenticated, every subsequent
user's sync fetched that first user's Garmin data and stored it under
their own user_id. The result: multiple users seeing identical activities.

What this script does
---------------------
1. Deletes Garmin-sourced rows in ``activities``, ``activity_splits``, and
   ``fitness_data`` for every user *except* the admin(s). The admin's own
   data was correct (their tokens stayed valid for themselves); everyone
   else's "Garmin" rows are suspect and should be re-fetched after the fix.
2. Resets ``user_connections.last_sync`` to NULL for those users so the
   background scheduler treats them as stale and re-syncs promptly.
3. Removes the shared token directory so nothing stale lingers on disk.

Run with ``--dry-run`` first to see per-user counts. Add ``--apply`` to
commit the deletions. Safe to re-run: deletes are keyed on non-admin users
only, so repeated runs are idempotent once users re-sync with the fix.

Usage
-----
    python scripts/cleanup_garmin_token_bug.py --dry-run
    python scripts/cleanup_garmin_token_bug.py --apply
"""
import argparse
import os
import shutil
import sys

# Make ``db`` / ``api`` importable when run from the project root on Azure
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import session as db_session  # noqa: E402
from db.models import (  # noqa: E402
    Activity, ActivitySplit, FitnessData, User, UserConnection,
)


def _find_admin_ids(db) -> list[str]:
    """Admins keep their own Garmin rows — everyone else's are suspect."""
    rows = db.query(User.id).filter(User.is_superuser == True).all()  # noqa: E712
    return [r[0] for r in rows]


def _summarize(db, admin_ids: list[str]) -> dict:
    """Count rows the script would delete, grouped by user."""
    summary: dict = {"users": [], "totals": {"activities": 0, "splits": 0, "fitness": 0}}
    users = db.query(User).filter(~User.id.in_(admin_ids)).all()
    for u in users:
        acts = db.query(Activity).filter(
            Activity.user_id == u.id, Activity.source == "garmin",
        ).count()
        splits = db.query(ActivitySplit).filter(
            ActivitySplit.user_id == u.id,
            ActivitySplit.activity_id.in_(
                db.query(Activity.activity_id).filter(
                    Activity.user_id == u.id, Activity.source == "garmin",
                )
            ),
        ).count()
        fitness = db.query(FitnessData).filter(
            FitnessData.user_id == u.id, FitnessData.source == "garmin",
        ).count()
        if acts or splits or fitness:
            summary["users"].append({
                "email": u.email,
                "activities": acts,
                "splits": splits,
                "fitness": fitness,
            })
            summary["totals"]["activities"] += acts
            summary["totals"]["splits"] += splits
            summary["totals"]["fitness"] += fitness
    return summary


def _apply(db, admin_ids: list[str]) -> dict:
    """Delete suspect Garmin rows and reset last_sync so re-sync fires."""
    # Splits FK the activity_id; delete them via a subquery keyed on suspect
    # activities rather than blanket-deleting so Stryd-sourced splits survive.
    suspect_activity_ids = db.query(Activity.activity_id).filter(
        ~Activity.user_id.in_(admin_ids),
        Activity.source == "garmin",
    ).subquery()

    split_count = db.query(ActivitySplit).filter(
        ActivitySplit.activity_id.in_(suspect_activity_ids),
    ).delete(synchronize_session=False)

    act_count = db.query(Activity).filter(
        ~Activity.user_id.in_(admin_ids),
        Activity.source == "garmin",
    ).delete(synchronize_session=False)

    fit_count = db.query(FitnessData).filter(
        ~FitnessData.user_id.in_(admin_ids),
        FitnessData.source == "garmin",
    ).delete(synchronize_session=False)

    conn_count = db.query(UserConnection).filter(
        ~UserConnection.user_id.in_(admin_ids),
        UserConnection.platform == "garmin",
    ).update({"last_sync": None, "status": "connected"}, synchronize_session=False)

    db.commit()
    return {
        "activities_deleted": act_count,
        "splits_deleted": split_count,
        "fitness_deleted": fit_count,
        "connections_reset": conn_count,
    }


def _purge_shared_token_dir() -> bool:
    """Remove the old shared token directory if it still exists on disk."""
    data_dir = os.environ.get(
        "DATA_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
    )
    shared = os.path.join(os.path.dirname(data_dir), "sync", ".garmin_tokens")
    # After the fix, per-user dirs live *under* this path. Only remove loose
    # token files at the root — leave sub-directories (they are per-user now).
    if not os.path.isdir(shared):
        return False
    removed_any = False
    for entry in os.listdir(shared):
        full = os.path.join(shared, entry)
        if os.path.isfile(full):
            os.remove(full)
            removed_any = True
    return removed_any


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Show counts only; do not delete.")
    ap.add_argument("--apply", action="store_true", help="Apply deletions.")
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        ap.error("specify --dry-run or --apply")
    if args.dry_run and args.apply:
        ap.error("--dry-run and --apply are mutually exclusive")

    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        admin_ids = _find_admin_ids(db)
        if not admin_ids:
            print("ERROR: no admin users found (is_superuser=True). Aborting so we", file=sys.stderr)
            print("don't accidentally wipe the only Garmin rows in the database.", file=sys.stderr)
            return 2

        print(f"Admins kept: {len(admin_ids)} user(s).")
        summary = _summarize(db, admin_ids)

        if not summary["users"]:
            print("No suspect Garmin rows found — nothing to do.")
            return 0

        print("\nSuspect Garmin rows by user:")
        for u in summary["users"]:
            print(f"  {u['email']}: activities={u['activities']} "
                  f"splits={u['splits']} fitness_rows={u['fitness']}")
        print(f"\nTotals: {summary['totals']}")

        if args.dry_run:
            print("\n[dry-run] no rows deleted. Re-run with --apply to commit.")
            return 0

        result = _apply(db, admin_ids)
        print(f"\nDeleted: {result}")

        purged = _purge_shared_token_dir()
        print(f"Shared tokenstore cleanup: {'removed stale files' if purged else 'nothing to clean'}")
        print("\nDone. Affected users will be picked up by the sync scheduler;")
        print("encourage them to run Settings → Backfill for ≥180 days.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
