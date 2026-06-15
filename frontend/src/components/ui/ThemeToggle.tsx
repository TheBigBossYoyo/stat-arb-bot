import { Icons } from "../icons";
import { useTheme } from "../../theme/useTheme";
import { nextPref, type ThemePref } from "../../theme/theme";

const LABEL: Record<ThemePref, string> = { dark: "Dark", light: "Light", system: "System" };
const ICON = { dark: Icons.moon, light: Icons.sun, system: Icons.monitor } as const;

/** Top-bar theme switcher. Cycles dark → light → system; the icon reflects the
 *  current preference. Preference persists to localStorage (see ThemeProvider). */
export default function ThemeToggle() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  const Icon = ICON[theme];
  return (
    <button
      type="button"
      onClick={() => setTheme(nextPref(theme))}
      title={`Theme: ${LABEL[theme]}${theme === "system" ? ` (${resolvedTheme})` : ""} — click to change`}
      aria-label={`Theme: ${LABEL[theme]} (click to change)`}
      data-theme-pref={theme}
      className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 px-2 py-1 text-xs font-medium text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200"
    >
      <Icon size={14} />
      <span className="hidden md:inline">{LABEL[theme]}</span>
    </button>
  );
}
