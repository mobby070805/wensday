import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError, type TokenStore } from "@/lib/api";
import type { Tokens } from "@/lib/types";

function memStore(initial: Tokens | null): TokenStore & { value: Tokens | null } {
  const s = { value: initial, get: () => s.value, set: (t: Tokens | null) => { s.value = t; } };
  return s;
}
const json = (status: number, body: unknown = {}) => new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("ApiClient", () => {
  it("sends the bearer token and JSON body", async () => {
    const f = vi.fn().mockResolvedValue(json(200, { ok: 1 }));
    const c = new ApiClient(memStore({ access_token: "A", refresh_token: "R" }), f, "http://api");
    await c.post("/tasks", { title: "x" });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://api/tasks");
    expect(init.method).toBe("POST");
    expect(init.headers.authorization).toBe("Bearer A");
    expect(init.body).toBe('{"title":"x"}');
  });

  it("refreshes once on 401, stores the rotated pair, and retries", async () => {
    const store = memStore({ access_token: "old", refresh_token: "R1" });
    const f = vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith("/auth/refresh")) return json(200, { access_token: "new", refresh_token: "R2" });
      return (init.headers as Record<string, string>).authorization === "Bearer new" ? json(200, { ok: true }) : json(401);
    });
    const c = new ApiClient(store, f as unknown as typeof fetch, "http://api");
    expect(await c.get("/tasks")).toEqual({ ok: true });
    expect(store.value).toEqual({ access_token: "new", refresh_token: "R2" });
  });

  it("shares ONE refresh between parallel 401s (the server revokes a replayed refresh token)", async () => {
    const store = memStore({ access_token: "old", refresh_token: "R1" });
    let refreshes = 0;
    const f = vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith("/auth/refresh")) { refreshes++; await new Promise((r) => setTimeout(r, 10)); return json(200, { access_token: "new", refresh_token: "R2" }); }
      return (init.headers as Record<string, string>).authorization === "Bearer new" ? json(200, []) : json(401);
    });
    const c = new ApiClient(store, f as unknown as typeof fetch, "http://api");
    await Promise.all([c.get("/tasks"), c.get("/notes"), c.get("/goals")]);
    expect(refreshes).toBe(1);
  });

  it("signs out when the refresh fails", async () => {
    const store = memStore({ access_token: "old", refresh_token: "R1" });
    const out = vi.fn();
    const f = vi.fn(async () => json(401, { detail: "nope" }));
    const c = new ApiClient(store, f as unknown as typeof fetch, "http://api", out);
    await expect(c.get("/tasks")).rejects.toBeInstanceOf(ApiError);
    expect(store.value).toBeNull();
    expect(out).toHaveBeenCalledOnce();
  });

  it("does not try to refresh unauthenticated calls (login failures are plain 401s)", async () => {
    const f = vi.fn(async () => json(401, { detail: "invalid email or password" }));
    const c = new ApiClient(memStore(null), f as unknown as typeof fetch, "http://api");
    await expect(c.request("/auth/login", { body: { email: "a", password: "b" }, auth: false })).rejects.toMatchObject({ status: 401, message: "invalid email or password" });
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("surfaces FastAPI validation errors and handles 204", async () => {
    const f = vi.fn()
      .mockResolvedValueOnce(json(422, { detail: [{ msg: "bad" }] }))
      .mockResolvedValueOnce(json(204));
    const c = new ApiClient(memStore({ access_token: "A", refresh_token: "R" }), f, "http://api");
    await expect(c.post("/tasks", {})).rejects.toMatchObject({ status: 422 });
    expect(await c.del("/tasks/1")).toBeUndefined();
  });

  it("builds the realtime URL from the access token", () => {
    const c = new ApiClient(memStore({ access_token: "a b", refresh_token: "R" }), vi.fn(), "https://api.example.com/api/v1");
    expect(c.wsUrl()).toBe("wss://api.example.com/api/v1/ws?token=a%20b");
    expect(new ApiClient(memStore(null), vi.fn(), "http://x").wsUrl()).toBeNull();
  });
});
