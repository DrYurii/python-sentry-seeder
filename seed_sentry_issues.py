#!/usr/bin/env python3
"""
Seed various types of issues to a Sentry project.

Uses SENTRY_AUTH_TOKEN to fetch the project DSN via API, then sends
multiple exception types and messages to create sample issues.

Usage:
  export SENTRY_AUTH_TOKEN="sntrys_..."
  python seed_sentry_issues.py

  # Or with explicit DSN (skips API):
  export SENTRY_DSN="https://...@....ingest.sentry.io/..."
  python seed_sentry_issues.py

  # Optional: target a specific project by slug
  export SENTRY_PROJECT="my-project"
  python seed_sentry_issues.py

  # Seed 100 issues per run, 5 events per issue (events grouped by fingerprint; mixed priority):
  export SENTRY_DSN="..."
  SEED_COUNT=100 python seed_sentry_issues.py
  SEED_EVENTS_PER_ISSUE=10 python seed_sentry_issues.py
"""

import base64
import json
import os
import random
import string
import sys
import uuid
from typing import Any, Optional

import requests
import sentry_sdk


def _random_values() -> dict[str, Any]:
    """Generate random values to verify Sentry captures variable/extra data."""
    return {
        "request_id": f"req_{random.randint(10000, 99999)}",
        "user_id": random.randint(1000, 99999),
        "amount_cents": random.randint(1, 99999),
        "api_token_suffix": "".join(random.choices(string.ascii_letters + string.digits, k=12)),
        "correlation_id": f"{random.getrandbits(32):08x}",
        "session_id": f"sess_{random.getrandbits(48):012x}",
    }


def decode_sentry_token(token: str) -> dict:
    """Decode the payload part of a Sentry auth token (base64)."""
    if not token.startswith("sntrys_"):
        return {}
    try:
        payload_b64 = token.replace("sntrys_", "", 1).split("_")[0]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        decoded = base64.urlsafe_b64decode(payload_b64)
        return json.loads(decoded)
    except Exception:
        return {}


def get_dsn_from_api(token: str, org_slug: Optional[str] = None, project_slug: Optional[str] = None) -> Optional[str]:
    """Use Sentry API to list projects and get the first project's DSN."""
    payload = decode_sentry_token(token)
    region_url = (payload.get("region_url") or "https://us.sentry.io").rstrip("/")
    org = org_slug or payload.get("org")
    if not org:
        print("Could not determine org from token. Set SENTRY_ORG or use SENTRY_DSN.", file=sys.stderr)
        return None

    api_base = region_url.replace("sentry.io", "sentry.io/api/0")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # List projects
    r = requests.get(f"{api_base}/organizations/{org}/projects/", headers=headers, timeout=15)
    if not r.ok:
        print(f"API list projects failed: {r.status_code} {r.text[:200]}", file=sys.stderr)
        if r.status_code == 403:
            print(
                "Your token doesn't have permission to list projects. Use the DSN instead:",
                file=sys.stderr,
            )
            print(
                "  1. In Sentry: Project Settings → Client Keys (DSN) → copy the DSN",
                file=sys.stderr,
            )
            print('  2. Run: export SENTRY_DSN="https://...@....ingest.sentry.io/..."', file=sys.stderr)
            print("  3. Run this script again (no SENTRY_AUTH_TOKEN needed)", file=sys.stderr)
        return None
    projects = r.json()
    if not projects:
        print("No projects found in organization.", file=sys.stderr)
        return None

    # Pick project
    if project_slug:
        proj = next((p for p in projects if p.get("slug") == project_slug), None)
        if not proj:
            print(f"Project '{project_slug}' not found. Available: {[p.get('slug') for p in projects]}", file=sys.stderr)
            return None
    else:
        proj = projects[0]
        if len(projects) > 1:
            print(f"Using first project: {proj.get('slug')}. Set SENTRY_PROJECT to pick another.", file=sys.stderr)

    slug = proj.get("slug")
    # Get client keys (DSN)
    r2 = requests.get(f"{api_base}/projects/{org}/{slug}/keys/", headers=headers, timeout=15)
    if not r2.ok:
        print(f"API list keys failed: {r2.status_code} {r2.text[:200]}", file=sys.stderr)
        return None
    keys = r2.json()
    if not keys:
        print("No client keys (DSN) found for project.", file=sys.stderr)
        return None
    dsn = keys[0].get("dsn", {}).get("public")
    return dsn


