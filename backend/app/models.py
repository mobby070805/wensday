"""ORM models. Portable across SQLite (dev/test) and PostgreSQL (prod): string UUIDs, JSON columns.

Every user-owned, syncable table carries `updated_at` and `deleted_at` (tombstone) so devices
can pull incremental changes via `GET /sync?since=`.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship

from .core.timeutil import utcnow


def _id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Stamped:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Owned(Stamped):
    @declared_attr
    def user_id(cls) -> Mapped[str]:
        return mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True)


# ------------------------------------------------------------------ identity
class User(Stamped, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    language: Mapped[str] = mapped_column(String(16), default="auto")  # auto | ta | en | tanglish


class OAuthAccount(Stamped, Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "subject"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(255))
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    jti: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Device(Owned, Base):
    __tablename__ = "devices"
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(32))  # web | android | ios | desktop
    push_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Preference(Owned, Base):
    __tablename__ = "preferences"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)


# ------------------------------------------------------------------ memory
class Memory(Owned, Base):
    __tablename__ = "memories"
    kind: Mapped[str] = mapped_column(String(16), default="episodic")  # episodic | fact
    text: Mapped[str] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Conversation(Owned, Base):
    __tablename__ = "conversations"
    title: Mapped[str] = mapped_column(String(200), default="")
    lang: Mapped[str] = mapped_column(String(16), default="en")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Owned, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    text: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(16), default="en")
    intent: Mapped[str | None] = mapped_column(String(48), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


# ------------------------------------------------------------------ productivity
class Goal(Owned, Base):
    __tablename__ = "goals"
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    target_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | done | paused
    manual_progress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    milestones: Mapped[list["Milestone"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class Milestone(Stamped, Base):
    __tablename__ = "milestones"
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    done: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(Owned, Base):
    __tablename__ = "tasks"
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open | done
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 1 low .. 4 urgent
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    goal_id: Mapped[str | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Reminder(Owned, Base):
    __tablename__ = "reminders"
    __table_args__ = (Index("ix_reminders_due", "status", "due_at"),)
    title: Mapped[str] = mapped_column(String(300))
    due_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | fired | cancelled
    recurrence: Mapped[str] = mapped_column(String(16), default="none")  # none | daily | weekdays | weekly | monthly
    style: Mapped[str] = mapped_column(String(4), default="en")  # language style to speak the reminder in
    fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Event(Owned, Base):
    __tablename__ = "events"
    title: Mapped[str] = mapped_column(String(300))
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    location: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    attendees: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(16), default="local")  # local | google
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Note(Owned, Base):
    __tablename__ = "notes"
    title: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(16), default="note")  # note | meeting | summary
    tags: Mapped[list] = mapped_column(JSON, default=list)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)  # filled lazily by knowledge search


class Document(Owned, Base):
    __tablename__ = "documents"
    title: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(80), default="text/plain")
    text: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    chunks: Mapped[list["DocumentChunk"]] = relationship(cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)


class EmailDraft(Owned, Base):
    __tablename__ = "email_drafts"
    recipient: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | sent | queued | discarded
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lang: Mapped[str] = mapped_column(String(4), default="en")


# ------------------------------------------------------------------ automation
class Workflow(Owned, Base):
    __tablename__ = "workflows"
    name: Mapped[str] = mapped_column(String(120))
    trigger: Mapped[dict] = mapped_column(JSON, default=dict)  # {"type":"phrase|schedule|event", ...}
    steps: Mapped[list] = mapped_column(JSON, default=list)  # [{"tool":"create_task","args":{...}}, ...]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkflowRun(Owned, Base):
    __tablename__ = "workflow_runs"
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | failed
    log: Mapped[list] = mapped_column(JSON, default=list)


class PluginSetting(Owned, Base):
    __tablename__ = "plugin_settings"
    __table_args__ = (UniqueConstraint("user_id", "plugin"),)
    plugin: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    granted_scopes: Mapped[list] = mapped_column(JSON, default=list)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class PendingAction(Owned, Base):
    """A side-effecting action awaiting the user's confirmation (e.g. sending an email)."""

    __tablename__ = "pending_actions"
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | done | cancelled | expired
    expires_at: Mapped[datetime] = mapped_column(DateTime)


# Tables exposed through the incremental sync endpoint
SYNCABLE = {"tasks": Task, "reminders": Reminder, "events": Event, "notes": Note, "goals": Goal}
