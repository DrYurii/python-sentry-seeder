# python-sentry Expansion Spec

<!-- Created: 2026-04-07 | Author: DrYurii (maat-re@proton.me) | Phase 4 of Schema Consolidation (NOV-1462) -->

This specification describes how the **python-sentry** companion repo should produce seed data that is directly consumable by Sentinel's State API. An implementing agent can follow this document end-to-end without needing additional context from the Sentinel codebase.

---

## 1. Background

### Sentinel seed pipeline

Sentinel seeds its SQLite database through a **State API** (`POST /api/state`) that accepts a JSON payload mapping entity names to arrays of records. There are three ways to produce that payload:

| Path | Description |
|------|-------------|
| `pnpm seed` | Generates synthetic data via `buildSeedPayload()` in `lib/seed/payload.ts` |
| `pnpm seed:fetch-reference` | Fetches real data from the Sentry REST API via `fetch-reference-seed.ts` |
| `pnpm seed --from-file <path>` | Loads a JSON file and applies it; merges mock identity data automatically |

The python-sentry repo should produce JSON files compatible with the third path (`--from-file`). Identity data (users, org, tokens) is **not** included — Sentinel's `seed.ts` merges it automatically from `lib/seed/mock-data.ts`.

### Current python-sentry data flow

```
python-sentry scripts (SDK ingest)
       │
       ▼ sentry_sdk.capture_exception / capture_message
  Sentry SaaS (issues, events, releases, traces, logs)
       │
       ▼ fetch-reference-seed.ts (or generate-seed.py from this spec)
  prisma/fetched-seed.json
       │
       ▼ pnpm seed --from-file
  Sentinel SQLite DB
```

### Existing python-sentry scripts

These scripts create data **in Sentry SaaS** via SDK ingest and REST API — they do not produce JSON files. They require no changes for schema consolidation since the Sentry SDK handles field serialization natively.

| Script | Purpose |
|--------|---------|
| `seed_sentry_issues.py` | Seed issues into Sentry via SDK (`capture_exception` / `capture_message`) |
| `create_sentry_release.py` | Create releases via REST API (`POST /releases/`) |
| `add_events_to_issue.py` | Send a single FileNotFoundError event via SDK |
| `scripts/seed-bulk.sh` | Wrapper: bulk seed (100 issues, 5 events each) |
| `scripts/seed-variety.sh` | Wrapper: variety seed (one-off issue types) |
| `scripts/seed-persistent.sh` | Wrapper: persistent issues (fixed fingerprints) |
| `scripts/seed-logs.sh` | Wrapper: structured logs |
| `scripts/seed-traces.sh` | Wrapper: traces (transactions + spans) |

The new `generate-seed.py` script (Section 7) is the only addition needed — it **fetches** existing data from Sentry REST API and writes it as StatePayload JSON.

---

## 2. Feed All filters and SDK seed enrichment

This section merges the former `docs/feed-all-filter-matrix.md` and `docs/feed-all-seed-enrichment-guide.md`. It documents Sentinel **Feed → All** filter keys (`age` through `geo.subdivision`), how they map to Sentry payloads, and how `seed_sentry_issues.py` should populate them before fetch → State API.

### 2.1 Goal

Create Sentry issues/events that populate every searchable field in Feed All–tab scope (`age` through `geo.*`), so Sentinel can fetch and replay that data locally without losing filter-critical attributes.

### 2.2 Sentinel source of truth (key order / query mapping)

In the Sentinel repo:

- `lib/filter-registry/filter-keys.ts` (key order/types)
- `lib/filter-registry/issue-filters.ts` and `lib/filter-registry/event-filters.ts` (connectors/defaults)
- `lib/search/issue-parser.ts`, `lib/search/event-sql-builder.ts`, `lib/search/event-matcher.ts` (query mapping)

### 2.3 Filter key matrix (`age` → `geo.subdivision`)