def seed_issues(dsn: str) -> None:
    """Send a variety of events to Sentry to create sample issues."""
    sentry_sdk.init(
        dsn=dsn,
        environment="seed-script",
        traces_sample_rate=0,
    )

    # --- Messages (different levels) ---
    sentry_sdk.capture_message("Seed: Info message", level="info")
    sentry_sdk.capture_message("Seed: Warning message", level="warning")
    sentry_sdk.capture_message("Seed: Error message", level="error")
    sentry_sdk.capture_message("Seed: Fatal message", level="fatal")
    sentry_sdk.capture_message("Seed: Debug message", level="debug")

    # --- Exceptions ---
    try:
        raise ValueError("Seed: Invalid value for user_id")
    except ValueError:
        sentry_sdk.capture_exception()

    try:
        raise TypeError("Seed: expected str, got int")
    except TypeError:
        sentry_sdk.capture_exception()

    try:
        raise KeyError("Seed: missing key 'config'")
    except KeyError:
        sentry_sdk.capture_exception()

    try:
        raise RuntimeError("Seed: service unavailable")
    except RuntimeError:
        sentry_sdk.capture_exception()

    try:
        _ = 1 / 0
    except ZeroDivisionError:
        sentry_sdk.capture_exception()

    try:
        raise FileNotFoundError(2, "No such file", "/tmp/seed-missing.txt")
    except FileNotFoundError:
        sentry_sdk.capture_exception()

    try:
        raise ConnectionError("Seed: failed to connect to database")
    except ConnectionError:
        sentry_sdk.capture_exception()

    try:
        raise PermissionError(13, "Permission denied", "/etc/shadow")
    except PermissionError:
        sentry_sdk.capture_exception()

    # --- With breadcrumbs ---
    sentry_sdk.add_breadcrumb(category="auth", message="User login attempt", level="info")
    sentry_sdk.add_breadcrumb(category="http", message="GET /api/users", level="info")
    try:
        raise ValueError("Seed: Auth failed after login attempt")
    except ValueError:
        sentry_sdk.capture_exception()

    # --- With extra context ---
    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("seed", "true")
        scope.set_tag("feature", "checkout")
        scope.set_extra("cart_id", "cart-12345")
        scope.set_extra("user_agent", "SeedScript/1.0")
        try:
            raise RuntimeError("Seed: Payment gateway timeout")
        except RuntimeError:
            sentry_sdk.capture_exception()

    # --- Random values: check in Sentry whether variables show under "Additional Data" and stack "Local Variables" ---
    rv = _random_values()

    def _fail_with_locals(
        request_id: str,
        user_id: int,
        amount_cents: int,
        api_token_suffix: str,
        correlation_id: str,
        session_id: str,
    ) -> None:
        # These args and locals may appear as "Local Variables" in the event stack frame in Sentry.
        payload = {
            "amount": amount_cents,
            "currency": "USD",
            "correlation_id": correlation_id,
            "session_id": session_id,
            "api_token_suffix": api_token_suffix,
        }
        raise ValueError(
            f"Seed: Charge failed for request {request_id} (user={user_id}, amount={amount_cents}, payload={payload})"
        )

    with sentry_sdk.configure_scope() as scope:
        for key, value in rv.items():
            scope.set_extra(f"random_{key}", value)
        scope.set_tag("seed_random", "true")
        try:
            _fail_with_locals(
                request_id=rv["request_id"],
                user_id=rv["user_id"],
                amount_cents=rv["amount_cents"],
                api_token_suffix=rv["api_token_suffix"],
                correlation_id=rv["correlation_id"],
                session_id=rv["session_id"],
            )
        except ValueError:
            sentry_sdk.capture_exception()

    print("Random values sent (check in Sentry: Additional Data + stack Local Variables):", rv)

    # --- Chained exception (Python 3) ---
    try:
        try:
            raise OSError(111, "Connection refused")
        except OSError as e:
            raise RuntimeError("Seed: Wrapper error") from e
    except RuntimeError:
        sentry_sdk.capture_exception()

    # --- AssertionError ---
    try:
        assert False, "Seed: Assertion failed in validation"
    except AssertionError:
        sentry_sdk.capture_exception()

    # --- IndexError ---
    try:
        [1, 2, 3][10]
    except IndexError:
        sentry_sdk.capture_exception()

    # --- AttributeError ---
    try:
        (None).missing_attr
    except AttributeError:
        sentry_sdk.capture_exception()

    sentry_sdk.flush(timeout=5)
    print("Seeding complete. Check your Sentry project for the new issues.")


