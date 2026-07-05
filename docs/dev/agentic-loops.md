# Agentic loops — the self-improvement platform

**Status:** Design / north-star. The **change loop** (#362, PR #373) is the first
instance; most of the shared substrate below is not built yet (tracked in #377).
**Question:** How do AI agents run in *loops* — not one-shot pipelines — that
learn from outcomes to improve the Praxys product *and* its operations?

## TL;DR

- A **loop** is `sense → decide → act → observe → learn` (OODA). The *learn* edge
  — outcomes feeding back to change future behavior — is what makes it a loop and
  not a pipeline. Most "AI features" are pipelines; we want loops.
- There are **two levels**, and conflating them is the usual confusion:
  - **Inner loop** = one unit of work: *feedback → triage → agent drafts PR →
    human reviews → merge/reject.* **One PR ≈ one inner-loop iteration.** It acts;
    it does **not** learn.
  - **Outer loop** = the improvement loop. It watches *many* inner-loop outcomes
    and tunes the **policy** that drives the inner loop (prompts, thresholds,
    rubrics, model, runbooks). It runs periodically / every N outcomes — **not**
    per PR. **This is where "self-improve" lives.**
- It is not one loop but a **family** (change, incident, product/quality,
  meta/eval) — same shape, different signals and actuators.
- They share one **substrate**: trace log · outcome capture · eval corpus + replay
  · shadow→promote · policy-as-code + policy PRs · metrics + autonomy ladder.
  Building that substrate **once** — instead of per loop — is what makes the whole
  product + devops self-improving, rather than one clever automation.

## 1. Loops, not pipelines

```
        ┌─────────────────────────── learn (outer loop) ───────────────────────────┐
        │                                                                           │
   ┌────▼─────┐     ┌──────────┐     ┌────────┐     ┌───────────────┐     ┌─────────┴────────┐
   │  SENSE   │ ──▶ │  DECIDE  │ ──▶ │  ACT   │ ──▶ │    OBSERVE    │ ──▶ │  aggregate + tune │
   │ (signal) │     │ (policy) │     │ (agent)│     │ (outcome edge)│     │  policy (meta)    │
   └──────────┘     └──────────┘     └────────┘     └───────────────┘     └──────────────────┘
        └──────────────── inner loop: one unit of work (≈ one PR) ─────────────────┘
```

The **inner loop** runs once per work item and is stateless across items. The
**outer loop** closes the big arc: it reads the *observe* edge across many items
and edits the **policy** (the prompt / rubric / threshold / model / runbook) that
`DECIDE` uses next time. Without a captured *observe* edge, there is no outer loop
— you have a pipeline that never improves.

## 2. Loop granularity — "one PR, or many loops per PR?"

**One PR is one iteration of the *inner* loop.** Self-improvement is *not*
per-PR; it is the **outer** loop running over a *batch* of PRs/outcomes (e.g.
weekly, or every N drafts). So:

- Don't try to make a single PR "learn" from itself — that's just review.
- Do accumulate the outcomes of many PRs and let the outer loop propose a
  *policy* change (a PR against the prompt/rubric), which the next batch benefits
  from. Improvement compounds across iterations, not within one.

## 3. The loop family

Same OODA shape, different sensors and actuators:

| Loop | Sense | Decide (policy) | Act | Learns from |
|---|---|---|---|---|
| **Change** (built — #362) | user feedback | is this a real, actionable defect? (`agent_eligible`) | Copilot drafts a fix PR | review outcome: merged clean / edited / rejected; post-merge reverts |
| **Incident** (Loop B — `praxys-ops-agent`) | alerts, telemetry anomalies, error spikes | RCA + severity + is it auto-mitigable? | mitigate (restart/rollback/scale/config) + draft postmortem + **hand a fix to the change loop** | MTTR, recurrence, did the mitigation hold |
| **Product / quality** | usage telemetry, feedback themes, funnels | what to build / fix next (prioritization) | draft specs/epics, sometimes prototype PRs | did the target metric move |
| **Meta / eval** | the agents' own outcomes | which policy/prompt/model is underperforming | open **policy PRs**, swap models, adjust thresholds | eval score, acceptance rate, precision |

The meta loop is special: its *product* is the other loops' policies. It is the
engine of "self-improvement."

## 4. The shared substrate (the actual "how")

Every decision point — triage `kind`, `agent_eligible`, priority, sensitivity,
RCA hypothesis, mitigation choice, prioritization — is a **policy**. Each policy
should run on the same six rails:

1. **Trace log.** Record every decision: inputs (scrubbed), the *policy version*,
   the model, and the output. *Today:* App Insights + `api/telemetry.py` log
   feature/usage events; agent **decisions** are only `logger.info`-level (see
   `api/feedback_triage.py` `change-loop agent-ready decision …`). *Gap:* a
   structured, queryable decisions store.
2. **Outcome capture** (the feedback edge). A reconciler that records what the
   human/world actually did — PR merged/edited/rejected, issue close-reason, alert
   resolved/recurred. **This is the missing edge that makes shadow mode able to
   learn.** *Today:* none. *Gap:* a scheduled reconciler (or the ops-agent) that
   joins decisions to GitHub/telemetry outcomes.
3. **Eval corpus + replay.** Labeled examples harvested from human corrections, +
   an offline/CI runner that *scores* a policy and blocks regressions when a
   prompt/threshold changes. *Today:* none. *Gap:* seed a corpus from #2, add a
   replay check.
4. **Shadow → promote.** Run a candidate policy in *compute-but-don't-act* mode
   against live traffic, compare to the current policy **and** to eventual
   outcomes, and promote only if it wins. *Today:* the change loop has the
   *compute-but-don't-act* half (`PRAXYS_AGENT_READY_SHADOW`); it logs but does
   **not** yet compare/promote. *Gap:* the compare + promote half.
5. **Policy-as-code + policy PRs.** The things agents tune — prompts, thresholds,
   `copilot-instructions.md`, runbooks — are versioned files. Improvement =
   the meta-agent opens a **PR** to change them, **gated by the eval harness +
   human review**. Auditable, revertible, never a hidden weight update. *Today:*
   prompts/instructions are already files; nothing opens tuning PRs yet.
6. **Metrics + an autonomy ladder.** Track acceptance rate, human-edit distance,
   MTTR, precision/recall, % autonomous vs escalated — and use them to move each
   task-type up or down the autonomy ladder (§5). *Today:* product telemetry
   exists; agent-quality metrics do not.

## 5. Autonomy ladder & guardrails

Each task-type sits on a dial, raised **only** when the metrics in rail 6 justify
it, and always revertible:

```
suggest-only  →  draft-with-approval  →  auto-act-with-rollback  →  autonomous(narrow)
```

The change loop is at **draft-with-approval** (Copilot drafts; a human merges).
You would only move a *narrow* class (e.g. dependency bumps, trivial typo fixes)
toward auto-act, and only behind a fast rollback.

**Non-negotiable guardrails** (apply to every loop):

- **Human owns the merge/ship gate** — branch protection; agents draft, never
  self-merge (see `docs/ops/change-loop.md`).
- **Scrub before any external surface** — anything user-derived passes
  `api/feedback_scrub.py` before it reaches a public issue/PR (the repo is public).
- **Least-privilege, ephemeral identities** — scoped tokens / OIDC, not standing
  creds (the ops-agent pattern).
- **Eval-gated policy changes + kill switch** — a policy PR must pass the replay
  eval; every loop has an off switch (shadow mode / disable workflow).

## 6. How it maps to the repos

- **`dddtc2005/praxys` (this repo, public).** Hosts the **change loop** and the
  **product/quality loop**, and is the natural home for the **shared substrate**
  (telemetry, the decisions/outcomes store, the eval corpus, the policy files).
- **`dddtc2005/praxys-ops-agent` (private).** Hosts the **incident loop**;
  consumes the same substrate. Event-triggered + ephemeral, acting on praxys via a
  scoped GitHub App + Azure OIDC.
- **Cross-loop edges** (the interesting part): the incident loop can *emit into*
  the change loop (an RCA that needs a code fix becomes an `agent-ready`-eligible
  issue); change-loop rejections and incident postmortems both feed the **eval
  corpus** the meta loop learns from.

## 7. Current state → gaps → phased rollout

**Have:** App Insights + `api/telemetry.py`; the change loop (`api/feedback_triage.py`,
`.github/workflows/assign-copilot.yml`, `copilot-setup-steps.yml`); the shadow
*primitive*; `feedback_scrub` + private-by-construction guardrails; the ops-agent
skeleton.

**Missing (the substrate):** the outcome edge (rail 2), the eval corpus + replay
(rail 3), the shadow *compare/promote* half (rail 4), policy-PR generation
(rail 5), agent-quality metrics + the autonomy dial (rail 6).

**Phases** (tracked in **#377**):

- **Phase 0 — instrument.** Structured decision logging + outcome capture. Shadow
  mode already lets us collect "what would the loop have done" safely.
- **Phase 1 — eval.** Seed the corpus from human corrections; add a replay CI
  check that gates prompt/threshold changes.
- **Phase 2 — close the loop.** Shadow→promote; a meta-agent that turns recurring
  misses into policy PRs; a metrics/autonomy dashboard.

Start where signal is densest (the change loop's triage policy), prove the outer
loop end-to-end on that one policy, then generalize the substrate to the incident
and product loops.

## Glossary

- **Policy** — the tunable decision function at a `DECIDE` node (a prompt, rubric,
  threshold, or model choice). The unit the outer loop improves.
- **Inner / outer loop** — per-work-item execution vs the periodic improvement
  loop over many items.
- **Shadow mode** — compute a decision without acting, to measure a policy safely.
- **Policy PR** — a human-reviewed, eval-gated PR that changes a policy file.
- **Autonomy ladder** — suggest → draft-with-approval → auto-act-with-rollback →
  narrow-autonomous.

## Related

- #362 — the change loop; **PR #373** — its implementation (+ shadow primitive,
  actionability gate). `docs/ops/change-loop.md` — the operator runbook.
- **#377** — the self-improvement platform tracker (the substrate above).
- `dddtc2005/praxys-ops-agent` — the incident loop (Loop B).
- `docs/dev/architecture.md` — the (non-agentic) system architecture.