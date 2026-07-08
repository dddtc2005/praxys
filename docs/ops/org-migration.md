# Migrate the repos to the `praxys-run` organization

> **Summary:** Move `praxys`, `praxys-coach-plugin`, and `praxys-ops-agent` from
> the personal account `dddtc2005` into the free org **`praxys-run`** with **zero
> deploy outage**, by pre-staging Azure OIDC before the transfer and repointing
> the GitHub App, submodule, and tokens after.
> **Use when:** Executing (or reviewing) the org migration.

## Why this is delicate

A repo transfer is mostly seamless (GitHub redirects git URLs, and **secrets +
variables + webhooks + deploy keys remain** with the repo). The things that
**break** are the ones keyed to the *old owner/repo path*:

- **Azure OIDC** — the federated credentials on app `trainsight-cicd` trust
  `repo:dddtc2005/praxys:*`. After transfer the Actions token's subject becomes
  `repo:praxys-run/praxys:*` and **every OIDC login (all deploys + i18n) fails**
  until a matching credential exists. This is the one that can cause an outage,
  so we **pre-stage it additively before** the transfer.
- **The feedback GitHub App** installation is on the `dddtc2005` *user*; an
  org-owned repo needs the app installed on the *org*.
- **The submodule URL** and a pile of `dddtc2005/praxys` references in docs
  (redirects keep them working, but we update for correctness).

Verified prerequisites (this session): the Copilot **coding agent runs on a free
org's repos** on the maintainer's personal entitlement (live-tested on
`praxys-run`), so the change loop is **not** broken or billed by the move.

## Who does what

| Legend | Meaning |
|---|---|
| 🧑 **You** | Needs your GitHub/Azure identity or a decision (org-owner approval, minting a PAT, clicking Transfer). |
| 🤖 **Agent** | I can run it (Azure CLI as `dddtc2006@live.cn`, or `gh` with your session, or a PR). |

## Environment (values used below)

| Thing | Value |
|---|---|
| Target org | `praxys-run` (GitHub **Free** plan) |
| Subscription | `3ff02750-211c-4579-94a6-8c9af4e6d891` |
| OIDC app (CI/deploy) | `trainsight-cicd` — appId `d3deb736-e95d-400e-b5a5-c2f76b23ae25` |
| — existing fed-creds | `github-deploy` → `repo:dddtc2005/praxys:ref:refs/heads/main`; `i18n` → `repo:dddtc2005/praxys:ref:refs/heads/i18n-azure-openai` |
| Feedback GitHub App | App ID `4180162`, current install `143455902` (on user `dddtc2005`) |
| Repos | `dddtc2005/praxys` (public), `dddtc2005/praxys-coach-plugin` (public), `dddtc2005/praxys-ops-agent` (private) |
| Submodule | `plugins/praxys` → `github.com/dddtc2005/praxys-coach-plugin.git` |

## Prerequisites

- 🧑 You are **owner** of the `praxys-run` org (create-repo rights) and **admin**
  on all three repos.
- 🧑 Azure: Contributor + **Application Administrator** (to edit `trainsight-cicd`
  federated credentials). Agent is logged in as `dddtc2006@live.cn`.
- 🤖 `gh` authenticated as you; `az` logged in to the subscription above.

---

## Phase 0 — Pre-stage (additive, NO downtime) — do BEFORE any transfer

### 0.1 Add Azure OIDC federated credentials for the new path 🤖
Additive — the old `dddtc2005` creds stay valid, so nothing breaks yet. (Max 20
creds/app; we are adding 2.)

```bash
APP=d3deb736-e95d-400e-b5a5-c2f76b23ae25
az ad app federated-credential create --id $APP --parameters '{
  "name":"github-deploy-praxysrun",
  "issuer":"https://token.actions.githubusercontent.com",
  "subject":"repo:praxys-run/praxys:ref:refs/heads/main",
  "audiences":["api://AzureADTokenExchange"]}'
az ad app federated-credential create --id $APP --parameters '{
  "name":"i18n-praxysrun",
  "issuer":"https://token.actions.githubusercontent.com",
  "subject":"repo:praxys-run/praxys:ref:refs/heads/i18n-azure-openai",
  "audiences":["api://AzureADTokenExchange"]}'
```

