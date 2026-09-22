"""Voice + realtime channel.

`/ws?token=<access jwt>` is the single realtime socket for every client:

  client -> server   {"type":"text","text":"…","conversation_id"?,"speak"?:bool}
                     <binary audio frames…> then {"type":"audio_end","mime":"audio/webm","lang_hint"?}
                     {"type":"cancel"}            barge-in: stop speaking now
                     {"type":"ping"}
  server -> client   {"type":"ready"} | {"type":"transcript","text"} | {"type":"reply",…ChatOut}
                     {"type":"audio_start","mime"} <binary chunks…> {"type":"audio_end"}
                     {"type":"reminder.due",…} | {"type":"sync",…}   (pushed from any device / the worker)
                     {"type":"error","message"} | {"type":"pong"}
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user, rate_limit, user_from_token
from app.models import User
from app.schemas import SpeechSegment
from app.voice.providers import VoiceUnavailable
from app.voice.splitter import split_speech

log = logging.getLogger("wensday.voice")
router = APIRouter(tags=["voice"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_TEXT_BYTES = 32 * 1024  # generous headroom over a 4000-char chat message in worst-case 3-byte-per-char Tamil UTF-8
CHUNK = 16 * 1024


@router.get("/voice/config", dependencies=[Depends(rate_limit)])
async def voice_config(request: Request, user: User = Depends(current_user)):
    st = request.app.state
    return {
        "stt": st.stt.name, "tts": st.tts.name,
        "server_stt": st.stt.name != "browser", "server_tts": st.tts.name != "browser",
        "voices": {"ta": st.settings.voice_ta, "en": st.settings.voice_en},
        "wake_word": "wensday",
        # substrings to look for when a client picks a *female* voice from its local voice list
        "preferred_voice_hints": {"ta-IN": ["Pallavi", "Female", "Google தமிழ்"], "en-IN": ["Neerja", "Heera", "Female", "Google हिन्दी"]},
        "locales": {"ta": "ta-IN", "en": "en-IN", "tanglish": "en-IN"},
    }


@router.post("/voice/transcribe", dependencies=[Depends(rate_limit)])
async def transcribe(request: Request, audio: UploadFile = File(...), lang_hint: str | None = Form(None), user: User = Depends(current_user)):
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "audio too large")
    try:
        res = await request.app.state.stt.transcribe(data, audio.content_type or "audio/webm", lang_hint)
    except VoiceUnavailable as e:
        raise HTTPException(501, str(e)) from e
    return {"text": res.text, "lang": res.lang, "confidence": res.confidence}


class SpeakIn(BaseModel):
    text: str
    style: str = "en"   # en | tg | ta


@router.post("/voice/speak", dependencies=[Depends(rate_limit)])
async def speak(body: SpeakIn, request: Request, user: User = Depends(current_user)):
    st = request.app.state
    segments = split_speech(body.text, body.style, st.settings)
    try:
        audio, mime = await st.tts.synthesize(segments)
    except VoiceUnavailable as e:
        raise HTTPException(501, str(e)) from e
    return Response(content=audio, media_type=mime)


# ------------------------------------------------------------------ websocket
async def _stream_audio(ws: WebSocket, tts, segments: list[SpeechSegment]) -> None:
    try:
        audio, mime = await tts.synthesize(segments)
    except VoiceUnavailable:
        return  # client speaks the `speech` segments itself
    except Exception:  # noqa: BLE001
        log.exception("tts failed")
        await ws.send_json({"type": "error", "message": "speech synthesis failed"})
        return
    await ws.send_json({"type": "audio_start", "mime": mime})
    for i in range(0, len(audio), CHUNK):
        await ws.send_bytes(audio[i:i + CHUNK])
        await asyncio.sleep(0)  # yield so a `cancel` can interrupt mid-stream
    await ws.send_json({"type": "audio_end"})


@router.websocket("/ws")
async def realtime(ws: WebSocket, token: str = ""):
    st = ws.app.state
    ip = ws.client.host if ws.client else "unknown"
    attempts = await st.cache.incr_window(f"ws-connect:{ip}", 60)
    if attempts > st.settings.ws_connect_limit_per_minute:
        await ws.close(code=4429)  # mirrors HTTP 429; caps connection-flood / token-brute-force cheaply
        return
    async with st.db.session() as s:
        try:
            uid = (await user_from_token(s, st.settings, token)).id
        except HTTPException:
            await ws.close(code=4401)
            return
    await ws.accept()
    queue = st.hub.subscribe(uid)
    audio_buf = bytearray()
    speaking: asyncio.Task | None = None
    await ws.send_json({"type": "ready"})

    async def forward_events():
        while True:
            await ws.send_json(await queue.get())

    async def run_turn(text: str, conversation_id: str | None, lang_hint: str, speak_reply: bool):
        nonlocal speaking
        async with st.db.session() as s:
            user = await s.get(User, uid)
            out = await st.agent.handle(st.make_ctx(s, user), text, conversation_id, lang_hint)
            await s.commit()
        await ws.send_json({"type": "reply", **out.model_dump(mode="json")})
        if speak_reply and st.tts.name != "browser":
            if speaking and not speaking.done():
                speaking.cancel()
            speaking = asyncio.create_task(_stream_audio(ws, st.tts, out.speech))

    pump = asyncio.create_task(forward_events())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                audio_buf += msg["bytes"]
                if len(audio_buf) > MAX_AUDIO_BYTES:
                    audio_buf.clear()
                    await ws.send_json({"type": "error", "message": "audio too large"})
                continue
            raw_text = msg.get("text") or "{}"
            if len(raw_text.encode("utf-8", "ignore")) > MAX_TEXT_BYTES:
                await ws.send_json({"type": "error", "message": "message too large"})
                continue
            try:
                data = json.loads(raw_text)
            except ValueError:
                await ws.send_json({"type": "error", "message": "invalid JSON"})
                continue
            kind = data.get("type")
            if kind == "ping":
                await ws.send_json({"type": "pong"})
            elif kind == "cancel":
                if speaking and not speaking.done():
                    speaking.cancel()
                await ws.send_json({"type": "audio_cancelled"})
            elif kind == "text" and str(data.get("text", "")).strip():
                await run_turn(str(data["text"])[:4000], data.get("conversation_id"), data.get("lang_hint", "auto"), data.get("speak", True))
            elif kind == "audio_end":
                blob, audio_buf = bytes(audio_buf), bytearray()
                if not blob:
                    await ws.send_json({"type": "error", "message": "no audio received"})
                    continue
                try:
                    res = await st.stt.transcribe(blob, data.get("mime", "audio/webm"), data.get("lang_hint"))
                except VoiceUnavailable as e:
                    await ws.send_json({"type": "error", "message": str(e)})
                    continue
                except Exception:  # noqa: BLE001
                    log.exception("stt failed")
                    await ws.send_json({"type": "error", "message": "speech recognition failed"})
                    continue
                await ws.send_json({"type": "transcript", "text": res.text, "lang": res.lang})
                if res.text.strip():
                    await run_turn(res.text, data.get("conversation_id"), data.get("lang_hint") or "auto", True)
    except WebSocketDisconnect:
        pass
    finally:
        pump.cancel()
        if speaking and not speaking.done():
            speaking.cancel()
        st.hub.unsubscribe(uid, queue)