| Key | Type | Connectors | Sentinel mapping (storage/query) | Sentry payload path to seed |
| --- | ---- | ---------- | --------------------------------- | --------------------------- |
| `age` | `date` | date ops | alias of Issue `firstSeen` | issue `firstSeen` |
| `assigned` | `string` | `is`, `is not` | Issue `assignedToId` / `assignedToTeamId` | issue `assignedTo` |
| `assigned_or_suggested` | `string` | `is`, `is not` | currently same as `assigned` | issue `assignedTo` |
| `bookmarks` | `string` | `is`, `is not` | `IssueBookmark.userId -> issueId` relation | issue bookmark state (`isBookmarked`) |
| `firstRelease` | `string` | extended string | Issue `firstReleaseVersion` | issue `firstRelease.version` |
| `firstSeen` | `date` | date ops | Issue `firstSeen` | issue `firstSeen` |
| `has` | `string` | key-style has/does not have | event existence in columns/tags/context | event tag/context key presence |
| `is` | `string` | key-style is/is not | status/substatus/link/assignment mapping | issue `status`/`substatus` and related data |
| `issue` | `string` | `is`, `is not` | Issue `shortId` | issue `shortId` |
| `issue.category` | `string` | `is`, `is not` | Issue `category` | issue `issueCategory` |
| `issue.priority` | `string` | `is`, `is not` | Issue `priority` | issue `priority` |
| `issue.type` | `string` | `is`, `is not` | Issue `type` | issue `type` |
| `lastSeen` | `date` | date ops | Issue `lastSeen` | issue `lastSeen` |
| `timesSeen` | `number` | numeric ops | Issue `count` | issue `count` |
| `app.in_foreground` | `boolean` | `is`, `is not` | event context lookup | `contexts.app.in_foreground` |
| `device.arch` | `string` | extended string | event context lookup | `contexts.device.arch` |
| `device.brand` | `string` | extended string | event context lookup | `contexts.device.brand` |
| `device.class` | `string` | extended string | event tags lookup (`1`/`2`/`3` normalized) | tags `device.class` |
| `device.family` | `string` | extended string | event tags lookup | tags `device.family` |
| `device.locale` | `string` | extended string | event context lookup | `contexts.device.locale` |
| `device.model` | `string` | extended string | event tags lookup | tags `device.model` |
| `device.model_id` | `string` | extended string | event context lookup | `contexts.device.model_id` |
| `device.name` | `string` | extended string | event context lookup | `contexts.device.name` |
| `device.orientation` | `string` | extended string | event context lookup | `contexts.device.orientation` |
| `device.uuid` | `string` | extended string | event context lookup | `contexts.device.uuid` |
| `dist` | `string` | extended string | event tags lookup | tags `dist` |
| `error.handled` | `boolean` | `is`, `is not` | exception values boolean lookup | `exception.values[].mechanism.handled` |
| `error.main_thread` | `boolean` | `is`, `is not` | exception values boolean lookup | `exception.values[].main_thread` |
| `error.mechanism` | `string` | extended string | exception values string lookup | `exception.values[].mechanism.type` |
| `error.type` | `string` | extended string | exception values string lookup | `exception.values[].type` |
| `error.unhandled` | `boolean` | `is`, `is not` | inverse of handled | derived from `mechanism.handled` |
| `error.value` | `string` | extended string | exception values string lookup | `exception.values[].value` |
| `event.timestamp` | `date` | date ops | Event `dateCreated` | event `dateCreated`/timestamp |
| `event.type` | `string` | extended string | Event `type` | event `type` (`error`, `transaction`, etc.) |
| `geo.city` | `string` | extended string | event tags/context + fallback | `geo.city` or `user.geo.city` |
| `geo.country_code` | `string` | extended string | event tags/context + fallback | `geo.country_code` or `user.geo.country_code` |
| `geo.region` | `string` | extended string | event tags/context + fallback | `geo.region` or `user.geo.region` |
| `geo.subdivision` | `string` | extended string | event tags/context + fallback | `geo.subdivision` or `user.geo.subdivision` |

### 2.4 Payload rules (ideal coverage)

- Include at least one issue per project with **explicit assignee user**, **explicit assignee team**, and **unassigned** states (SDK ingest alone cannot set these; use Sentry UI/API or post-fetch transforms).
- Include bookmark state on a subset of issues (bookmarked + not bookmarked).
- For each issue, send **multiple events** with varied event contexts/tags so event-level filters can diverge within the same issue.
- Include both `geo.*` tags and nested `user.geo.*` across samples to validate fallback behavior.
- Keep values realistic and repeated enough to produce meaningful query result sets.

### 2.5 Example values and validation queries

