#!/usr/bin/env python3
"""
Send a single event to Sentry: FileNotFoundError for an optional config file.

No API, no issue ID, no auth token. Only SENTRY_DSN is required.

Usage:
  export SENTRY_DSN="https://...@....ingest.sentry.io/..."
  python3 add_events_to_issue.py
"""

import os
import sys

import sentry_sdk


def _raise_bulk_exception() -> None:
    """Raise FileNotFoundError so the stack shows __main__ in _raise_bulk_exception."""
    raise FileNotFoundError(2, "Optional config file not found", "/tmp/seed-13031.txt")


def main() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        print("Set SENTRY_DSN.", file=sys.stderr)
        sys.exit(1)

    sentry_sdk.init(
        dsn=dsn,
        environment="seed-script",
        traces_sample_rate=0,
    )
    try:
        _raise_bulk_exception()
    except FileNotFoundError:
        sentry_sdk.capture_exception()
    sentry_sdk.flush(timeout=5)
    print("Sent one FileNotFoundError event.")


if __name__ == "__main__":
    main()