# Issue kinds for bulk seeding: (fingerprint_key, exc_type, message_template, level).
# Events with the same fingerprint group into one Issue. Level sets priority: error/fatal=High, warning=Medium, info/debug=Low.
# See: https://docs.sentry.io/product/issues/grouping-and-fingerprints
# See: https://docs.sentry.io/product/issues/issue-priority
_ISSUE_KINDS: list[tuple[str, type[Exception], str, str]] = [
    # High priority (error/fatal)
    ("validation-error", ValueError, "Validation failed for request {request_id}", "error"),
    ("service-timeout", RuntimeError, "Service timeout for session {session_id}", "error"),
    ("connection-refused", ConnectionError, "Database connection refused (correlation_id={correlation_id})", "error"),
    ("permission-denied", PermissionError, "Access denied to resource for user {user_id}", "error"),
    ("fatal-crash", RuntimeError, "Fatal: unrecoverable state (request_id={request_id})", "fatal"),
    # Medium priority (warning)
    ("config-missing", KeyError, "Missing config key in payload", "warning"),
    ("type-mismatch", TypeError, "Unexpected type for user_id={user_id}", "warning"),
    ("deprecation", RuntimeError, "Deprecated API used at session {session_id}", "warning"),
    ("rate-limit", RuntimeError, "Rate limit approached for user {user_id}", "warning"),
    # Low priority (info/debug)
    ("audit-info", ValueError, "Audit: validation skipped for request {request_id}", "info"),
    ("debug-trace", AssertionError, "Debug assertion: amount_cents={amount_cents}", "debug"),
    ("file-missing", FileNotFoundError, "Optional config file not found", "info"),
]


def _raise_bulk_exception(exc_cls: type[Exception], message: str) -> None:
    """Raise an exception so we can capture it. FileNotFoundError has a different signature."""
    if exc_cls is FileNotFoundError:
        raise FileNotFoundError(2, message, f"/tmp/seed-{random.getrandbits(16)}.txt")
    raise exc_cls(message)


def seed_bulk_issues(dsn: str, issue_count: int, events_per_issue: int) -> None:
    """Send `issue_count` issues; each issue gets `events_per_issue` events that share one fingerprint (grouped).
    Uses a new run_id per run so each run creates new issues. Different issue kinds have different levels (priority)."""
    sentry_sdk.init(
        dsn=dsn,
        environment="seed-script",
        traces_sample_rate=0,
    )
    run_id = str(uuid.uuid4())
    kinds = _ISSUE_KINDS
    total_events = 0
    for issue_idx in range(issue_count):
        kind_key, exc_cls, msg_tpl, level = kinds[issue_idx % len(kinds)]
        # Same fingerprint for all events in this issue → they group into one Issue (see Sentry grouping docs).
        fingerprint = ["seed-group", run_id, kind_key]
        for event_idx in range(events_per_issue):
            rv = _random_values()
            try:
                message = msg_tpl.format(**rv)
            except KeyError:
                message = msg_tpl
            with sentry_sdk.configure_scope() as scope:
                scope.fingerprint = fingerprint
                scope.set_level(level)
                for key, value in rv.items():
                    scope.set_extra(f"random_{key}", value)
                scope.set_extra("event_index", event_idx + 1)
                scope.set_extra("events_per_issue", events_per_issue)
                scope.set_tag("seed_bulk", "true")
                scope.set_tag("issue_kind", kind_key)
                scope.set_tag("priority", level)
                try:
                    _raise_bulk_exception(exc_cls, message)
                except Exception:
                    sentry_sdk.capture_exception()
            total_events += 1
        if (issue_idx + 1) % 5 == 0 or issue_idx == 0:
            print(f"  Issue {issue_idx + 1}/{issue_count} ({events_per_issue} events each)...")
    sentry_sdk.flush(timeout=15)
    print(
        f"Seeding complete. {issue_count} issues created ({total_events} events total, "
        f"{events_per_issue} events per issue). Run again to add more issues."
    )


def main() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    token = os.environ.get("SENTRY_AUTH_TOKEN")
    project = os.environ.get("SENTRY_PROJECT")
    org = os.environ.get("SENTRY_ORG")

    if not dsn and token:
        print("Fetching DSN from Sentry API...")
        dsn = get_dsn_from_api(token, org_slug=org, project_slug=project)
    if not dsn:
        if not token and not dsn:
            print(
                "Set SENTRY_AUTH_TOKEN or SENTRY_DSN. Optional: SENTRY_PROJECT, SENTRY_ORG.",
                file=sys.stderr,
            )
        sys.exit(1)

    try:
        seed_count = int(os.environ.get("SEED_COUNT", "100"))
    except ValueError:
        seed_count = 100
    try:
        events_per_issue = int(os.environ.get("SEED_EVENTS_PER_ISSUE", "5"))
    except ValueError:
        events_per_issue = 5

    if seed_count > 0:
        print(
            f"Bulk seeding {seed_count} issues ({events_per_issue} events per issue, "
            "grouped by fingerprint; mixed priorities)..."
        )
        seed_bulk_issues(dsn, seed_count, events_per_issue)
    else:
        seed_issues(dsn)


if __name__ == "__main__":
    main()
