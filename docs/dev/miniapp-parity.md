# Web ↔ Mini Program parity matrix

This document tracks feature parity between the Praxys web app (`web/src/`)
and the WeChat Mini Program (`miniapp/`). The bar set in `CLAUDE.md`'s
"Web ↔ miniapp parity" section is that **read views and write operations
should match**, even if the visual presentation differs.

Pages with no miniapp counterpart by design:

- `web/src/pages/Admin.tsx` — invitation generation / user management is
  web-only, since the audience is small and infrequent.
- `web/src/pages/Setup.tsx` — first-time onboarding (activity categories,
  backfill range, platform connection wizard). The mini program currently
  documents "go to web for first-time setup" rather than implementing
  the wizard natively. Revisit if mini-first onboarding becomes a goal.

---

## Read-side parity

The mini program already mirrors web's read-only views on every shared
page (Today / Training / Goal / History / Science / Settings). Charts,
text cards, citations, recommendations, milestone trackers — all
present and powered by the same API responses.

Known minor gaps:

| Page | Surface | Status | Notes |
|------|---------|--------|-------|
| Today | `WeeklyLoadMini` 7-day load-vs-target bar | partial | Data is in state (`hasWeekLoad`, `weekLoadActual`, `weekLoadPlannedSuffix`) but the bar viz is a text-only card on miniapp. Acceptable since the page is already dense. |
| Training | `AiInsightsCard` (CLI training-review insights) | gap | Web reads `/api/insights/training_review`. Skipped on miniapp until LLM endpoint replaces rule-based prose (see memory: `project_llm_insights_i18n`). |
| Training | `SleepPerfChart` (sleep score vs avg power) | matched | Closed by issue #76. |
| Training | `UpcomingPlanCard` (next 7-28 days from `/api/training`) | gap | Today already shows a single upcoming workout; weekly preview is a nice-to-have. |

---

## Write-side parity (priority gaps)

The miniapp historically restricted itself to read-only data plus theme
and language preferences. The new direction (per CLAUDE.md) is **write
parity wherever it's safe to do so**.

### High severity

| Page | Gap | Effort | Status |
|------|-----|--------|--------|
| Goal | Goal editor — set / change mode (race-date / cp-milestone / continuous), distance, target time, race date | ~150 LOC | open |
| Science | Pick active theory per pillar (`updateScience({science: {[pillar]: id}})`) | ~80 LOC | open |
| Settings | Manual sync trigger (`POST /api/sync/all` and per-platform) | ~100 LOC | open |
| Settings | Change training base (Power / HR / Pace) | ~30 LOC | open |
| Settings | Connect platform (Garmin / Stryd / Oura credentials; Strava is OAuth and stays web-only) | ~250 LOC | open — risky without OAuth bridge; defer |
| Settings | Disconnect platform | ~40 LOC | open |
| Settings | Threshold source per-metric override | ~60 LOC | open |

### Medium severity

| Page | Gap | Effort | Status |
|------|-----|--------|--------|
| Settings | Display name editor | ~30 LOC | open |
| Settings | Unit system (metric / imperial) | ~20 LOC | open |
| Settings | Language picker (Auto / English / 中文) | ~20 LOC | partial — preference is stored, picker UI matches theme picker |
| Settings | Sync backfill range | ~50 LOC | open |
| Settings | Auto-sync frequency (6 / 12 / 24 h) | ~30 LOC | open |
| Settings | Data preferences (activities / recovery / plan source) | ~80 LOC | open |
| Science | Zone label set picker (`updateScience({zone_labels: id})`) | ~30 LOC | open |

### Mini-only (web does not have)

| Page | Feature | Notes |
|------|---------|-------|
| Settings | Switch / unlink WeChat account (`POST /api/auth/wechat/unlink`) | Mini-specific by design; web has no WeChat binding. |

---

## Recommended sequence

1. **Goal editor + sync trigger + training-base picker** — biggest user-facing
   wins, all touch settled API routes.
2. **Science theory selection + zone label picker** — small write ops,
   close issue #76 entirely.
3. **Display name / units / language pickers + sync interval / backfill** —
   small Settings polish.
4. **Threshold source override + data preferences** — final Settings polish.
5. **Platform connect / disconnect** — defer until OAuth bridge story is
   solid, since Strava can't work without it and partial connect coverage
   would confuse users.

Onboarding (`Setup.tsx`) stays web-only for now. The mini program's
first-time flow is "open in mini → tap Sign in with WeChat → if no
existing account, link via email/password OR register here".
