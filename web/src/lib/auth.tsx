"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import type { Tokens, User } from "./types";

interface AuthValue {
  user: User | null;
  loading: boolean;
  login(email: string, password: string): Promise<void>;
  register(email: string, password: string, name: string): Promise<void>;
  acceptTokens(t: Tokens): Promise<void>;
  updateProfile(p: Partial<Pick<User, "name" | "timezone" | "language">>): Promise<void>;
  logout(): Promise<void>;
}

const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const loadMe = useCallback(async () => {
    try {
      setUser(await api.get<User>("/auth/me"));
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    (api.tokens ? loadMe() : Promise.resolve()).finally(() => setLoading(false));
  }, [loadMe]);

  const value = useMemo<AuthValue>(
    () => ({
      user,
      loading,
      async login(email, password) {
        api.setTokens(await api.request<Tokens>("/auth/login", { body: { email, password }, auth: false }));
        await loadMe();
      },
      async register(email, password, name) {
        api.setTokens(await api.request<Tokens>("/auth/register", { body: { email, password, name }, auth: false }));
        await loadMe();
      },
      async acceptTokens(t) {
        api.setTokens(t);
        await loadMe();
      },
      async updateProfile(p) {
        setUser(await api.patch<User>("/auth/me", p));
      },
      async logout() {
        const t = api.tokens;
        if (t) await api.request("/auth/logout", { body: { refresh_token: t.refresh_token }, auth: false }).catch(() => {});
        api.setTokens(null);
        setUser(null);
      },
    }),
    [user, loading, loadMe],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside <AuthProvider>");
  return v;
}
