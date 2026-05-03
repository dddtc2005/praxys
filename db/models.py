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
    demo_of = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    used_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    used_at = Column(DateTime, nullable=True)
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
