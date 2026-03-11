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

  # Structured logs are sent to Sentry Logs (enable_logs=True). Requires sentry-sdk>=2.35.0.

  # Persistent issues: same few issues get new events every run (fixed fingerprints; no new issues):
  SEED_PERSISTENT=1 python seed_sentry_issues.py
  SEED_PERSISTENT=1 SEED_PERSISTENT_EVENTS_PER_RUN=10 python seed_sentry_issues.py
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
from datetime import datetime, timezone
from typing import Any, Optional

import requests
import sentry_sdk

# Structured logs (Sentry Logs). Requires sentry-sdk>=2.35.0. See https://docs.sentry.io/platforms/python/logs
# Import from the logger submodule (sentry_sdk.logger) since the package may not expose it as an attribute.
try:
    from sentry_sdk.logger import (  # type: ignore[attr-defined]
        trace as _log_trace,
        debug as _log_debug,
        info as _log_info,
        warning as _log_warning,
        error as _log_error,
        fatal as _log_fatal,
    )

    class _SentryLogger:
        trace = staticmethod(_log_trace)
        debug = staticmethod(_log_debug)
        info = staticmethod(_log_info)
        warning = staticmethod(_log_warning)
        error = staticmethod(_log_error)
        fatal = staticmethod(_log_fatal)

    _sentry_logger = _SentryLogger()
    _logs_enabled = True
except (ImportError, AttributeError):
    class _NoopLogger:
        """No-op when sentry_sdk.logger is not available (e.g. SDK < 2.35.0)."""

        def trace(self, msg, **kwargs): pass  # no-op
        def debug(self, msg, **kwargs): pass  # no-op
        def info(self, msg, **kwargs): pass  # no-op
        def warning(self, msg, **kwargs): pass  # no-op
        def error(self, msg, **kwargs): pass  # no-op
        def fatal(self, msg, **kwargs): pass  # no-op
    _sentry_logger = _NoopLogger()
    _logs_enabled = False

# Per-event release override (see docs/features/releases.md). Set before capture so before_send can attach it.
_current_release: contextvars.ContextVar[str | None] = contextvars.ContextVar("_current_release", default=None)
# Per-event environment; events are distributed across these.
_current_environment: contextvars.ContextVar[str | None] = contextvars.ContextVar("_current_environment", default=None)
# Per-event exception enrichment for Feed All (before_send applies these to exception.values[]).
_current_mechanism_type: contextvars.ContextVar[str] = contextvars.ContextVar("_current_mechanism_type", default="generic")
_current_mechanism_handled: contextvars.ContextVar[bool] = contextvars.ContextVar("_current_mechanism_handled", default=True)
_current_main_thread: contextvars.ContextVar[bool] = contextvars.ContextVar("_current_main_thread", default=True)

# Feed All enrichment presets (docs/feed-all-filter-matrix.md, docs/feed-all-seed-enrichment-guide.md).
# Device context: type required; arch, brand, family, model, model_id, name, locale, orientation, uuid.
_DEVICE_PRESETS: list[dict[str, Any]] = [
    {"type": "device", "arch": "arm64", "brand": "Apple", "family": "iPhone", "model": "iPhone15,2", "model_id": "iPhone15,2", "name": "iPhone 15 Pro", "locale": "en_US", "orientation": "portrait"},
    {"type": "device", "arch": "arm64", "brand": "Samsung", "family": "Galaxy", "model": "SM-S908B", "model_id": "GVU6C", "name": "Galaxy S23 Ultra", "locale": "en_GB", "orientation": "landscape"},
    {"type": "device", "arch": "x86_64", "brand": "Google", "family": "Pixel", "model": "Pixel 8", "model_id": "sdk_gphone_x86", "name": "Pixel 8", "locale": "de_DE", "orientation": "portrait"},
]
# device.class: 1/2/3 (query as low/medium/high); dist: build identifiers.
_DEVICE_CLASS_VALUES: list[str] = ["1", "2", "3"]
_DIST_VALUES: list[str] = ["1001", "2001", "beta", "rc1"]
# App context: in_foreground boolean.
_APP_PRESETS: list[dict[str, Any]] = [
    {"type": "app", "in_foreground": True},
    {"type": "app", "in_foreground": False},
]
# Geo: user.geo and/or tags geo.*. Guide: include both user.geo and geo tags across samples.
_GEO_USER_PRESETS: list[dict[str, str]] = [
    {"city": "Miami", "country_code": "US", "region": "United States", "subdivision": "Florida"},
    {"city": "Berlin", "country_code": "DE", "region": "Germany", "subdivision": "Berlin"},
    {"city": "Recife", "country_code": "BR", "region": "Pernambuco", "subdivision": "Pernambuco"},
    {"city": "Tokyo", "country_code": "JP", "region": "Tokyo Prefecture", "subdivision": "Tokyo"},
]
# Geo tag keys for Feed All (event-level geo filters).
_TAG_GEO_CITY = "geo.city"
_TAG_GEO_COUNTRY_CODE = "geo.country_code"
_TAG_GEO_REGION = "geo.region"
_TAG_GEO_SUBDIVISION = "geo.subdivision"
_GEO_TAG_PRESETS: list[dict[str, str]] = [
    {_TAG_GEO_CITY: "Miami", _TAG_GEO_COUNTRY_CODE: "US", _TAG_GEO_REGION: "United States", _TAG_GEO_SUBDIVISION: "California"},
    {_TAG_GEO_CITY: "Berlin", _TAG_GEO_COUNTRY_CODE: "DE", _TAG_GEO_REGION: "Germany", _TAG_GEO_SUBDIVISION: "Bayern"},
    {_TAG_GEO_CITY: "Recife", _TAG_GEO_COUNTRY_CODE: "BR", _TAG_GEO_REGION: "Pernambuco", _TAG_GEO_SUBDIVISION: "Pernambuco"},
    {_TAG_GEO_CITY: "Tokyo", _TAG_GEO_COUNTRY_CODE: "JP", _TAG_GEO_REGION: "Tokyo Prefecture", _TAG_GEO_SUBDIVISION: "Tokyo"},
]
# Exception mechanism: type (generic, onerror, instrument), handled, main_thread.
_ERROR_MECHANISM_PRESETS: list[tuple[str, bool, bool]] = [
    ("generic", True, True),
    ("onerror", False, True),
    ("instrument", True, False),
    ("generic", False, False),
]

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


