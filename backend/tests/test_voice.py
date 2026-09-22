"""Voice: transliteration, language-run splitting, SSML, STT/TTS providers and the realtime audio socket."""
import re
import xml.etree.ElementTree as ET

import httpx
import pytest

from app.config import Settings
from app.voice.providers import (AzureSTT, AzureTTS, STTResult, VoiceUnavailable, WhisperSTT, BrowserSTT, BrowserTTS,
                                 build_stt, build_tts)
from app.voice.splitter import split_speech, to_ssml
from app.voice.translit import transliterate, transliterate_word
from .conftest import API, Person, running

S = Settings(jwt_secret="x" * 40)
_TAMIL_ONLY = re.compile(r"^[஀-௿\s.,?!:;'-]+$")   # Tamil script, plus punctuation that rides along


# ------------------------------------------------------------------ transliteration
@pytest.mark.parametrize("word", ["nalaiku", "panniten", "vanakkam", "inniku", "sollunga", "iruken", "saptingala", "romba", "eppo"])
def test_transliteration_produces_only_tamil_script(word):
    out = transliterate_word(word)
    assert out and _TAMIL_ONLY.match(out), out


def test_transliteration_known_forms_and_gemination():
    assert transliterate_word("vanakkam") == "வனக்கம்"       # kk -> க் + க
    assert transliterate_word("amma").startswith("அம்")        # vowel-initial + geminate mm
    assert transliterate("naa office") == transliterate_word("naa") + " " + transliterate_word("office")


def test_transliteration_is_deterministic_and_safe_on_junk():
    assert transliterate_word("panniten") == transliterate_word("PANNITEN")
    assert transliterate_word("") == "" and transliterate_word("123") == ""


# ------------------------------------------------------------------ splitting into voice runs
def test_tanglish_reply_is_split_into_tamil_and_english_voices():
    segs = split_speech("Sure Madesh, nalaiku morning 9:00 AM-ku meeting reminder set panniten.", "tg", S)
    by_lang = {}
    for s in segs:
        by_lang.setdefault(s.lang, []).append(s.text)
    assert all(_TAMIL_ONLY.match(t) for t in by_lang["ta"])          # Tanglish words reach the Tamil voice as Tamil script
    joined_en = " ".join(by_lang["en"])
    assert "Sure Madesh" in joined_en and "meeting" in joined_en and "9:00 AM" in joined_en           # numbers stay with the English run
    assert {s.voice for s in segs} == {"ta-IN-PallaviNeural", "en-IN-NeerjaNeural"}


def test_english_reply_is_one_english_segment():
    segs = split_speech("Sure Madesh, I've set a reminder for tomorrow at 9:00 AM.", "en", S)
    assert len(segs) == 1 and segs[0].lang == "en"


def test_tamil_reply_keeps_tamil_voice_and_hands_latin_names_to_english():
    segs = split_speech("சரி Madesh, நாளை காலை 9:00 மணிக்கு நினைவூட்டல் அமைத்துவிட்டேன்.", "ta", S)
    assert [s.lang for s in segs] == ["ta", "en", "ta"] or segs[0].lang == "ta"
    assert any(s.lang == "en" and "Madesh" in s.text for s in segs)


def test_splitting_never_loses_words():
    text = "Naan AI, saapaadu thevai illa. Neenga saptingala?"
    segs = split_speech(text, "tg", S)
    assert sum(len(s.text.split()) for s in segs) >= len(text.split()) - 1
    assert split_speech("", "en", S) == [] and split_speech("   ", "tg", S) == []


def test_ssml_is_valid_xml_with_per_run_voices_and_escaping():
    segs = split_speech("Tom & Jerry <meeting> nalaiku", "tg", S)
    root = ET.fromstring(to_ssml(segs, rate="slow"))               # parses => properly escaped
    ns = {"s": "http://www.w3.org/2001/10/synthesis"}
    voices = root.findall("s:voice", ns)
    assert {v.get("name") for v in voices} == {s.voice for s in segs}
    langs = {l.get("{http://www.w3.org/XML/1998/namespace}lang") for v in voices for l in v}
    assert langs <= {"ta-IN", "en-IN"} and "Tom & Jerry <meeting>" in "".join(root.itertext())


