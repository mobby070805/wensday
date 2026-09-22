import type { ApiClient } from "./api";
import type { ServerEvent } from "./types";

type Listener = (e: ServerEvent) => void;
type Binary = (chunk: ArrayBuffer) => void;

/** The single realtime socket: voice turns, reminder pushes and cross-device sync events. */
export class Realtime {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private binary = new Set<Binary>();
  private stopped = true;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  connected = false;
  onStatus: (connected: boolean) => void = () => {};

  constructor(private client: ApiClient) {}

  start() {
    this.stopped = false;
    this.open();
  }

  stop() {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
    this.ws = null;
  }

  on(l: Listener) {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  }

  onBinary(l: Binary) {
    this.binary.add(l);
    return () => this.binary.delete(l);
  }

  send(msg: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
    else throw new Error("not connected");
  }

  sendBinary(data: ArrayBuffer | Blob) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(data);
  }

  private async open() {
    const url = this.client.wsUrl();
    if (!url || this.stopped) return;
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      this.attempt = 0;
      this.connected = true;
      this.onStatus(true);
    };
    ws.onmessage = (m) => {
      if (typeof m.data === "string") {
        try {
          const evt = JSON.parse(m.data) as ServerEvent;
          this.listeners.forEach((l) => l(evt));
        } catch {
          /* ignore malformed frame */
        }
      } else this.binary.forEach((l) => l(m.data as ArrayBuffer));
    };
    ws.onclose = async (ev) => {
      this.connected = false;
      this.onStatus(false);
      if (this.stopped) return;
      // 4401 = the access token expired: fetch a fresh one through a cheap authenticated call, then reconnect
      if (ev.code === 4401) await this.client.get("/auth/me").catch(() => {});
      const delay = Math.min(15000, 500 * 2 ** this.attempt++) + Math.random() * 300;
      this.timer = setTimeout(() => this.open(), delay);
    };
  }
}
