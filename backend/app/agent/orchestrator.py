"""The agent: one turn from utterance to reply.

    detect language -> pending confirmation / slot answer? -> workflow phrase?
      -> rule-based NLU (tier 1) -> handler via the tool registry
      -> unknown? explicit facts -> knowledge lookup -> LLM with tools (tier 2) -> offline fallback
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.timeutil import utc_to_local, utcnow
from app.i18n.detect import LangProfile, detect
from app.i18n.persona import about_part, fmt_clock, fmt_date, fmt_when, say, title_part
from app.models import Conversation, EmailDraft, Message, PendingAction
from app.nlu.engine import NLUResult, analyze, free_text
from app.schemas import ChatOut
from app.services import email as email_svc
from app.services import workflows as wf_svc
from app.voice.splitter import split_speech
from .tools import Ctx, ToolRegistry

log = logging.getLogger("wensday.agent")

_FORCED = {"ta": LangProfile("ta", confidence=1.0), "en": LangProfile("en", confidence=1.0), "tanglish": LangProfile("tanglish", confidence=1.0)}
_NEW_COMMAND_VERBS = {"do", "add", "v_add", "send", "v_send", "v_take", "v_call", "show", "v_show", "remind"}
_SLOT_TTL = timedelta(minutes=10)
_CONVERSATION_IDLE = timedelta(minutes=30)


@dataclass
class Reply:
    text: str
    intent: str
    tier: str = "rules"
    data: dict = field(default_factory=dict)
    awaiting: str | None = None        # slot the agent is waiting for the user to fill
    slot_entities: dict | None = None


class Agent:
    def __init__(self, registry: ToolRegistry):
        self.reg = registry

    # ================================================================ public
    async def handle(self, ctx: Ctx, text: str, conversation_id: str | None = None, lang_hint: str = "auto") -> ChatOut:
        s = ctx.session
        conv = await self._conversation(ctx, conversation_id)
        ctx.conversation_id = conv.id
        prefs = await ctx.memory.preferences(s, ctx.user.id) if ctx.memory else {}
        ctx.extra["prefs"] = prefs
        ctx.extra["name"] = (prefs.get("name") or ctx.user.name or "").split(" ")[0] or None

        profile = await self._profile(ctx, text, conv, lang_hint, prefs)
        ctx.profile, ctx.style = profile, profile.style
        nlu = analyze(text, ctx.now, profile)

        s.add(Message(user_id=ctx.user.id, conversation_id=conv.id, role="user", text=text, lang=profile.lang, intent=nlu.intent))
        try:
            reply = await self._route(ctx, nlu, text, conv)
        except Exception:  # noqa: BLE001 - the user always gets an answer
            log.exception("turn failed")
            reply = Reply(say("error", ctx.style, ctx.extra["name"]), "error", "rules")

        s.add(Message(user_id=ctx.user.id, conversation_id=conv.id, role="assistant", text=reply.text, lang=profile.lang, intent=reply.intent))
        if not conv.title:
            conv.title = text[:60]
        conv.updated_at = utcnow()
        if ctx.memory and reply.tier != "offline":
            await ctx.memory.note_event(s, ctx.user.id, f"[{ctx.now:%Y-%m-%d}] {text}", reply.intent)
        await s.flush()
        return ChatOut(conversation_id=conv.id, reply=reply.text, intent=reply.intent, lang=profile.lang, style=ctx.style,
                       tier=reply.tier, data=reply.data, speech=split_speech(reply.text, ctx.style, ctx.settings))

    # ================================================================ plumbing
    async def _conversation(self, ctx: Ctx, cid: str | None) -> Conversation:
        if cid:
            conv = await ctx.session.get(Conversation, cid)
            if conv and conv.user_id == ctx.user.id:
                return conv
        # No id (e.g. a wake-word device that doesn't track conversations): continue the user's
        # most recent conversation if it is still fresh, so language and pending questions carry over.
        recent = (await ctx.session.execute(select(Conversation).where(
            Conversation.user_id == ctx.user.id, Conversation.deleted_at.is_(None), Conversation.updated_at > utcnow() - _CONVERSATION_IDLE)
            .order_by(Conversation.updated_at.desc()).limit(1))).scalars().first()
        if recent:
            return recent
        conv = Conversation(user_id=ctx.user.id)
        ctx.session.add(conv)
        await ctx.session.flush()
        return conv

    async def _profile(self, ctx: Ctx, text: str, conv: Conversation, hint: str, prefs: dict) -> LangProfile:
        forced = hint if hint != "auto" else (ctx.user.language if ctx.user.language != "auto" else prefs.get("language"))
        if forced in _FORCED:
            return _FORCED[forced]
        p = detect(text)
        # One or two words carry little language evidence ("meeting", "ok"): a bare English word after a
        # Tanglish/Tamil turn is a code-switch inside the same conversation, so keep that conversation's language.
        if len(text.split()) <= 2 and p.lang == "en":
            prev = (await ctx.session.execute(select(Message.lang).where(
                Message.conversation_id == conv.id, Message.role == "user").order_by(Message.created_at.desc()).limit(1))).scalars().first()
            if prev in _FORCED:
                return _FORCED[prev]
        return p

    def _say(self, ctx: Ctx, key: str, **vars) -> str:
        return say(key, ctx.style, ctx.extra.get("name"), seed=ctx.extra.get("seed", ""), **vars)

    def _when(self, ctx: Ctx, ent: dict) -> str:
        return fmt_when(datetime.fromisoformat(ent["when"]), ctx.now, ctx.style, has_time=ent.get("has_time", True), relative=ent.get("relative", False))

    @staticmethod
    def _day_word(ctx: Ctx, ent: dict) -> str:
        days = (datetime.fromisoformat(ent["when"]).date() - ctx.now.date()).days
        table = {"en": ("today", "tomorrow"), "tg": ("inniku", "nalaiku"), "ta": ("இன்று", "நாளை")}[ctx.style]
        return table[0] if days == 0 else table[1] if days == 1 else fmt_when(datetime.fromisoformat(ent["when"]), ctx.now, ctx.style, has_time=False)

    async def _active_pending(self, ctx: Ctx) -> PendingAction | None:
        q = (select(PendingAction).where(PendingAction.user_id == ctx.user.id, PendingAction.status == "pending",
                                         PendingAction.expires_at > utcnow()).order_by(PendingAction.created_at.desc()).limit(1))
        return (await ctx.session.execute(q)).scalars().first()

    async def _clear_pending(self, ctx: Ctx, kind: str | None = None) -> None:
        q = select(PendingAction).where(PendingAction.user_id == ctx.user.id, PendingAction.status == "pending")
        if kind:
            q = q.where(PendingAction.kind == kind)
        for p in (await ctx.session.execute(q)).scalars():
            p.status = "cancelled"

    # ================================================================ routing
    async def _route(self, ctx: Ctx, nlu: NLUResult, text: str, conv: Conversation) -> Reply:
        ctx.extra["seed"] = text
        pending = await self._active_pending(ctx)

        if pending and pending.kind == "email_send" and nlu.intent.startswith("confirm_"):
            return await self._resolve_email(ctx, pending, nlu)

        if pending and pending.kind == "slot":
            reply = await self._continue_slot(ctx, pending, nlu, text)
            if reply is not None:
                return reply

        if not nlu.intent.startswith("confirm_"):
            wf = await wf_svc.match_phrase(ctx.session, ctx.user.id, text)
            if wf:
                return await self._run_workflow(ctx, wf)

        reply = await self._dispatch(ctx, nlu.intent, nlu.entities, nlu, text, conv)
        if reply.awaiting:
            await self._clear_pending(ctx, "slot")
            ctx.session.add(PendingAction(user_id=ctx.user.id, conversation_id=ctx.conversation_id, kind="slot", expires_at=utcnow() + _SLOT_TTL,
                                          payload={"intent": reply.intent, "entities": reply.slot_entities or {}, "awaiting": reply.awaiting}))
        return reply

    async def _dispatch(self, ctx: Ctx, intent: str, ent: dict, nlu: NLUResult | None, text: str, conv: Conversation | None) -> Reply:
        h = getattr(self, f"_h_{intent}", None) if intent != "unknown" else None
        if h is None:  # unknown intent (or one without a rule handler) -> facts / knowledge / LLM tier
            return await self._h_unknown(ctx, ent, nlu, text, conv)
        return await h(ctx, ent)

    async def _continue_slot(self, ctx: Ctx, pending: PendingAction, nlu: NLUResult, text: str) -> Reply | None:
        payload = pending.payload
        if nlu.intent in ("confirm_no",) or (nlu.intent == "stop"):
            pending.status = "cancelled"
            return Reply(self._say(ctx, "stop"), "stop")
        is_new_command = nlu.intent not in ("unknown", payload["intent"]) and bool(nlu.concepts & _NEW_COMMAND_VERBS) \
            and not nlu.intent.startswith("confirm_")
        if is_new_command:
            pending.status = "cancelled"
            return None
        ent = dict(payload["entities"])
        new = nlu.entities
        if "when" in new:
            old_when = ent.get("when")
            if not new.get("has_date") and ent.get("has_date") and new.get("has_time") and old_when:  # "nalaiku" … then "9 mani"
                merged = datetime.fromisoformat(old_when).replace(hour=datetime.fromisoformat(new["when"]).hour,
                                                                   minute=datetime.fromisoformat(new["when"]).minute)
                ent.update({"when": merged.isoformat(), "has_time": True})
            else:
                ent.update({k: new[k] for k in ("when", "has_time", "has_date", "relative", "part") if k in new})
        awaiting = payload["awaiting"]
        if awaiting in ("subject", "both") and not ent.get("subject"):
            ent["subject"] = new.get("subject") or free_text(text, ctx.now)
        elif awaiting in ("recipient", "body", "contact", "query") and not ent.get(awaiting):
            ent[awaiting] = new.get(awaiting) or free_text(text, ctx.now)
        pending.status = "done"
        reply = await self._dispatch(ctx, payload["intent"], {k: v for k, v in ent.items() if v not in (None, "")}, nlu, text, None)
        if reply.awaiting:
            ctx.session.add(PendingAction(user_id=ctx.user.id, conversation_id=ctx.conversation_id, kind="slot", expires_at=utcnow() + _SLOT_TTL,
                                          payload={"intent": reply.intent, "entities": reply.slot_entities or {}, "awaiting": reply.awaiting}))
        return reply

    def _ask(self, ctx: Ctx, key: str, intent: str, ent: dict, awaiting: str, **vars) -> Reply:
        return Reply(self._say(ctx, key, **vars), intent, awaiting=awaiting, slot_entities=ent)

    # ================================================================ social
    async def _h_greeting(self, ctx, ent): return Reply(self._say(ctx, "greeting"), "greeting")
    async def _h_howru(self, ctx, ent): return Reply(self._say(ctx, "howru"), "howru")
    async def _h_ate_q(self, ctx, ent): return Reply(self._say(ctx, "ate_q"), "ate_q")
    async def _h_thanks(self, ctx, ent): return Reply(self._say(ctx, "thanks"), "thanks")
    async def _h_bye(self, ctx, ent): return Reply(self._say(ctx, "bye"), "bye")
    async def _h_help(self, ctx, ent): return Reply(self._say(ctx, "help"), "help")
    async def _h_stop(self, ctx, ent): return Reply(self._say(ctx, "stop"), "stop")

    async def _h_confirm_yes(self, ctx, ent): return Reply(self._say(ctx, "nothing_pending"), "nothing_pending")
    _h_confirm_no = _h_confirm_review = _h_confirm_direct = _h_confirm_yes

    async def _h_time_now(self, ctx, ent): return Reply(self._say(ctx, "time_now", time=fmt_clock(ctx.now, ctx.style)), "time_now")
    async def _h_date_now(self, ctx, ent): return Reply(self._say(ctx, "date_now", date=fmt_date(ctx.now, ctx.style)), "date_now")

    async def _h_weather(self, ctx, ent):
        tool = self.reg.get("get_weather")
        if tool and ctx.plugins and await ctx.plugins.allowed(ctx, tool):
            res = await self.reg.call("get_weather", ctx, {})
            if res.ok and res.data.get("summary"):
                return Reply(res.data["summary"], "weather", data=res.data)
        return Reply(self._say(ctx, "weather_unavailable"), "weather")

    # ================================================================ reminders
    async def _h_reminder_create(self, ctx: Ctx, ent: dict) -> Reply:
        subj, when = ent.get("subject"), ent.get("when")
        if not subj and not when:
            return self._ask(ctx, "reminder_ask_details", "reminder_create", ent, "both")
        if not when:
            return self._ask(ctx, "reminder_ask_when", "reminder_create", ent, "when", title=title_part(subj, ctx.style), about=about_part(subj))
        if not ent.get("has_time", True):
            return self._ask(ctx, "reminder_ask_time", "reminder_create", ent, "when", when=self._day_word(ctx, ent), title=title_part(subj, ctx.style))
        if not subj:
            return self._ask(ctx, "reminder_ask_what", "reminder_create", ent, "subject", when=self._when(ctx, ent))
        res = await self.reg.call("create_reminder", ctx, {"title": subj, "when": ent["when"]})
        if not res.ok:
            return Reply(self._say(ctx, "error"), "error")
        return Reply(self._say(ctx, "reminder_ok", when=self._when(ctx, ent), title=title_part(subj, ctx.style)), "reminder_create", data=res.data)

    async def _h_reminder_list(self, ctx, ent):
        res = await self.reg.call("list_reminders", ctx, {})
        rows = res.data.get("reminders", [])
        if not rows:
            return Reply(self._say(ctx, "reminder_list_empty"), "reminder_list")
        items = "\n".join(f"• {fmt_when(datetime.fromisoformat(r['when']), ctx.now, ctx.style)} — {r['title']}" for r in rows)
        return Reply(self._say(ctx, "reminder_list", items=items), "reminder_list", data=res.data)

    # ================================================================ tasks / notes / goals
    async def _h_task_create(self, ctx, ent):
        subj = ent.get("subject")
        if not subj:
            return self._ask(ctx, "task_ask", "task_create", ent, "subject")
        res = await self.reg.call("create_task", ctx, {"title": subj, **({"due": ent["when"]} if ent.get("when") else {})})
        return Reply(self._say(ctx, "task_ok", title=subj), "task_create", data=res.data)

    async def _h_task_list(self, ctx, ent):
        res = await self.reg.call("list_tasks", ctx, {"limit": 8})
        rows = res.data.get("tasks", [])
        if not rows:
            return Reply(self._say(ctx, "task_list_empty"), "task_list")
        return Reply(self._say(ctx, "task_list", items="\n".join(f"• {t['title']}" for t in rows)), "task_list", data=res.data)

    async def _h_task_complete(self, ctx, ent):
        q = ent.get("subject", "")
        res = await self.reg.call("complete_task", ctx, {"query": q}) if q else None
        if res is None:
            return self._ask(ctx, "task_done_missing", "task_complete", ent, "subject")
        if not res.ok:
            return Reply(self._say(ctx, "task_done_missing"), "task_complete")
        return Reply(self._say(ctx, "task_done", title=res.data["title"]), "task_complete", data=res.data)

    async def _h_note_create(self, ctx, ent):
        subj = ent.get("subject")
        if not subj:
            return self._ask(ctx, "note_ask", "note_create", ent, "subject")
        res = await self.reg.call("create_note", ctx, {"body": subj})
        return Reply(self._say(ctx, "note_ok", title=subj), "note_create", data=res.data)

    async def _h_note_search(self, ctx, ent):
        res = await self.reg.call("search_notes", ctx, {"query": ent.get("query", "")})
        rows = res.data.get("notes", [])
        if not rows:
            return Reply(self._say(ctx, "note_search_empty"), "note_search")
        return Reply(self._say(ctx, "note_search", items="\n".join(f"• {n['title'] or n['body'][:50]}" for n in rows)), "note_search", data=res.data)

    async def _h_goal_create(self, ctx, ent):
        subj = ent.get("subject")
        if not subj:
            return self._ask(ctx, "goal_ask", "goal_create", ent, "subject")
        res = await self.reg.call("create_goal", ctx, {"title": subj})
        return Reply(self._say(ctx, "goal_ok", title=subj), "goal_create", data=res.data)

    async def _h_goal_list(self, ctx, ent):
        res = await self.reg.call("list_goals", ctx, {})
        rows = res.data.get("goals", [])
        if not rows:
            return Reply(self._say(ctx, "goal_list_empty"), "goal_list")
        return Reply(self._say(ctx, "goal_list", items="\n".join(f"• {g['title']} — {g['progress']}%" for g in rows)), "goal_list", data=res.data)

    # ================================================================ calendar
    async def _h_calendar_create(self, ctx, ent):
        subj = ent.get("subject") or "Meeting"
        if not ent.get("when") or not ent.get("has_time", True):
            return self._ask(ctx, "event_ask_time", "calendar_create", {**ent, "subject": subj}, "when")
        res = await self.reg.call("create_event", ctx, {"title": subj, "start": ent["when"]})
        if not res.ok:
            return Reply(self._say(ctx, "error"), "error")
        text = self._say(ctx, "event_ok", title=subj, when=self._when(ctx, ent))
        if res.data.get("conflicts"):
            text += " " + self._say(ctx, "event_conflict", other=res.data["conflicts"][0])
        return Reply(text, "calendar_create", data=res.data)

    async def _h_calendar_query(self, ctx, ent):
        if ent.get("has_date"):
            res = await self.reg.call("list_events", ctx, {"day": ent["when"]})
            rows = res.data.get("events", [])
            if not rows:
                return Reply(self._say(ctx, "calendar_none"), "calendar_query")
            items = "\n".join(f"• {fmt_clock(datetime.fromisoformat(e['start']), ctx.style)} — {e['title']}" for e in rows)
            return Reply(self._say(ctx, "calendar_list", items=items), "calendar_query", data=res.data)
        res = await self.reg.call("next_event", ctx, {})
        ev = res.data.get("event")
        if not ev:
            return Reply(self._say(ctx, "calendar_none"), "calendar_query")
        when = fmt_when(datetime.fromisoformat(ev["start"]), ctx.now, ctx.style)
        return Reply(self._say(ctx, "calendar_next", title=ev["title"], when=when), "calendar_query", data=res.data)

    async def _h_schedule_update(self, ctx, ent):
        if not ent.get("when") and not ent.get("subject"):
            return self._ask(ctx, "schedule_update_ask", "schedule_update", ent, "when")
        if not ent.get("when"):
            return self._ask(ctx, "schedule_update_ask", "schedule_update", ent, "when")
        res = await self.reg.call("reschedule_event", ctx, {"query": ent.get("subject", ""), "start": ent["when"]})
        if not res.ok:
            return Reply(self._say(ctx, "schedule_update_missing"), "schedule_update")
        return Reply(self._say(ctx, "schedule_update_ok", title=res.data["title"], when=self._when(ctx, ent)), "schedule_update", data=res.data)

    # ================================================================ email
    async def _h_email_draft(self, ctx, ent):
        if not ent.get("recipient"):
            return self._ask(ctx, "email_ask_recipient", "email_draft", ent, "recipient")
        if not ent.get("body"):
            return self._ask(ctx, "email_ask_body", "email_draft", ent, "body", recipient=ent["recipient"])
        await self._clear_pending(ctx, "email_send")
        res = await self.reg.call("draft_email", ctx, {"recipient": ent["recipient"], "body": ent["body"]})
        if not res.ok:
            return Reply(self._say(ctx, "error"), "error")
        return Reply(self._say(ctx, "email_draft_ready"), "email_draft", data=res.data)

    async def _resolve_email(self, ctx: Ctx, pending: PendingAction, nlu: NLUResult) -> Reply:
        draft = await ctx.session.get(EmailDraft, pending.payload["draft_id"])
        if not draft or draft.status != "draft":
            pending.status = "cancelled"
            return Reply(self._say(ctx, "nothing_pending"), "nothing_pending")
        if nlu.intent == "confirm_review":
            return Reply(self._say(ctx, "email_show_draft", recipient=draft.recipient or "—", subject=draft.subject, body=draft.body),
                         "email_review", data={"draft_id": draft.id})
        if nlu.intent == "confirm_no":
            draft.status, pending.status = "discarded", "cancelled"
            return Reply(self._say(ctx, "email_discarded"), "email_discard")
        # confirm_yes / confirm_direct: the user explicitly approved sending
        res = await self.reg.call("send_email", ctx, {"draft_id": draft.id})
        pending.status = "done"
        if res.ok and res.data["status"] == "sent":
            return Reply(self._say(ctx, "email_sent", recipient=draft.recipient), "email_send", data=res.data)
        return Reply(self._say(ctx, "email_queued"), "email_send", data=res.data)

    async def _h_email_status(self, ctx, ent):
        d = await email_svc.latest(ctx.session, ctx.user.id)
        if d is None:
            return Reply(self._say(ctx, "email_status_none"), "email_status")
        if d.status == "sent":
            when = fmt_when(utc_to_local(d.sent_at, ctx.tz), ctx.now, ctx.style)
            return Reply(self._say(ctx, "email_status_sent", recipient=d.recipient, when=when), "email_status")
        return Reply(self._say(ctx, "email_status_pending", recipient=d.recipient or "—"), "email_status")

    # ================================================================ people / mood / planning
    async def _h_call_contact(self, ctx, ent):
        contact = ent.get("contact")
        if not contact:
            return self._ask(ctx, "call_ask", "call_contact", ent, "contact")
        return Reply(self._say(ctx, "call_ok", contact=contact), "call_contact", data={"action": "dial", "contact": contact})

    async def _h_presence_update(self, ctx, ent):
        key = "presence_office" if ent.get("place") == "office" else "presence_other"
        return Reply(self._say(ctx, key), "presence_update", data={"place": ent.get("place")})

    async def _h_mood_low(self, ctx, ent):
        plan = (await self.reg.call("plan_day", ctx, {"low_energy": True})).data
        extra = self._say(ctx, "mood_extra", task=plan["focus"]) if plan.get("focus") else ""
        key = "mood_tired" if ent.get("mood") == "tired" else "mood_stressed"
        return Reply(self._say(ctx, key, extra=(" " + extra) if extra else ""), "mood_low", data={"mood": ent.get("mood"), **plan})

    async def _h_plan_day(self, ctx, ent):
        plan = (await self.reg.call("plan_day", ctx, {})).data
        if not plan["items"]:
            return Reply(self._say(ctx, "plan_empty"), "plan_day")
        lines = []
        for i in plan["items"]:
            at = f"{fmt_clock(datetime.fromisoformat(i['at']), ctx.style)} — " if i.get("at") else ""
            lines.append(f"• {at}{i['title']}")
        return Reply(self._say(ctx, "plan_day", items="\n".join(lines)), "plan_day", data=plan)

    # ================================================================ workflows
    async def _run_workflow(self, ctx: Ctx, wf) -> Reply:
        run = await wf_svc.run_workflow(ctx, self.reg, wf)
        if run.status != "ok":
            return Reply(self._say(ctx, "error"), "workflow", data={"log": run.log})
        return Reply(self._say(ctx, "workflow_done", wf=wf.name, steps=len(wf.steps)), "workflow", data={"log": run.log})

    # ================================================================ tier 2: facts -> knowledge -> LLM -> offline
    async def _h_unknown(self, ctx: Ctx, ent: dict, nlu: NLUResult | None, text: str, conv: Conversation | None) -> Reply:
        if ctx.memory:
            facts = await ctx.memory.learn(ctx.session, ctx.user, text)
            if facts:
                f = facts[0]
                if f.type == "language":
                    ctx.style = {"ta": "ta", "en": "en", "tanglish": "tg"}[f.value]
                    return Reply(self._say(ctx, "lang_ok"), "language_pref")
                if f.type == "name":
                    ctx.extra["name"] = f.value
                    return Reply(say("name_ok", ctx.style, f.value, who=f.value), "name_pref")
                return Reply(self._say(ctx, "fact_ok"), "remember_fact")

        if ctx.knowledge and nlu is not None and ("?" in text or nlu.concepts & {"what", "when", "who", "where", "why", "how"}):
            hits = await ctx.knowledge.search(ctx.session, ctx.user.id, text, k=1)
            if hits and hits[0].score >= 0.35 and not (ctx.llm and ctx.llm.has_remote):
                return Reply(self._say(ctx, "knowledge_answer", answer=hits[0].text[:280]), "knowledge", data={"source": hits[0].source})

        if ctx.llm and ctx.llm.has_remote and conv is not None:
            out = await self._llm_turn(ctx, text, conv)
            if out:
                return Reply(out, "llm", tier="llm")
        return Reply(self._say(ctx, "unknown_offline"), "unknown", tier="offline")

    def _system_prompt(self, ctx: Ctx, memory_block: str) -> str:
        p = ctx.profile
        style = {"ta": "Tamil script (தமிழ்)", "en": "English", "tg": "Tanglish (Tamil written in English letters, natural Chennai tone)"}[ctx.style]
        return (
            "You are Wensday, a calm, intelligent, respectful female personal assistant — like a trusted human assistant.\n"
            "Language rules: mirror the user's language. Tamil script -> reply in Tamil script. Tanglish -> reply in Tanglish. "
            "English -> English. Mixed -> Tanglish-leaning mix. Tamil, English and Tanglish are all first-class; never translate "
            "unless asked. Use respectful forms (neenga/நீங்கள்), never slang like 'da' yourself.\n"
            f"The user's latest message is {style}{' (code-mixed)' if p and p.mixed else ''}; reply in that style.\n"
            "Replies are spoken aloud: keep them to 1-3 short sentences, no markdown.\n"
            "Use the tools to act on the user's data; never claim an action is done unless a tool result confirms it. "
            "Emails are only drafted; the user must confirm sending.\n"
            f"User name: {ctx.extra.get('name') or 'unknown'}. Local time: {ctx.now:%A %d %B %Y, %I:%M %p} ({ctx.tz}).\n"
            + (memory_block + "\n" if memory_block else "")
        )

    async def _llm_turn(self, ctx: Ctx, text: str, conv: Conversation) -> str | None:
        mem = await ctx.memory.context_block(ctx.session, ctx.user, text) if ctx.memory else ""
        rows = (await ctx.session.execute(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.desc()).limit(10))).scalars().all()
        history = [{"role": m.role, "content": m.text} for m in reversed(rows) if m.role in ("user", "assistant")]
        if not history or history[-1]["content"] != text:
            history.append({"role": "user", "content": text})
        tools = await self.reg.specs(ctx)
        system = self._system_prompt(ctx, mem)
        for _ in range(4):
            resp = await ctx.llm.complete(system, history, tools)
            if resp.provider == "offline":
                return None
            if not resp.tool_calls:
                return resp.text or None
            history.append({"role": "assistant", "content": resp.text, "tool_calls": [{"id": t.id, "name": t.name, "args": t.args} for t in resp.tool_calls]})
            for tc in resp.tool_calls:
                result = await self.reg.call(tc.name, ctx, tc.args)
                history.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result.as_json(), default=str)})
        return None
