// Global toast queue: any view calls toast() and <Toasts/> (mounted once in
// App) renders the stack. Replaces the per-view inline "flash" messages.

import { create } from "zustand";

export type ToastKind = "info" | "success" | "error";

export interface Toast {
  id: number;
  text: string;
  kind: ToastKind;
}

interface ToastState {
  toasts: Toast[];
  push: (t: Toast) => void;
  dismiss: (id: number) => void;
}

export const useToasts = create<ToastState>((set) => ({
  toasts: [],
  push: (t) => set((s) => ({ toasts: [...s.toasts, t] })),
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

let nextId = 1;

export function toast(text: string, kind: ToastKind = "info", durationMs = 3500): void {
  const id = nextId++;
  useToasts.getState().push({ id, text, kind });
  window.setTimeout(() => useToasts.getState().dismiss(id), durationMs);
}
