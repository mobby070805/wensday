"""Meeting summaries: transcript -> summary, decisions, action items (optionally turned into tasks).

Uses the LLM when reachable; otherwise a multilingual heuristic that recognises English and
Tanglish/Tamil cues ("pannanum", "venum", "mudivu", "முடிவு").
"""
from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.knowledge import extractive_summary
from app.models import Note
from . import tasks as tasks_svc

_SPEAKER = re.compile(r"^\s*([A-Z][\w .'-]{0,30}):\s*(.+)$")
_ACTION = re.compile(r"\b(action item|to-?do|will|need to|needs to|should|must|follow up|please|by (?:monday|tuesday|wednesday|thursday|friday|tomorrow|eod))\b"
                     r"|pannanum|pannunga|panren|panniduven|venum|seiyanum|anuppanum|செய்ய|வேண்டும்|பண்ணனும்", re.I)
_DECISION = re.compile(r"\b(decided|agreed|finali[sz]ed|approved|concluded|confirmed)\b|mudivu|mudivaachu|ok nu mudivu|முடிவு|ஒப்புக்கொண்ட", re.I)
_SENT = re.compile(r"(?<=[.!?।])\s+|\n+")


def heuristic(transcript: str) -> dict:
    actions, decisions = [], []
    for line in (s.strip() for s in _SENT.split(transcript) if s.strip()):
        m = _SPEAKER.match(line)
        owner, text = (m.group(1), m.group(2)) if m else (None, line)
        if _DECISION.search(text):
            decisions.append(text.strip(" ."))
        elif _ACTION.search(text):
            actions.append({"text": text.strip(" ."), "owner": owner})
    plain = "\n".join(_SPEAKER.sub(r"\2", ln) for ln in transcript.splitlines())
    return {"summary": extractive_summary(plain), "decisions": decisions, "action_items": actions}


async def summarize(llm, transcript: str) -> dict:
    if llm is not None and getattr(llm, "has_remote", False):
        try:
            data = await llm.json_task(
                system="Summarise the meeting transcript. Reply ONLY with JSON: "
                       '{"summary": str, "decisions": [str], "action_items": [{"text": str, "owner": str|null}]}. '
                       "Write in the transcript's language (Tamil, English or Tanglish).",
                user=transcript[:14000], max_tokens=900)
            if data and "summary" in data:
                data.setdefault("decisions", [])
                data.setdefault("action_items", [])
                return data
        except Exception:  # noqa: BLE001
            pass
    return heuristic(transcript)


async def save_meeting(session: AsyncSession, user_id: str, title: str, result: dict, *, create_tasks: bool) -> dict:
    lines = [result["summary"]]
    if result["decisions"]:
        lines += ["", "Decisions:"] + [f"- {d}" for d in result["decisions"]]
    if result["action_items"]:
        lines += ["", "Action items:"] + [f"- {a['text']}" + (f" ({a['owner']})" if a.get("owner") else "") for a in result["action_items"]]
    note = Note(user_id=user_id, title=title, body="\n".join(lines), kind="meeting", tags=["meeting"], meta={"action_items": len(result["action_items"])})
    session.add(note)
    task_ids: list[str] = []
    if create_tasks:
        for a in result["action_items"]:
            t = await tasks_svc.create_task(session, user_id, a["text"][:280], tags=["meeting"], notes=f"From meeting: {title}")
            task_ids.append(t.id)
    await session.flush()
    return {"note_id": note.id, "task_ids": task_ids}
