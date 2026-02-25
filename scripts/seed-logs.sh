#!/usr/bin/env bash
# Seed data so structured logs appear in Sentry (Explore → Logs). Uses variety run (issues + logs).
# Usage: ./scripts/seed-logs.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_setup.sh"
SEED_COUNT=0 python3 seed_sentry_issues.py
