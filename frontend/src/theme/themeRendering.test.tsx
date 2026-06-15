import { beforeEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import { THEME_STORAGE_KEY } from "./theme";
import { NotLiveBanner, DemoOnlyBanner, ShadowBanner, ReportBlock } from "../components/Banners";
import { Badge } from "../components/ui";
import { ChartCard, EquityChart } from "../components/charts";

/** A representative slice of the dashboard: safety banners, a danger badge, a
 *  chart and a rendered report. Used to prove nothing becomes invisible or
 *  unrenderable when the theme flips. */
function Slice() {
  return (
    <div>
      <NotLiveBanner />
      <DemoOnlyBanner />
      <ShadowBanner />
      <Badge tone="red" dot>DANGER</Badge>
      <ChartCard title="Equity curve">
        <EquityChart data={[{ ts: "2026-06-10", equity: 100 }, { ts: "2026-06-11", equity: 101 }]} />
      </ChartCard>
      <ReportBlock report={"# Weekly review\n\nRecommendation: CONTINUE"} />
    </div>
  );
}

function expectSliceVisible() {
  expect(screen.getByText(/NOT LIVE ELIGIBLE/i)).toBeInTheDocument();
  expect(screen.getByText(/DEMO ONLY/i)).toBeInTheDocument();
  expect(screen.getByText(/SHADOW MODE/i)).toBeInTheDocument();
  expect(screen.getByText("DANGER")).toBeInTheDocument();
  expect(screen.getByText("Equity curve")).toBeInTheDocument();         // chart card mounted
  expect(screen.getByText(/Recommendation: CONTINUE/)).toBeInTheDocument(); // report rendered
  // no live-trading control exists in any theme
  expect(screen.queryByRole("button", { name: /live/i })).toBeNull();
}

describe("theme rendering safety", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark", "light");
  });

  it("renders safety banners, badges, charts and reports in DARK mode", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    renderWithProviders(<Slice />);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expectSliceVisible();
  });

  it("renders safety banners, badges, charts and reports in LIGHT mode", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    renderWithProviders(<Slice />);
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expectSliceVisible();
  });
});
