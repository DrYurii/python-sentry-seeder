#!/usr/bin/env bash
# Variety seed: one-off set of different issue types (no bulk). Sends logs and traces.
# Usage: ./scripts/seed-variety.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_setup.sh"
SEED_COUNT=0 python3 seed_sentry_issues.py