| Filter key | Sentry payload/source | Realistic values to generate | Validation queries |
| ---------- | --------------------- | ---------------------------- | ------------------ |
| `age` | issue `firstSeen` | now-1h, now-2d, now-14d | `age:-24h`, `age:+7d` |
| `assigned` | issue `assignedTo` | current user, `#backend`, unassigned | `assigned:me`, `assigned:#backend`, `assigned:none` |
| `assigned_or_suggested` | issue `assignedTo` (current Sentinel behavior) | same as `assigned` | `assigned_or_suggested:me` |
| `bookmarks` | issue bookmark state | bookmarked by current user, not bookmarked | `bookmarks:me` |
| `firstRelease` | issue `firstRelease.version` | `myapp@1.0.0`, `myapp@2.1.0`, `web@2026.03.11` | `firstRelease:myapp@1.0.0` |
| `firstSeen` | issue `firstSeen` | now-6h, now-3d, now-30d | `firstSeen:-7d` |
| `has` | event context/tag key presence | include/exclude keys: `device.uuid`, `geo.city`, `error.value` | `has:geo.city`, `!has:device.uuid` |
| `is` | issue `status`/`substatus`/link state | unresolved/new, unresolved/escalating, resolved, ignored | `is:unresolved`, `is:escalating`, `!is:archived` |
| `issue` | issue `shortId` | `API-101`, `WEB-42`, `MOB-7` | `issue:API-101` |
| `issue.category` | issue `issueCategory` | `error`, `outage`, `metric`, `frontend`, `mobile` | `issue.category:error` |
| `issue.priority` | issue `priority` | `high`, `medium`, `low` | `issue.priority:[high,medium]` |
| `issue.type` | issue `type` | `error`, `feedback`, `metric_issue`, `uptime_domain_failure` | `issue.type:error` |
| `lastSeen` | issue `lastSeen` | now-5m, now-2h, now-3d | `lastSeen:-24h` |
| `timesSeen` | issue `count` | 1, 8, 57, 1200 | `timesSeen:>100` |
| `app.in_foreground` | `contexts.app.in_foreground` | `true`, `false` | `app.in_foreground:true` |
| `device.arch` | `contexts.device.arch` | `arm64`, `x86_64`, `x86` | `device.arch:arm64` |
| `device.brand` | `contexts.device.brand` | `Apple`, `Samsung`, `Google` | `device.brand:Apple` |
| `device.class` | tags `device.class` | `1`, `2`, `3` (query as low/medium/high) | `device.class:high` |
| `device.family` | tags `device.family` | `iPhone`, `Galaxy`, `Pixel` | `device.family:iPhone` |
| `device.locale` | `contexts.device.locale` | `en_US`, `en_GB`, `de_DE`, `pt_BR` | `device.locale:en_US` |
| `device.model` | tags `device.model` | `iPhone15,2`, `SM-S908B`, `Pixel 8` | `device.model:*Pixel*` |
| `device.model_id` | `contexts.device.model_id` | `iPhone15,2`, `GVU6C`, `sdk_gphone_x86` | `device.model_id:iPhone15,2` |
| `device.name` | `contexts.device.name` | `iPhone 15 Pro`, `Galaxy S23 Ultra`, `Pixel 8` | `device.name:*iPhone*` |
| `device.orientation` | `contexts.device.orientation` | `portrait`, `landscape` | `device.orientation:portrait` |
| `device.uuid` | `contexts.device.uuid` | UUIDv4-like strings | `has:device.uuid` |
| `dist` | tags `dist` | `1001`, `2001`, `beta`, `rc1` | `dist:beta`, `!has:dist` |
| `error.handled` | `exception.values[].mechanism.handled` | true, false | `error.handled:1`, `error.handled:0` |
| `error.main_thread` | `exception.values[].main_thread` | true, false | `error.main_thread:true` |
| `error.mechanism` | `exception.values[].mechanism.type` | `generic`, `onerror`, `instrument` | `error.mechanism:onerror` |
| `error.type` | `exception.values[].type` | `TypeError`, `ReferenceError`, `RuntimeError` | `error.type:*Error` |
| `error.unhandled` | inverse of handled | 1 for unhandled, 0 for handled | `error.unhandled:1` |
| `error.value` | `exception.values[].value` | timeout message, null deref message, connection error | `error.value:*timeout*` |
| `event.timestamp` | event timestamp/dateCreated | now-2m, now-20m, now-12h | `event.timestamp:-24h` |
| `event.type` | event `type` | `error`, `transaction` (plus optional `csp`) | `event.type:error`, `event.type:transaction` |
| `geo.city` | tag/context `geo.city` or `user.geo.city` | Miami, Berlin, Recife, Tokyo | `geo.city:Recife` |
| `geo.country_code` | tag/context `geo.country_code` or `user.geo.country_code` | US, DE, BR, JP | `geo.country_code:[US,BR]` |
| `geo.region` | tag/context `geo.region` or `user.geo.region` | United States, Germany, Pernambuco, Tokyo Prefecture | `geo.region:*Germany*` |
| `geo.subdivision` | tag/context `geo.subdivision` or `user.geo.subdivision` | California, Ontario, Pernambuco, Bayern | `geo.subdivision:California` |

### 2.6 `seed_sentry_issues.py` (this repo)

`seed_sentry_issues.py` populates **event-level** Feed All fields (device, app, geo, os, browser, dist, error mechanism/handled/main_thread) on variety, bulk, and persistent runs. Transaction names use HTTP-style paths where appropriate (see **§4.6 Event**). **Issue-level** fields such as assignee, bookmarks, and status/substatus variety are **not** set by the script; set them in Sentry or in generated State JSON.

### 2.7 End-to-end validation (Sentinel)

- Run `pnpm seed:fetch-sentry` (or `generate-seed.py` per **§7**) and inspect output for `Issue`, `Event`, `IssueBookmark`, and assignee fields.
- Run `pnpm prisma:seed` / `pnpm seed --from-file` as applicable.
- Validate query samples in Feed search.
- Run `pnpm check` and `pnpm test`.

State API field shapes for merged `contexts` / `tags` on events are detailed under **§4.6 Event** (enrichment tables).

---

## 3. Target JSON Format (StatePayload)

The output file must be a single JSON object where each key is a Prisma model name and each value is an array of records.

```json
{
  "Project": [ ... ],
  "Team": [ ... ],
  "TeamProject": [ ... ],
  "ProjectEnvironment": [ ... ],
  "Issue": [ ... ],
  "Event": [ ... ],
  "IssueHash": [ ... ],
  "IssueBookmark": [ ... ],
  "TagValue": [ ... ],
  "Release": [ ... ],
  "ProjectRelease": [ ... ],
  "AlertRule": [ ... ],
  "SentryAppInstallation": [ ... ],
  "ExternalIssue": [ ... ]
}
```

