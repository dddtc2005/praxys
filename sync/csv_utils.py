"""Shared CSV utilities: read, append with deduplication."""
import csv
import logging
import os

import portalocker

logger = logging.getLogger(__name__)

EMPTY_RESULT: list[dict] = []


def read_csv(path: str) -> list[dict]:
    """Read a CSV file and return list of dicts. Returns empty list if file doesn't exist."""
    if not os.path.exists(path):
        return []
    with open(path, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _row_key(row: dict, key_column: str | list[str]) -> str:
    """Build a dedup key from one or more columns."""
    if isinstance(key_column, list):
        return "\x00".join(row.get(k, "") for k in key_column)
    return row[key_column]


def append_rows(path: str, new_rows: list[dict], key_column: str | list[str]) -> None:
    """Append rows to a CSV, deduplicating by key_column(s). Newer rows win on conflict.

    Uses file-level locking to prevent concurrent writes from corrupting data.
    """
    if not new_rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lock_path = path + ".lock"
    with portalocker.Lock(lock_path, timeout=30):
        existing = read_csv(path)
        merged = {}
        for row in existing:
            key = _row_key(row, key_column)
            if key.strip():
                merged[key] = row
        for row in new_rows:
            key = _row_key(row, key_column)
            if key.strip():
                merged[key] = row
        fieldnames = list(new_rows[0].keys())
        for row in existing:
            for k in row.keys():
                if k not in fieldnames:
                    fieldnames.append(k)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in merged.values():
                writer.writerow(row)
