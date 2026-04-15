"""SQLAlchemy ORM models for the Trainsight database."""
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    Column,
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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    training_base = Column(String(10), default="power")
    preferences = Column(JSON, default=dict)
    thresholds = Column(JSON, default=dict)
    zones = Column(JSON, default=dict)
    goal = Column(JSON, default=dict)
    science = Column(JSON, default=dict)
    zone_labels = Column(String(50), default="standard")
    activity_routing = Column(JSON, default=dict)
    source_options = Column(JSON, default=dict)

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
    )  # connected, error, expired, disconnected

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
