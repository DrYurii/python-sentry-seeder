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
"""

import base64
import json
import os
import random
import string
import sys
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

    seed_issues(dsn)


if __name__ == "__main__":
    main()
