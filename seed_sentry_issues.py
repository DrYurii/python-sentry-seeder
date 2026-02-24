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

  # 3 releases per run (package@version, see docs/features/releases.md). Override base:
  SENTRY_RELEASE="seed-script@2.0.0" python seed_sentry_issues.py

  # Events are spread across 3 environments (production, staging, development). Override:
  SENTRY_SEED_ENVIRONMENTS="production,staging,development,preview" python seed_sentry_issues.py

  # Trace data (transaction + spans) is sent by default so issues link to Trace View. Disable with:
  SENTRY_TRACES_SAMPLE_RATE=0 python seed_sentry_issues.py
"""

import base64
import contextvars
import json
import os
import random
import re
import string
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Any, Optional

import requests
import sentry_sdk

# Per-event release override (see docs/features/releases.md). Set before capture so before_send can attach it.
_current_release: contextvars.ContextVar[str | None] = contextvars.ContextVar("_current_release", default=None)
# Per-event environment; events are distributed across these.
_current_environment: contextvars.ContextVar[str | None] = contextvars.ContextVar("_current_environment", default=None)

# Span names for seed trace (Sentry Tracing: transaction + spans). 10 entries per trace.
# See https://docs.sentry.io/concepts/key-terms/tracing/
_SEED_SPAN_NAMES = (
    "validate",
    "load",
    "parse",
    "transform",
    "process",
    "resolve",
    "execute",
    "commit",
    "finalize",
    "run",
)
_SEED_SPAN_SLEEP = 0.005  # small delay so spans have duration in Trace View


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


def _get_releases() -> list[str]:
    """Return 3 release names (package@version) per run. See docs/features/releases.md.
    Format: package@version (semver); shortVersion in UI is the part after @.
    Override base via SENTRY_RELEASE (e.g. seed-script@1.0.0) to derive 3 versions."""
    base = (os.environ.get("SENTRY_RELEASE") or "seed-script@1.0.0").strip() or "seed-script@1.0.0"
    match = re.match(r"^(.+@)(\d+)\.(\d+)\.(\d+)$", base)
    if match:
        prefix, major, minor, patch = match.group(1), int(match.group(2)), int(match.group(3)), int(match.group(4))
        return [f"{prefix}{major}.{minor}.{patch}", f"{prefix}{major}.{minor + 1}.0", f"{prefix}{major + 1}.0.0"]
    # Fallback: non-semver base, append suffixes
    return [f"{base}-a", f"{base}-b", f"{base}-c"]


def _get_environments() -> list[str]:
    """Return environment names to distribute events across (e.g. production, staging, development)."""
    env_var = os.environ.get("SENTRY_SEED_ENVIRONMENTS")
    if env_var:
        return [e.strip() for e in env_var.split(",") if e.strip()]
    return ["production", "staging", "development"]


def _get_traces_sample_rate() -> float:
    """Sample rate for tracing (0 = no traces, 1.0 = all). Enables Trace View / linking errors to traces."""
    try:
        return float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "1.0"))
    except ValueError:
        return 1.0


@contextmanager
def _seed_transaction(transaction_name: str):
    """
    Run code inside a Sentry transaction with child spans so seeded events have trace data.
    Errors captured inside the 'execute' span are linked to this trace (Trace View in Sentry).
    See https://docs.sentry.io/concepts/key-terms/tracing/
    """
    with sentry_sdk.start_transaction(op="seed.task", name=transaction_name):
        for span_name in _SEED_SPAN_NAMES[:-1]:
            with sentry_sdk.start_span(op="seed.step", name=span_name):
                time.sleep(_SEED_SPAN_SLEEP)
        with sentry_sdk.start_span(op="seed.step", name=_SEED_SPAN_NAMES[-1]):
            yield


def _before_send_set_release(event: dict, hint: dict) -> dict | None:
    """Set event release and environment from per-event overrides."""
    release = _current_release.get()
    if release:
        event["release"] = release
    env = _current_environment.get()
    if env:
        event["environment"] = env
    return event


def _set_release_and_capture(
    releases: list[str], environments: list[str], event_idx: list[int], level: str | None, message: str | None = None
) -> None:
    """Set current release and environment (round-robin) then capture; for variety seed."""
    _current_release.set(releases[event_idx[0] % len(releases)])
    _current_environment.set(environments[event_idx[0] % len(environments)])
    event_idx[0] += 1
    if message is not None:
        sentry_sdk.capture_message(message, level=level or "info")
    else:
        sentry_sdk.capture_exception()


def seed_issues(dsn: str, releases: list[str], environments: list[str]) -> None:
    """Send a variety of events to Sentry to create sample issues. Events distributed across releases and environments."""
    sentry_sdk.init(
        dsn=dsn,
        release=releases[0],
        environment=environments[0],
        traces_sample_rate=_get_traces_sample_rate(),
        before_send=_before_send_set_release,
    )
    ev = [0]

    # --- Messages (different levels) ---
    with _seed_transaction("Seed: Info message"):
        _set_release_and_capture(releases, environments, ev, "info", "Seed: Info message")
    with _seed_transaction("Seed: Warning message"):
        _set_release_and_capture(releases, environments, ev, "warning", "Seed: Warning message")
    with _seed_transaction("Seed: Error message"):
        _set_release_and_capture(releases, environments, ev, "error", "Seed: Error message")
    with _seed_transaction("Seed: Fatal message"):
        _set_release_and_capture(releases, environments, ev, "fatal", "Seed: Fatal message")
    with _seed_transaction("Seed: Debug message"):
        _set_release_and_capture(releases, environments, ev, "debug", "Seed: Debug message")

    # --- Exceptions (with deep stack: up to 10 frames for Sentry Issue Details) ---
    with _seed_transaction("Seed: ValueError user_id"):
        try:
            _seed_stack_0(ValueError, "Seed: Invalid value for user_id")
        except ValueError:
            _set_release_and_capture(releases, environments, ev, None)

    with _seed_transaction("Seed: TypeError"):
        try:
            raise TypeError("Seed: expected str, got int")
        except TypeError:
            _set_release_and_capture(releases, environments, ev, None)

    with _seed_transaction("Seed: KeyError config"):
        try:
            raise KeyError("Seed: missing key 'config'")
        except KeyError:
            _set_release_and_capture(releases, environments, ev, None)

    with _seed_transaction("Seed: RuntimeError unavailable"):
        try:
            raise RuntimeError("Seed: service unavailable")
        except RuntimeError:
            _set_release_and_capture(releases, environments, ev, None)

    with _seed_transaction("Seed: ZeroDivisionError"):
        try:
            _ = 1 / 0
        except ZeroDivisionError:
            _set_release_and_capture(releases, environments, ev, None)

    with _seed_transaction("Seed: FileNotFoundError"):
        try:
            raise FileNotFoundError(2, "No such file", "/tmp/seed-missing.txt")
        except FileNotFoundError:
            _set_release_and_capture(releases, environments, ev, None)

    with _seed_transaction("Seed: ConnectionError"):
        try:
            raise ConnectionError("Seed: failed to connect to database")
        except ConnectionError:
            _set_release_and_capture(releases, environments, ev, None)

    with _seed_transaction("Seed: PermissionError"):
        try:
            raise PermissionError(13, "Permission denied", "/etc/shadow")
        except PermissionError:
            _set_release_and_capture(releases, environments, ev, None)

    # --- With breadcrumbs ---
    sentry_sdk.add_breadcrumb(category="auth", message="User login attempt", level="info")
    sentry_sdk.add_breadcrumb(category="http", message="GET /api/users", level="info")
    with _seed_transaction("Seed: Auth failed after login"):
        try:
            raise ValueError("Seed: Auth failed after login attempt")
        except ValueError:
            _set_release_and_capture(releases, environments, ev, None)

    # --- With extra context ---
    with _seed_transaction("Seed: Payment gateway timeout"):
        with sentry_sdk.configure_scope() as scope:
            scope.set_tag("seed", "true")
            scope.set_tag("feature", "checkout")
            scope.set_extra("cart_id", "cart-12345")
            scope.set_extra("user_agent", "SeedScript/1.0")
            try:
                raise RuntimeError("Seed: Payment gateway timeout")
            except RuntimeError:
                _set_release_and_capture(releases, environments, ev, None)

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

    with _seed_transaction("Seed: Charge failed (random values)"):
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
                _set_release_and_capture(releases, environments, ev, None)

    print("Random values sent (check in Sentry: Additional Data + stack Local Variables):", rv)

    # --- Chained exception (Python 3) ---
    with _seed_transaction("Seed: Chained RuntimeError from OSError"):
        try:
            try:
                raise OSError(111, "Connection refused")
            except OSError as e:
                raise RuntimeError("Seed: Wrapper error") from e
        except RuntimeError:
            _set_release_and_capture(releases, environments, ev, None)

    # --- AssertionError ---
    with _seed_transaction("Seed: AssertionError"):
        try:
            assert False, "Seed: Assertion failed in validation"
        except AssertionError:
            _set_release_and_capture(releases, environments, ev, None)

    # --- IndexError ---
    with _seed_transaction("Seed: IndexError"):
        try:
            [1, 2, 3][10]
        except IndexError:
            _set_release_and_capture(releases, environments, ev, None)

    # --- AttributeError ---
    with _seed_transaction("Seed: AttributeError"):
        try:
            (None).missing_attr
        except AttributeError:
            _set_release_and_capture(releases, environments, ev, None)

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


# Call chain to produce a stack trace with up to 10 frames (Sentry Issue Details stack trace).
def _seed_stack_9(exc_cls: type[Exception], message: str) -> None:
    _raise_bulk_exception(exc_cls, message)


def _seed_stack_8(exc_cls: type[Exception], message: str) -> None:
    _seed_stack_9(exc_cls, message)


def _seed_stack_7(exc_cls: type[Exception], message: str) -> None:
    _seed_stack_8(exc_cls, message)


def _seed_stack_6(exc_cls: type[Exception], message: str) -> None:
    _seed_stack_7(exc_cls, message)


def _seed_stack_5(exc_cls: type[Exception], message: str) -> None:
    _seed_stack_6(exc_cls, message)


def _seed_stack_4(exc_cls: type[Exception], message: str) -> None:
    _seed_stack_5(exc_cls, message)


def _seed_stack_3(exc_cls: type[Exception], message: str) -> None:
    _seed_stack_4(exc_cls, message)


def _seed_stack_2(exc_cls: type[Exception], message: str) -> None:
    _seed_stack_3(exc_cls, message)


def _seed_stack_1(exc_cls: type[Exception], message: str) -> None:
    _seed_stack_2(exc_cls, message)


def _seed_stack_0(exc_cls: type[Exception], message: str) -> None:
    _seed_stack_1(exc_cls, message)


def seed_bulk_issues(dsn: str, issue_count: int, events_per_issue: int, releases: list[str], environments: list[str]) -> None:
    """Send `issue_count` issues; each issue gets `events_per_issue` events that share one fingerprint (grouped).
    Events are distributed across releases and environments."""
    sentry_sdk.init(
        dsn=dsn,
        release=releases[0],
        environment=environments[0],
        traces_sample_rate=_get_traces_sample_rate(),
        before_send=_before_send_set_release,
    )
    run_id = str(uuid.uuid4())
    kinds = _ISSUE_KINDS
    total_events = 0
    global_event_idx = 0
    for issue_idx in range(issue_count):
        kind_key, exc_cls, msg_tpl, level = kinds[issue_idx % len(kinds)]
        # Same fingerprint for all events in this issue → they group into one Issue (see Sentry grouping docs).
        fingerprint = ["seed-group", run_id, kind_key]
        for event_idx in range(events_per_issue):
            _current_release.set(releases[global_event_idx % len(releases)])
            _current_environment.set(environments[global_event_idx % len(environments)])
            global_event_idx += 1
            rv = _random_values()
            try:
                message = msg_tpl.format(**rv)
            except KeyError:
                message = msg_tpl
            with _seed_transaction(transaction_name=f"Seed {kind_key} event {event_idx + 1}"):
                with sentry_sdk.configure_scope() as scope:
                    scope.fingerprint = fingerprint
                    scope.set_level(level)
                    for key, value in rv.items():
                        scope.set_extra(f"random_{key}", value)
                    scope.set_extra("event_index", event_idx + 1)
                    scope.set_extra("events_per_issue", events_per_issue)
                    scope.set_tag("seed_bulk", "true")
                    scope.set_tag("seed_run_id", run_id)
                    scope.set_tag("issue_kind", kind_key)
                    scope.set_tag("priority", level)
                    try:
                        _seed_stack_0(exc_cls, message)
                    except Exception:
                        sentry_sdk.capture_exception()
            total_events += 1
        if (issue_idx + 1) % 5 == 0 or issue_idx == 0:
            print(f"  Issue {issue_idx + 1}/{issue_count} ({events_per_issue} events each)...")
    sentry_sdk.flush(timeout=15)
    print(
        f"Seeding complete. {issue_count} issues created ({total_events} events total, "
        f"{events_per_issue} events per issue), across {len(releases)} releases and {len(environments)} environments. Run again to add more issues."
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

    releases = _get_releases()
    environments = _get_environments()
    print(f"Using {len(releases)} releases: {', '.join(releases)}")
    print(f"Using {len(environments)} environments: {', '.join(environments)}")

    if seed_count > 0:
        print(
            f"Bulk seeding {seed_count} issues ({events_per_issue} events per issue, "
            f"grouped by fingerprint; mixed priorities; events spread across {len(releases)} releases and {len(environments)} environments)..."
        )
        seed_bulk_issues(dsn, seed_count, events_per_issue, releases, environments)
    else:
        seed_issues(dsn, releases, environments)


if __name__ == "__main__":
    main()
