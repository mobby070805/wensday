import type { Tokens } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface TokenStore {
  get(): Tokens | null;
  set(t: Tokens | null): void;
}

/** localStorage-backed store (SSR-safe: returns null on the server). */
export const browserStore: TokenStore = {
  get() {
    if (typeof localStorage === "undefined") return null;
    try {
      return JSON.parse(localStorage.getItem("wensday.tokens") ?? "null");
    } catch {
      return null;
    }
  },
  set(t) {
    if (typeof localStorage === "undefined") return;
    if (t) localStorage.setItem("wensday.tokens", JSON.stringify(t));
    else localStorage.removeItem("wensday.tokens");
  },
};

type Fetch = typeof fetch;

export class ApiClient {
  private refreshing: Promise<boolean> | null = null;

  constructor(
    private store: TokenStore = browserStore,
    private fetcher: Fetch = (...a) => fetch(...a),
    public base: string = API_BASE,
    private onSignedOut: () => void = () => {},
  ) {}

  get tokens() {
    return this.store.get();
  }

  setTokens(t: Tokens | null) {
    this.store.set(t);
  }

  /** One refresh at a time: parallel 401s must not each burn (and thereby revoke) the refresh token. */
  private refresh(): Promise<boolean> {
    if (!this.refreshing) {
      this.refreshing = (async () => {
        const current = this.store.get();
        if (!current) return false;
        try {
          const r = await this.fetcher(`${this.base}/auth/refresh`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ refresh_token: current.refresh_token }),
          });
          if (!r.ok) return false;
          const j = await r.json();
          this.store.set({ access_token: j.access_token, refresh_token: j.refresh_token });
          return true;
        } catch {
          return false;
        }
      })().finally(() => {
        this.refreshing = null;
      });
    }
    return this.refreshing;
  }

  async request<T>(path: string, opts: { method?: string; body?: unknown; auth?: boolean; form?: FormData } = {}): Promise<T> {
    const send = () => {
      const headers: Record<string, string> = {};
      if (opts.body !== undefined) headers["content-type"] = "application/json";
      const t = this.store.get();
      if (opts.auth !== false && t) headers.authorization = `Bearer ${t.access_token}`;
      return this.fetcher(this.base + path, {
        method: opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET"),
        headers,
        body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
      });
    };

    let res = await send();
    if (res.status === 401 && opts.auth !== false) {
      if (await this.refresh()) res = await send();
      else {
        this.store.set(null);
        this.onSignedOut();
      }
    }
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const j = await res.json();
        detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(res.status, detail);
    }
    return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
  }

  get = <T,>(path: string) => this.request<T>(path);
  post = <T,>(path: string, body?: unknown) => this.request<T>(path, { method: "POST", body: body ?? {} });
  patch = <T,>(path: string, body: unknown) => this.request<T>(path, { method: "PATCH", body });
  put = <T,>(path: string, body: unknown) => this.request<T>(path, { method: "PUT", body });
  del = <T,>(path: string) => this.request<T>(path, { method: "DELETE" });

  wsUrl(): string | null {
    const t = this.store.get();
    return t ? `${this.base.replace(/^http/, "ws")}/ws?token=${encodeURIComponent(t.access_token)}` : null;
  }
}

export const api = new ApiClient(browserStore, undefined, API_BASE, () => {
  if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) window.location.assign("/login");
});