> If any deploy workflow also runs from **tags** or a **pull_request**/environment
> subject, add those too (e.g. `repo:praxys-run/praxys:ref:refs/tags/api-*` is not
> a valid subject shape — use `repo:praxys-run/praxys:ref:refs/tags/<tag>` only if
> a workflow triggers on a specific tag via OIDC). The current deploys log in on
> `push`→`main`, so the `main` subject covers them.

> **Status (2026-07-08): already staged.** The two creds above exist on
> `trainsight-cicd` (`github-deploy-praxysrun`, `i18n-praxysrun`); the old
> `dddtc2005` creds are retained, so prod is unaffected until Phase 4 cleanup.

### 0.2 Note the retired-name behavior 🧑
After transfer, `dddtc2005/praxys` (100+ Actions uses/week) is **permanently
retired** — redirects work, but **never recreate** a repo at the old path or the
redirects are deleted.

---

## Phase 1 — Transfer the repos 🧑 (disruptive step)

Transferring **to an org you own is immediate** (no email accept). Do the plugin
and ops first, then praxys.

```bash
gh api --method POST repos/dddtc2005/praxys-coach-plugin/transfer -f new_owner=praxys-run
gh api --method POST repos/dddtc2005/praxys-ops-agent/transfer   -f new_owner=praxys-run
gh api --method POST repos/dddtc2005/praxys/transfer             -f new_owner=praxys-run
```

> You (the original owner) are auto-added as a collaborator, so you keep admin.
> Issues assigned to non-org-members are cleared on transfer; `@copilot`
> assignments are fine.

---

## Phase 2 — Repoint & reconfigure (right after transfer)

### 2.1 Confirm OIDC deploys work 🤖
The pre-staged creds mean the next deploy just works. Force one:

```bash
gh workflow run deploy-backend.yml  -R praxys-run/praxys   # or push a trivial change
```

### 2.2 Reinstall the feedback GitHub App on the org 🧑
The app (ID `4180162`) was installed on the **user**; install it on the **org**:

