import { useContext } from "react";
import { ThemeContext, type ThemeContextValue } from "./ThemeProvider";

/** Access the active theme + setter. Must be used within <ThemeProvider>. */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within a <ThemeProvider>");
  }
  return ctx;
}
