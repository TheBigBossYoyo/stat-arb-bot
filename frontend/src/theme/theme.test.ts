import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_THEME,
  THEME_PREFS,
  THEME_STORAGE_KEY,
  applyTheme,
  nextPref,
  readStoredTheme,
  resolveTheme,
  storeTheme,
  systemTheme,
} from "./theme";

describe("theme helpers", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark", "light");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("offers exactly three preferences (dark, light, system)", () => {
    expect(THEME_PREFS).toEqual(["dark", "light", "system"]);
  });

  it("defaults to the brand dark theme when nothing is stored", () => {
    expect(readStoredTheme()).toBe(DEFAULT_THEME);
    expect(DEFAULT_THEME).toBe("dark");
  });

  it("persists and reads back a preference from localStorage", () => {
    storeTheme("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(readStoredTheme()).toBe("light");
  });

  it("ignores a corrupt stored value and falls back to the default", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "neon");
    expect(readStoredTheme()).toBe(DEFAULT_THEME);
  });

  it("resolves explicit prefs directly and system via matchMedia", () => {
    expect(resolveTheme("dark")).toBe("dark");
    expect(resolveTheme("light")).toBe("light");
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: true, media: q }));
    expect(systemTheme()).toBe("light");
    expect(resolveTheme("system")).toBe("light");
  });

  it("cycles dark -> light -> system -> dark", () => {
    expect(nextPref("dark")).toBe("light");
    expect(nextPref("light")).toBe("system");
    expect(nextPref("system")).toBe("dark");
  });

  it("applyTheme toggles the html class + color-scheme", () => {
    applyTheme("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    applyTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.classList.contains("light")).toBe(false);
  });
});