# ------------------------------------------------------------------ providers
def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_browser_providers_refuse_server_side_work():
    with pytest.raises(VoiceUnavailable):
        await BrowserSTT().transcribe(b"x", "audio/webm")
    with pytest.raises(VoiceUnavailable):
        await BrowserTTS().synthesize([])


async def test_whisper_biases_toward_tanglish_and_only_forces_language_when_told():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.content.decode("latin-1"))
        return httpx.Response(200, json={"text": " nalaiku 9 mani meeting remind pannu "})

    stt = WhisperSTT(_client(handler), "http://whisper/v1", "k")
    assert (await stt.transcribe(b"aud", "audio/webm")).text == "nalaiku 9 mani meeting remind pannu"
    assert (await stt.transcribe(b"aud", "audio/webm", "ta")).text
    assert "pannu" in seen[0] and 'name="language"' not in seen[0]      # mixed speech: let Whisper code-switch
    assert 'name="language"' in seen[1]


async def test_azure_stt_recognises_in_tamil_and_english_and_keeps_the_more_confident():
    def handler(req: httpx.Request):
        loc = req.url.params["language"]
        conf = {"ta-IN": 0.42, "en-IN": 0.91}[loc]
        return httpx.Response(200, json={"RecognitionStatus": "Success", "NBest": [{"Display": f"heard-{loc}", "Confidence": conf}]})

    stt = AzureSTT(_client(handler), "key", "centralindia")
    best = await stt.transcribe(b"aud", "audio/wav")
    assert best.text == "heard-en-IN" and best.lang == "en"
    assert (await stt.transcribe(b"aud", "audio/wav", "ta")).text == "heard-ta-IN"        # explicit hint -> single call


async def test_azure_stt_ignores_a_failed_locale_but_raises_when_all_fail():
    def one_bad(req):
        if req.url.params["language"] == "ta-IN":
            return httpx.Response(500)
        return httpx.Response(200, json={"RecognitionStatus": "Success", "NBest": [{"Display": "ok", "Confidence": 0.8}]})

    assert (await AzureSTT(_client(one_bad), "k", "r").transcribe(b"a", "audio/wav")).text == "ok"
    with pytest.raises(httpx.HTTPStatusError):
        await AzureSTT(_client(lambda r: httpx.Response(500)), "k", "r").transcribe(b"a", "audio/wav")


def test_build_stt_picks_the_configured_provider(caplog):
    http = httpx.AsyncClient()
    assert isinstance(build_stt(Settings(jwt_secret="x" * 40, stt_provider="whisper", whisper_base_url="http://w/v1"), http), WhisperSTT)
    assert isinstance(build_stt(Settings(jwt_secret="x" * 40, stt_provider="azure", azure_speech_key="k", azure_speech_region="r"), http), AzureSTT)
    assert isinstance(build_stt(Settings(jwt_secret="x" * 40, stt_provider="browser"), http), BrowserSTT)
    assert isinstance(build_tts(Settings(jwt_secret="x" * 40, tts_provider="azure", azure_speech_key="k", azure_speech_region="r"), http), AzureTTS)


def test_incomplete_provider_config_falls_back_but_logs_a_warning_instead_of_failing_silently(caplog):
    """Before this test: setting WENSDAY_STT_PROVIDER=azure with a missing key/region silently
    became browser STT with zero explanation anywhere — an operator would have no way to tell
    "intentionally browser" from "meant to be Azure but misconfigured" short of reading the code."""
    http = httpx.AsyncClient()
    with caplog.at_level("WARNING", logger="wensday.voice.providers"):
        assert isinstance(build_stt(Settings(jwt_secret="x" * 40, stt_provider="azure", azure_speech_key="k"), http), BrowserSTT)
    assert any("azure" in r.message.lower() and "falling back" in r.message.lower() for r in caplog.records)
    caplog.clear()

    with caplog.at_level("WARNING", logger="wensday.voice.providers"):
        assert isinstance(build_stt(Settings(jwt_secret="x" * 40, stt_provider="whisper"), http), BrowserSTT)
    assert any("whisper" in r.message.lower() for r in caplog.records)
    caplog.clear()

    with caplog.at_level("WARNING", logger="wensday.voice.providers"):
        assert isinstance(build_tts(Settings(jwt_secret="x" * 40, tts_provider="azure", azure_speech_region="r"), http), BrowserTTS)
    assert any("falling back" in r.message.lower() for r in caplog.records)


