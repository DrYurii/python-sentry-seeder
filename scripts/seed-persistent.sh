#!/usr/bin/env bash
# Persistent issues: add events to the same fixed set of issues (no new issues). Sends logs and traces.
# Usage: ./scripts/seed-persistent.sh
# Override: SEED_PERSISTENT_EVENTS_PER_RUN=10 ./scripts/seed-persistent.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_setup.sh"
SEED_PERSISTENT=1 python3 seed_sentry_issues.py
