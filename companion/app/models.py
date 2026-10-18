"""ORM models. Every table lives in schema ``companion`` (R12); nothing references ``public`` (R2)."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, MetaData, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "companion"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class User(Base):
    """The single operator. ``password_hash`` is argon2; failures drive the lockout (risks.md D1)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebSession(Base):
    """A browser login. Only the SHA-256 of the cookie value is stored, so a DB read can't hijack a session."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    csrf_token: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class ApiToken(Base):
    """A scoped, revocable API token for Shortcuts and scripts (design §5.3, risks.md D4).

    ``scope`` is ``all``, ``read`` or ``log:<tracker_key>``.
    """

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    scope: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Setting(Base):
    """Behaviour settings edited in the app (not secrets: those stay in the environment, R11)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MetricSetting(Base):
    """Our per-metric behaviour for a HealthLog metric (seeded from HealthLog's registry, then ours to edit).

    ``aggregation``: sum | avg | min | max. ``source_priority``: sources to prefer, in order; empty means
    the default policy (merged stream, else the source with the most samples). Daily values outside
    ``[min_value, max_value]`` are treated as missing. ``user_edited`` stops re-seeding from overwriting it.
    """

    __tablename__ = "metric_settings"

    metric: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    aggregation: Mapped[str] = mapped_column(Text)
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_priority: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    analyse: Mapped[bool] = mapped_column(Boolean, server_default="true")
    user_edited: Mapped[bool] = mapped_column(Boolean, server_default="false")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StateOfMindEntry(Base):
    """An Apple Health State of Mind entry, copied from HealthLog's raw archive (deduplicated by HAE's id)."""

    __tablename__ = "mood_entries"

    hae_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    start_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    valence: Mapped[float | None] = mapped_column(Float, nullable=True)
    valence_classification: Mapped[str | None] = mapped_column(Text, nullable=True)
    labels: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    associations: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    payload_id: Mapped[int] = mapped_column(BigInteger)


class FeatureDef(Base):
    """What a daily feature is. Rebuilt with ``daily_features``."""

    __tablename__ = "feature_defs"

    feature: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text)  # healthlog | sleep | stress | energy | workout | mood
    kind: Mapped[str] = mapped_column(Text)  # continuous | count
    analyse: Mapped[bool] = mapped_column(Boolean, server_default="true")


class DailyFeature(Base):
    """One value per (Companion day, feature): the cache every analysis reads, fully rebuilt (design §7)."""

    __tablename__ = "daily_features"

    day: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    feature: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[float] = mapped_column(Float)
