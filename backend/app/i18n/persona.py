"""Wensday's voice: calm, intelligent, respectful, efficient.

Every reply is authored natively in three styles — ``en`` (English), ``tg`` (Tanglish),
``ta`` (Tamil script) — rather than translated. `say()` picks the style that mirrors
the user's language; `fmt_when()` phrases times the way that style would say them.
"""
from __future__ import annotations

import zlib
from datetime import datetime

Style = str  # "en" | "tg" | "ta"

# ---------------------------------------------------------------- time phrasing
_TA_DAYS = ["திங்கள்", "செவ்வாய்", "புதன்", "வியாழன்", "வெள்ளி", "சனி", "ஞாயிறு"]
_EN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def day_part(hour: int) -> str:
    return "morning" if hour < 12 else "afternoon" if hour < 16 else "evening" if hour < 19 else "night"


_PART_TA = {"morning": "காலை", "afternoon": "மதியம்", "evening": "மாலை", "night": "இரவு"}


def _clock(dt: datetime) -> str:
    h12 = dt.hour % 12 or 12
    return f"{h12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def fmt_when(dt: datetime, now: datetime, style: Style, *, has_time: bool = True, relative: bool = False) -> str:
    """'nalaiku morning 9:00 AM-ku' / 'tomorrow at 9:00 AM' / 'நாளை காலை 9:00 மணிக்கு'."""
    delta = int((dt - now).total_seconds() // 60)
    if relative and 0 <= delta < 180:
        if delta < 60 or delta % 60:
            return {"en": f"in {delta} minutes", "tg": f"{delta} nimisham la", "ta": f"{delta} நிமிடத்தில்"}[style]
        h = delta // 60
        return {"en": f"in {h} hour{'s' if h > 1 else ''}", "tg": f"{h} mani neram la", "ta": f"{h} மணி நேரத்தில்"}[style]

    days = (dt.date() - now.date()).days
    part = day_part(dt.hour)
    if style == "en":
        day = "today" if days == 0 else "tomorrow" if days == 1 else \
            f"on {_EN_DAYS[dt.weekday()]}" if 0 < days < 7 else f"on {dt.day} {dt.strftime('%b')}"
        return f"{day} at {_clock(dt)}" if has_time else f"{day} {part}"
    if style == "tg":
        day = "inniku" if days == 0 else "nalaiku" if days == 1 else \
            f"{_EN_DAYS[dt.weekday()]}" if 0 < days < 7 else f"{dt.day} {dt.strftime('%b')}"
        if days not in (0, 1):
            return f"{day} {part} {_clock(dt)}-ku" if has_time else f"{day} {part}-ku"
        return f"{day} {part} {_clock(dt)}-ku" if has_time else f"{day} {part}-ku"
    day = "இன்று" if days == 0 else "நாளை" if days == 1 else \
        f"{_TA_DAYS[dt.weekday()]}க்கிழமை" if 0 < days < 7 else f"{dt.day} {dt.strftime('%b')}"
    h12 = dt.hour % 12 or 12
    return f"{day} {_PART_TA[part]} {h12}:{dt.minute:02d} மணிக்கு" if has_time else f"{day} {_PART_TA[part]}"


# ------------------------------------------------------------------ templates
# key -> {style: [variants]}.  {addr} = ", <Name>" or "".  Variants are chosen deterministically.
T: dict[str, dict[str, list[str]]] = {
    "greeting": {
        "en": ["Hello{addr}. How can I help you today?", "Hi{addr}. What can I do for you?"],
        "tg": ["Vanakkam{addr}. Enna help venum?", "Hi{addr}. Innaiku enna pannanum?"],
        "ta": ["வணக்கம்{addr}. நான் எப்படி உதவலாம்?", "வணக்கம்{addr}. இன்று என்ன செய்யலாம்?"],
    },
    "howru": {
        "en": ["I'm doing well, thank you{addr}. How are you?"],
        "tg": ["Naan nalla iruken{addr}. Neenga epdi irukinga?"],
        "ta": ["நான் நலமாக இருக்கிறேன்{addr}. நீங்கள் எப்படி இருக்கிறீர்கள்?"],
    },
    "ate_q": {
        "en": ["I'm an AI, so I skip meals{addr} — but have you eaten?"],
        "tg": ["Naan AI{addr}, enakku saapaadu thevai illa. Neenga saptingala?"],
        "ta": ["நான் AI என்பதால் எனக்கு சாப்பாடு தேவையில்லை{addr}. நீங்கள் சாப்பிட்டீர்களா?"],
    },
    "thanks": {
        "en": ["You're welcome{addr}."],
        "tg": ["Paravala{addr}. Vera edhavathu venuma?"],
        "ta": ["பரவாயில்லை{addr}. வேறு ஏதாவது வேண்டுமா?"],
    },
    "bye": {
        "en": ["Alright{addr}. Take care."],
        "tg": ["Sari{addr}, paathu poitu vaanga."],
        "ta": ["சரி{addr}, பத்திரமாகப் போய் வாருங்கள்."],
    },
    "help": {
        "en": ["I can set reminders, manage tasks, notes and goals, check your calendar, draft emails, plan your day and remember what matters to you. Just speak in Tamil, English or Tanglish."],
        "tg": ["Naan reminders, tasks, notes, goals, calendar, mail draft, day plan ellam pannuven. Tamil, English, Tanglish edhula venaalum pesunga."],
        "ta": ["நினைவூட்டல்கள், பணிகள், குறிப்புகள், இலக்குகள், நாட்காட்டி, மின்னஞ்சல் வரைவு, நாள் திட்டம் எல்லாவற்றிலும் உதவுவேன். தமிழ், ஆங்கிலம், தங்கிலிஷ் எதிலும் பேசலாம்."],
    },
    # ---- reminders
    "reminder_ok": {
        "en": ["Sure{nm}, I've set a reminder{title} for {when}."],
        "tg": ["Sure{nm}, {when} {title}reminder set panniten."],
        "ta": ["சரி{nm}, {when} {title}நினைவூட்டல் அமைத்துவிட்டேன்."],
    },
    "reminder_ask_details": {
        "en": ["Sure{addr}. What should I remind you about, and when?"],
        "tg": ["Sure{addr}. Enna, eppo remind pannanum?"],
        "ta": ["சரி{addr}. எதற்கு, எப்போது நினைவூட்ட வேண்டும்?"],
    },
    "reminder_ask_when": {
        "en": ["Okay{addr}. When should I remind you{about}?"],
        "tg": ["Okay{addr}. {title}eppo remind pannanum?"],
        "ta": ["சரி{addr}. {title}எப்போது நினைவூட்ட வேண்டும்?"],
    },
    "reminder_ask_time": {
        "en": ["What time {when}?"],
        "tg": ["{when} {title}enna time-ku remind pannanum?"],
        "ta": ["{when} {title}எத்தனை மணிக்கு நினைவூட்ட வேண்டும்?"],
    },
    "reminder_ask_what": {
        "en": ["Okay{addr}. What should I remind you about {when}?"],
        "tg": ["Okay{addr}. {when} enna remind pannanum?"],
        "ta": ["சரி{addr}. {when} எதை நினைவூட்ட வேண்டும்?"],
    },
    "reminder_list": {
        "en": ["Here are your upcoming reminders{addr}:\n{items}"],
        "tg": ["Unga upcoming reminders{addr}:\n{items}"],
        "ta": ["உங்கள் வரவிருக்கும் நினைவூட்டல்கள்{addr}:\n{items}"],
    },
    "reminder_list_empty": {
        "en": ["You have no upcoming reminders{addr}."],
        "tg": ["Upcoming reminders edhuvum illa{addr}."],
        "ta": ["வரவிருக்கும் நினைவூட்டல்கள் எதுவும் இல்லை{addr}."],
    },
    "reminder_due": {
        "en": ["Reminder{addr}: {title}"],
        "tg": ["Reminder{addr}: {title}"],
        "ta": ["நினைவூட்டல்{addr}: {title}"],
    },
    # ---- tasks
    "task_ok": {
        "en": ["Added to your tasks{addr}: {title}."],
        "tg": ["Task add panniten{addr}: {title}."],
        "ta": ["பணியைச் சேர்த்துவிட்டேன்{addr}: {title}."],
    },
    "task_ask": {
        "en": ["Sure{addr}. What's the task?"],
        "tg": ["Sure{addr}. Enna task add pannanum?"],
        "ta": ["சரி{addr}. என்ன பணியைச் சேர்க்க வேண்டும்?"],
    },
    "task_list": {
        "en": ["Your open tasks{addr}:\n{items}"],
        "tg": ["Unga open tasks{addr}:\n{items}"],
        "ta": ["உங்கள் நிலுவையிலுள்ள பணிகள்{addr}:\n{items}"],
    },
    "task_list_empty": {
        "en": ["You have no open tasks{addr}. Nice and clear."],
        "tg": ["Open tasks edhuvum illa{addr}. Ellam clear!"],
        "ta": ["நிலுவையில் பணிகள் எதுவும் இல்லை{addr}."],
    },
    "task_done": {
        "en": ["Marked as done{addr}: {title}. Well done."],
        "tg": ["Done nu mark panniten{addr}: {title}. Nalla velai!"],
        "ta": ["முடிந்தது என்று குறித்துவிட்டேன்{addr}: {title}. நன்று!"],
    },
    "task_done_missing": {
        "en": ["I couldn't find a matching open task{addr}."],
        "tg": ["Andha task open la illa{addr}. Pera konjam sollunga."],
        "ta": ["அந்தப் பணி கிடைக்கவில்லை{addr}. பெயரைச் சொல்லுங்கள்."],
    },
    # ---- notes / goals
    "note_ok": {
        "en": ["Noted{addr}: {title}."],
        "tg": ["Note eduthuten{addr}: {title}."],
        "ta": ["குறித்துக்கொண்டேன்{addr}: {title}."],
    },
    "note_ask": {
        "en": ["What should I note down{addr}?"],
        "tg": ["Enna note pannanum{addr}?"],
        "ta": ["என்ன குறிப்பு எடுக்க வேண்டும்{addr}?"],
    },
    "note_search": {
        "en": ["Found these notes{addr}:\n{items}"],
        "tg": ["Indha notes kedachuchu{addr}:\n{items}"],
        "ta": ["இந்தக் குறிப்புகள் கிடைத்தன{addr}:\n{items}"],
    },
    "note_search_empty": {
        "en": ["I couldn't find any matching notes{addr}."],
        "tg": ["Match aagura notes edhuvum illa{addr}."],
        "ta": ["பொருந்தும் குறிப்புகள் இல்லை{addr}."],
    },
    "goal_ok": {
        "en": ["Goal set{addr}: {title}. I'll help you track it."],
        "tg": ["Goal set panniten{addr}: {title}. Progress track panren."],
        "ta": ["இலக்கை அமைத்துவிட்டேன்{addr}: {title}. முன்னேற்றத்தைக் கண்காணிக்கிறேன்."],
    },
    "goal_ask": {
        "en": ["What's the goal{addr}?"],
        "tg": ["Enna goal set pannanum{addr}?"],
        "ta": ["என்ன இலக்கை அமைக்க வேண்டும்{addr}?"],
    },
    "goal_list": {
        "en": ["Your goals{addr}:\n{items}"],
        "tg": ["Unga goals{addr}:\n{items}"],
        "ta": ["உங்கள் இலக்குகள்{addr}:\n{items}"],
    },
    "goal_list_empty": {
        "en": ["No goals yet{addr}. Want to set one?"],
        "tg": ["Goals edhuvum illa{addr}. Onnu set pannalama?"],
        "ta": ["இலக்குகள் எதுவும் இல்லை{addr}. ஒன்றை அமைக்கலாமா?"],
    },
    # ---- calendar
    "event_ok": {
        "en": ["Scheduled{addr}: {title} {when}."],
        "tg": ["Schedule panniten{addr}: {when} {title}."],
        "ta": ["அட்டவணையில் சேர்த்துவிட்டேன்{addr}: {when} {title}."],
    },
    "event_conflict": {
        "en": ["Heads up{addr}: that overlaps with \"{other}\". I've still added it — want to move one?"],
        "tg": ["Gavanam{addr}: idhu \"{other}\" oda clash aagudhu. Add panniten, edhavadhu move pannanuma?"],
        "ta": ["கவனம்{addr}: இது \"{other}\" உடன் மோதுகிறது. சேர்த்துவிட்டேன், ஒன்றை மாற்றலாமா?"],
    },
    "event_ask_time": {
        "en": ["Sure{addr}. When is the meeting?"],
        "tg": ["Sure{addr}. Meeting eppo?"],
        "ta": ["சரி{addr}. கூட்டம் எப்போது?"],
    },
    "calendar_next": {
        "en": ["Your next event{addr} is \"{title}\" {when}."],
        "tg": ["Unga next event{addr}: \"{title}\", {when}."],
        "ta": ["உங்கள் அடுத்த நிகழ்வு{addr}: \"{title}\", {when}."],
    },
    "calendar_none": {
        "en": ["Nothing scheduled coming up{addr}."],
        "tg": ["Upcoming schedule la edhuvum illa{addr}."],
        "ta": ["வரவிருக்கும் நிகழ்வுகள் எதுவும் இல்லை{addr}."],
    },
    "calendar_list": {
        "en": ["Your schedule{addr}:\n{items}"],
        "tg": ["Unga schedule{addr}:\n{items}"],
        "ta": ["உங்கள் அட்டவணை{addr}:\n{items}"],
    },
    "schedule_update_ask": {
        "en": ["Sure{addr}. Which event should I change, and to when?"],
        "tg": ["Sure{addr}. Edha maathanum, enna time-ku?"],
        "ta": ["சரி{addr}. எதை, எப்போதுக்கு மாற்ற வேண்டும்?"],
    },
    "schedule_update_ok": {
        "en": ["Moved \"{title}\" to {when}{addr}."],
        "tg": ["\"{title}\" ah {when} maathiten{addr}."],
        "ta": ["\"{title}\" நிகழ்வை {when} மாற்றிவிட்டேன்{addr}."],
    },
    "schedule_update_missing": {
        "en": ["I couldn't find that event{addr}. Which one do you mean?"],
        "tg": ["Andha event kedaikala{addr}. Edhu nu sollunga?"],
        "ta": ["அந்த நிகழ்வு கிடைக்கவில்லை{addr}. எது என்று சொல்லுங்கள்?"],
    },
    # ---- email
    "email_ask_recipient": {
        "en": ["Sure{addr}. Who should I send it to?"],
        "tg": ["Sure{addr}. Yaarukku mail anuppanum?"],
        "ta": ["சரி{addr}. யாருக்கு மின்னஞ்சல் அனுப்ப வேண்டும்?"],
    },
    "email_ask_body": {
        "en": ["What should the mail to {recipient} say{addr}?"],
        "tg": ["{recipient} ku enna mail anuppanum{addr}?"],
        "ta": ["{recipient} க்கு என்ன எழுத வேண்டும்{addr}?"],
    },
    "email_draft_ready": {
        "en": ["Mail draft ready. Do you want to review it, or should I send it directly?"],
        "tg": ["Mail draft ready. Review panna venduma illa direct send panna venduma?"],
        "ta": ["மின்னஞ்சல் வரைவு தயார். பார்க்க வேண்டுமா, நேரடியாக அனுப்பட்டுமா?"],
    },
    "email_show_draft": {
        "en": ["Here's the draft{addr}:\nTo: {recipient}\nSubject: {subject}\n\n{body}\n\nShall I send it?"],
        "tg": ["Draft idhu{addr}:\nTo: {recipient}\nSubject: {subject}\n\n{body}\n\nSend pannatuma?"],
        "ta": ["வரைவு இதோ{addr}:\nபெறுநர்: {recipient}\nதலைப்பு: {subject}\n\n{body}\n\nஅனுப்பட்டுமா?"],
    },
    "email_sent": {
        "en": ["Sent{addr}. Your mail to {recipient} is on its way."],
        "tg": ["Send panniten{addr}. {recipient} ku mail poiduchu."],
        "ta": ["அனுப்பிவிட்டேன்{addr}. {recipient} க்கு மின்னஞ்சல் சென்றுவிட்டது."],
    },
    "email_queued": {
        "en": ["Email isn't connected yet{addr}, so I've saved the draft to send later."],
        "tg": ["Email connect aagala{addr}, adhunala draft save panni vechuruken."],
        "ta": ["மின்னஞ்சல் இணைக்கப்படவில்லை{addr}; வரைவைச் சேமித்து வைத்துள்ளேன்."],
    },
    "email_discarded": {
        "en": ["Okay{addr}, I've discarded the draft."],
        "tg": ["Sari{addr}, draft ah cancel panniten."],
        "ta": ["சரி{addr}, வரைவை நீக்கிவிட்டேன்."],
    },
    "email_status_none": {
        "en": ["I haven't sent any mail yet{addr}. Shall I draft one?"],
        "tg": ["Innum mail edhuvum send pannala{addr}. Draft pannava?"],
        "ta": ["இன்னும் எந்த மின்னஞ்சலும் அனுப்பவில்லை{addr}. வரைவு செய்யட்டுமா?"],
    },
    "email_status_sent": {
        "en": ["Yes{addr}, the mail to {recipient} was sent {when}."],
        "tg": ["Aama{addr}, {recipient} ku mail {when} send panniten."],
        "ta": ["ஆம்{addr}, {recipient} க்கு மின்னஞ்சல் {when} அனுப்பப்பட்டது."],
    },
    "email_status_pending": {
        "en": ["Not yet{addr} — the draft to {recipient} is waiting for your go-ahead."],
        "tg": ["Innum illa{addr} — {recipient} ku draft ready, nee OK sonna send panren."],
        "ta": ["இன்னும் இல்லை{addr} — {recipient} க்கான வரைவு உங்கள் ஒப்புதலுக்காகக் காத்திருக்கிறது."],
    },
    # ---- calls / presence / mood / plan
    "call_ok": {
        "en": ["Calling {contact} now{addr}."],
        "tg": ["{contact} ku call panren{addr}."],
        "ta": ["{contact} அவர்களை அழைக்கிறேன்{addr}."],
    },
    "call_ask": {
        "en": ["Sure{addr}. Who should I call?"],
        "tg": ["Sure{addr}. Yaarukku call pannanum?"],
        "ta": ["சரி{addr}. யாரை அழைக்க வேண்டும்?"],
    },
    "mood_tired": {
        "en": ["Okay. I'll keep today light and prioritize only the important tasks.{extra}"],
        "tg": ["Okay. Inniku schedule la important tasks mattum prioritize panren.{extra}"],
        "ta": ["சரி. இன்று முக்கியமான பணிகளுக்கு மட்டும் முன்னுரிமை தருகிறேன்.{extra}"],
    },
    "mood_stressed": {
        "en": ["I hear you{addr}. Let's take it one thing at a time.{extra}"],
        "tg": ["Puriyudhu{addr}. Oru nerathula onnu onnaa paakalam.{extra}"],
        "ta": ["புரிகிறது{addr}. ஒவ்வொன்றாகப் பார்க்கலாம்.{extra}"],
    },
    "mood_extra": {
        "en": [" Start with: {task}."],
        "tg": [" Mudhalla: {task}."],
        "ta": [" முதலில்: {task}."],
    },
    "presence_office": {
        "en": ["Alright{addr}, travel safe. I'll keep your notifications quiet and be here when you're back."],
        "tg": ["Sari{addr}, paathu poitu vaanga. Vandhathum pending items sollatuma?"],
        "ta": ["சரி{addr}, பத்திரமாகப் போய் வாருங்கள். வந்ததும் நிலுவையில் உள்ளவற்றைச் சொல்கிறேன்."],
    },
    "presence_other": {
        "en": ["Alright{addr}. See you soon."],
        "tg": ["Sari{addr}. Seekiram vaanga."],
        "ta": ["சரி{addr}. விரைவில் வாருங்கள்."],
    },
    "plan_day": {
        "en": ["Here's your day{addr}:\n{items}"],
        "tg": ["Unga inniku plan{addr}:\n{items}"],
        "ta": ["உங்கள் இன்றைய திட்டம்{addr}:\n{items}"],
    },
    "plan_empty": {
        "en": ["Your day is clear{addr}. Want to add a task or goal?"],
        "tg": ["Inniku edhuvum pending illa{addr}. Task illa goal add pannalama?"],
        "ta": ["இன்று எதுவும் நிலுவையில் இல்லை{addr}. பணியோ இலக்கோ சேர்க்கலாமா?"],
    },
    "time_now": {
        "en": ["It's {time}{addr}."],
        "tg": ["Ippo {time}{addr}."],
        "ta": ["இப்போது {time}{addr}."],
    },
    "date_now": {
        "en": ["Today is {date}{addr}."],
        "tg": ["Inniku {date}{addr}."],
        "ta": ["இன்று {date}{addr}."],
    },
    "weather_unavailable": {
        "en": ["I don't have a weather plugin enabled yet{addr}. You can add one from Plugins."],
        "tg": ["Weather plugin innum enable aagala{addr}. Plugins la add pannalam."],
        "ta": ["வானிலை செருகுநிரல் இன்னும் இயக்கப்படவில்லை{addr}."],
    },
    "stop": {
        "en": ["Okay{addr}, dropped it."],
        "tg": ["Sari{addr}, vittudren."],
        "ta": ["சரி{addr}, விட்டுவிடுகிறேன்."],
    },
    "nothing_pending": {
        "en": ["Okay{addr}. Anything else I can help with?"],
        "tg": ["Sari{addr}. Vera edhavathu help venuma?"],
        "ta": ["சரி{addr}. வேறு ஏதாவது உதவி வேண்டுமா?"],
    },
    "unknown_offline": {
        "en": ["Sorry{addr}, I didn't quite get that. I'm in offline mode, so I can handle reminders, tasks, notes, goals and your schedule."],
        "tg": ["Sorry{addr}, idhu enakku puriyala. Ippo offline mode la iruken — reminders, tasks, notes, goals, schedule mattum pannuven."],
        "ta": ["மன்னிக்கவும்{addr}, புரியவில்லை. இப்போது ஆஃப்லைனில் இருக்கிறேன்; நினைவூட்டல், பணிகள், குறிப்புகள், இலக்குகள், அட்டவணை மட்டும் செய்வேன்."],
    },
    "error": {
        "en": ["Sorry{addr}, something went wrong on my side. Please try again."],
        "tg": ["Sorry{addr}, en side la oru problem. Thirumba try pannunga."],
        "ta": ["மன்னிக்கவும்{addr}, ஏதோ பிழை ஏற்பட்டது. மீண்டும் முயலுங்கள்."],
    },
}


def _pick(options: list[str], seed: str) -> str:
    return options[zlib.crc32(seed.encode("utf-8")) % len(options)] if len(options) > 1 else options[0]


class _Safe(dict):
    def __missing__(self, key):  # unknown placeholders render empty instead of raising
        return ""


def say(key: str, style: Style, name: str | None = None, seed: str = "", **vars) -> str:
    """Render reply *key* in *style* (en | tg | ta)."""
    variants = T[key].get(style) or T[key]["en"]
    tpl = _pick(variants, key + seed)
    addr = f", {name}" if name else ""
    nm = f" {name}" if name else ""   # "Sure{nm}, ..." -> "Sure Madesh, ..."
    return tpl.format_map(_Safe(addr=addr, nm=nm, **vars)).strip()


def title_part(subject: str | None, style: Style) -> str:
    """Optional title fragment placed inside a sentence (`{title}`)."""
    if not subject:
        return ""
    return f' "{subject}"' if style == "en" else f"{subject} "


def about_part(subject: str | None) -> str:
    """English-only 'about X' fragment (`{about}`)."""
    return f' about "{subject}"' if subject else ""


_TA_MONTHS = ["ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்"]


def fmt_date(dt: datetime, style: Style) -> str:
    if style == "ta":
        return f"{dt.day} {_TA_MONTHS[dt.month - 1]} {dt.year}, {_TA_DAYS[dt.weekday()]}கிழமை"
    return f"{_EN_DAYS[dt.weekday()]}, {dt.day} {dt.strftime('%B')} {dt.year}"


def fmt_clock(dt: datetime, style: Style) -> str:
    return _clock(dt) if style != "ta" else f"{_PART_TA[day_part(dt.hour)]} {dt.hour % 12 or 12}:{dt.minute:02d} மணி"


T.update({
    "fact_ok": {
        "en": ["Got it{addr}. I'll remember that."],
        "tg": ["Sari{addr}, nyabagam vechukren."],
        "ta": ["சரி{addr}, நினைவில் வைத்துக்கொள்கிறேன்."],
    },
    "name_ok": {
        "en": ["Nice to meet you, {who}. I'll call you {who} from now on."],
        "tg": ["Nice to meet you, {who}. Ini {who} nu koopidren."],
        "ta": ["உங்களைச் சந்தித்ததில் மகிழ்ச்சி, {who}. இனி {who} என்று அழைக்கிறேன்."],
    },
    "lang_ok": {
        "en": ["Sure{addr}, I'll reply in English."],
        "tg": ["Sure{addr}, Tanglish la reply panren."],
        "ta": ["சரி{addr}, தமிழிலேயே பதில் சொல்கிறேன்."],
    },
    "knowledge_answer": {
        "en": ["From your notes{addr}: {answer}"],
        "tg": ["Unga notes la irundhu{addr}: {answer}"],
        "ta": ["உங்கள் குறிப்புகளிலிருந்து{addr}: {answer}"],
    },
    "workflow_done": {
        "en": ["Done{addr} — ran \"{wf}\" ({steps} steps)."],
        "tg": ["Done{addr} — \"{wf}\" workflow run panniten ({steps} steps)."],
        "ta": ["முடிந்தது{addr} — \"{wf}\" ({steps} படிகள்) இயக்கினேன்."],
    },
})
