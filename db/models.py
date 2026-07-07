"""SQLAlchemy ORM models for the Praxys database.

The on-disk SQLite filename is still `trainsight.db` — we keep the legacy
filename to avoid user-data migration risk. Only the codebase-level brand
references have been renamed.
"""
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    Index,
    String,
    Float,
    Integer,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    JSON,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    """User model for FastAPI-Users."""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email = Column(String(320), unique=True, index=True, nullable=False)
    hashed_password = Column(String(1024), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_demo = Column(Boolean, default=False, nullable=False)
    # ondelete=SET NULL is a DB-level safety net: the account-deletion path
    # removes a deleted user's demo mirror, but SET NULL guarantees a raw delete
    # can't strand a dangling demo_of reference (issue #366).
    demo_of = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Throttled last-activity timestamp powering the WAU/DAU admin gauge.
    # Written by api/auth.py on authenticated requests, but only when stale
    # (see LAST_SEEN_THROTTLE) so it is not a per-request write. Admin-only
    # aggregate display; never exposed per-user to non-admins.
    last_seen_at = Column(DateTime, nullable=True, index=True)

    # EULA acceptance recorded at registration: proves which Terms/EULA
    # version each user agreed to and when. See api/legal.py::TERMS_VERSION.
    terms_version = Column(String(20), nullable=True)
    terms_accepted_at = Column(DateTime, nullable=True)

    # WeChat Mini Program identity. openid is per-app, unionid spans apps under the
    # same WeChat Open Platform account. We keep email NOT NULL for FastAPI-Users
    # compatibility; WeChat-only users get the synthetic sentinel "wechat:<openid>"
    # (see api/routes/wechat.py::_synthetic_email — unquoted colon cannot collide
    # with a real RFC-5322 address).
    wechat_openid = Column(String(64), unique=True, index=True, nullable=True)
    wechat_unionid = Column(String(64), index=True, nullable=True)
    wechat_nickname = Column(String(100), nullable=True)
    wechat_avatar_url = Column(String(500), nullable=True)

    config = relationship("UserConfig", back_populates="user", uselist=False)
    connections = relationship("UserConnection", back_populates="user")


class Invitation(Base):
    """One-time invitation codes for registration."""

    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(12), unique=True, nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # NOTE: intentionally NO ondelete=SET NULL here. Invitation validity is
    # "is_active AND used_by IS NULL" (see api/invitations.py), so nulling
    # used_by alone would recycle a consumed code. The account-deletion path
    # nulls used_by AND deactivates the code together; a bare DB SET NULL can't
    # flip is_active, so it is deliberately omitted (issue #366).
    used_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    used_at = Column(DateTime, nullable=True)
    # Optional expiry for emailed invitations (waitlist-invite flow). NULL =
    # never expires (admin-generated codes). Enforced in api/invitations.py so
    # an expired code cannot be claimed even though it is still is_active.
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    note = Column(String(200), default="")


class UserConfig(Base):
    """Per-user configuration (mirrors analysis.config.UserConfig dataclass)."""

    __tablename__ = "user_config"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    display_name = Column(String(100), default="")
    unit_system = Column(String(10), default="metric")
    training_base = Column(String(10), default="power")
    preferences = Column(JSON, default=dict)
    thresholds = Column(JSON, default=dict)
    zones = Column(JSON, default=dict)
    goal = Column(JSON, default=dict)
    science = Column(JSON, default=dict)
    zone_labels = Column(String(50), default="standard")
    activity_routing = Column(JSON, default=dict)
    source_options = Column(JSON, default=dict)
    language = Column(String(10), nullable=True)

    user = relationship("User", back_populates="config")


class UserConnection(Base):
    """Per-user platform connections with encrypted credentials."""

    __tablename__ = "user_connections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    platform = Column(String(20), nullable=False)  # garmin, stryd, oura
    encrypted_credentials = Column(LargeBinary, nullable=True)
    wrapped_dek = Column(LargeBinary, nullable=True)
    preferences = Column(JSON, default=dict)  # {"activities": True, "recovery": True, ...}
    last_sync = Column(DateTime, nullable=True)
    status = Column(
        String(20), default="disconnected"
    )  # connected, error, auth_required, expired, disconnected

    # Scheduler backoff state. Without this, a stuck connection (expired
    # token, account-locked, CAPTCHA-gated) made the scheduler retry every
    # 10 min indefinitely, which on 2026-04-25 escalated Garmin's bot
    # mitigation from transient 429s to a persistent CAPTCHA flag against
    # the App Service outbound IP. consecutive_failures drives exponential
    # backoff; next_retry_at gates the scheduler (skip while in future);
    # last_error captures a short tag for the UI. All three reset on
    # successful sync or when the user reconnects credentials.
    consecutive_failures = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)

    user = relationship("User", back_populates="connections")
    __table_args__ = (
        UniqueConstraint("user_id", "platform", name="uq_user_platform"),
    )