### Entity keys NOT to include

The following are auto-merged by `seed.ts` from the mock base. Do **not** include them:

- `AppConfiguration`
- `User`
- `Organization`
- `OrganizationMember`
- `OrganizationToken`
- `TeamMember`
- `TeamMemberRequest`

### Auto-derived entities

If **`ProjectEnvironment`** is omitted, `seed.ts` will auto-derive it from `Event.environment` values. Including it explicitly is preferred for deterministic output.

---

## 4. Field-by-Field Entity Schemas

All string IDs must be strings (not numbers). All dates must be ISO 8601 strings. JSON-valued fields (e.g., `metadata`, `contexts`, `tags`) must be **JSON-encoded strings**, not raw objects.

### 4.1 Project

```json
{
  "id": "4510828451528704",
  "organizationId": "org-sentinel-demo",
  "slug": "python",
  "name": "python",
  "platform": "python",
  "dateCreated": "2026-02-04T15:45:03.150Z",
  "isBookmarked": false,
  "hasReleases": true,
  "hasLogs": false
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Use Sentry's numeric project ID as a string |
| `organizationId` | string | yes | Must be `"org-sentinel-demo"` (mock org ID) |
| `slug` | string | yes | |
| `name` | string | yes | |
| `platform` | string \| null | no | e.g. `"python"`, `"javascript-react"` |
| `dateCreated` | string (ISO 8601) | yes | |
| `isBookmarked` | boolean | no | Defaults to `false` |
| `hasReleases` | boolean | no | Set `true` if releases exist for this project |
| `hasLogs` | boolean | no | Set `true` if log events exist for this project |

### 4.2 Team

```json
{
  "id": "7891",
  "slug": "backend",
  "name": "#backend",
  "organizationId": "org-sentinel-demo",
  "openMembership": false,
  "defaultRole": "member"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | |
| `slug` | string | yes | |
| `name` | string | yes | Use Sentry's real name (often `#slug`) |
| `organizationId` | string | yes | Must be `"org-sentinel-demo"` |
| `openMembership` | boolean | no | Defaults to `false` |
| `defaultRole` | string | no | Defaults to `"member"` |

### 4.3 TeamProject

Derived from Project-Team associations.

```json
{
  "id": "tp-7891-4510828451528704",
  "teamId": "7891",
  "projectId": "4510828451528704"
}
```

### 4.4 ProjectEnvironment

One record per (project, environment) pair observed in events.

```json
{
  "id": "pe_1",
  "projectId": "4510828451528704",
  "name": "production",
  "isHidden": false
}
```

### 4.5 Issue

```json
{
  "id": "6177543890",
  "shortId": "PYTHON-3K",
  "title": "ValueError: Validation failed for request req_42345",
  "culprit": "seed_sentry_issues._seed_stack_0",
  "level": "error",
  "status": "unresolved",
  "substatus": "ongoing",
  "platform": "python",
  "type": "error",
  "metadata": "{\"type\":\"ValueError\",\"value\":\"Validation failed...\"}",
  "numComments": 0,
  "userCount": 3,
  "count": 5,
  "isPublic": false,
  "hasSeen": false,
  "priority": "high",
  "issueCategory": "error",
  "logger": null,
  "isSubscribed": false,
  "assignedToId": null,
  "firstRelease": "seed-script@1.0.0",
  "lastRelease": "seed-script@1.1.0",
  "lastTransaction": null,
  "firstSeen": "2026-03-10T12:00:00.000Z",
  "lastSeen": "2026-03-11T14:30:00.000Z",
  "projectId": "4510828451528704",
  "organizationId": "org-sentinel-demo"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Sentry issue ID as string |
| `shortId` | string \| null | no | e.g. `"PYTHON-3K"` |
| `title` | string | yes | |
| `culprit` | string \| null | no | |
| `level` | string \| null | no | `"fatal"`, `"error"`, `"warning"`, `"info"`, `"debug"` |
| `status` | string | yes | `"unresolved"`, `"resolved"`, `"ignored"` |
| `substatus` | string \| null | no | `"new"`, `"ongoing"`, `"escalating"`, `"regressed"` |
| `platform` | string \| null | no | |
| `type` | string \| null | no | `"error"`, `"default"` |
| `metadata` | string \| null | no | **JSON-encoded string** of the metadata object |
| `numComments` | number | no | Defaults to `0` |
| `userCount` | number | no | |
| `count` | number | yes | **Must be a number**, not a string (Sentry API may return string) |
| `isPublic` | boolean | no | |
| `hasSeen` | boolean | no | |
| `priority` | string \| null | no | `"high"`, `"medium"`, `"low"` |
| `issueCategory` | string \| null | no | `"error"`, `"performance"`, `"replay"`, etc. |
| `logger` | string \| null | no | |
| `isSubscribed` | boolean | no | |
| `assignedToId` | string \| null | no | Set to `null` — mock users don't map to Sentry users |
| `firstRelease` | string \| null | no | **Version string** (extract `.version` from the API object) |
| `lastRelease` | string \| null | no | **Version string** |
| `lastTransaction` | string \| null | no | |
| `firstSeen` | string (ISO 8601) | yes | |
| `lastSeen` | string (ISO 8601) | yes | |
| `projectId` | string | yes | FK to Project |
| `organizationId` | string | yes | Must be `"org-sentinel-demo"` |

#### Issue-level data variety for search filter coverage

To make Sentinel's Feed search filters testable, seed issues with varied values for these fields:

| Filter key | Issue field | Values to include |
|------------|------------|-------------------|
| `is` | `status` / `substatus` | `"unresolved"/"new"`, `"unresolved"/"ongoing"`, `"unresolved"/"escalating"`, `"resolved"/null`, `"ignored"/null` |
| `issue.category` | `issueCategory` | `"error"`, `"performance"`, `"replay"` |
| `issue.priority` | `priority` | `"high"`, `"medium"`, `"low"` |
| `issue.type` | `type` | `"error"`, `"default"` |
| `assigned` | `assignedToId` | At least one issue with non-null value, and several with `null` |
| `bookmarks` | via `IssueBookmark` | At least one bookmarked issue and several non-bookmarked |
| `firstRelease` | `firstRelease` | Multiple distinct version strings |
| `timesSeen` | `count` | Range of values: `1`, `8`, `57`, `1200` |
| `firstSeen` / `lastSeen` / `age` | `firstSeen`, `lastSeen` | Varied timestamps spanning hours to weeks |

### 4.6 Event

```json
{
  "id": "evt-001",
  "eventID": "abc123def456789000000000deadbeef",
  "title": "ValueError: Validation failed",
  "message": "",
  "level": "error",
  "platform": "python",
  "type": "error",
  "contexts": "{\"browser\":{},\"os\":{},\"trace\":{\"trace_id\":\"abc\",\"span_id\":\"def\"}}",
  "tags": "{\"environment\":\"production\",\"level\":\"error\",\"release\":\"1.0.0\"}",
  "release": "seed-script@1.0.0",
  "transaction": "/api/checkout",
  "duration": null,
  "environment": "production",
  "dateCreated": "2026-03-10T12:00:00.000Z",
  "dateReceived": "2026-03-10T12:00:01.000Z",
  "projectId": "4510828451528704",
  "issueId": "6177543890"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Unique event ID |
| `eventID` | string | yes | Hex event ID from Sentry (**uppercase D**) |
| `title` | string \| null | no | |
| `message` | string \| null | no | |
| `level` | string \| null | no | |
| `platform` | string \| null | no | |
| `type` | string \| null | no | `"error"`, `"transaction"`, `"default"`, `"log"` |
| `contexts` | string \| null | no | **JSON-encoded string** — merge `contexts`, `entries`, `user`, `request`, `response` from API into one object |
| `tags` | string \| null | no | **JSON-encoded string** of `Record<string, string>` — flatten Sentry's `[{key, value}]` array |
| `release` | string \| null | no | Version string |
| `transaction` | string \| null | no | Transaction name |
| `duration` | number \| null | no | Milliseconds (`(endTimestamp - startTimestamp) * 1000` for transactions) |
| `environment` | string \| null | no | e.g. `"production"`, `"staging"` |
| `dateCreated` | string (ISO 8601) | yes | |
| `dateReceived` | string (ISO 8601) | no | |
| `projectId` | string | yes | FK to Project |
| `issueId` | string \| null | no | FK to Issue (null for standalone transactions/logs) |

**Transaction/trace event extra fields** (all optional, null for error events):

| Field | Type | Notes |
|-------|------|-------|
| `spanOp` | string \| null | e.g. `"http.server"`, `"db"` |
| `spanStatus` | string \| null | e.g. `"ok"`, `"internal_error"` |
| `spanDescription` | string \| null | e.g. `"SELECT * FROM users"` |
| `selfTime` | number \| null | Milliseconds |
| `spanCategory` | string \| null | |
| `spanAction` | string \| null | |
| `spanDomain` | string \| null | |
| `replayId` | string \| null | |
| `profileId` | string \| null | |
| `traceSampled` | boolean | Defaults to `false` |
| `samplingFactor` | number \| null | |

#### Event contexts/tags enrichment for search filter coverage

When seeding events via `seed_sentry_issues.py`, include these contexts and tags so that Sentinel's Feed search filters work end-to-end. The `contexts` JSON string should contain the nested objects below; `tags` should contain the flat key-value pairs.

**`contexts` object keys to populate:**

| Context path | Example values | Filter key |
|-------------|----------------|------------|
| `app.in_foreground` | `true`, `false` | `app.in_foreground` |
| `device.arch` | `"arm64"`, `"x86_64"` | `device.arch` |
| `device.brand` | `"Apple"`, `"Samsung"`, `"Google"` | `device.brand` |
| `device.locale` | `"en_US"`, `"de_DE"`, `"pt_BR"` | `device.locale` |
| `device.model_id` | `"iPhone15,2"`, `"GVU6C"` | `device.model_id` |
| `device.name` | `"iPhone 15 Pro"`, `"Galaxy S23 Ultra"` | `device.name` |
| `device.orientation` | `"portrait"`, `"landscape"` | `device.orientation` |
| `device.uuid` | UUIDv4 strings | `has:device.uuid` |
| `os.name` | `"macOS"`, `"iOS"`, `"Android"` | — |
| `browser.name` | `"Chrome"`, `"Safari"` | — |
| `trace.trace_id` | hex string | trace linkage |
| `trace.span_id` | hex string | trace linkage |

**`tags` flat keys to populate:**

| Tag key | Example values | Filter key |
|---------|----------------|------------|
| `environment` | `"production"`, `"staging"`, `"development"` | environment filter |
| `level` | `"error"`, `"warning"`, `"info"` | — |
| `release` | `"myapp@1.0.0"` | — |
| `dist` | `"1001"`, `"beta"`, `"rc1"` | `dist` |
| `device.family` | `"iPhone"`, `"Galaxy"`, `"Pixel"` | `device.family` |
| `device.model` | `"iPhone15,2"`, `"SM-S908B"` | `device.model` |
| `device.class` | `"1"`, `"2"`, `"3"` | `device.class` |
| `geo.city` | `"Miami"`, `"Berlin"`, `"Tokyo"` | `geo.city` |
| `geo.country_code` | `"US"`, `"DE"`, `"JP"` | `geo.country_code` |
| `geo.region` | `"California"`, `"Bayern"` | `geo.region` |
| `geo.subdivision` | `"California"`, `"Ontario"` | `geo.subdivision` |

**Error-level enrichment** (in exception entries within `contexts`):

| Path | Example values | Filter key |
|------|----------------|------------|
| `exception.values[].type` | `"TypeError"`, `"RuntimeError"` | `error.type` |
| `exception.values[].value` | `"timeout"`, `"null reference"` | `error.value` |
| `exception.values[].mechanism.type` | `"generic"`, `"onerror"` | `error.mechanism` |
| `exception.values[].mechanism.handled` | `true`, `false` | `error.handled` |
| `exception.values[].main_thread` | `true`, `false` | `error.main_thread` |

Vary values across events within the same issue so that event-level filter queries return meaningful subsets.

### 4.7 IssueHash

One record per issue. Hash is a 32-character hex fingerprint.

```json
{
  "id": "ih-6177543890",
  "issueId": "6177543890",
  "hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
  "latestEvent": "evt-001",
  "sourceIssueId": null
}
```

Generate the hash by SHA-256 hashing the issue ID and taking the first 32 hex characters:

```python
import hashlib
hash = hashlib.sha256(issue_id.encode()).hexdigest()[:32]
```

### 4.8 IssueBookmark

Only include if the issue is bookmarked (`isBookmarked: true` from Sentry API).

```json
{
  "id": "bookmark-6177543890",
  "issueId": "6177543890",
  "userId": "user_2",
  "projectId": "4510828451528704"
}
```

`userId` should always be `"user_2"` (the default logged-in mock user).

### 4.9 TagValue

Environment tag values per project, derived from event data.

```json
{
  "id": "tv_1",
  "key": "environment",
  "value": "production",
  "count": 42,
  "firstSeen": "2026-03-10T12:00:00.000Z",
  "lastSeen": "2026-03-11T14:30:00.000Z",
  "projectId": "4510828451528704"
}
```

Build by scanning events: for each unique `(projectId, environment)` pair, count occurrences and track first/last `dateCreated`.

### 4.10 Release

```json
{
  "id": "12345",
  "organizationId": "org-sentinel-demo",
  "version": "seed-script@1.0.0",
  "shortVersion": "1.0.0",
  "status": "open",
  "dateCreated": "2026-03-10T12:00:00.000Z",
  "firstEvent": "2026-03-10T12:00:00.000Z",
  "lastEvent": "2026-03-11T14:30:00.000Z",
  "newGroups": 5
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Sentry release ID **coerced to string** (API returns numeric) |
| `organizationId` | string | yes | Must be `"org-sentinel-demo"` |
| `version` | string | yes | Full version string |
| `shortVersion` | string \| null | no | Part after `@` if present |
| `status` | string | no | `"open"` or `"archived"` |
| `dateCreated` | string (ISO 8601) | yes | |
| `firstEvent` | string (ISO 8601) \| null | no | |
| `lastEvent` | string (ISO 8601) \| null | no | |
| `newGroups` | number | no | Defaults to `0` |

### 4.11 ProjectRelease

One record per (project, release) association. Derived from `Release.projects[]`.

```json
{
  "id": "pr-1",
  "projectId": "4510828451528704",
  "releaseId": "12345"
}
```

### 4.12 AlertRule

```json
{
  "id": "456",
  "name": "High Error Rate",
  "type": "issue",
  "status": "active",
  "dateCreated": "2026-03-10T12:00:00.000Z",
  "environment": "production",
  "frequency": 30,
  "actionMatch": "all",
  "filterMatch": "all",
  "conditions": "[{\"id\":\"sentry.rules.conditions.first_seen_event\"}]",
  "actions": "[{\"id\":\"sentry.mail.actions.NotifyEmailAction\"}]",
  "filters": null,
  "triggers": null,
  "projectId": "4510828451528704",
  "organizationId": "org-sentinel-demo"
}
```

- `type`: `"issue"` for issue alert rules, `"metric"` for metric alert rules, `"uptime"` for uptime monitors
- `conditions`, `actions`, `filters`, `triggers`: **JSON-encoded strings** of arrays
- For metric alerts: `status` is a **number** in the Sentry API (0 = active) — convert to string `"active"` / `"inactive"`

### 4.13 SentryAppInstallation / ExternalIssue

Include empty arrays if none exist:

```json
{
  "SentryAppInstallation": [],
  "ExternalIssue": []
}
```

---

## 5. Constants and IDs

### Organization ID

Always use: `"org-sentinel-demo"`

This is the mock organization ID from `lib/seed/mock-data.ts`. All `organizationId` fields must reference this value. The actual org record is auto-merged by `seed.ts`.

### User ID for bookmarks

Always use: `"user_2"` (the default logged-in user in mock data).

### ID generation

- **Sentry-provided IDs**: Use them as-is (coerced to string). This includes: `Project.id`, `Team.id`, `Issue.id`, `Release.id`, `AlertRule.id`.
- **Synthetic IDs**: Generate for derived entities with a consistent prefix: `tp-{teamId}-{projectId}` for TeamProject, `ih-{issueId}` for IssueHash, `pe_{idx}` for ProjectEnvironment, `tv_{idx}` for TagValue, `pr-{idx}` for ProjectRelease, `bookmark-{issueId}` for IssueBookmark.

---

## 6. Data Transformation Rules

### JSON string encoding

Sentry returns objects/arrays for certain fields. Sentinel stores these as JSON-encoded strings:

| Sentry API field | Sentinel field | Transform |
|------------------|---------------|-----------|
| `Issue.metadata` (object) | `metadata` | `json.dumps(metadata)` |
| `Event.contexts` + `entries` + `user` + `request` (objects) | `contexts` | Merge into one object, then `json.dumps(merged)` |
| `Event.tags` (array of `{key, value}`) | `tags` | Flatten to `{key: value, ...}`, then `json.dumps(flat)` |
| `AlertRule.conditions` (array) | `conditions` | `json.dumps(conditions)` |
| `AlertRule.actions` (array) | `actions` | `json.dumps(actions)` |
| `AlertRule.filters` (array) | `filters` | `json.dumps(filters)` |
| `AlertRule.triggers` (array) | `triggers` | `json.dumps(triggers)` |

### Type coercions

| Field | Sentry type | Sentinel type | Rule |
|-------|------------|---------------|------|
| `Issue.count` | string or number | number (Int) | `int(count)` |
| `Release.id` | number | string | `str(id)` |
| `Issue.firstRelease` | object `{version}` | string | Extract `.version` |
| `Issue.lastRelease` | object `{version}` | string | Extract `.version` |
| `AlertRule.status` (metric) | number | string | `0` → `"active"`, else `"inactive"` |

### Fields to omit or set to null

- `Issue.assignedToId`: Set to `null` (mock users don't correspond to Sentry users)
- `Issue.assignedToTeamId`: Set to `null`
- `Issue.resolvedById`: Set to `null`
- `Issue.reviewedById`: Set to `null`

---

## 7. Script Requirements

### 7.1 Primary script: `generate-seed.py`

Create a Python script that:

1. Accepts CLI arguments matching `fetch-reference-seed.ts`:
   - `--org` (default: env `SENTRY_ORG` or `"blue-ridge-systems"`)
   - `--project` (filter to specific project slug)
   - `--limit` (max issues per project, default: 1000)
   - `--events-per-issue` (max events per issue, default: 5)
   - `--output` (output path, default: `prisma/fetched-seed.json`)
   - `--query` (Sentry search query filter)

2. Fetches data from Sentry REST API:
   - Organization details
   - All projects (or filtered by `--project`)
   - All teams
   - Releases (limit 100)
   - Environments
   - Issues per project (with pagination)
   - Events per issue
   - Alert rules (issue + metric)

3. Transforms data per Section 6 rules

4. Outputs a single JSON file matching Section 3 format

### 7.2 Authentication

Use `SENTRY_AUTH_TOKEN` environment variable (Bearer token). Same as the existing TypeScript fetch script.

```python
import os
token = os.environ["SENTRY_AUTH_TOKEN"]
headers = {"Authorization": f"Bearer {token}"}
```

### 7.3 Pagination

Sentry uses cursor-based pagination via the `Link` header. Parse the `next` cursor:

```python
def parse_next_cursor(link_header: str) -> str | None:
    # Parse Link header for rel="next"; results="true"
    ...
```

### 7.4 Example usage

```bash
# Fetch all projects
export SENTRY_AUTH_TOKEN="sntrys_..."
python generate-seed.py --output prisma/fetched-seed.json

# Fetch only Python project, small dataset
python generate-seed.py --project python --limit 20 --events-per-issue 2

# Apply in Sentinel
cd /path/to/sentinel
pnpm seed --from-file 'prisma/fetched-seed.json'
```

---

## 8. Relationship to Existing Files

### `sentry-full.json`

If a `sentry-full.json` already exists in the python-sentry repo, it was likely produced by an older format. The new script should replace it with output matching this spec. The old file can be deleted.

### `SEED_SPAN_NAMES` / `_SEED_SPAN_NAMES`

Sentinel's synthetic seed (`lib/seed/payload.ts`) references `python-sentry`'s `_SEED_SPAN_NAMES` for trace span names:

```
validate, load, parse, transform, process, resolve, execute, commit, finalize, run
```

If the python-sentry SDK ingest scripts generate traces, use these same span names for consistency with synthetic seed data.

---

## 9. Validation Checklist

After generating a seed file, verify:

- [ ] All `organizationId` values are `"org-sentinel-demo"`
- [ ] All IDs are strings (not numbers)
- [ ] `metadata`, `contexts`, `tags`, `conditions`, `actions`, `filters`, `triggers` are JSON-encoded strings (not raw objects)
- [ ] `Issue.count` is a number (not a string)
- [ ] `Release.id` is a string (Sentry returns numeric)
- [ ] `Issue.firstRelease` / `lastRelease` are version strings (not objects)
- [ ] No `User`, `Organization`, `AppConfiguration`, `OrganizationMember`, `OrganizationToken`, `TeamMember`, or `TeamMemberRequest` keys in the output
- [ ] `Event.eventID` uses uppercase `D` (not `eventId`)
- [ ] File loads successfully: `pnpm seed --from-file '<path>'`
- [ ] Sentinel UI shows issues, events, and environment filters after seeding
- [ ] Search filters return results: `is:unresolved`, `issue.priority:high`, `device.arch:arm64`, `geo.country_code:US`, `error.type:TypeError`
- [ ] Event contexts contain device, geo, and error enrichment keys (see Section 4.6 enrichment tables)

### Quick validation script

```python
import json, sys

with open(sys.argv[1]) as f:
    data = json.load(f)

FORBIDDEN_KEYS = {"User", "Organization", "AppConfiguration", "OrganizationMember", "OrganizationToken", "TeamMember", "TeamMemberRequest"}
REQUIRED_KEYS = {"Project", "Issue", "Event"}

errors = []
for key in FORBIDDEN_KEYS & set(data.keys()):
    errors.append(f"FORBIDDEN key present: {key}")
for key in REQUIRED_KEYS - set(data.keys()):
    errors.append(f"REQUIRED key missing: {key}")

for issue in data.get("Issue", []):
    if isinstance(issue.get("count"), str):
        errors.append(f"Issue {issue['id']}: count is string, must be number")
    if isinstance(issue.get("metadata"), dict):
        errors.append(f"Issue {issue['id']}: metadata is object, must be JSON string")

for event in data.get("Event", []):
    if "eventId" in event and "eventID" not in event:
        errors.append(f"Event {event['id']}: uses eventId instead of eventID")
    if isinstance(event.get("contexts"), dict):
        errors.append(f"Event {event['id']}: contexts is object, must be JSON string")
    if isinstance(event.get("tags"), (list, dict)) and not isinstance(event.get("tags"), str):
        errors.append(f"Event {event['id']}: tags is object/array, must be JSON string")

for release in data.get("Release", []):
    if isinstance(release.get("id"), int):
        errors.append(f"Release {release['id']}: id is number, must be string")

if errors:
    print(f"FAILED ({len(errors)} errors):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print(f"OK — {len(data)} entity keys, {sum(len(v) for v in data.values() if isinstance(v, list))} total records")
```

---

## 10. Mapping Summary

| StatePayload Key | Source | Sentry API Endpoint |
|------------------|--------|---------------------|
| `Project` | Direct | `GET /api/0/organizations/{org}/projects/` |
| `Team` | Direct | `GET /api/0/organizations/{org}/teams/` |
| `TeamProject` | Derived | From `Project.teams[]` |
| `ProjectEnvironment` | Derived | From `Event.environment` per project |
| `Issue` | Direct | `GET /api/0/projects/{org}/{proj}/issues/` + detail |
| `Event` | Direct | `GET /api/0/organizations/{org}/issues/{id}/events/` |
| `IssueHash` | Derived | SHA-256 of issue ID |
| `IssueBookmark` | Derived | From `Issue.isBookmarked` |
| `TagValue` | Derived | From events + environments API |
| `Release` | Direct | `GET /api/0/organizations/{org}/releases/` |
| `ProjectRelease` | Derived | From `Release.projects[]` |
| `AlertRule` | Direct | Issue: `GET /api/0/projects/{org}/{proj}/rules/` + Metric: `GET /api/0/organizations/{org}/alert-rules/` |
| `SentryAppInstallation` | Direct | `GET /api/0/organizations/{org}/sentry-app-installations/` |
| `ExternalIssue` | Direct | `GET /api/0/organizations/{org}/issues/{id}/external-issues/` |