async def test_azure_tts_posts_ssml_with_the_right_headers():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(headers=req.headers, body=req.content.decode())
        return httpx.Response(200, content=b"MP3DATA")

    audio, mime = await AzureTTS(_client(handler), "key", "centralindia").synthesize(split_speech("hello nalaiku", "tg", S))
    assert audio == b"MP3DATA" and mime == "audio/mpeg"
    assert seen["headers"]["content-type"] == "application/ssml+xml" and "<speak" in seen["body"]


# ------------------------------------------------------------------ REST endpoints
class FakeSTT:
    name = "fake"

    def __init__(self, text="nalaiku 9 mani meeting remind pannu"):
        self.text = text

    async def transcribe(self, audio, mime, lang_hint=None):
        return STTResult(self.text, "ta", 0.9)


class FakeTTS:
    name = "fake"

    async def synthesize(self, segments, rate="default"):
        return b"A" * 40000, "audio/mpeg"


def test_voice_config_advertises_female_voices_and_client_side_defaults(madesh):
    cfg = madesh.get("/voice/config").json()
    assert cfg["server_stt"] is False and cfg["server_tts"] is False and cfg["wake_word"] == "wensday"
    assert cfg["voices"] == {"ta": "ta-IN-PallaviNeural", "en": "en-IN-NeerjaNeural"}
    assert "Pallavi" in cfg["preferred_voice_hints"]["ta-IN"] and cfg["locales"]["tanglish"] == "en-IN"


def test_server_side_voice_endpoints_are_501_when_the_client_owns_voice(madesh):
    assert madesh.post("/voice/transcribe", files={"audio": ("a.webm", b"x", "audio/webm")}).status_code == 501
    assert madesh.post("/voice/speak", {"text": "hi"}).status_code == 501


def test_transcribe_and_speak_with_server_providers():
    with running(stt=FakeSTT(), tts=FakeTTS()) as c:
        p = Person(c, "a@x.com", "Madesh")
        r = p.post("/voice/transcribe", files={"audio": ("a.webm", b"xx", "audio/webm")}, data={"lang_hint": "ta"})
        assert r.json() == {"text": "nalaiku 9 mani meeting remind pannu", "lang": "ta", "confidence": 0.9}
        sp = p.post("/voice/speak", {"text": "Sari Madesh", "style": "tg"})
        assert sp.status_code == 200 and sp.headers["content-type"] == "audio/mpeg" and len(sp.content) == 40000
        big = p.post("/voice/transcribe", files={"audio": ("a.webm", b"x" * (10 * 1024 * 1024 + 5), "audio/webm")})
        assert big.status_code == 413


# ------------------------------------------------------------------ realtime socket: full voice turn
def _drain_until(ws, wanted_type, limit=20):
    """Collect messages until one of `wanted_type`; returns (that message, everything before it)."""
    seen = []
    for _ in range(limit):
        m = ws.receive()
        if m.get("bytes") is not None:
            seen.append(m["bytes"])
            continue
        import json
        j = json.loads(m["text"])
        if j["type"] == wanted_type:
            return j, seen
        seen.append(j)
    raise AssertionError(f"never saw {wanted_type}: {seen}")


