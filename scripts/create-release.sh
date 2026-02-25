#!/usr/bin/env bash
# Create a release in Sentry via API. Requires SENTRY_AUTH_TOKEN (and optionally SENTRY_ORG, SENTRY_PROJECT) in .env.
# Usage: ./scripts/create-release.sh
# Override: SENTRY_RELEASE="my-app@2.0.0" ./scripts/create-release.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_setup.sh"
python3 create_sentry_release.py
