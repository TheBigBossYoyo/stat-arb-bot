// Adds jest-dom matchers (toBeInTheDocument, toBeDisabled, ...) to Vitest's expect.
import "@testing-library/jest-dom/vitest";

// jsdom has no WebSocket; the layout's live channel hook constructs one on mount.
// A no-op stub lets components that subscribe to a channel render in tests.
class MockWebSocket {
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  close(): void {}
  send(): void {}
}
// @ts-expect-error test stub for jsdom
globalThis.WebSocket = MockWebSocket;

// jsdom has no matchMedia; the theme system queries it for the system preference.
// Default to a dark OS preference so tests are deterministic. Individual tests may
// override window.matchMedia to assert system-mode behaviour.
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = ((query: string) => ({
    matches: false, // "(prefers-color-scheme: light)" => false => dark
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
