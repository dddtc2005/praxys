# Admin tasks

> **Summary:** The admin operations console and focused management workflows.
> **Use when:** Checking health and attention queues, or managing users, incidents,
> feedback, invitations, demo accounts, and announcements.

## Who is an admin

`users.is_superuser = true`. On a fresh DB the **first registered user** becomes
admin automatically. The address in `PRAXYS_ADMIN_EMAIL` is always granted admin
on register. Everyone else needs an invitation code — unless **self-registration** is open (see Registration below). All `/api/admin/*` endpoints
enforce `require_admin` (403 otherwise) — see `api/views.py`.

The web-only admin console is split into focused routes. `/admin` redirects to the
operations overview:

- `/admin/ops` — attention queue, live service health, and aggregate usage context
- `/admin/users` — registration, seats, users, invitations, waitlist, demo accounts
- `/admin/feedback` — feedback triage and GitHub reconciliation
- `/admin/incidents` — public-status incident management
- `/admin/communications` — system announcements

The API equivalents are listed below for scripting.

## Operations overview

Open `/admin/ops` for the first-response view. The
`GET /api/admin/ops/summary?window=24h|7d|28d` endpoint returns aggregate-only
sections with an explicit `source`, `window`, `freshness`, and `as_of` value:

- **Needs attention:** active incident counts and actionable feedback counts,
  including critical/high priority totals.
- **Service health:** live API, database, and background-sync component probes.
- **Product value:** registered users plus DAU/WAU/MAU based on authenticated
  request activity. These are labeled **directional**.
- **Azure alerts and platform health:** explicitly `unavailable` in Phase 1 while
  the telemetry trust boundary in [#417](https://github.com/praxys-run/praxys/issues/417)
  remains open. Use [monitoring-and-alerts.md](./monitoring-and-alerts.md) for the
  source-of-truth KQL and alert inventory.

The response never contains emails, raw user IDs, invitation codes, feedback
text/screenshots, or Coach comments. DB-backed sections fail independently, so an
unavailable summary block does not disable the focused management routes. The
endpoint is admin-only and returns `Cache-Control: private, no-store`; future
Azure-backed subsections will own their short server-side cache.

## Invitations

- UI: `/admin/users` → **Invitation codes** → generate / copy / revoke codes.
- API: `POST /api/admin/invitations` (`{note}`) → `{code}`; `GET /api/admin/invitations`;
  `DELETE /api/admin/invitations/{id}`.

## Registration (open / close + seat cap)

Praxys is invitation-only by default. To let people sign up without a code:

- UI: `/admin/users` → **Registration** → toggle **Self-registration** on and set the
  **seat cap**. The public login page then shows a "Create account" path; new
  code-less sign-ups must **verify their email** (requires SMTP — see below)
  before they can log in.
- API: `GET /api/admin/config` (status + DAU/WAU gauge + `email_configured`);
  `PATCH /api/admin/config` (`{registration_open, registration_max_users}`).
  Unauthenticated `GET /api/public/config` exposes **only** the effective boolean.

**Seat cap = committed seats** = registered non-demo users **plus** outstanding
(active, unused, unexpired) invitation codes. Sending an invitation reserves a
seat, so an invited user is never turned away at the door. Self-registration
**auto-closes** when committed ≥ cap; admin-issued invitations are deliberate and
still allowed past it. The DAU/WAU tiles are the readiness gauge — review before
raising the cap (100 → 1000; see [cost-and-scaling.md](./cost-and-scaling.md)).

**Email is required for the full experience** (verification + auto-sent invites).
Without `PRAXYS_SMTP_*` configured (see
[config-and-secrets.md](./config-and-secrets.md)), open sign-ups are created
*verified* (no ownership check) and invitation codes are shown for you to
copy/email by hand.

## Waitlist → invite

Prospective users who joined the waitlist (login page, or the WeChat mini program)
appear in `/admin/users` → **Waitlist**.

- **Invite** a row → generates a 14-day invitation code, marks the row, and emails
  the code + a prefilled register link (if SMTP is configured; otherwise copy the
  code or use the mailto fallback shown in the result). **Re-invite** revokes the
  previous unused code and issues a fresh one.
- API: `GET /api/admin/waitlist`; `POST /api/admin/waitlist/{id}/invite`.

## User roles

- Promote/demote: `PATCH /api/admin/users/{id}/role` (`{is_superuser}`).
- List: `GET /api/admin/users`. Delete: `DELETE /api/admin/users/{id}`.
- Don't demote the last admin — keep at least one superuser (and/or rely on
  `PRAXYS_ADMIN_EMAIL`).

## Demo accounts

- `POST /api/admin/demo-accounts` (`{email, password}`) — creates a read-mostly
  demo user (used by the public "Try the demo" CTA and perf baselines).

## System announcements

- UI: `/admin/communications` → **System announcements** (site-wide banners; `info`/`warning`/`success`).
- API: `GET/POST/PATCH/DELETE /api/admin/announcements`; users read active rows from `GET /api/announcements`.
- Bilingual (#355): fill the **Default (English)** fields (the fallback) and,
  optionally, the **中文** fields. Content is stored as an English base plus a
  per-locale `translations` override (`{"zh": {title, body, link_text}}`); a user
  sees `translations[<their locale>]` and falls back to the English base, so a
  `zh` user never gets an English-only banner. Author both language versions
  before publishing to avoid mixed-language banners.

## Feedback triage

In-app bug reports / feature requests land in `/admin/feedback`
(badge shows the count needing attention). The list defaults to **Active**
tickets — use the status filter to view **All** or a single status
(`resolved`, `rejected`, …). During AI triage each ticket is also assigned a
**priority** (`low`/`medium`/`high`/`critical`), shown as a badge and mirrored
to a `priority: <level>` label on the filed GitHub issue. Per-row actions:
- **Approve & file** — publish a parked (`needs_review`) report's scrubbed
  title/body to GitHub.
- **Retry** — re-run triage.
- **Reject** — discard.

**Sync from GitHub** reconciles each filed ticket with its linked issue: a
closed issue flips the ticket to `resolved`, a reopened one back to
`issue_created`. It reads only the issue *state* (no ticket text leaves) and is
a no-op when GitHub isn't configured — no extra permission is needed beyond the
GitHub App's existing *Issues: write*.

Auto-filing + the sensitivity gate are configured via the GitHub App settings
(`PRAXYS_GITHUB_APP_*` / `PRAXYS_FEEDBACK_GITHUB_*`; see
[config-and-secrets.md](./config-and-secrets.md) and
[setup-github-app.md](./setup-github-app.md)).
To get emailed when something needs review, wire the alert in
[monitoring-and-alerts.md](./monitoring-and-alerts.md).

> The feedback feature ships in praxys-run/praxys#328; ticket status sync, status
> filtering, and priority suggestions in praxys-run/praxys#359.

## Related

- [monitoring-and-alerts.md](./monitoring-and-alerts.md) · `api/routes/admin.py` · `api/routes/announcements.py`

---
_Last reviewed: 2026-07-17 · Owner: @dddtc2005_
