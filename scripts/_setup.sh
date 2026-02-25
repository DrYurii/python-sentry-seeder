# Shared setup: repo root, venv, deps, .env
# Source this from other scripts:  source "$(dirname "$0")/_setup.sh"
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [ ! -d ".venv" ]; then
  echo "Creating .venv..."
  python3 -m venv .venv
fi
# Activate so we use venv Python and pip
# shellcheck source=/dev/null
. "$ROOT/.venv/bin/activate"

# Install/refresh deps (idempotent)
pip install -q -r requirements.txt

# Load .env if present (SENTRY_DSN, SENTRY_AUTH_TOKEN, etc.)
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$ROOT/.env"
  set +a
fi
