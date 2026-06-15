// Theme system: framework-agnostic helpers used by ThemeProvider/useTheme.
// Preferences are "dark" | "light" | "system"; "system" resolves to the OS
// preference at runtime. Theme choice NEVER affects trading logic or safety
// gates — it only swaps presentation tokens.

export type ThemePref = "dark" | "light" | "system";
export type ResolvedTheme = "dark" | "light";

export const THEME_STORAGE_KEY = "statarb.theme";
export const THEME_PREFS: ThemePref[] = ["dark", "light", "system"];
export const DEFAULT_THEME: ThemePref = "dark";

export function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "dark";
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function resolveTheme(pref: ThemePref): ResolvedTheme {
  return pref === "system" ? systemTheme() : pref;
}

export function readStoredTheme(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY);
    if (v === "dark" || v === "light" || v === "system") return v;
  } catch {
    /* localStorage unavailable (private mode / SSR) — fall through */
  }
  return DEFAULT_THEME;
}

export function storeTheme(pref: ThemePref): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, pref);
  } catch {
    /* ignore persistence failures */
  }
}

/** Apply a resolved theme to <html>: toggles the class, color-scheme + data attr. */
export function applyTheme(resolved: ResolvedTheme): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.remove("dark", "light");
  root.classList.add(resolved);
  root.style.colorScheme = resolved;
  root.setAttribute("data-theme", resolved);
}

/** Cycle dark → light → system → dark for the toggle button. */
export function nextPref(pref: ThemePref): ThemePref {
  const i = THEME_PREFS.indexOf(pref);
  return THEME_PREFS[(i + 1) % THEME_PREFS.length];
}
