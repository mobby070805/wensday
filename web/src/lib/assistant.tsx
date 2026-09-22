"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { Realtime } from "./realtime";
import type { ChatReply, ServerEvent, Style, VoiceConfig } from "./types";
import { BrowserVoice, recordUtterance, type VoiceState } from "./voice";
import { hasWakeWord, recognitionLocale, stripWakeWord } from "./voice-utils";

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  style?: Style;
  intent?: string;
  tier?: string;
}

interface AssistantValue {
  messages: Message[];
  voiceState: VoiceState;
  interim: string;
  connected: boolean;
  syncTick: number;               // bumps whenever another device (or a voice command) changed data
  handsFree: boolean;
  muted: boolean;
  speechPref: "auto" | "ta-IN" | "en-IN";
  voiceConfig: VoiceConfig | null;
  error: string | null;
  send(text: string): Promise<void>;
  toggleListening(): void;
  interrupt(): void;
  setHandsFree(v: boolean): void;
  setMuted(v: boolean): void;
  setSpeechPref(v: "auto" | "ta-IN" | "en-IN"): void;
  clearError(): void;
}

const Ctx = createContext<AssistantValue | null>(null);
let seq = 0;
const mid = () => `m${Date.now()}-${seq++}`;

export function AssistantProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [interim, setInterim] = useState("");
  const [connected, setConnected] = useState(false);
  const [syncTick, setSyncTick] = useState(0);
  const [handsFree, setHandsFreeState] = useState(false);
  const [muted, setMuted] = useState(false);
  const [speechPref, setSpeechPref] = useState<"auto" | "ta-IN" | "en-IN">("auto");
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  const voice = useRef(new BrowserVoice());
  const rt = useRef<Realtime | null>(null);
  const conversation = useRef<string | null>(null);
  const lastStyle = useRef<Style | null>(null);
  const state = useRef<VoiceState>("idle");
  const handsFreeRef = useRef(false);
  const mutedRef = useRef(false);
  const prefRef = useRef(speechPref);
  const sendRef = useRef<(t: string) => Promise<void>>(async () => {});

  const setState = (s: VoiceState) => {
    state.current = s;
    setVoiceState(s);
  };
  useEffect(() => { mutedRef.current = muted; }, [muted]);
  useEffect(() => { prefRef.current = speechPref; }, [speechPref]);

  // ---- speaking
  const speak = useCallback(async (reply: Pick<ChatReply, "speech" | "reply" | "style">) => {
    if (mutedRef.current) return;
    setState("speaking");
    try {
      if (voiceConfig?.server_tts) {
        const res = await fetch(`${api.base}/voice/speak`, {
          method: "POST",
          headers: { "content-type": "application/json", authorization: `Bearer ${api.tokens?.access_token}` },
          body: JSON.stringify({ text: reply.reply, style: reply.style }),
        });
        if (res.ok) {
          const audio = new Audio(URL.createObjectURL(await res.blob()));
          await new Promise<void>((done) => { audio.onended = () => done(); audio.onerror = () => done(); void audio.play().catch(() => done()); });
        }
      } else {
        await voice.current.speak(reply.speech);
      }
    } finally {
      setState("idle");
      if (handsFreeRef.current) startContinuous();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceConfig]);

  // ---- chat
  const send = useCallback(async (text: string) => {
    const t = text.trim();
    if (!t) return;
    setError(null);
    setInterim("");
    setMessages((m) => [...m, { id: mid(), role: "user", text: t }]);
    setState("thinking");
    try {
      const r = await api.post<ChatReply>("/chat", { text: t, conversation_id: conversation.current });
      conversation.current = r.conversation_id;
      lastStyle.current = r.style;
      setMessages((m) => [...m, { id: mid(), role: "assistant", text: r.reply, style: r.style, intent: r.intent, tier: r.tier }]);
      await speak(r);
    } catch (e) {
      setState("idle");
      setError(e instanceof Error ? e.message : "Something went wrong");
    }
  }, [speak]);
  sendRef.current = send;

  // ---- listening
  const listenOnce = useCallback(async () => {
    setError(null);
    if (voiceConfig?.server_stt) {
      try {
        setState("listening");
        const { blob, mime } = await recordUtterance();
        setState("thinking");
        const form = new FormData();
        form.append("audio", blob, "utterance.webm");
        const out = await api.request<{ text: string }>("/voice/transcribe", { form });
        void (out.text ? sendRef.current(out.text) : setState("idle"));
        void mime;
      } catch (e) {
        setState("idle");
        setError(e instanceof Error ? e.message : "Recording failed");
      }
      return;
    }
    setState("listening");
    voice.current.startListening(recognitionLocale(prefRef.current, lastStyle.current), {
      onInterim: setInterim,
      onFinal: (text) => { voice.current.stopListening(); void sendRef.current(stripWakeWord(text)); },
      onError: (m) => { setError(m); setState("idle"); },
      onEnd: () => { if (state.current === "listening") setState("idle"); },
    });
  }, [voiceConfig]);

  // hands-free: keep listening, act only on utterances that start with the wake word
  const startContinuous = useCallback(() => {
    if (!handsFreeRef.current || state.current === "thinking" || state.current === "speaking") return;
    voice.current.startListening(recognitionLocale(prefRef.current, lastStyle.current), {
      onInterim: () => {},
      onFinal: (text) => { if (hasWakeWord(text)) { voice.current.stopListening(); void sendRef.current(stripWakeWord(text)); } },
      onError: (m) => setError(m),
      onEnd: () => { if (handsFreeRef.current && state.current === "idle") setTimeout(startContinuous, 300); },
    }, true);
  }, []);

  const setHandsFree = useCallback((v: boolean) => {
    handsFreeRef.current = v;
    setHandsFreeState(v);
    if (v) startContinuous();
    else if (state.current === "idle") voice.current.stopListening();
  }, [startContinuous]);

  const toggleListening = useCallback(() => {
    if (state.current === "speaking") { voice.current.cancelSpeech(); setState("idle"); return; }   // barge-in
    if (state.current === "listening") { voice.current.stopListening(); setState("idle"); return; }
    if (state.current === "idle") void listenOnce();
  }, [listenOnce]);

  const interrupt = useCallback(() => { voice.current.cancelSpeech(); setState("idle"); }, []);

  // ---- realtime + setup
  useEffect(() => {
    api.get<VoiceConfig>("/voice/config").then((c) => { setVoiceConfig(c); voice.current.setVoiceHints(c.preferred_voice_hints); }).catch(() => {});
    const socket = new Realtime(api);
    rt.current = socket;
    socket.onStatus = setConnected;
    const off = socket.on((e: ServerEvent) => {
      if (e.type === "sync") setSyncTick((n) => n + 1);
      if (e.type === "reminder.due") {
        setSyncTick((n) => n + 1);
        setMessages((m) => [...m, { id: mid(), role: "system", text: `⏰ ${e.text}`, style: e.style }]);
        void speak({ reply: e.text, style: e.style, speech: [{ text: e.text, lang: e.style === "ta" ? "ta" : "en", voice: "" }] });
        if (typeof Notification !== "undefined" && Notification.permission === "granted") new Notification("Wensday", { body: e.text });
      }
    });
    socket.start();
    if (typeof Notification !== "undefined" && Notification.permission === "default") void Notification.requestPermission();
    return () => { off(); socket.stop(); voice.current.stopListening(); voice.current.cancelSpeech(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Space bar = push-to-talk (when not typing)
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.code === "Space" && !["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) && !el.isContentEditable) { e.preventDefault(); toggleListening(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [toggleListening]);

  const value = useMemo<AssistantValue>(() => ({
    messages, voiceState, interim, connected, syncTick, handsFree, muted, speechPref, voiceConfig, error,
    send, toggleListening, interrupt, setHandsFree, setMuted, setSpeechPref, clearError: () => setError(null),
  }), [messages, voiceState, interim, connected, syncTick, handsFree, muted, speechPref, voiceConfig, error, send, toggleListening, interrupt, setHandsFree]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAssistant(): AssistantValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAssistant must be used inside <AssistantProvider>");
  return v;
}