class Activity(Base):
    """Activity data (merged from Garmin/Stryd/etc.)."""

    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    activity_id = Column(String(100), nullable=False)
    date = Column(Date, nullable=False, index=True)
    activity_type = Column(String(50), default="running")
    distance_km = Column(Float, nullable=True)
    duration_sec = Column(Float, nullable=True)
    avg_power = Column(Float, nullable=True)
    max_power = Column(Float, nullable=True)
    avg_hr = Column(Float, nullable=True)
    max_hr = Column(Float, nullable=True)
    avg_pace_min_km = Column(String(20), nullable=True)
    avg_pace_sec_km = Column(Float, nullable=True)
    elevation_gain_m = Column(Float, nullable=True)
    avg_cadence = Column(Float, nullable=True)
    training_effect = Column(Float, nullable=True)
    rss = Column(Float, nullable=True)
    trimp = Column(Float, nullable=True)
    rtss = Column(Float, nullable=True)
    cp_estimate = Column(Float, nullable=True)
    load_score = Column(Float, nullable=True)
    start_time = Column(String(50), nullable=True)
    source = Column(String(20), default="garmin")

    __table_args__ = (
        UniqueConstraint("user_id", "activity_id", name="uq_user_activity"),
    )


class ActivitySplit(Base):
    """Per-interval split data within activities."""

    __tablename__ = "activity_splits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    activity_id = Column(String(100), nullable=False)
    split_num = Column(Integer, nullable=False)
    distance_km = Column(Float, nullable=True)
    duration_sec = Column(Float, nullable=True)
    avg_power = Column(Float, nullable=True)
    avg_hr = Column(Float, nullable=True)
    max_hr = Column(Float, nullable=True)
    avg_pace_min_km = Column(String(20), nullable=True)
    avg_pace_sec_km = Column(Float, nullable=True)
    avg_cadence = Column(Float, nullable=True)
    elevation_change_m = Column(Float, nullable=True)


class ActivitySample(Base):
    """Per-second time-series data for an activity.

    One row per second per activity. Columns cover the union of all connector
    field sets; connector-specific fields are NULL for other sources. The
    unique constraint on (user_id, activity_id, t_sec) makes re-syncs idempotent —
    duplicate writes are silently ignored via INSERT OR IGNORE.

    Storage estimate: ~3,600 rows/hour of running. At SQLite scale for
    personal use this is negligible; multi-user growth is managed by the
    user_id index enabling efficient per-user pruning.
    """

    __tablename__ = "activity_samples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    activity_id = Column(String(100), nullable=False)
    source = Column(String(20), nullable=False)  # stryd | garmin | coros | strava

    # Seconds since epoch — the time axis for all other fields
    t_sec = Column(Integer, nullable=False)

    # Core — present across all connectors
    power_watts = Column(Float, nullable=True)
    hr_bpm = Column(Float, nullable=True)
    speed_ms = Column(Float, nullable=True)
    pace_sec_km = Column(Float, nullable=True)
    cadence_spm = Column(Float, nullable=True)
    altitude_m = Column(Float, nullable=True)
    distance_m = Column(Float, nullable=True)  # cumulative from activity start

    # GPS — Garmin, Strava, COROS
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    grade_pct = Column(Float, nullable=True)
    temperature_c = Column(Float, nullable=True)

    # Stryd running dynamics
    ground_time_ms = Column(Float, nullable=True)
    oscillation_mm = Column(Float, nullable=True)
    leg_spring_kn_m = Column(Float, nullable=True)
    vertical_ratio = Column(Float, nullable=True)
    form_power_watts = Column(Float, nullable=True)

    # Garmin-specific
    respiration_rate = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "activity_id", "t_sec", name="uq_sample_user_activity_t"),
        Index("ix_sample_activity", "activity_id"),
    )


class RecoveryData(Base):
    """Sleep and readiness data (from Oura, Garmin, etc.)."""

    __tablename__ = "recovery_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    readiness_score = Column(Float, nullable=True)
    hrv_avg = Column(Float, nullable=True)
    resting_hr = Column(Float, nullable=True)
    sleep_score = Column(Float, nullable=True)
    total_sleep_sec = Column(Float, nullable=True)
    deep_sleep_sec = Column(Float, nullable=True)
    rem_sleep_sec = Column(Float, nullable=True)
    body_temp_delta = Column(Float, nullable=True)
    source = Column(String(20), default="oura")

    __table_args__ = (
        UniqueConstraint("user_id", "date", "source", name="uq_user_date_recovery"),
    )


