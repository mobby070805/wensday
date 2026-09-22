"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { user, login, register } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (user) router.replace("/");
  }, [user, router]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  async function google() {
    try {
      const { url } = await api.request<{ url: string }>("/auth/google/login", { auth: false });
      window.location.assign(url);
    } catch {
      setError("Google sign-in isn't configured on this server.");
    }
  }

  return (
    <div className="login">
      <form className="card" onSubmit={submit} aria-label={mode === "login" ? "Sign in" : "Create account"}>
        <div className="brand"><i />WENSDAY</div>
        <p className="muted" style={{ margin: 0 }}>Vanakkam! Your calm, voice-first assistant — Tamil, English & Tanglish.</p>
        {mode === "register" && (
          <label>Name<input className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" placeholder="What should I call you?" /></label>
        )}
        <label>Email<input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></label>
        <label>Password<input className="input" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>
        {error && <div className="error" role="alert">{error}</div>}
        <button className="btn primary" disabled={busy}>{mode === "login" ? "Sign in" : "Create account"}</button>
        <button type="button" className="btn" onClick={google}>Continue with Google</button>
        <button type="button" className="btn small" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}
