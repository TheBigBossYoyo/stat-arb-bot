import { beforeEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../../test/renderWithProviders";
import { THEME_STORAGE_KEY } from "../../theme/theme";
import ThemeToggle from "./ThemeToggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark", "light");
  });

  it("renders the default (dark) preference", () => {
    renderWithProviders(<ThemeToggle />);
    const btn = screen.getByRole("button", { name: /theme: dark/i });
    expect(btn).toBeInTheDocument();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("switches to light mode and persists the choice", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ThemeToggle />);
    await user.click(screen.getByRole("button", { name: /theme: dark/i }));
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(screen.getByRole("button", { name: /theme: light/i })).toBeInTheDocument();
  });

  it("cycles dark -> light -> system (system option exists)", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ThemeToggle />);
    const getBtn = () => screen.getByRole("button");
    await user.click(getBtn()); // -> light
    await user.click(getBtn()); // -> system
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");
    expect(screen.getByRole("button", { name: /theme: system/i })).toBeInTheDocument();
  });

  it("switches back to dark mode on the full cycle", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ThemeToggle />);
    const getBtn = () => screen.getByRole("button");
    await user.click(getBtn()); // light
    await user.click(getBtn()); // system
    await user.click(getBtn()); // dark
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