class FitnessData(Base):
    """Per-metric fitness data (VO2max, LTHR, CP estimate, etc.)."""

    __tablename__ = "fitness_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    metric_type = Column(String(30), nullable=False)
    value = Column(Float, nullable=True)
    value_str = Column(String(100), nullable=True)
    source = Column(String(20), default="garmin")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "date", "metric_type", "source", name="uq_user_date_metric"
        ),
    )


class AiInsight(Base):
    """AI-generated insights — written by the post-sync LLM runner
    (``api/insights_runner.py``) and the legacy CLI / MCP push paths."""

    __tablename__ = "ai_insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    insight_type = Column(String(30), nullable=False)  # training_review, daily_brief, race_forecast
    headline = Column(String(200), nullable=True)
    summary = Column(Text, nullable=True)
    findings = Column(JSON, default=list)  # [{type, text}, ...]
    recommendations = Column(JSON, default=list)  # [str, ...]
    meta = Column(JSON, default=dict)  # data_range, training_base, dataset_hash, etc.
    # Issue #103: bilingual payload. Top-level fields stay English so legacy
    # CLI/MCP push paths keep working; the frontend reads
    # translations[locale] when present and falls back to top-level English.
    translations = Column(JSON, default=dict)
    generated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "insight_type", name="uq_user_insight_type"),
    )


class CacheRevision(Base):
    """Per-(user, scope) monotonic counter for HTTP cache revalidation (issue #147).

    A scope groups one or more underlying tables that an endpoint pack reads;
    sync writers and config-mutation routes bump the relevant scopes after a
    commit. The ETag for each /api/* response is built from the revisions of
    the scopes that endpoint actually consumes, so a goal edit won't bust the
    Today page's ETag and a sync writing only activities won't bust the
    Science page's ETag.

    A counter is preferred over a timestamp because two writes within the same
    second still produce distinct revisions — no risk of a 304 hiding a fresh
    write that landed in the same wall-clock second as the prior request.
    """

    __tablename__ = "cache_revisions"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    scope = Column(String(20), primary_key=True)
    revision = Column(Integer, nullable=False, default=0)
    bumped_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DashboardCache(Base):
    """Per-(user, section) materialized response payload (issue #148 / L3).

    Each row stores one endpoint's full JSON response, tagged with the
    ``source_version`` it was computed from — a pipe-separated string of
    the L2 revision counters for the scopes the endpoint reads, with
    scopes sorted alphabetically so two callers produce byte-identical
    strings. Example for ``today`` on 2026-04-26 with all-zero revisions:
    ``"activities=0|config=0|fitness=0|plans=0|recovery=0|d=2026-04-26"``.

    Read path is two-step:

      1. ``SELECT payload_json, source_version FROM dashboard_cache``
         keyed on ``(user_id, section)``. If ``source_version`` matches the
         currently-computed value, return ``payload_json`` directly —
         sub-50 ms cache hit.
      2. On mismatch (post-write or first visit), fall through to the
         original pack-based compute path; write the result back keyed on
         the snapshot taken BEFORE the compute. A concurrent write that
         lands mid-compute leaves the cache row labelled with the older
         revisions; the very next read sees fresh revisions, mismatches,
         and recomputes — never wrong, just sometimes a wasted compute.

    Why a single table instead of one-per-section (the issue's literal
    spec): same correctness, half the schema. ``section`` is a small
    closed enum (enforced by the CHECK constraint below), the PK
    ``(user_id, section)`` has one row per pair, and SQLite's
    database-level write lock means per-section tables wouldn't even
    reduce contention. Documented in the PR for #148.

    The CHECK constraint on ``section`` makes the closed enum
    storage-layer enforced: a buggy writer that bypasses
    ``api.dashboard_cache.write_cache`` cannot leave an orphan row
    keyed on a typo'd section name.
    """

    __tablename__ = "dashboard_cache"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    section = Column(String(32), primary_key=True)
    source_version = Column(String(255), nullable=False)
    payload_json = Column(LargeBinary, nullable=False)
    computed_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "section IN ('today','training','goal')",
            name="ck_dashboard_cache_section",
        ),
    )


