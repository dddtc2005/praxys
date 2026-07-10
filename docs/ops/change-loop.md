# The change loop (Loop A) — auto-draft bug fixes with the Copilot coding agent

> **Summary:** How a qualifying bug report is tagged `agent-ready` and handed to
> the GitHub Copilot coding agent to draft a fix PR, plus the one-time setup and
> the knobs that control quality and safety.
> **Use when:** Enabling / operating / tuning the change loop, or debugging "I
> labeled an issue `agent-ready` but Copilot was never assigned".

Praxys runs two agentic loops. **The change loop (a.k.a. Loop A) lives here** and
is GitHub-native: feedback → a drafted fix PR. The **incident loop (Loop B)** —
AIOps / incident response — lives in the private `praxys-run/praxys-ops-agent`
repo. This runbook is the change loop.

## How it works

```
feedback triage (api/feedback_triage.py)  ──adds `agent-ready` for a qualifying bug──┐
a maintainer manually adds `agent-ready`  ───────────────────────────────────────────┤
                                                                                      ▼
                          .github/workflows/assign-copilot.yml  ──assigns──▶  Copilot coding agent
                                                                                      │ opens
                                                                                      ▼
                                                          draft PR ──▶ human review + merge (protected)
```

`agent-ready` is the **sole trigger**; a bare issue-open never fires. Triage adds
it only when **all** of these hold (`_qualifies_for_agent` in
`api/feedback_triage.py`):

1. **It is a bug** — features are assist-not-act; `other` never qualifies.
2. **The model judged it actionable** (`agent_eligible`) — a genuine, reproducible
   *defect*, not a feature idea, a how-to / support question, expected behavior /
   user error, or a vague complaint. This is where a "user called it a bug but we
   would not" report is filtered out: the triage LLM reclassifies the `kind` **and**
   sets `agent_eligible=false`. Without an LLM verdict (no `AZURE_AI_ENDPOINT`)
   the report is parked for an admin anyway, so it is never auto-assigned.
3. **The sensitivity gate did not withhold it** — a `needs_review`/sensitive
   report is never tagged, and because the tag is gated on this, it never even
   lands in `ai_labels`, so a later admin *approve* cannot auto-assign it either.
4. **It has enough detail** — a cheap word-count floor beneath the model verdict.

**Backlog escape hatch:** a `backlog` or `later` label makes an issue ineligible
even if it is a bug (the workflow skips it). **Merge is always human** — autonomy
is *drafting* the fix; branch protection keeps a human in the loop.

### Shadow mode

Set `PRAXYS_AGENT_READY_SHADOW=true` (App Service setting) to compute the
`agent-ready` decision and log it **without** applying the label — nothing is
auto-assigned. Use it to measure precision on real feedback before trusting the
loop, then unset to go live. Decisions are logged as
`change-loop agent-ready decision for feedback <id>: applied=<bool> shadow=<bool>`.

### Screenshots (how the agent "sees" them)

