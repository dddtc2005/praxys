"""Background triage for user feedback: scrub → classify → publish.

Pipeline (runs as a FastAPI ``BackgroundTask`` after the submit returns):

1. Load the :class:`db.models.Feedback` row in its *own* DB session — the
   request session is closed by the time a background task runs. (Same
   transaction-ownership pattern as :mod:`api.insights_runner`.)
2. Deterministically scrub the raw message + context (:mod:`api.feedback_scrub`).
3. If Azure OpenAI is configured, ask the model to turn the scrubbed report
   into a clean issue title + structured markdown body and to confirm the
   ``kind``. The model only ever sees already-scrubbed text. When the model
   is unavailable, a deterministic rule-based title/body is used instead.
4. Run the final title + body through the scrubber *again* (we never trust the
   model as the sole redactor for a public repo).
5. If GitHub is configured, open an issue (labeled so an agent can pick it up)
   and record the number/url. Otherwise leave the row ``triaged`` for an admin
   to promote from the Admin page.

Nothing here raises: a failure marks the row ``failed`` with a short error and
returns. The submit endpoint already returned 200 to the user.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from api import feedback_scrub, github_issues, llm, telemetry

logger = logging.getLogger(__name__)

# Stable English labels the frontend / agents key off. Kind → GitHub label.
_KIND_LABEL = {"bug": "bug", "feature": "enhancement", "other": "feedback"}
_VALID_KINDS = set(_KIND_LABEL)

_TRIAGE_MODEL = llm.INSIGHT_MODEL


def _autofile_without_ai() -> bool:
    """Whether to auto-file to the public tracker when the LLM gate is absent.

    Off by default: with no AI to judge residual sensitivity, holding for an
    admin is the safe choice for a public repo. An operator who accepts the
    scrub-only risk can set PRAXYS_FEEDBACK_AUTOFILE_WITHOUT_AI=true.
    """
    return (os.environ.get("PRAXYS_FEEDBACK_AUTOFILE_WITHOUT_AI", "") or "").lower() in ("1", "true", "yes")


def _gate_blocks_publish(*, used_llm: bool, llm_flag: bool, body: str) -> bool:
    """Decide whether to withhold a report from auto-opening a public issue.

    Blocks when: (a) the scrubber removed a key/token — a strong signal the
    user pasted a secret; (b) the LLM judged the report still sensitive; or
    (c) there is no LLM verdict and the operator hasn't opted into scrub-only
    auto-filing. Blocked rows are parked as ``needs_review`` for an admin.
    """
    if "[redacted-key]" in body or "[redacted-token]" in body:
        return True
    if used_llm:
        return bool(llm_flag)
    return not _autofile_without_ai()


def _system_prompt() -> str:
    return (
        "You are a triage assistant for Praxys, an endurance-training analytics app. "
        "You convert a user's in-app feedback into a clean, actionable GitHub issue "
        "for an engineering team and AI coding agents.\n\n"
        "Rules:\n"
        "- The input has already been PII-scrubbed; if you still see anything that "
        "looks like personal data (emails, names, tokens, IPs), do NOT reproduce it.\n"
        "- Write a concise, specific issue title (<=80 chars, no trailing period).\n"
        "- Write a structured Markdown body with sections: a one-line summary, "
        "'Steps to reproduce' or 'Expected behavior' for bugs, 'Proposed change' "
        "for features, and an 'Environment' bullet list from the provided context.\n"
        "- Be factual; do not invent details the user didn't provide.\n"
        "- Classify the report as exactly one kind: bug, feature, or other.\n"
        "- The input is ALREADY PII-scrubbed (emails, tokens, keys, IPs, file "
        "paths, and long numbers are removed and shown as [redacted-*]). Set "
        "contains_sensitive=true ONLY if the report STILL clearly contains "
        "personal data, health details about an identifiable person, account or "
        "credential information, or private third-party info unsuitable for a "
        "public tracker. A normal product bug report or feature request is NOT "
        "sensitive — return false. Default to false, and ALWAYS include the "
        "contains_sensitive field in your response.\n"
        "Respond with a JSON object: "
        "{\"kind\": str, \"title\": str, \"body\": str, \"contains_sensitive\": bool}."
    )


def _user_payload(kind: str, message: str, context: dict) -> str:
    import json

    return json.dumps(
        {"reported_kind": kind, "message": message, "context": context},
        ensure_ascii=False,
    )


def _rule_based(kind: str, message: str, context: dict) -> tuple[str, str]:
    """Deterministic fallback title + body when the LLM is unavailable."""
    first_line = (message.strip().splitlines() or [""])[0]
    title = (first_line[:77] + "...") if len(first_line) > 80 else (first_line or f"User {kind}")
    label = {"bug": "Bug report", "feature": "Feature request"}.get(kind, "Feedback")
    lines = [f"**{label}** submitted via in-app feedback.", "", "## Report", message.strip(), ""]
    if context:
        lines.append("## Environment")
        for key, val in context.items():
            lines.append(f"- **{key}**: {val}")
        lines.append("")
    return title, "\n".join(lines)


def _publish_footer(feedback_id: int, user_id: Optional[str]) -> str:
    """Audit footer. Identifies the submitter by a non-reversible hash only."""
    who = telemetry.hash_user_id(user_id) if user_id else "anonymous"
    return (
        "\n\n---\n"
        f"_Auto-filed from Praxys in-app feedback (id `{feedback_id}`, "
        f"reporter `{who}`). PII-scrubbed before publication._"
    )


def triage_and_publish(feedback_id: int, *, _session: Optional[Session] = None) -> dict:
    """Triage one feedback row and publish it. Returns a small status dict.

    Args:
        feedback_id: PK of the :class:`db.models.Feedback` row to process.
        _session: Test-only injected session; otherwise a fresh ``SessionLocal``
            is opened and owned by this function.
    """
    from db.models import Feedback
    from db.session import SessionLocal

    owns_session = _session is None
    db = _session or (SessionLocal() if SessionLocal is not None else None)
    if db is None:
        logger.error("triage_and_publish: DB not initialized")
        return {"status": "error", "reason": "db_uninitialized"}

    row = None
    issue: dict | None = None
    try:
        row = db.query(Feedback).filter(Feedback.id == feedback_id).first()
        if row is None:
            logger.warning("triage_and_publish: feedback %s not found", feedback_id)
            return {"status": "error", "reason": "not_found"}
        if row.status not in ("new", "failed"):
            # Idempotent: don't re-publish an already-handled row.
            return {"status": "skipped", "reason": row.status}

        kind = row.kind if row.kind in _VALID_KINDS else "other"
        clean_message = feedback_scrub.scrub_text(row.message)
        clean_context = feedback_scrub.scrub_context(row.context_json)

        used_llm = False
        llm_flag = False
        client = llm.get_client()
        title = body = None
        if client is not None:
            result = llm.chat_json(
                client,
                system=_system_prompt(),
                user=_user_payload(kind, clean_message, clean_context),
                model=_TRIAGE_MODEL,
                max_completion_tokens=1200,
                # Deterministic: triage/classification shouldn't vary run-to-run.
                # Low temperature minimises the rare false-positive sensitivity
                # flip that parks benign reports.
                temperature=0.0,
                insight_type="feedback_triage",
            )
            if result and isinstance(result.get("title"), str) and isinstance(result.get("body"), str):
                maybe_title = result["title"].strip()
                maybe_body = result["body"].strip()
                # Only trust the model when it actually produced content. Empty
                # title/body would otherwise drop the user's report and publish a
                # contentless issue; treat it as "no usable LLM output" so the
                # rule-based fallback (which carries the real message) runs and
                # the gate falls back to its fail-safe no-LLM path.
                if maybe_title and maybe_body:
                    title = maybe_title
                    body = maybe_body
                    llm_kind = str(result.get("kind", "")).lower()
                    if llm_kind in _VALID_KINDS:
                        kind = llm_kind
                    # Missing field → treat as sensitive (fail safe).
                    llm_flag = bool(result.get("contains_sensitive", True))
                    used_llm = True

        if not title or not body:
            title, body = _rule_based(kind, clean_message, clean_context)

        # Belt-and-suspenders: never trust the model as the sole redactor.
        title = feedback_scrub.scrub_text(title)[:120] or f"User {kind}"
        body = feedback_scrub.scrub_text(body) + _publish_footer(feedback_id, row.user_id)

        labels = [_KIND_LABEL[kind], "feedback"]
        if used_llm:
            labels.append("ai-triaged")

        row.kind = kind
        row.ai_title = title
        row.ai_body = body
        row.ai_labels = labels

        if not github_issues.is_configured():
            # No GitHub configured — scrubbed + classified, awaiting manual
            # promotion from the Admin page.
            row.status = "triaged"
            row.error = None
        elif _gate_blocks_publish(used_llm=used_llm, llm_flag=llm_flag, body=body):
            # The report may still carry sensitive content — don't auto-open a
            # public issue. Park it for an admin to review / approve.
            row.status = "needs_review"
            row.error = None
        else:
            issue = github_issues.create_issue(title=title, body=body, labels=labels)
            if issue and issue.get("number"):
                row.github_issue_number = issue["number"]
                row.github_issue_url = issue.get("url")
                row.status = "issue_created"
                row.error = None
            else:
                row.status = "failed"
                row.error = "github_publish_failed"

        db.commit()
        telemetry.record_feedback(kind=kind, status=row.status)
        return {"status": row.status, "kind": kind, "used_llm": used_llm}

    except Exception:
        logger.exception("triage_and_publish failed for feedback %s", feedback_id)
        try:
            # If create_issue already opened a GitHub issue but the commit
            # failed, persist issue_created so a later retry can't file a
            # duplicate. Roll back the broken transaction and re-load the row
            # before writing the terminal state.
            db.rollback()
            recovered = db.query(Feedback).filter(Feedback.id == feedback_id).first()
            if recovered is not None:
                if issue and issue.get("number"):
                    recovered.github_issue_number = issue["number"]
                    recovered.github_issue_url = issue.get("url")
                    recovered.status = "issue_created"
                    recovered.error = None
                else:
                    recovered.status = "failed"
                    recovered.error = "triage_exception"
                db.commit()
                telemetry.record_feedback(kind=recovered.kind, status=recovered.status)
                return {"status": recovered.status}
        except Exception:
            db.rollback()
        return {"status": "failed"}
    finally:
        if owns_session:
            db.close()
