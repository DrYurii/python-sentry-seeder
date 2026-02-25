#!/usr/bin/env bash
# Send a single FileNotFoundError event (e.g. to add one event to an existing issue).
# Usage: ./scripts/seed-one-event.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_setup.sh"
python3 add_events_to_issue.py