def test_full_voice_turn_audio_in_transcript_reply_audio_out():
    with running(stt=FakeSTT(), tts=FakeTTS()) as c:
        p = Person(c, "a@x.com", "Madesh")
        with c.websocket_connect(f"{API}/ws?token={p.tokens['access_token']}") as ws:
            assert ws.receive_json() == {"type": "ready"}
            ws.send_bytes(b"\x01" * 3000)
            ws.send_bytes(b"\x02" * 3000)
            ws.send_json({"type": "audio_end", "mime": "audio/webm"})

            transcript, _ = _drain_until(ws, "transcript")
            assert transcript["text"] == "nalaiku 9 mani meeting remind pannu"
            reply, _ = _drain_until(ws, "reply")
            assert reply["reply"] == "Sure Madesh, nalaiku morning 9:00 AM-ku meeting reminder set panniten." and reply["intent"] == "reminder_create"
            start, _ = _drain_until(ws, "audio_start")
            assert start["mime"] == "audio/mpeg"
            end, chunks = _drain_until(ws, "audio_end")
            assert len(chunks) == 3 and sum(len(b) for b in chunks) == 40000       # streamed in 16 KiB chunks
        assert len(p.get("/reminders").json()) == 1


def test_socket_text_turn_with_browser_tts_returns_reply_and_speech_segments_only(client, madesh):
    with client.websocket_connect(f"{API}/ws?token={madesh.tokens['access_token']}") as ws:
        ws.receive_json()
        ws.send_json({"type": "text", "text": "Saptiya?"})
        reply = ws.receive_json()
        assert reply["type"] == "reply" and reply["speech"] and reply["style"] == "tg"
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}                            # and no audio frames were queued in between


def test_socket_barge_in_cancel_and_error_handling():
    with running(stt=FakeSTT(), tts=FakeTTS()) as c:
        p = Person(c, "a@x.com", "Madesh")
        with c.websocket_connect(f"{API}/ws?token={p.tokens['access_token']}") as ws:
            ws.receive_json()
            ws.send_json({"type": "cancel"})
            assert ws.receive_json() == {"type": "audio_cancelled"}
            ws.send_json({"type": "audio_end", "mime": "audio/webm"})           # no audio was sent first
            assert ws.receive_json()["type"] == "error"
            ws.send_text("{not json")
            assert ws.receive_json() == {"type": "error", "message": "invalid JSON"}
            ws.send_json({"type": "text", "text": "hello", "speak": False})
            assert ws.receive_json()["type"] == "reply"                          # still healthy afterwards


def test_socket_with_browser_stt_tells_the_client_to_send_text(client, madesh):
    with client.websocket_connect(f"{API}/ws?token={madesh.tokens['access_token']}") as ws:
        ws.receive_json()
        ws.send_bytes(b"audio")
        ws.send_json({"type": "audio_end"})
        err = ws.receive_json()
        assert err["type"] == "error" and "client" in err["message"]


# ------------------------------------------------------------------ socket hardening
def test_socket_rejects_an_oversized_text_frame_without_crashing(client, madesh):
    """An unbounded text frame let a client force the server to json.loads() an arbitrarily
    large string on every message — no cap existed before this test. The connection must survive
    and keep answering normal messages afterwards."""
    with client.websocket_connect(f"{API}/ws?token={madesh.tokens['access_token']}") as ws:
        ws.receive_json()
        huge = "x" * (200 * 1024)  # far past any legitimate 4000-char chat message, even in Tamil UTF-8
        ws.send_json({"type": "text", "text": huge})
        err = ws.receive_json()
        assert err["type"] == "error" and "large" in err["message"].lower()
        # the connection is still healthy and did NOT try to run the oversized text as a turn
        ws.send_json({"type": "text", "text": "hello", "speak": False})
        assert ws.receive_json()["type"] == "reply"


def test_socket_connection_flood_from_one_ip_is_rate_limited():
    """Before this test: nothing stopped a single client from opening unlimited websocket
    connections per second (each one does a DB lookup to validate the token) — a cheap DoS /
    auth-brute-force vector with no cap anywhere on the /ws route."""
    with running(ws_connect_limit_per_minute=3) as c:
        p = Person(c, "a@x.com", "Madesh")
        url = f"{API}/ws?token={p.tokens['access_token']}"
        for _ in range(3):
            with c.websocket_connect(url) as ws:
                assert ws.receive_json() == {"type": "ready"}
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with c.websocket_connect(url) as ws:
                ws.receive_json()
        assert exc_info.value.code == 4429