def _utc_now_iso() -> str:
    """Current time in UTC, ISO format. Use for log attributes so Sentry display can be verified."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _print_run_start_utc() -> None:
    """Print run start time (UTC) so users can verify log timestamps vs Sentry UI timezone."""
    utc = _utc_now_iso()
    print(
        f"Run started at UTC: {utc}  "
        "(Sentry shows log times in your account timezone: User Settings → Account → Timezone)"
    )


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


def _apply_enrichment_for_event(index: int) -> None:
    """Apply Feed All enrichment (device, app, geo, tags, exception vars) for the event at given index.
    Round-robins over presets so different events get different combinations; ensures coverage for filters.
    """
    i = index
    # Device context + tags (device.class, device.family, device.model)
    device = _DEVICE_PRESETS[i % len(_DEVICE_PRESETS)].copy()
    device["uuid"] = str(uuid.uuid4())
    sentry_sdk.set_context("device", device)
    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("device.class", _DEVICE_CLASS_VALUES[i % len(_DEVICE_CLASS_VALUES)])
        scope.set_tag("device.family", device.get("family", ""))
        scope.set_tag("device.model", device.get("model", ""))
        scope.set_tag("dist", _DIST_VALUES[i % len(_DIST_VALUES)])
    # App context
    sentry_sdk.set_context("app", _APP_PRESETS[i % len(_APP_PRESETS)].copy())
    # User geo and/or geo tags: vary so some events have only user.geo, some only tags, some both.
    geo_style = i % 3  # 0: user only, 1: tags only, 2: both
    if geo_style in (0, 2):
        sentry_sdk.set_user({"geo": _GEO_USER_PRESETS[i % len(_GEO_USER_PRESETS)].copy()})
    else:
        sentry_sdk.set_user(None)
    if geo_style in (1, 2):
        with sentry_sdk.configure_scope() as scope:
            tags = _GEO_TAG_PRESETS[i % len(_GEO_TAG_PRESETS)]
            for k, v in tags.items():
                scope.set_tag(k, v)
    # Exception mechanism (applied in before_send)
    mech_type, handled, main_thread = _ERROR_MECHANISM_PRESETS[i % len(_ERROR_MECHANISM_PRESETS)]
    _current_mechanism_type.set(mech_type)
    _current_mechanism_handled.set(handled)
    _current_main_thread.set(main_thread)


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
    """Set event release, environment, and exception mechanism from per-event overrides (Feed All)."""
    release = _current_release.get()
    if release:
        event["release"] = release
    env = _current_environment.get()
    if env:
        event["environment"] = env
    # Exception enrichment for Feed All: error.handled, error.mechanism, error.main_thread
    values = event.get("exception") and event["exception"].get("values")
    if values:
        mech_type = _current_mechanism_type.get()
        handled = _current_mechanism_handled.get()
        main_thread = _current_main_thread.get()
        for exc_val in values:
            if isinstance(exc_val, dict):
                exc_val["mechanism"] = exc_val.get("mechanism") or {}
                exc_val["mechanism"]["type"] = mech_type
                exc_val["mechanism"]["handled"] = handled
                exc_val["main_thread"] = main_thread
    return event


def _set_release_and_capture(
    releases: list[str], environments: list[str], event_idx: list[int], level: str | None, message: str | None = None
) -> None:
    """Set Feed All enrichment, release, and environment (round-robin) then capture; for variety seed."""
    idx = event_idx[0]
    _apply_enrichment_for_event(idx)
    _current_release.set(releases[idx % len(releases)])
    _current_environment.set(environments[idx % len(environments)])
    event_idx[0] += 1
    if message is not None:
        event_id = sentry_sdk.capture_message(message, level=level or "info")
    else:
        event_id = sentry_sdk.capture_exception()
    if event_id:
        print(f"  Sent event: {event_id}")
    else:
        print(
            "  Event dropped (not sent). Check DSN, network, and that before_send does not return None.",
            file=sys.stderr,
        )


def seed_issues(dsn: str, releases: list[str], environments: list[str]) -> None:
    """Send a variety of events to Sentry to create sample issues. Events distributed across releases and environments."""
    sentry_sdk.init(
        dsn=dsn,
        release=releases[0],
        environment=environments[0],
        traces_sample_rate=_get_traces_sample_rate(),
        before_send=_before_send_set_release,
        **({"enable_logs": True} if _logs_enabled else {}),
    )
    ev = [0]
    _print_run_start_utc()
    # Show where events go so you can confirm the project in Sentry (Project Settings → Client Keys).
    try:
        from urllib.parse import urlparse
        parsed = urlparse(dsn)
        host = parsed.hostname or parsed.netloc
        project_id = (parsed.path or "").strip("/").split("/")[0] or "?"
        print(f"Seeded issues will belong to project ID: {project_id}  (ingest: {host})")
    except Exception:
        pass

    # --- Sentry Logs (structured, queryable). See https://docs.sentry.io/platforms/python/logs ---
    _sentry_logger.trace(
        "Seed variety run started",
        attributes={"seed_mode": "variety", "event_count": 0, "seed_utc": _utc_now_iso()},
    )
    _sentry_logger.debug("Releases and environments configured", attributes={"release_count": len(releases), "environment_count": len(environments)})

    # --- Messages (different levels) ---
    with _seed_transaction("Seed: Info message"):
        _sentry_logger.info("Seed message: info level")
        _set_release_and_capture(releases, environments, ev, "info", "Seed: Info message")
    with _seed_transaction("Seed: Warning message"):
        _sentry_logger.warning("Seed message: warning level", attributes={"seed_level": "warning"})
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
        _sentry_logger.info(
            "Checkout attempt for request {request_id} user {user_id} amount_cents {amount_cents}",
            request_id=rv["request_id"],
            user_id=rv["user_id"],
            amount_cents=rv["amount_cents"],
            attributes={
                "session_id": rv["session_id"],
                "correlation_id": rv["correlation_id"],
            },
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

    print("Flushing events to Sentry...")
    sentry_sdk.flush(timeout=5)
    print("Flush done. Check your Sentry project for the new issues.")


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

# Persistent issues: fixed fingerprints (no run_id). Every run adds events to the same issues.
# See https://docs.sentry.io/product/issues/grouping-and-fingerprints
PERSISTENT_ISSUE_KIND_KEYS: list[str] = [
    "validation-error",
    "file-missing",
    "service-timeout",
    "connection-refused",
    "rate-limit",
    "config-missing",
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
        **({"enable_logs": True} if _logs_enabled else {}),
    )
    run_id = str(uuid.uuid4())
    _print_run_start_utc()
    _sentry_logger.info(
        "Seed bulk run started: {issue_count} issues, {events_per_issue} events each",
        issue_count=issue_count,
        events_per_issue=events_per_issue,
        attributes={"seed_run_id": run_id, "seed_mode": "bulk", "seed_utc": _utc_now_iso()},
    )
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
            _apply_enrichment_for_event(global_event_idx)
            global_event_idx += 1
            rv = _random_values()
            try:
                message = msg_tpl.format(**rv)
            except KeyError:
                message = msg_tpl
            with _seed_transaction(transaction_name=f"Seed {kind_key} event {event_idx + 1}"):
                _sentry_logger.debug(
                    "Seed event started: issue_kind={issue_kind} event_index={event_index} request_id={request_id}",
                    issue_kind=kind_key,
                    event_index=event_idx + 1,
                    request_id=rv["request_id"],
                    attributes={
                        "seed_run_id": run_id,
                        "session_id": rv["session_id"],
                        "amount_cents": rv["amount_cents"],
                    },
                )
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
                        _sentry_logger.error(
                            "Seed event failed: issue_kind={issue_kind} request_id={request_id}",
                            issue_kind=kind_key,
                            request_id=rv["request_id"],
                            attributes={"seed_run_id": run_id, "event_index": event_idx + 1},
                        )
                        sentry_sdk.capture_exception()
            total_events += 1
        if (issue_idx + 1) % 5 == 0 or issue_idx == 0:
            print(f"  Issue {issue_idx + 1}/{issue_count} ({events_per_issue} events each)...")
    sentry_sdk.flush(timeout=15)
    print(
        f"Seeding complete. {issue_count} issues created ({total_events} events total, "
        f"{events_per_issue} events per issue), across {len(releases)} releases and {len(environments)} environments. Run again to add more issues."
    )


def seed_persistent_issues(
    dsn: str,
    releases: list[str],
    environments: list[str],
    events_per_run: int = 5,
) -> None:
    """Send events only to a fixed set of issues (same fingerprint every run).
    Use this to keep a few issues 'going' by adding new events to them on each run.
    First run creates the issues; subsequent runs add events to the same issues.
    See https://docs.sentry.io/product/issues/grouping-and-fingerprints
    """
    sentry_sdk.init(
        dsn=dsn,
        release=releases[0],
        environment=environments[0],
        traces_sample_rate=_get_traces_sample_rate(),
        before_send=_before_send_set_release,
        **({"enable_logs": True} if _logs_enabled else {}),
    )
    _print_run_start_utc()
    _sentry_logger.debug(
        "Persistent seed run started",
        attributes={"seed_mode": "persistent", "seed_utc": _utc_now_iso()},
    )
    kind_lookup = {k[0]: k for k in _ISSUE_KINDS}
    total_events = 0
    global_event_idx = 0
    for kind_key in PERSISTENT_ISSUE_KIND_KEYS:
        if kind_key not in kind_lookup:
            continue
        _, exc_cls, msg_tpl, level = kind_lookup[kind_key]
        # Fixed fingerprint: no run_id → same Issue every time (persistent).
        fingerprint = ["seed-persistent", kind_key]
        for event_idx in range(events_per_run):
            _current_release.set(releases[global_event_idx % len(releases)])
            _current_environment.set(environments[global_event_idx % len(environments)])
            _apply_enrichment_for_event(global_event_idx)
            global_event_idx += 1
            rv = _random_values()
            try:
                message = msg_tpl.format(**rv)
            except KeyError:
                message = msg_tpl
            with _seed_transaction(transaction_name=f"Seed persistent {kind_key} event {event_idx + 1}"):
                _sentry_logger.debug(
                    "Persistent seed event: issue_kind={issue_kind} event_index={event_index}",
                    issue_kind=kind_key,
                    event_index=event_idx + 1,
                    attributes={"seed_mode": "persistent"},
                )
                with sentry_sdk.configure_scope() as scope:
                    scope.fingerprint = fingerprint
                    scope.set_level(level)
                    scope.set_extra("event_index", event_idx + 1)
                    scope.set_extra("events_per_run", events_per_run)
                    scope.set_tag("seed_persistent", "true")
                    scope.set_tag("issue_kind", kind_key)
                    scope.set_tag("priority", level)
                    for key, value in rv.items():
                        scope.set_extra(f"random_{key}", value)
                    try:
                        _seed_stack_0(exc_cls, message)
                    except Exception:
                        _sentry_logger.error(
                            "Persistent seed event failed: issue_kind={issue_kind}",
                            issue_kind=kind_key,
                            attributes={"event_index": event_idx + 1},
                        )
                        sentry_sdk.capture_exception()
            total_events += 1
    sentry_sdk.flush(timeout=15)
    print(
        f"Persistent issues: added {total_events} events to {len(PERSISTENT_ISSUE_KIND_KEYS)} issues "
        f"({events_per_run} events per issue). Run again to add more events to the same issues."
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

    # Persistent issues: fixed fingerprints; each run only adds events to those same issues.
    if os.environ.get("SEED_PERSISTENT"):
        try:
            events_per_run = int(os.environ.get("SEED_PERSISTENT_EVENTS_PER_RUN", "5"))
        except ValueError:
            events_per_run = 5
        print(
            f"Persistent mode: adding events to {len(PERSISTENT_ISSUE_KIND_KEYS)} fixed issues "
            f"({events_per_run} events per issue per run)."
        )
        seed_persistent_issues(dsn, releases, environments, events_per_run=events_per_run)
        return

    if not _logs_enabled:
        _ver = getattr(sentry_sdk, "VERSION", "?")
        print(
            f"Sentry Logs: disabled (this Python has sentry-sdk {_ver}; need >=2.35.0). "
            f"Python: {sys.executable}"
        )
        print("  To enable logs, run with your venv:  .venv/bin/python seed_sentry_issues.py")
    else:
        print("Sentry Logs: enabled. View in Sentry: Explore → Logs (or your project’s Logs section).")

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
