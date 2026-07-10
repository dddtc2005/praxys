# Set up the feedback GitHub App (no-rotation issue filing)

> **Summary:** Configure the GitHub App that lets the backend file feedback as
> GitHub issues. It mints short-lived installation tokens on demand, so there is
> no token to rotate.
> **Use when:** Standing up feedback → GitHub issue filing. The App is the only
> auth path; without it, feedback is still captured for admin-only manual
> promotion.

## Why a GitHub App

A **GitHub App** issues ~1h *installation tokens* that the backend mints + caches
automatically (`api/github_issues.py`), so there is **nothing to rotate** — unlike
a long-lived personal access token. This is the sole auth path for feedback issue
filing.

## Inputs an agent needs

Gather these before step 3 — an agent can't derive them:
- **App ID** — the app's settings page (from step 1).
- **Installation ID** — the number at the end of the install URL
  `…/installations/<ID>` (step 2). A normal `gh`/PAT token can't read it via the API.
- **Private key** — the `.pem` downloaded in step 1 (its path on the operator's machine).

## Prerequisite — running backend build

Steps 1–3 (create / install / store config) can run any time and are safe to do
early. **Step 4 (deploy → verify) only takes effect once the deployed backend
includes the GitHub App support (PR praxys-run/praxys#328 or later)** — setting the
config before that ships just sits idle until the next backend deploy.

## Steps

### 1. Create the App  — human (GitHub UI)

GitHub → *Settings → Developer settings → GitHub Apps → New GitHub App*:
- **Name:** e.g. `praxys-feedback`.
- **Homepage URL:** `https://www.praxys.run` (anything valid).
- **Webhook:** uncheck *Active* (we don't receive webhooks).
- **Permissions → Repository → Issues:** **Read and write**. No other permissions.
- **Where can this App be installed:** *Only on this account*.
- Create, then note the **App ID**.
- *Generate a private key* → downloads a `.pem`. Keep it secret.

### 2. Install it on the repo  — human

App → *Install App* → install on `praxys-run/praxys` (or your triage repo), *Only
select repositories* → that repo. After installing, the browser URL ends in
`…/installations/<INSTALLATION_ID>` — **that number is the Installation ID.**

> Heads up: a normal `gh` / PAT token **cannot** read this via the API
> (`gh api /repos/<owner>/<repo>/installation` requires the app's own JWT, not a
> user token). The install URL is the reliable source.

### 3. Store the config  — agent-executable

The private key must be stored **single-line with `\n` escapes** (App Service
settings don't keep multi-line cleanly; the backend restores the newlines).

```bash
# App ID + Installation ID are non-secret → Actions variables
gh variable set PRAXYS_GITHUB_APP_ID --repo praxys-run/praxys --body '<APP_ID>'
gh variable set PRAXYS_GITHUB_APP_INSTALLATION_ID --repo praxys-run/praxys --body '<INSTALLATION_ID>'
gh variable set PRAXYS_FEEDBACK_GITHUB_REPO --repo praxys-run/praxys --body 'praxys-run/praxys'

# Private key → Actions secret, flattened to one line with literal \n
KEY_ONELINE=$(awk 'BEGIN{ORS="\\n"}{print}' path/to/private-key.pem)
printf '%s' "$KEY_ONELINE" | gh secret set PRAXYS_GITHUB_APP_PRIVATE_KEY --repo praxys-run/praxys
```

### 4. Roll out  — agent-executable

```bash
gh workflow run deploy-backend.yml --ref main
```

The deploy's *sync settings* step pushes the variables + secret to App Service
(they're optional — see [config-and-secrets.md](./config-and-secrets.md)).

## Verify

**Before deploy (optional, fast):** confirm the credentials are right without
shipping anything — sign the app JWT, mint an installation token, and check the
grant. A `201` with `"issues": "write"` means filing will work:

```bash
# needs python + cryptography/PyJWT; or do the JWT+POST by hand
python - <<'PY'
import jwt, time, httpx, pathlib
app_id, inst = "<APP_ID>", "<INSTALLATION_ID>"
key = pathlib.Path("<path/to/key.pem>").read_text()
j = jwt.encode({"iat": int(time.time())-60, "exp": int(time.time())+540, "iss": app_id}, key, algorithm="RS256")
r = httpx.post(f"https://api.github.com/app/installations/{inst}/access_tokens",
               headers={"Authorization": f"Bearer {j}", "Accept": "application/vnd.github+json"})
print(r.status_code, r.json().get("permissions"), r.json().get("repository_selection"))
PY
```

**After deploy:** submit a test bug report (or Admin → User Feedback → **Retry** a
`failed` row) and confirm it reaches `issue_created` with a real issue link. The
issue is authored by the App (e.g. `praxys-feedback[bot]`), not a personal account.

## Rollback / Recovery

Unset the three App settings and feedback auto-filing goes dormant — reports are
still captured for **admin-only manual promotion** (Admin → User Feedback). The
App can be uninstalled from the repo at any time without affecting the rest of
the app.

## Related

- [config-and-secrets.md](./config-and-secrets.md) · [admin-tasks.md](./admin-tasks.md) · `api/github_issues.py`
- Feedback feature: praxys-run/praxys#328

---
_Last reviewed: 2026-06-30 · Owner: @dddtc2005_
