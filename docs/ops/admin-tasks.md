# Admin tasks

> **Summary:** In-app operational tasks for a Praxys admin (superuser).
> **Use when:** Managing users, invitations, demo accounts, announcements, or
> triaging feedback.

## Who is an admin

`users.is_superuser = true`. On a fresh DB the **first registered user** becomes
admin automatically. The address in `PRAXYS_ADMIN_EMAIL` is always granted admin
on register. Everyone else needs an invitation code. All `/api/admin/*` endpoints
enforce `require_admin` (403 otherwise) — see `api/views.py`.

Most tasks have a UI on the **Admin** page (`/admin`); the API equivalents are
listed for scripting.

## Invitations

- UI: Admin → generate / copy / revoke codes.
- API: `POST /api/admin/invitations` (`{note}`) → `{code}`; `GET /api/admin/invitations`;
  `DELETE /api/admin/invitations/{id}`.

## User roles

- Promote/demote: `PATCH /api/admin/users/{id}/role` (`{is_superuser}`).
- List: `GET /api/admin/users`. Delete: `DELETE /api/admin/users/{id}`.
- Don't demote the last admin — keep at least one superuser (and/or rely on
  `PRAXYS_ADMIN_EMAIL`).

## Demo accounts

- `POST /api/admin/demo-accounts` (`{email, password}`) — creates a read-mostly
  demo user (used by the public "Try the demo" CTA and perf baselines).

## System announcements

- UI: Admin → Announcements (site-wide banners; `info`/`warning`/`success`).
- API: `POST/PATCH/DELETE /api/admin/announcements`; users read `GET /api/announcements`.

## Feedback triage

In-app bug reports / feature requests land in **Admin → User Feedback**
(badge shows the count needing attention). Each row:
- **Approve & file** — publish a parked (`needs_review`) report's scrubbed
  title/body to GitHub.
- **Retry** — re-run triage.
- **Reject** — discard.

Auto-filing + the sensitivity gate are configured via the GitHub App settings
(`PRAXYS_GITHUB_APP_*` / `PRAXYS_FEEDBACK_GITHUB_*`; see
[config-and-secrets.md](./config-and-secrets.md) and
[setup-github-app.md](./setup-github-app.md)).
To get emailed when something needs review, wire the alert in
[monitoring-and-alerts.md](./monitoring-and-alerts.md).

> The feedback feature ships in dddtc2005/praxys#328.

## Related

- [monitoring-and-alerts.md](./monitoring-and-alerts.md) · `api/routes/admin.py` · `api/routes/announcements.py`

---
_Last reviewed: 2026-06-30 · Owner: @dddtc2005_
