# Sentry issue seeder

Seeds a Sentry project with various issue types (exceptions and messages) for testing and demos.

## Setup

Use `python3` if your system doesn’t provide a `python` command (e.g. some Linux distros).

```bash
python -m venv .venv
# or: python3 -m venv .venv
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
# or: python3 seed_sentry_issues.py
```

### Option 2: Use auth token (API)

If your token has **project:read** (or similar) permission, the script can fetch the DSN via the Sentry API:

```bash
export SENTRY_AUTH_TOKEN="sntrys_..."
python seed_sentry_issues.py
# or: python3 seed_sentry_issues.py
```

If you get `403 You do not have permission to perform this action`, use **Option 1** (DSN) instead.

Optional env vars when using the token:

- **SENTRY_PROJECT** – project slug to target (default: first project in the org)
- **SENTRY_ORG** – org slug (default: decoded from token)

### Bulk seeding (default: 100 issues, 5 events per issue)

In Sentry, **events** with the same [fingerprint](https://docs.sentry.io/product/issues/grouping-and-fingerprints) are grouped into one **issue**. By default the script creates **100 issues** per run; each issue gets **5 events** that share one fingerprint, so each issue shows multiple events. Each run uses a new run ID so new issues are created (previous issues are not overwritten). Issues have mixed **priorities** (High / Medium / Low) based on event level ([docs](https://docs.sentry.io/product/issues/issue-priority)): `error`/`fatal` → High, `warning` → Medium, `info`/`debug` → Low.

```bash
export SENTRY_DSN="https://..."
python seed_sentry_issues.py
# Run again to add another 100 issues (each with 5 events):
python seed_sentry_issues.py
```

- **SEED_COUNT** – number of issues to create per run (default: `100`). Use `SEED_COUNT=0` for the one-off “variety” seed only.
- **SEED_EVENTS_PER_ISSUE** – number of events to send per issue (default: `5`). All share the same fingerprint so they group into one issue.
- **SENTRY_RELEASE** – base for **3 releases** per run (default: `seed-script@1.0.0`). The script derives 3 semantic versions (e.g. `1.0.0`, `1.1.0`, `2.0.0`) and distributes events across them so Sentry shows 3 releases. See `docs/features/releases.md` for naming (`package@version`).

```bash
SEED_COUNT=20 SEED_EVENTS_PER_ISSUE=10 python seed_sentry_issues.py
SENTRY_RELEASE="seed-script@2.0.0" python seed_sentry_issues.py   # releases: 2.0.0, 2.1.0, 3.0.0
SEED_COUNT=0 python seed_sentry_issues.py   # variety seed only
```

## What gets sent

- **Bulk mode (default):** Each run creates `SEED_COUNT` **issues**. Each issue gets `SEED_EVENTS_PER_ISSUE` **events** with the same fingerprint (so they appear as one issue with multiple events). Events are spread across **3 releases** per run (semantic versions derived from `SENTRY_RELEASE`). Issue kinds vary by exception type and **priority** (High/Medium/Low). Run again to add more issues.
- **Variety mode (SEED_COUNT=0):** One-off set of messages and exceptions, distributed across the same 3 releases.

After running, check your Sentry project: **Releases** lists 3 versions; each issue’s detail page shows multiple events and a release; the Issues stream shows mixed priorities.
