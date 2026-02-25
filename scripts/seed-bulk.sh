#!/usr/bin/env bash
# Bulk seed: create many issues (default 100), each with 5 events. Sends logs and traces.
# Usage: ./scripts/seed-bulk.sh
# Override: SEED_COUNT=20 SEED_EVENTS_PER_ISSUE=10 ./scripts/seed-bulk.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_setup.sh"
python3 seed_sentry_issues.py
