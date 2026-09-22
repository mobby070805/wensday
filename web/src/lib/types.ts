export type Style = "en" | "tg" | "ta";

export interface Tokens {
  access_token: string;
  refresh_token: string;
}

export interface User {
  id: string;
  email: string;
  name: string;
  timezone: string;
  language: "auto" | "ta" | "en" | "tanglish";
}

export interface SpeechSegment {
  text: string;
  lang: "ta" | "en";
  voice: string;
}

export interface ChatReply {
  conversation_id: string;
  reply: string;
  intent: string;
  lang: string;
  style: Style;
  tier: "rules" | "llm" | "offline";
  data: Record<string, unknown>;
  speech: SpeechSegment[];
}

export interface Task {
  id: string;
  title: string;
  notes: string;
  status: "open" | "done";
  priority: number;
  due_at: string | null;
  tags: string[];
  goal_id: string | null;
  completed_at: string | null;
}

export interface Reminder {
  id: string;
  title: string;
  due_at: string;
  status: string;
  recurrence: string;
  style: Style;
}

export interface CalEvent {
  id: string;
  title: string;
  start_at: string;
  end_at: string;
  location: string;
  source: string;
}

export interface Note {
  id: string;
  title: string;
  body: string;
  kind: string;
  tags: string[];
  pinned: boolean;
}

export interface Goal {
  id: string;
  title: string;
  description: string;
  status: string;
  progress: number;
  milestones: { id: string; title: string; done: boolean }[];
}

export interface Memory {
  id: string;
  kind: string;
  text: string;
  importance: number;
  created_at: string;
}

export interface PluginInfo {
  name: string;
  version: string;
  description: string;
  scopes: string[];
  tools: string[];
  enabled: boolean;
  granted_scopes: string[];
}

export interface Dashboard {
  tasks: { open: number; overdue: number; completed_total: number; completed_series: { date: string; completed: number }[] };
  streak_days: number;
  goals: { title: string; progress: number }[];
  reminders_fired: number;
  language_usage: Record<string, number>;
}

export interface VoiceConfig {
  stt: string;
  tts: string;
  server_stt: boolean;
  server_tts: boolean;
  voices: { ta: string; en: string };
  wake_word: string;
  preferred_voice_hints: Record<string, string[]>;
  locales: Record<string, string>;
}

export type ServerEvent =
  | { type: "ready" }
  | { type: "pong" }
  | { type: "transcript"; text: string; lang?: string }
  | ({ type: "reply" } & ChatReply)
  | { type: "reminder.due"; id: string; title: string; text: string; style: Style }
  | { type: "sync"; kind: string; op: string; id?: string }
  | { type: "audio_start"; mime: string }
  | { type: "audio_end" }
  | { type: "audio_cancelled" }
  | { type: "error"; message: string };