class TrainingPlan(Base):
    """Planned workouts (from Stryd, AI-generated, etc.)."""

    __tablename__ = "training_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    workout_type = Column(String(50), nullable=True)
    planned_duration_min = Column(Float, nullable=True)
    planned_distance_km = Column(Float, nullable=True)
    target_power_min = Column(Float, nullable=True)
    target_power_max = Column(Float, nullable=True)
    target_hr_min = Column(Float, nullable=True)
    target_hr_max = Column(Float, nullable=True)
    target_pace_min = Column(String(20), nullable=True)
    target_pace_max = Column(String(20), nullable=True)
    workout_description = Column(Text, nullable=True)
    source = Column(String(20), default="stryd")  # stryd or ai
    # External platform's identifier for this workout, when the plan
    # row was imported from a platform calendar (e.g. Stryd's workout
    # `id`). NULL for AI-generated rows. Lets `/api/plan` join AI rows
    # against platform rows on date and detect mismatches: if Praxys
    # pushed a workout, we know its external_id from the push log; if
    # the platform has a workout with a different external_id on that
    # date, it's user-created (mismatch).
    external_id = Column(String(100), nullable=True)
    # Absolute UTC instant of the workout start, as Stryd serializes it
    # ("2026-06-29T16:00:00Z"). The canonical source for which calendar day
    # a workout belongs to: clients bucket it in the viewer's tz. `date` is
    # a server-truncated fallback for backend windowing and legacy rows.
    start_time = Column(DateTime, nullable=True)
    meta = Column(JSON, nullable=True)  # for AI plans: generated_at, cp_at_generation

    __table_args__ = (
        UniqueConstraint(
            "user_id", "date", "source", "workout_type", name="uq_user_date_plan"
        ),
    )


class SystemAnnouncement(Base):
    """Admin-configurable site-wide notification banners.

    Active announcements are returned by GET /api/announcements to all
    authenticated users and rendered as dismissible banners in the web UI.
    Dismissed banner IDs are stored client-side (localStorage) so they
    don't re-appear after reload without server-side per-user tracking.
    """

    __tablename__ = "system_announcements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    type = Column(String(20), default="info", nullable=False)  # info | warning | success
    is_active = Column(Boolean, default=True, nullable=False)
    link_text = Column(String(100), nullable=True)
    link_url = Column(String(500), nullable=True)
    # Issue #355: bilingual payload. Top-level title/body/link_text stay the
    # canonical base (English) fallback; translations["zh"] = {title, body,
    # link_text} overrides per locale. Mirrors the AiInsight.translations
    # contract (#103): the frontend prefers translations[locale] and falls back
    # to the top-level fields, so single-language announcements keep working.
    translations = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WaitlistSignup(Base):
    """Private-alpha waitlist captures.

    Praxys is invitation-only during alpha; the login page lets prospective
    users drop their email + a one-line note so we can reach back when a
    slot opens. We store these locally rather than relying on the support
    inbox alone — that way a busy inbox can't lose a lead.
    """

    __tablename__ = "waitlist_signups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # unique=True is defense-in-depth: the route already does a check-then-
    # update for idempotent refresh, but a unique index closes the race
    # window for two near-simultaneous submits with the same address.
    email = Column(String(320), nullable=False, unique=True, index=True)
    note = Column(String(500), default="")
    locale = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    invited_at = Column(DateTime, nullable=True)
    # ondelete=SET NULL: a waitlist lead survives if the invitation it was sent
    # is later deleted (e.g. the inviting admin's account is removed); the link
    # is simply cleared rather than blocking the delete (issue #366).
    invitation_id = Column(Integer, ForeignKey("invitations.id", ondelete="SET NULL"), nullable=True)


