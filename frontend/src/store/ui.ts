import { create } from "zustand";

export type WsStatus = "connected" | "reconnecting" | "disconnected";

export interface Toast { id: number; kind: "info" | "success" | "error"; text: string }

interface UiState {
  wsStatus: WsStatus;
  toasts: Toast[];
  setWsStatus: (s: WsStatus) => void;
  toast: (kind: Toast["kind"], text: string) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useUi = create<UiState>((set) => ({
  wsStatus: "disconnected",
  toasts: [],
  setWsStatus: (wsStatus) => set({ wsStatus }),
  toast: (kind, text) => {
    const id = nextId++;
    set((s) => ({ toasts: [...s.toasts, { id, kind, text }] }));
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 6000);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
