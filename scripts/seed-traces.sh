#!/usr/bin/env bash
# Seed data so traces (transactions + spans) appear in Sentry Trace View. Uses variety run.
# Usage: ./scripts/seed-traces.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_setup.sh"
SEED_COUNT=0 python3 seed_sentry_issues.py