class Feedback(Base):
    """User-submitted bug reports, feature requests, and general feedback.

    Canonical store for the in-app "Send feedback" entrance (web + mini
    program). The raw ``message`` is kept here (private, server-side only) so
    a human/admin can always see exactly what the user wrote. A background
    triage step (:mod:`api.feedback_triage`) then PII-scrubs + classifies the
    submission and — when GitHub is configured — opens an issue in the
    operator-chosen triage repo so an agent can pick it up. The scrubbed
    title/body that actually left the system are stored in ``ai_title`` /
    ``ai_body`` for auditability (what did we publish about this user?).

    Mirrors the WaitlistSignup pattern: store locally first so a lead/report
    survives even if the downstream (GitHub, support inbox) is unavailable.
    """

    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Nullable + SET NULL on delete: a deleted user shouldn't cascade-delete
    # the feedback (it's operationally useful history), but we also don't want
    # a dangling FK. The submitter is always set at creation time.
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # bug | feature | other — validated at the route layer (Literal), stored
    # as a stable English string the frontend maps to a localized label.
    kind = Column(String(20), nullable=False, default="other")
    # Raw, unscrubbed user text. Never leaves the server verbatim — only the
    # scrubbed ai_body is published to GitHub.
    message = Column(Text, nullable=False)
    # Client-supplied diagnostic context (route, app version, user agent,
    # viewport, locale). Captured automatically so users don't have to
    # describe their environment. Scrubbed before publication.
    context_json = Column(JSON, nullable=True)
    locale = Column(String(10), nullable=True)
    # new | triaged | needs_review | issue_created | resolved | failed | rejected
    # ``resolved`` is set when the linked GitHub issue is closed (synced back via
    # the admin "Sync from GitHub" action); a reopen flips it to issue_created.
    status = Column(String(20), nullable=False, default="new", index=True)
    # Outputs of the triage step — the scrubbed, agent-ready title/body and
    # labels that were (or would be) published. Kept for audit + admin review.
    ai_title = Column(String(200), nullable=True)
    ai_body = Column(Text, nullable=True)
    ai_labels = Column(JSON, nullable=True)
    # LLM-suggested triage priority: low | medium | high | critical. NULL when
    # triaged without an LLM (the rule-based fallback doesn't guess a priority)
    # or not yet triaged. Mirrored to a ``priority: <value>`` GitHub label.
    priority = Column(String(10), nullable=True)
    github_issue_number = Column(Integer, nullable=True)
    github_issue_url = Column(String(500), nullable=True)
    # Last triage/publish error (truncated) so admins can see why a row is
    # stuck in "failed" without digging through server logs.
    error = Column(String(500), nullable=True)
    # --- Optional screenshot attachment (issue #337) ---
    # References (storage keys) for user-attached screenshots — private,
    # admin-only. The raw image never sits on this row or in a public issue;
    # only the key lives here (Azure Blob now, Tencent COS later). See
    # api/feedback_storage.py. A list of 0-3 keys, or NULL when none attached.
    image_keys = Column(JSON, nullable=True)
    # Vision-LLM-derived, PII-scrubbed textual description of the screenshot(s)
    # (UI state, visible error text). This is the ONLY image-derived text that
    # may be published to a (public) issue — never the image itself.
    image_description = Column(Text, nullable=True)
    # Vision sensitivity verdict feeding the same gate as the text path: True =
    # the model saw faces / emails / names / health-or-performance data. NULL =
    # not yet analysed (or no vision model), which the gate treats as "unsafe
    # to auto-publish" and parks for admin review.
    image_sensitive = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AppConfig(Base):
    """System-wide operational config as a small key-value store.

    Praxys previously had only per-user config (UserConfig). This table holds
    a handful of operator-owned flags that are toggled at runtime from the
    Admin page (not env vars) — currently the self-registration gate and its
    seat cap. Values are stored as strings and parsed by api/app_config.py,
    which owns the typed getters/setters and the safe defaults for missing
    keys, so a fresh DB behaves identically to one that has never been touched.
    """

    __tablename__ = "app_config"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # ondelete=SET NULL: keep the operator flag row when the admin who last
    # toggled it is deleted; just drop the stale reference (issue #366).
    updated_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ServiceIncident(Base):
    """An operator-declared service incident shown on the public status page.

    Models the Atlassian Statuspage-style lifecycle: an incident opens with an
    ``impact`` and moves through ``status`` states (investigating -> identified
    -> monitoring -> resolved) via a running timeline of
    :class:`ServiceIncidentUpdate` rows. Active (unresolved) incidents drive the
    overall banner on ``GET /api/status``; resolved ones remain as history.
    """

    __tablename__ = "service_incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    # investigating | identified | monitoring | resolved -- validated at the
    # route layer. An incident is "active" while status != 'resolved'.
    status = Column(String(20), nullable=False, default="investigating")
    # minor | major | critical -- maps to the public severity of the banner
    # (degraded / partial outage / major outage).
    impact = Column(String(20), nullable=False, default="minor")
    # When the incident began affecting users (operator-settable; defaults to
    # creation time). Distinct from created_at, the row's insert timestamp.
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Set when status flips to 'resolved'; NULL while the incident is open.
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    updates = relationship(
        "ServiceIncidentUpdate",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="ServiceIncidentUpdate.created_at",
    )


class ServiceIncidentUpdate(Base):
    """One timeline entry on a :class:`ServiceIncident`.

    Each post records the incident ``status`` at that moment plus the
    operator's ``body`` message, so the public status page can render a
    chronological narrative ("Identified -- we found the cause", "Resolved").
    """

    __tablename__ = "service_incident_updates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(
        Integer,
        ForeignKey("service_incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The incident status as of this update (investigating | identified |
    # monitoring | resolved) -- lets the timeline show state transitions.
    status = Column(String(20), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    incident = relationship("ServiceIncident", back_populates="updates")