Feedback screenshots are **private by construction** (issue #337): the raw image
stays in Blob storage and only its key lands on the row — it is **never** put in
the (public) GitHub issue, and the coding agent has no path to it (no Azure
credential, and giving it one would pipe potentially-PII image bytes into a
public-repo agent).

Instead, the vision model (`api/feedback_vision.py`) is the **single controlled
image→text crossing**: at triage it writes a thorough, **PII-scrubbed** description
of what the screenshot shows (screen, affected component, visible error text, what
looks broken) into the issue body's `## Screenshot` section. That description —
double-scrubbed, and only ever from a **non-sensitive** image (a screenshot the
vision model flags sensitive parks the report as `needs_review`, so it is never
`agent-ready`) — is what the coding agent reads. For a code-fixing agent, a
complete scrubbed description is effectively equivalent to the image, since it
fixes bugs by reading code and reasoning about the described symptom, not by
pixel-measuring. The rare pixel-precise visual bug that a description cannot
capture should be `agent_eligible=false` and handled by a human (who *can* view the
image in the admin console).

**Do not** build a second path (an MCP tool or credential) that hands the agent the
raw image — that would breach the #337 invariant for a public repo. Enrich the
scrubbed description instead.

## Prerequisites

- Repo admin (to enable the coding agent, create labels, set branch protection).
- `gh` CLI authenticated (`gh auth status`).

## Steps

### 1. Enable the Copilot coding agent for the repo

Repo (or org) admin: **Settings → Copilot → Coding agent** → enable. Verify it is
assignable — the bot must appear as `copilot-swe-agent`:

```bash
gh api graphql -f query='query($o:String!,$n:String!){
  repository(owner:$o,name:$n){ suggestedActors(capabilities:[CAN_BE_ASSIGNED], first:100){
    nodes{ login } } } }' -F o=dddtc2005 -F n=praxys \
  --jq '.data.repository.suggestedActors.nodes[].login' | grep copilot-swe-agent
```

### 2. Create the labels

```bash
gh label create agent-ready -c 1D76DB -d "Trigger: hand this issue to the Copilot coding agent (change loop)" -R praxys-run/praxys
gh label create backlog     -c 5319E7 -d "Deferred; ineligible for auto-assign even if a bug" -R praxys-run/praxys
```

The workflow also honours an existing `later` label as a backlog synonym.

### 3. Configure the assignment token (REQUIRED for auto-assign)

**Agent assignment needs a user token — the built-in `GITHUB_TOKEN` cannot do
it.** The GraphQL API rejects a GitHub App installation token with
`FORBIDDEN: Assigning agents is not supported with GitHub App installation
tokens` (issue #400). Without `COPILOT_ASSIGN_TOKEN` the workflow now fails
*loudly* (it comments on the issue) instead of silently leaving it unassigned.

Create a **fine-grained PAT**, least-privilege:

- **Resource owner:** `praxys-run`; **Repository access:** *Only select
  repositories* → `praxys` (this repo only).
- **Permissions:** *Issues → Read and write* (nothing else).
- **Expiration:** set one (e.g. 90 days) and calendar a rotation.

Then store it and re-run:

```bash
gh secret set COPILOT_ASSIGN_TOKEN -R praxys-run/praxys   # paste the PAT when prompted
```

Manual assignment via the GitHub UI keeps working without this token (it uses
your user session) — the token is only needed for the *workflow* to assign.

### 4. Confirm branch protection on `main`

So the agent can draft but never ship, protect `main`:

- **Require a pull request before merging** with **at least 1 approving review**.
- **Require status checks to pass** — the backend-tests check from **#361**
  (`Run backend pytest on pull requests`). Add it once that workflow has run on a
  PR so the check name is selectable.

```bash
gh api repos/praxys-run/praxys/branches/main/protection --jq '{reviews:.required_pull_request_reviews, checks:.required_status_checks}'
```

## Tuning the agent (quality knobs)

- **Repo-wide instructions (the "prompt"):** the issue body *is* the task prompt;
  durable guidance lives in `.github/copilot-instructions.md` ("Coding-agent
  guidance") — always add a test, run `pytest`, follow the 7-step metric
  checklist, keep metrics pure, never weaken scrub / tokenstore invariants. Edit
  there rather than stuffing per-issue boilerplate into the public tracker.
- **Environment:** `.github/workflows/copilot-setup-steps.yml` preinstalls Python
  + deps (and Node/web) and bootstraps a throwaway `.env`, so the agent can run
  `pytest` / `npm` deterministically instead of rediscovering the toolchain. It
  only takes effect once on the default branch.
- **Model selection:** which LLM the coding agent uses is an **org/repo Copilot
  setting** (Settings → Copilot → Coding agent), not a per-assignment parameter —
  do not try to pin a model in `assign-copilot.yml`. Pick it in settings.
- **Custom agents** (`.github/agents/*.md`): not needed for the change loop today —
  it is a single "fix this bug" job, and repo-wide `copilot-instructions.md`
  covers it. Revisit only if we want multiple distinct agent personas with
  different toolsets.

## Self-improvement

The change loop is meant to get better every iteration (each feedback → draft PR →
review). The human's action on the draft (merged clean / merged-with-edits /
rejected) and on the issue (kept / relabelled / closed-not-a-bug) is the training
signal for both triage precision and draft quality. Shadow mode + the
`agent_eligible` gate are the first instrumentation; the full loop (outcome
tracking, an eval corpus seeded from human corrections, a replay CI check, and
postmortem → policy PRs that tighten `copilot-instructions.md`) is tracked in
**#377**.

## Security & abuse resistance

An automated, agent-driven flow is itself a target: attackers scan public repos
for agentic signals (bot-filed issues, `agent-ready` / `copilot` labels, Copilot
PRs) and inject at the human/agent seams — hoping a maintainer who trusts the
automation applies a malicious "patch", or that an LLM agent obeys instructions
hidden in issue text. Defenses, in layers:

**Structural (the load-bearing ones):**

- **Only a Copilot draft PR is a legitimate fix.** It comes from the
  `copilot-swe-agent` bot on a `copilot/*` branch, reviewable line-by-line. A
  zip / "patched build" / diff attached by a non-collaborator is **never** our
  flow — do not download, unzip, run, or apply it.
- **Humans own merge** (branch protection, §4). Agents draft; they never ship.
- **The trigger is write-gated.** `agent-ready` can only be added by the triage
  bot or a maintainer — a drive-by account cannot start the loop. Keep it that
  way (don't let automation add the label from untrusted input).
- **Least-privilege, expiring token** for assignment (§3); the agent runs in
  GitHub's sandbox with its firewall on — don't disable it.
- **Protect `.github/**`** with CODEOWNERS + required review so a PR can't
  quietly weaken a workflow or exfiltrate secrets; pin actions, keep
  `permissions:` minimal, never expose secrets to fork/PR code.

**Treat all user-supplied text as untrusted (prompt-injection):** issue bodies,
comments, and screenshot-derived text can carry "ignore your instructions…"
payloads. The agent's task is the *vetted issue body*, not the comment thread;
`.github/copilot-instructions.md` tells it never to follow instructions embedded
in issue/PR/comment content, never to add dependencies/URLs or touch
secrets/auth/sync on a whim, and never to fetch or apply external attachments.
Everything user-derived still passes `api/feedback_scrub.py` before it is
published.

**Detective:** watch for a brand-new account (age < a few days, 0 repos)
commenting on a bot-filed / `agent-ready` issue within seconds, or any
attachment (esp. `.zip` / binaries) from a non-collaborator. Consider
`Settings → Moderation → Interaction limits` → *Limit to existing users* when a
wave hits (feedback is filed in-app, so external GitHub participation is minimal
and the cost is low).

**Responsive — malicious-contribution runbook:**

1. **Do not** download / open the attachment. Assume it is hostile.
2. Hide the comment: `minimizeComment(classifier: SPAM)` (or *Hide → Spam* in the
   UI).
3. Lock the issue: `gh issue lock <n> --reason spam`.
4. Block the account (needs the `user` scope: `gh auth refresh -s user` then
   `gh api --method PUT /user/blocks/<login>`, or *Block* on their profile).
5. **Report** the account/comment to GitHub (web UI — no API).
6. Assign the legitimate flow (Copilot) so a trusted draft PR replaces the vacuum
   the attacker aimed for. A *working* auto-assign is itself a mitigation: the
   faster a real `copilot/*` PR appears, the less plausible a fake "patch" looks.

## Verify

- Label a **qualifying bug** `agent-ready` → the `Change loop — assign
  agent-ready issues to Copilot` workflow runs and the issue gets
  `copilot-swe-agent` as an assignee; a draft PR follows.
- A **feature**, a **not-actionable** bug, a `backlog`/`later` bug, or a
  `needs_review`/sensitive report is never auto-assigned.
- Shadow mode on → no label is applied, but the decision is logged.

```bash
gh run list --workflow=assign-copilot.yml -R praxys-run/praxys --limit 5
```

## Rollback / Recovery

- **Pause the loop:** disable the workflow (`Actions → Change loop … → ⋯ →
  Disable`) or delete `.github/workflows/assign-copilot.yml`. Triage still *adds*
  the label, but nothing acts on it. Or set `PRAXYS_AGENT_READY_SHADOW=true` to
  stop tagging without disabling anything.
- **Un-assign Copilot:** `gh issue edit <n> --remove-assignee copilot-swe-agent`
  and remove the `agent-ready` label.

## Related

- Trigger source: `api/feedback_triage.py` (`_qualifies_for_agent`, `_agent_ready_shadow`).
- Workflows: `.github/workflows/assign-copilot.yml`, `.github/workflows/copilot-setup-steps.yml`.
- Agent guidance: `.github/copilot-instructions.md`.
- Secrets / flags: [config-and-secrets.md](./config-and-secrets.md) (`COPILOT_ASSIGN_TOKEN`, `PRAXYS_AGENT_READY_SHADOW`).
- Issue-filing setup: [setup-github-app.md](./setup-github-app.md).
- Design: praxys-run/praxys#362 (the change loop); #361 (backend pytest gate); #377 (self-improvement).

---
_Last reviewed: 2026-07-05 · Owner: @dddtc2005_