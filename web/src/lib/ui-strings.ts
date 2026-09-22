/** UI chrome strings in English and Tamil (the assistant's own replies are handled by the server). */
export type UiLang = "en" | "ta";

const S = {
  en: {
    assistant: "Assistant", tasks: "Tasks", reminders: "Reminders", calendar: "Calendar", notes: "Notes", goals: "Goals",
    memory: "Memory", dashboard: "Dashboard", plugins: "Plugins", settings: "Settings", signOut: "Sign out",
    tapToSpeak: "Tap to speak", listening: "Listening…", thinking: "Thinking…", speaking: "Speaking…", handsFree: "Hands-free (say “Wensday”)",
    typeMessage: "Type in Tamil, English or Tanglish…", send: "Send", add: "Add", delete: "Delete", empty: "Nothing here yet.",
    online: "Connected", offline: "Reconnecting…", today: "Today", openTasks: "Open tasks", streak: "Day streak", overdue: "Overdue",
  },
  ta: {
    assistant: "உதவியாளர்", tasks: "பணிகள்", reminders: "நினைவூட்டல்கள்", calendar: "நாட்காட்டி", notes: "குறிப்புகள்", goals: "இலக்குகள்",
    memory: "நினைவகம்", dashboard: "முகப்பு", plugins: "செருகுநிரல்கள்", settings: "அமைப்புகள்", signOut: "வெளியேறு",
    tapToSpeak: "பேச தட்டவும்", listening: "கேட்கிறேன்…", thinking: "யோசிக்கிறேன்…", speaking: "பேசுகிறேன்…", handsFree: "கைகள் இல்லாமல் (“Wensday” என்று சொல்லுங்கள்)",
    typeMessage: "தமிழ், English, Tanglish எதிலும் எழுதுங்கள்…", send: "அனுப்பு", add: "சேர்", delete: "நீக்கு", empty: "இன்னும் எதுவும் இல்லை.",
    online: "இணைந்துள்ளது", offline: "மீண்டும் இணைக்கிறது…", today: "இன்று", openTasks: "நிலுவைப் பணிகள்", streak: "தொடர் நாட்கள்", overdue: "தாமதம்",
  },
} as const;

export type UiKey = keyof (typeof S)["en"];

export function t(lang: UiLang, key: UiKey): string {
  return S[lang][key] ?? S.en[key];
}

export const UI_KEYS_EN = Object.keys(S.en) as UiKey[];
export const UI_KEYS_TA = Object.keys(S.ta) as UiKey[];
