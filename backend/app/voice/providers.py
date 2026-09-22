"""Speech-to-text and text-to-speech providers.

`browser` (default) means the *client* does STT/TTS with the Web Speech API / OS engines —
zero server cost, works offline on-device, gives real-time interim transcripts. Server
providers (Whisper-compatible, Azure) handle clients that can't, or want better Tamil.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings
from app.schemas import SpeechSegment
from .splitter import to_ssml

log = logging.getLogger("wensday.voice.providers")


class VoiceUnavailable(Exception):
    """The configured provider does not run server-side (e.g. `browser`) or is not configured."""


@dataclass
class STTResult:
    text: str
    lang: str | None = None     # ta | en when the provider knows
    confidence: float | None = None


class STTProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes, mime: str, lang_hint: str | None = None) -> STTResult: ...


class TTSProvider(Protocol):
    name: str

    async def synthesize(self, segments: list[SpeechSegment], rate: str = "default") -> tuple[bytes, str]: ...


# Biases Whisper towards Tanglish/Tamil vocabulary so code-switched speech isn't "corrected" into English.
_WHISPER_PROMPT = "Wensday, nalaiku 9 mani meeting remind pannu. Mail send pannunga. நாளை காலை ரிமைண்டர் வை. Naa office poitu varen."


class BrowserSTT:
    name = "browser"

    async def transcribe(self, audio, mime, lang_hint=None):
        raise VoiceUnavailable("speech recognition runs on the client (browser/OS); send text instead")


class BrowserTTS:
    name = "browser"

    async def synthesize(self, segments, rate="default"):
        raise VoiceUnavailable("speech synthesis runs on the client; use the `speech` segments in the reply")


class WhisperSTT:
    """OpenAI-compatible /audio/transcriptions (OpenAI, faster-whisper-server, whisper.cpp server…)."""

    name = "whisper"

    def __init__(self, client: httpx.AsyncClient, base_url: str, api_key: str | None, model: str = "whisper-1"):
        self._c, self._base, self._key, self._model = client, base_url.rstrip("/"), api_key, model

    async def transcribe(self, audio, mime, lang_hint=None):
        data = {"model": self._model, "prompt": _WHISPER_PROMPT, "response_format": "json"}
        if lang_hint in ("ta", "en"):  # for Tanglish/mixed, leave language unset so Whisper can code-switch
            data["language"] = lang_hint
        ext = "webm" if "webm" in mime else "wav" if "wav" in mime else "mp3" if "mpeg" in mime else "m4a"
        r = await self._c.post(f"{self._base}/audio/transcriptions", data=data, files={"file": (f"audio.{ext}", audio, mime)},
                               headers={"Authorization": f"Bearer {self._key}"} if self._key else {}, timeout=60)
        r.raise_for_status()
        return STTResult(text=r.json().get("text", "").strip())


class AzureSTT:
    """Azure short-audio REST. Recognises with ta-IN and en-IN in parallel and keeps the more confident
    result — a pragmatic answer to Tamil/English code-switching without the streaming SDK."""

    name = "azure"

    def __init__(self, client: httpx.AsyncClient, key: str, region: str):
        self._c, self._key, self._region = client, key, region

    async def _one(self, audio: bytes, mime: str, locale: str) -> STTResult:
        url = f"https://{self._region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
        r = await self._c.post(url, params={"language": locale, "format": "detailed"}, content=audio, timeout=30, headers={
            "Ocp-Apim-Subscription-Key": self._key, "Content-Type": mime if "wav" in mime else "audio/ogg; codecs=opus"})
        r.raise_for_status()
        j = r.json()
        if j.get("RecognitionStatus") != "Success":
            return STTResult("", locale[:2], 0.0)
        best = (j.get("NBest") or [{}])[0]
        return STTResult(best.get("Display") or j.get("DisplayText", ""), locale[:2], float(best.get("Confidence", 0.0)))

    async def transcribe(self, audio, mime, lang_hint=None):
        locales = {"ta": ["ta-IN"], "en": ["en-IN"]}.get(lang_hint or "", ["ta-IN", "en-IN"])
        results = await asyncio.gather(*(self._one(audio, mime, loc) for loc in locales), return_exceptions=True)
        ok = [r for r in results if isinstance(r, STTResult) and r.text]
        if not ok:
            errs = [r for r in results if isinstance(r, Exception)]
            if errs:
                raise errs[0]
            return STTResult("", None, 0.0)
        return max(ok, key=lambda r: r.confidence or 0.0)


class AzureTTS:
    name = "azure"

    def __init__(self, client: httpx.AsyncClient, key: str, region: str):
        self._c, self._key, self._region = client, key, region

    async def synthesize(self, segments, rate="default"):
        r = await self._c.post(f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1", content=to_ssml(segments, rate).encode(),
                               timeout=30, headers={"Ocp-Apim-Subscription-Key": self._key, "Content-Type": "application/ssml+xml",
                                                    "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3"})
        r.raise_for_status()
        return r.content, "audio/mpeg"


def build_stt(settings: Settings, client: httpx.AsyncClient) -> STTProvider:
    if settings.stt_provider == "whisper":
        if settings.whisper_base_url:
            return WhisperSTT(client, settings.whisper_base_url, settings.openai_api_key)
        log.warning("WENSDAY_STT_PROVIDER=whisper but WENSDAY_WHISPER_BASE_URL is unset; falling back to browser STT")
    elif settings.stt_provider == "azure":
        if settings.azure_speech_key and settings.azure_speech_region:
            return AzureSTT(client, settings.azure_speech_key, settings.azure_speech_region)
        log.warning("WENSDAY_STT_PROVIDER=azure but AZURE_SPEECH_KEY/AZURE_SPEECH_REGION is incomplete; falling back to browser STT")
    return BrowserSTT()


def build_tts(settings: Settings, client: httpx.AsyncClient) -> TTSProvider:
    if settings.tts_provider == "azure":
        if settings.azure_speech_key and settings.azure_speech_region:
            return AzureTTS(client, settings.azure_speech_key, settings.azure_speech_region)
        log.warning("WENSDAY_TTS_PROVIDER=azure but AZURE_SPEECH_KEY/AZURE_SPEECH_REGION is incomplete; falling back to browser TTS")
    return BrowserTTS()