1. `github.com/settings/installations` (or the app's page) → **Install** app
   `4180162` on **`praxys-run`**, granting it the **`praxys`** repo (Issues: write).
2. Note the **new installation ID** (URL of the org installation settings page).

### 2.3 Update the App + feedback variables 🤖 (needs the new install ID from 2.2)

```bash
gh variable set PRAXYS_GITHUB_APP_INSTALLATION_ID -R praxys-run/praxys --body "<NEW_INSTALL_ID>"
gh variable set PRAXYS_FEEDBACK_GITHUB_REPO        -R praxys-run/praxys --body "praxys-run/praxys"
```
Then redeploy the backend so App Service picks up the new settings (deploy-backend
syncs app settings from these variables).

### 2.4 Update the submodule URL 🤖 (PR)
`.gitmodules` → `https://github.com/praxys-run/praxys-coach-plugin.git`, then
`git submodule sync`. (Redirects keep the old URL working; this is for correctness.)

### 2.5 Create `COPILOT_ASSIGN_TOKEN` for the change loop 🧑→🤖
Agent assignment needs a **user PAT** (see `change-loop.md` §3). Mint a
fine-grained PAT — resource owner **`praxys-run`**, **only** `praxys`, permission
**Issues: Read and write**, with an expiry. Then:

```bash
gh secret set COPILOT_ASSIGN_TOKEN -R praxys-run/praxys   # paste the PAT
```

### 2.6 The ops-agent's own OIDC 🧑/🤖
`praxys-ops-agent` logs in with `AZURE_OPS_CLIENT_ID`. There is currently **no**
`repo:dddtc2005/praxys-ops-agent:*` federated credential on `trainsight-cicd`, so
resolve which app that secret points to and add the new-path subject:

```bash
# find the app behind AZURE_OPS_CLIENT_ID (value is a secret — read it from the repo settings),
# then, on that app id:
az ad app federated-credential create --id <OPS_APP_ID> --parameters '{
  "name":"ops-runner-praxysrun",
  "issuer":"https://token.actions.githubusercontent.com",
  "subject":"repo:praxys-run/praxys-ops-agent:ref:refs/heads/main",
  "audiences":["api://AzureADTokenExchange"]}'
```
Also update any `owner: dddtc2005` / cross-repo references in the ops-agent
workflows to `praxys-run`.

### 2.7 Update local clones' remotes & submodule 🤖
Git redirects the old URL after transfer, but repoint every working copy for
correctness (do this **only after** the transfer — before it, the new URL 404s):

```bash
# in each local checkout of praxys:
git remote set-url origin https://github.com/praxys-run/praxys.git
git remote -v            # verify origin now points at praxys-run
git submodule sync --recursive   # picks up the .gitmodules change from step 2.4
```

> All `git worktree`s of a checkout share one `.git`, so a single `set-url`
> covers every worktree. Repeat for local clones of `praxys-coach-plugin` and
> `praxys-ops-agent`.

---

## Phase 3 — Verify

- 🤖 **Backend deploy** green (OIDC login step succeeds) → `https://api.praxys.run` healthy.
- 🤖 **Frontend deploy** green → `https://www.praxys.run` serves.
- 🤖 **i18n** workflow (push to main) logs in via OIDC.
- 🧑/🤖 **Feedback → issue**: submit a test in-app feedback (or re-run triage) → a
  new issue is filed in `praxys-run/praxys`.
- 🤖 **Change loop**: label a throwaway bug `agent-ready` → `assign-copilot.yml`
  assigns `copilot-swe-agent` (now that `COPILOT_ASSIGN_TOKEN` is set).
- 🤖 **Secrets/variables** carried over: `gh secret list -R praxys-run/praxys` and
  `gh variable list -R praxys-run/praxys` match the pre-transfer set.
- 🤖 **Branch protection / ruleset** intact on the public repo (`gh api
  repos/praxys-run/praxys/rulesets`).

## Phase 4 — Cleanup

- 🤖 Remove the **old** OIDC creds once the new path is verified:
  ```bash
  az ad app federated-credential delete --id d3deb736-e95d-400e-b5a5-c2f76b23ae25 --federated-credential-id github-deploy
  az ad app federated-credential delete --id d3deb736-e95d-400e-b5a5-c2f76b23ae25 --federated-credential-id i18n
  ```
- 🤖 **Docs sweep** (PR): update `dddtc2005/praxys` → `praxys-run/praxys` across
  `docs/`, `CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md`, `README`,
  `.env.example`, and workflow comments. (Redirects keep links alive; this is for
  correctness and future clarity.)
- 🧑 Delete the throwaway test repo: `gh repo delete praxys-run/agent-availability-check`
  (needs `delete_repo` scope: `gh auth refresh -h github.com -s delete_repo`).

## Rollback / Recovery

- **OIDC**: pre-staging is additive, so a mid-migration abort leaves prod working
  on the old creds. If deploys fail post-transfer, the fix is always "add the
  missing `repo:praxys-run/...` federated credential" (subject mismatch is the
  only OIDC failure mode here).
- **Transfer**: a repo can be transferred **back** to `dddtc2005` (you're still a
  collaborator). Do this within the redirect window and **don't** recreate the old
  name in the meantime.
- **GitHub App**: if issue-filing breaks, re-check the org installation + the two
  variables (2.2–2.3); the app private key (`PRAXYS_GITHUB_APP_PRIVATE_KEY`) is
  unchanged.

## Free-org caveats (accepted)

- `praxys-ops-agent` is **private** → on a Free org it has **no** branch
  protection (already the case; PR-only is enforced via agent instructions) and
  shares the org's **2,000 Actions min/month** private-repo allowance. Public
  repos keep branch protection and unlimited Actions minutes.
- The org has **$0 Copilot** of its own — expected. Copilot runs on *your*
  personal entitlement when *you* initiate it (verified). Other members/bots
  would need their own seats or org Copilot Business.
- DNS (`praxys.run`, `api.`, `www.`) points at Azure, **unaffected** by transfer.

## Related

- [config-and-secrets.md](./config-and-secrets.md) — where each secret/variable lives.
- [environment.md](./environment.md) — Azure resource names/IDs.
- [change-loop.md](./change-loop.md) — `COPILOT_ASSIGN_TOKEN` details.
- [deploy.md](./deploy.md) — the deploy workflows that use OIDC.

---
_Last reviewed: 2026-07-08 · Owner: @dddtc2005_