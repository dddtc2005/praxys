#!/usr/bin/env python3
"""CLI entry point: outputs training context as JSON to stdout.

Usage:
    python scripts/build_training_context.py
    python scripts/build_training_context.py --pretty
"""
import argparse
import json
import sys
import os

# Ensure the project root is on sys.path so `api` and `analysis` resolve.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.ai import build_training_context  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Output training context as JSON")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    context = build_training_context()

    indent = 2 if args.pretty else None
    json.dump(context, sys.stdout, indent=indent, default=str)
    if indent:
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
