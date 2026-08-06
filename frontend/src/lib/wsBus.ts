// Tiny pub/sub between the telemetry store (which owns the WebSocket) and
// features that need to send or observe messages without importing the store.
// Race Engineer both listens and talks, and a direct import in both directions
// would make store/telemetry.ts and store/engineer.ts a circular pair.

import type { ClientMessage, WsMessage } from "./types";

type Listener = (msg: WsMessage) => void;
type OpenListener = () => void;

const listeners = new Set<Listener>();
const openListeners = new Set<OpenListener>();
let sender: ((msg: ClientMessage) => boolean) | null = null;

/** Called by the telemetry store when the socket is ready to write. */
export function setWsSender(fn: ((msg: ClientMessage) => boolean) | null): void {
  sender = fn;
}

/** Send a client message; false when the socket isn't open (caller retries). */
export function sendWs(msg: ClientMessage): boolean {
  return sender ? sender(msg) : false;
}

export function publishWs(msg: WsMessage): void {
  for (const listener of listeners) listener(msg);
}

export function subscribeWs(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Fired on every (re)connect — capabilities must be re-registered. */
export function notifyWsOpen(): void {
  for (const listener of openListeners) listener();
}

export function subscribeWsOpen(listener: OpenListener): () => void {
  openListeners.add(listener);
  return () => openListeners.delete(listener);
}
