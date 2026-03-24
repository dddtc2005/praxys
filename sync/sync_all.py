"""Orchestrate syncing from all data sources."""
import argparse
import os
import sys

from dotenv import load_dotenv


def main():
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    parser = argparse.ArgumentParser(description="Sync all training data sources")
    parser.add_argument("--from-date", help="Start date (YYYY-MM-DD) for historical backfill")
    parser.add_argument("--skip", nargs="*", default=[], help="Sources to skip (garmin, stryd, oura)")
    args = parser.parse_args()

    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    from_date = args.from_date
    skip = [s.lower() for s in args.skip]

    if "oura" not in skip:
        try:
            from sync.oura_sync import sync as oura_sync
            token = os.environ.get("OURA_TOKEN")
            if token:
                oura_sync(token, data_dir, from_date)
            else:
                print("Oura: skipped (OURA_TOKEN not set)")
        except Exception as e:
            print(f"Oura: FAILED ({e})")

    if "garmin" not in skip:
        try:
            from sync.garmin_sync import sync as garmin_sync
            email = os.environ.get("GARMIN_EMAIL")
            password = os.environ.get("GARMIN_PASSWORD")
            if email and password:
                is_cn = os.environ.get("GARMIN_IS_CN", "").lower() == "true"
                garmin_sync(email, password, data_dir, from_date, is_cn=is_cn)
            else:
                print("Garmin: skipped (credentials not set)")
        except Exception as e:
            print(f"Garmin: FAILED ({e})")

    if "stryd" not in skip:
        try:
            from sync.stryd_sync import sync as stryd_sync
            user_id = os.environ.get("STRYD_USER_ID", "")
            email = os.environ.get("STRYD_EMAIL")
            password = os.environ.get("STRYD_PASSWORD")
            if email and password:
                stryd_sync(user_id, data_dir, email=email, password=password, from_date=from_date)
            else:
                print("Stryd: skipped (STRYD_EMAIL / STRYD_PASSWORD not set)")
        except Exception as e:
            print(f"Stryd: FAILED ({e})")

    print("\nSync complete.")


if __name__ == "__main__":
    main()
