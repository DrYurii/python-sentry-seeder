#!/usr/bin/env python3
"""
Create a release in Sentry via the API.

Follows Sentry release naming: use package@version (e.g. seed-script@1.0.0).
See: https://docs.sentry.io/product/releases/naming-releases/
     https://docs.sentry.io/api/releases/create-a-new-release-for-an-organization

Requires SENTRY_AUTH_TOKEN with project:releases (or org-level equivalent).

Usage:
  export SENTRY_AUTH_TOKEN="sntrys_..."
  export SENTRY_ORG="your-org-slug"
  python3 create_sentry_release.py

  # Custom version (default: seed-script@1.0.0). Use package@version.
  SENTRY_RELEASE="my-app@2.3.0" python3 create_sentry_release.py

  # Optional: target project
  SENTRY_PROJECT="my-project" python3 create_sentry_release.py
"""

import base64
import json
import os
import re
import sys
from typing import Optional

import requests

# Sentry: release name cannot contain newlines, tabs, /, \, be "." or "..", or exceed 200 chars.
_RELEASE_NAME_MAX = 200
_FORBIDDEN_RELEASE_CHARS = re.compile(r"[\n\t/\\]")
_FORBIDDEN_RELEASE_WHOLE = frozenset({".", "..", " ", ""})


def normalize_release_version(value: str, default_package: str = "seed-script") -> str:
    """
    Normalize SENTRY_RELEASE to Sentry's recommended format (package@version).
    If value is only a semver (e.g. 1.0.0), prefix with default_package.
    """
    raw = value.strip()
    if not raw:
        return f"{default_package}@1.0.0"
    if "@" in raw:
        return raw
    return f"{default_package}@{raw}"


def validate_release_name(name: str) -> Optional[str]:
    """Return None if valid, else an error message."""
    if name in _FORBIDDEN_RELEASE_WHOLE or name.strip() == "":
        return "Release name cannot be '.' or '..' or empty."
    if _FORBIDDEN_RELEASE_CHARS.search(name):
        return "Release name cannot contain newlines, tabs, /, or \\."
    if len(name) > _RELEASE_NAME_MAX:
        return f"Release name cannot exceed {_RELEASE_NAME_MAX} characters."
    return None


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


def _resolve_project_slug(
    api_base: str, org: str, headers: dict, project_slug: Optional[str]
) -> Optional[str]:
    """Return project slug (from argument or first project in org)."""
    if project_slug:
        return project_slug
    r = requests.get(f"{api_base}/organizations/{org}/projects/", headers=headers, timeout=15)
    if not r.ok:
        print(f"API list projects failed: {r.status_code} {r.text[:300]}", file=sys.stderr)
        if r.status_code == 403:
            print("Token may need project:read and project:releases.", file=sys.stderr)
        return None
    projects = r.json()
    if not projects:
        print("No projects found.", file=sys.stderr)
        return None
    slug = projects[0].get("slug")
    if len(projects) > 1:
        print(f"Using first project: {slug}. Set SENTRY_PROJECT to pick another.", file=sys.stderr)
    return slug


def create_release(
    token: str,
    version: str,
    org_slug: Optional[str] = None,
    project_slug: Optional[str] = None,
) -> bool:
    """Create a release for the given org and project. Returns True on success."""
    payload = decode_sentry_token(token)
    region_url = (payload.get("region_url") or "https://us.sentry.io").rstrip("/")
    org = org_slug or payload.get("org")
    if not org:
        print("Could not determine org. Set SENTRY_ORG.", file=sys.stderr)
        return False

    api_base = region_url.replace("sentry.io", "sentry.io/api/0")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    resolved_project = _resolve_project_slug(api_base, org, headers, project_slug)
    if not resolved_project:
        return False

    err = validate_release_name(version)
    if err:
        print(f"Invalid release name: {err}", file=sys.stderr)
        return False

    url = f"{api_base}/organizations/{org}/releases/"
    body = {"version": version, "projects": [resolved_project]}
    r = requests.post(url, headers=headers, json=body, timeout=15)
    if not r.ok:
        print(f"Create release failed: {r.status_code} {r.text[:300]}", file=sys.stderr)
        if r.status_code == 403:
            print("Token needs scope: project:releases", file=sys.stderr)
        elif r.status_code == 409:
            print("Release already exists (version is unique per org).", file=sys.stderr)
        return False
    data = r.json()
    release_version = data.get("version", version)
    short_version = data.get("shortVersion") or ""
    project_slugs = [p.get("slug") for p in data.get("projects", [])]
    print(f"Release name: {release_version}")
    if short_version:
        print(f"Short version: {short_version}")
    print(f"Projects: {project_slugs}")
    return True


def main() -> None:
    token = os.environ.get("SENTRY_AUTH_TOKEN")
    if not token:
        print("Set SENTRY_AUTH_TOKEN (with project:releases).", file=sys.stderr)
        sys.exit(1)
    raw = os.environ.get("SENTRY_RELEASE") or "seed-script@1.0.0"
    version = normalize_release_version(raw)
    org = os.environ.get("SENTRY_ORG")
    project = os.environ.get("SENTRY_PROJECT")
    if not create_release(token, version, org_slug=org, project_slug=project):
        sys.exit(1)


if __name__ == "__main__":
    main()
