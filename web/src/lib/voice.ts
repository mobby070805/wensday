/** Browser voice engine: speech recognition (STT), speech synthesis (TTS) and optional server-side recording.
 *
 * - STT: Web Speech API (real-time interim results) — one locale per session, chosen by `recognitionLocale`.
 * - TTS: SpeechSynthesis. A reply arrives pre-split into language runs (`speech`), each spoken with the best
 *        female voice for that language, so Tanglish replies switch between Tamil and English voices.
 * - Server STT: MediaRecorder + a tiny silence detector; audio goes over the realtime socket.
 */
import type { SpeechSegment } from "./types";
import { pickVoice, rateFor } from "./voice-utils";

export type VoiceState = "idle" | "listening" | "thinking" | "speaking";

interface RecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: any) => void) | null;
  onerror: ((e: any) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

export interface VoiceEvents {
  onInterim(text: string): void;
  onFinal(text: string): void;
  onError(message: string): void;
  onEnd(): void;
}

export class BrowserVoice {
  private rec: RecognitionLike | null = null;
  private hints: Record<string, string[]> = {};
  rate = 1;

  get sttSupported() {
    return typeof window !== "undefined" && !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);
  }

  get ttsSupported() {
    return typeof window !== "undefined" && "speechSynthesis" in window;
  }

  setVoiceHints(h: Record<string, string[]>) {
    this.hints = h;
  }

  startListening(locale: string, ev: VoiceEvents, continuous = false) {
    const Ctor = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!Ctor) return ev.onError("Speech recognition isn't supported in this browser. Try Chrome or Edge, or type instead.");
    this.stopListening();
    const rec: RecognitionLike = new Ctor();
    rec.lang = locale;
    rec.continuous = continuous;
    rec.interimResults = true;
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) ev.onFinal(r[0].transcript.trim());
        else interim += r[0].transcript;
      }
      if (interim) ev.onInterim(interim);
    };
    rec.onerror = (e) => {
      if (e.error === "no-speech" || e.error === "aborted") return;
      ev.onError(e.error === "not-allowed" ? "Microphone permission was denied." : `Speech recognition error: ${e.error}`);
    };
    rec.onend = () => ev.onEnd();
    this.rec = rec;
    rec.start();
  }

  stopListening() {
    this.rec?.abort();
    this.rec = null;
  }

  /** Speak each run with the right voice; resolves when finished or cancelled. */
  speak(segments: SpeechSegment[]): Promise<void> {
    if (!this.ttsSupported || !segments.length) return Promise.resolve();
    const synth = window.speechSynthesis;
    synth.cancel();
    const voices = synth.getVoices();
    return new Promise((resolve) => {
      segments.forEach((seg, i) => {
        const u = new SpeechSynthesisUtterance(seg.text);
        const v = pickVoice(voices, seg.lang, this.hints[seg.lang === "ta" ? "ta-IN" : "en-IN"] ?? []);
        if (v) u.voice = v;
        u.lang = v?.lang ?? (seg.lang === "ta" ? "ta-IN" : "en-IN");
        u.rate = rateFor(seg.lang, this.rate);
        u.pitch = 1.05; // a touch warmer
        if (i === segments.length - 1) {
          u.onend = () => resolve();
          u.onerror = () => resolve();
        }
        synth.speak(u);
      });
    });
  }

  /** Barge-in: stop talking immediately. */
  cancelSpeech() {
    if (this.ttsSupported) window.speechSynthesis.cancel();
  }
}

/** Record one utterance with a silence cut-off and hand back the audio (for server-side STT). */
export async function recordUtterance(opts: { maxMs?: number; silenceMs?: number; threshold?: number } = {}): Promise<{ blob: Blob; mime: string }> {
  const { maxMs = 15000, silenceMs = 1200, threshold = 0.02 } = opts;
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/mp4";
  const recorder = new MediaRecorder(stream, { mimeType: mime });
  const chunks: Blob[] = [];
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);

  const ctx = new AudioContext();
  const analyser = ctx.createAnalyser();
  ctx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Float32Array(analyser.fftSize);

  return new Promise((resolve) => {
    let lastVoice = performance.now();
    let heard = false;
    const started = performance.now();
    const tick = setInterval(() => {
      analyser.getFloatTimeDomainData(buf);
      const rms = Math.sqrt(buf.reduce((s, x) => s + x * x, 0) / buf.length);
      const now = performance.now();
      if (rms > threshold) {
        lastVoice = now;
        heard = true;
      }
      if (now - started > maxMs || (heard && now - lastVoice > silenceMs)) {
        clearInterval(tick);
        recorder.stop();
      }
    }, 100);
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close();
      resolve({ blob: new Blob(chunks, { type: mime }), mime: mime.split(";")[0] });
    };
    recorder.start(250);
  });
}
