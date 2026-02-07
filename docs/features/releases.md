# Releases: Naming, Seeding, and Resolved In

Reference for how releases work in Sentinel: Sentry naming convention, seed data shape, and where release data is used (Resolved In dropdown/modal, layout, API).

---

## 1. Sentry release naming (name vs version)

From [Sentry: Naming Releases](https://docs.sentry.io/product/releases/naming-releases/):

- **Release name** (our DB field `version`): The full identifier, unique per organization. Restrictions: no newlines, tabs, `/`, `\`, cannot be `.` or `..`, max 200 chars.
- **Short version** (our DB field `shortVersion`): “A short version of the release name without the hash” — used for display and for semver detection.

### Semantic versioning (recommended)

- **Format**: `package@version` or `package@version+build` (e.g. `my.project.name@2.3.12+1234`).
- **package**: Project/app identifier (e.g. project slug).
- **version**: Semver-like `<major>.<minor>.<patch>.<revision?>-<prerelease?>`.
- **shortVersion**: Store **only the version part** (e.g. `1.0.0`), not the full `package@1.0.0`. The UI uses this for display and to decide “semver” vs “non-semver”.

So for `nextjs-demo@1.0.0`:

- `version` (release name) = `nextjs-demo@1.0.0`
- `shortVersion` = `1.0.0`

The “name before” the `@` is the package; the part after `@` is the semver.

### Commit SHA

- **version** = full hash (e.g. `faf6c0f925b6`).
- **shortVersion** = same or shortened for display; non-semver.

### Pure version-only (legacy / optional)

- You can use `version: "1.0.0"` and `shortVersion: "1.0.0"` if not using `package@version`, but Sentry recommends prefixing with something project-specific (`package@version`).

---

## 2. Seed data (lib/seed-payload.ts)

- **RELEASES** array: Holds **full release names** (same as `Release.version`). Used by `pick(RELEASES, i)` for `issue.lastReleaseVersion` and `event.release`. Must match seeded `Release.version` values so lookups resolve.
- **releases**: Each item has `id`, `organizationId`, `version`, `shortVersion`, `status`, `dateCreated`.
  - Semver: `version: "${PROJECT_SLUG}@1.0.0"`, `shortVersion: "1.0.0"`.
  - Commit SHA: `version: "faf6c0f925b6"`, `shortVersion: "faf6c0f925b6"`.
  - Other package: `version: "seed-script@1.0.0"`, `shortVersion: "1.0.0"`.
- **projectReleases**: Links releases to project(s). Issue/event “release” is org-level; projectReleases associate which project the release belongs to.

After any change to release names, keep **RELEASES** in sync with `releases[].version` so issues and events reference valid releases.

---

## 3. Constants (lib/constants.ts)

- **DEFAULT_ORG_SLUG**: `"sentinel-demo"` — used for API calls when not in an org-scoped route (issues, releases, Resolved In modal query).
- **DEFAULT_PROJECT_SLUG**: `"nextjs-demo"` — default project for issues list, errors-outages, onboarding.

No prop drilling for org slug in issue detail: layout uses the constant for queries; Resolved In modal and hooks import it where needed.

---

## 4. Where release data is used

### Layout (app/(app)/issues/[id]/layout.tsx)

- Fetches **releases** with `limit: 5` for the main Resolve dropdown (“The current release” = first in list).
- Passes `releases` and `currentRelease` (first of list) to **IssueDetailActionBar** → **ResolveButton**. Does **not** pass `organizationSlug` (modal has its own query).

### ResolveButton (components/compositions/issue-detail/resolve-button.tsx)

- **Props**: `isResolved`, `onResolve`, `currentRelease`, `releases` (layout’s 5), `resolutionStatusDetails`.
- Main dropdown: “The next release”, “The current release” (uses `currentRelease`), “Another existing release…”, “A commit…”.
- “The current release” label: if `currentRelease.shortVersion ?? currentRelease.version` is semver → “The current semver release” + version below; else “The current release” + formatted version (non-semver shows “(non-semver)” and truncation at 12 chars).
- “Another existing release…” opens **ResolvedInModal** (no org slug prop; modal uses constant).

### ResolvedInModal (components/compositions/issue-detail/resolved-in-modal.tsx)

- **Own query**: `api.releases.list` when modal is open, `limit: 20`, `organization_id_or_slug: DEFAULT_ORG_SLUG` (from constants).
- **Props**: `open`, `onOpenChange`, `onResolve(releaseVersion)`, optional `organizationSlug` (defaults to constant).
- Version dropdown: header “Version” + Clear (clears search, closes dropdown), search “Search versions”, list filtered and capped at 10; states: “Loading releases…”, “No releases found”, or list. Resolve disabled until a version is selected.
- **Semver detection**: `shortVersion ?? version` tested with semver regex; semver → show version only; non-semver → show shortVersion/version + “(non-semver)” and truncate if length > 12.

### Backend (events router, updateIssue)

- Issue: `resolutionReason` (“in_next_release” | “in_release”), `resolvedById`, `resolvedInReleaseVersion`.
- **getIssue** returns `statusDetails`: `{ inNextRelease?, inRelease?, releaseVersion?, resolvedBy?: { name } }` built from those fields (see `getIssueStatusDetails` in events router).
- **updateIssue** accepts `statusDetails: { inNextRelease?, inRelease?, releaseVersion? }` and sets `resolvedInReleaseVersion` when `inRelease` + `releaseVersion`.

---

## 5. UI copy for “Resolved In”

- **Resolved in next release**: “{resolverName} marked this issue as resolved in the upcoming release.”
- **Resolved in version X**: “{resolverName} marked this issue as resolved in version {version}.”
- Resolver name is bold in the green bar subtext.

---

## 6. Key code locations

| What | Where |
|------|--------|
| Release naming (seed) | `lib/seed-payload.ts` — `releases`, `RELEASES` |
| Semver vs non-semver formatting | `resolve-button.tsx` (`formatReleaseLabel`, `isSemverVersion`), `resolved-in-modal.tsx` (same helpers) |
| statusDetails helper | `app/api/trpc/routers/events.ts` — `getIssueStatusDetails(issue)` |
| Layout releases query (5) | `app/(app)/issues/[id]/layout.tsx` — `api.releases.list` limit 5 |
| Modal releases query (20) | `components/compositions/issue-detail/resolved-in-modal.tsx` — `api.releases.list` when open, limit 20 |
| Default org/project | `lib/constants.ts` — `DEFAULT_ORG_SLUG`, `DEFAULT_PROJECT_SLUG` |

---

## 7. Checklist for another Cursor session

- When adding or changing releases in the seed: keep **version** = full name (`package@version` or SHA), **shortVersion** = display/semver part only; keep **RELEASES** in sync with `releases[].version`.
- Resolved In modal is its own component; it runs its own releases query and uses `DEFAULT_ORG_SLUG` from constants (no prop drilling).
- Semver detection and “(non-semver)” label use `shortVersion ?? version`; for `package@version` always set `shortVersion` to the part after `@`.
