# Sentry issue seeder

Seeds a Sentry project with various issue types (exceptions and messages) for testing and demos.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # or `.venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

## Usage

### Option 1: Use DSN (recommended)

Using the project DSN is the most reliable option and does not require API permissions on your token.

1. In Sentry: open your **project** → **Project Settings** (gear) → **Client Keys (DSN)**.
2. Copy the DSN (e.g. `https://abc123...@o123456.ingest.sentry.io/7890123`).
3. Run:

```bash
export SENTRY_DSN="https://YOUR_KEY@oXXXX.ingest.sentry.io/PROJECT_ID"
python seed_sentry_issues.py
```

### Option 2: Use auth token (API)

If your token has **project:read** (or similar) permission, the script can fetch the DSN via the Sentry API:

```bash
export SENTRY_AUTH_TOKEN="sntrys_..."
python seed_sentry_issues.py
```

If you get `403 You do not have permission to perform this action`, use **Option 1** (DSN) instead.

Optional env vars when using the token:

- **SENTRY_PROJECT** – project slug to target (default: first project in the org)
- **SENTRY_ORG** – org slug (default: decoded from token)

## What gets sent

- Messages at different levels: info, warning, error, fatal, debug
- Exceptions: `ValueError`, `TypeError`, `KeyError`, `RuntimeError`, `ZeroDivisionError`, `FileNotFoundError`, `ConnectionError`, `PermissionError`, `OSError`, `AssertionError`, `IndexError`, `AttributeError`
- One event with breadcrumbs and one with extra context/tags

After running, check your Sentry project for the new issues.
