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
