"""Email drafting + confirmation-gated sending.

Drafting uses the LLM when one is reachable and falls back to a clean template offline.
Sending goes through a `MailSender`; with no provider configured the draft is *queued*
(never silently dropped, never pretended-sent).
"""
from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import utcnow
from app.i18n.normalize import is_tamil_token
from app.models import EmailDraft, User


class MailSender(Protocol):
    name: str

    async def send(self, session: AsyncSession, user: User, draft: EmailDraft) -> bool: ...


class NullSender:
    """No mail provider connected: nothing is sent; the draft is kept as 'queued'."""

    name = "null"

    async def send(self, session: AsyncSession, user: User, draft: EmailDraft) -> bool:
        return False


def template_draft(recipient: str, hint: str, sender_name: str) -> tuple[str, str]:
    hint = hint.strip().rstrip(".") or "Following up"
    sentence = hint[0].upper() + hint[1:] + "."
    subject = hint[0].upper() + hint[1:]
    if len(subject) > 60:
        subject = subject[:57] + "..."
    tamil = any(is_tamil_token(t) for t in hint.split())
    who = recipient.split("@")[0].replace(".", " ").title() if recipient else "there"
    if tamil:
        body = f"வணக்கம் {who},\n\n{sentence}\n\nநன்றி,\n{sender_name}"
    else:
        body = f"Hi {who},\n\n{sentence}\n\nRegards,\n{sender_name}"
    return subject, body


async def compose(llm, recipient: str, hint: str, sender_name: str) -> tuple[str, str]:
    """Return (subject, body). Uses the LLM if available, else the template."""
    if llm is not None and getattr(llm, "has_remote", False):
        try:
            data = await llm.json_task(
                system="You draft short, polite, professional emails. Reply ONLY with JSON {\"subject\":str,\"body\":str}. "
                       "Write in the same language as the user's instruction (English unless it is Tamil script).",
                user=f"Recipient: {recipient or 'unknown'}\nSender: {sender_name}\nWhat to say: {hint}",
            )
            if data and data.get("subject") and data.get("body"):
                return str(data["subject"]), str(data["body"])
        except Exception:  # noqa: BLE001 - never fail a draft because the LLM is down
            pass
    return template_draft(recipient, hint, sender_name)


async def create_draft(session: AsyncSession, user: User, recipient: str, subject: str, body: str, lang: str = "en") -> EmailDraft:
    d = EmailDraft(user_id=user.id, recipient=recipient, subject=subject, body=body, lang=lang)
    session.add(d)
    await session.flush()
    return d


async def send_draft(session: AsyncSession, sender: MailSender, user: User, draft: EmailDraft) -> str:
    """Send a draft. Returns the resulting status: 'sent' or 'queued'."""
    ok = await sender.send(session, user, draft)
    draft.status = "sent" if ok else "queued"
    if ok:
        draft.sent_at = utcnow()
    await session.flush()
    return draft.status


async def latest(session: AsyncSession, user_id: str) -> EmailDraft | None:
    q = (select(EmailDraft).where(EmailDraft.user_id == user_id, EmailDraft.status != "discarded")
         .order_by(EmailDraft.created_at.desc()).limit(1))
    return (await session.execute(q)).scalars().first()
