from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer

from .core.timeutil import iso_z, to_naive_utc


def _parse_dt(v: Any) -> Any:
    if isinstance(v, str):
        v = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if isinstance(v, datetime):
        return to_naive_utc(v)
    return v


# Storage is naive UTC; the wire format is ISO-8601 with a trailing Z.
UTCDateTime = Annotated[datetime, BeforeValidator(_parse_dt), PlainSerializer(iso_z, return_type=str, when_used="json")]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth / user
class RegisterIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(ORM):
    id: str
    email: str
    name: str
    timezone: str
    language: str


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    timezone: str | None = None
    language: Literal["auto", "ta", "en", "tanglish"] | None = None


class PreferenceIn(BaseModel):
    value: Any


class PreferenceOut(ORM):
    key: str
    value: Any


# ---------------------------------------------------------------- productivity
class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str = ""
    priority: int = Field(default=2, ge=1, le=4)
    due_at: UTCDateTime | None = None
    tags: list[str] = []
    goal_id: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    notes: str | None = None
    status: Literal["open", "done"] | None = None
    priority: int | None = Field(default=None, ge=1, le=4)
    due_at: UTCDateTime | None = None
    tags: list[str] | None = None
    goal_id: str | None = None


class TaskOut(ORM):
    id: str
    title: str
    notes: str
    status: str
    priority: int
    due_at: UTCDateTime | None
    tags: list[str]
    goal_id: str | None
    completed_at: UTCDateTime | None
    updated_at: UTCDateTime


class ReminderIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_at: UTCDateTime
    recurrence: Literal["none", "daily", "weekdays", "weekly", "monthly"] = "none"
    style: Literal["en", "tg", "ta"] = "en"


class ReminderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    due_at: UTCDateTime | None = None
    status: Literal["pending", "cancelled"] | None = None
    recurrence: Literal["none", "daily", "weekdays", "weekly", "monthly"] | None = None


class ReminderOut(ORM):
    id: str
    title: str
    due_at: UTCDateTime
    status: str
    recurrence: str
    style: str
    fired_at: UTCDateTime | None
    updated_at: UTCDateTime


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    start_at: UTCDateTime
    end_at: UTCDateTime | None = None
    location: str = ""
    notes: str = ""
    attendees: list[str] = []


class EventUpdate(BaseModel):
    title: str | None = None
    start_at: UTCDateTime | None = None
    end_at: UTCDateTime | None = None
    location: str | None = None
    notes: str | None = None
    attendees: list[str] | None = None


class EventOut(ORM):
    id: str
    title: str
    start_at: UTCDateTime
    end_at: UTCDateTime
    location: str
    notes: str
    attendees: list[str]
    source: str
    updated_at: UTCDateTime


class NoteIn(BaseModel):
    title: str = Field(default="", max_length=300)
    body: str = ""
    kind: Literal["note", "meeting", "summary"] = "note"
    tags: list[str] = []
    pinned: bool = False


class NoteUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None
    pinned: bool | None = None


class NoteOut(ORM):
    id: str
    title: str
    body: str
    kind: str
    tags: list[str]
    pinned: bool
    meta: dict
    updated_at: UTCDateTime


class MilestoneIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class MilestoneOut(ORM):
    id: str
    title: str
    done: bool


class GoalIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    target_date: UTCDateTime | None = None
    milestones: list[MilestoneIn] = []


class GoalUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    target_date: UTCDateTime | None = None
    status: Literal["active", "done", "paused"] | None = None
    manual_progress: int | None = Field(default=None, ge=0, le=100)


class GoalOut(BaseModel):
    id: str
    title: str
    description: str
    target_date: UTCDateTime | None
    status: str
    progress: int
    milestones: list[MilestoneOut]
    updated_at: UTCDateTime


# ---------------------------------------------------------------- conversation
class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    lang_hint: Literal["auto", "ta", "en", "tanglish"] = "auto"


class SpeechSegment(BaseModel):
    text: str
    lang: Literal["ta", "en"]  # TTS voice to use for this run
    voice: str


class ChatOut(BaseModel):
    conversation_id: str
    reply: str
    intent: str
    lang: str
    style: str
    tier: Literal["rules", "llm", "offline"]
    data: dict = {}
    speech: list[SpeechSegment] = []


class MemoryIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: Literal["episodic", "fact"] = "fact"
    importance: float = Field(default=0.6, ge=0, le=1)


class MemoryOut(ORM):
    id: str
    kind: str
    text: str
    importance: float
    created_at: UTCDateTime


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1)
    mime: str = "text/plain"


class DocumentOut(ORM):
    id: str
    title: str
    mime: str
    summary: str
    updated_at: UTCDateTime


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class MeetingIn(BaseModel):
    title: str = "Meeting"
    transcript: str = Field(min_length=1)
    create_tasks: bool = False


class WorkflowIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    trigger: dict = {}
    steps: list[dict] = []
    enabled: bool = True


class WorkflowOut(ORM):
    id: str
    name: str
    trigger: dict
    steps: list[dict]
    enabled: bool


class DeviceIn(BaseModel):
    name: str
    platform: Literal["web", "android", "ios", "desktop"]
    push_token: str | None = None
