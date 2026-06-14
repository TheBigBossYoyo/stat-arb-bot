"""Tests for the paper-vs-backtest behaviour comparison (operator mission, Phase 5)."""

from __future__ import annotations

from app.execution.paper_vs_backtest import compare
from app.execution.supervised_paper import SupervisedPaperStore


def _store(tmp_path):
    return SupervisedPaperStore(tmp_path, "long_only_t212")


def _day(store, date, *, equity=10_000.0, gross=0.95, top=0.2, holdings=15,
         n_orders=2, n_rejected=0, order_notional=1000.0, slip=5.0, spy=10_000.0):
    store.append("daily_reports", {
        "date": date, "replay": False, "equity": equity, "gross_exposure": gross,
        "top_weight": top, "n_holdings": holdings, "n_orders": n_orders,
        "n_rejected": n_rejected, "drawdown_pct": -1.0})
    store.append("orders", {"date": date, "notional": order_notional})
    store.append("tca", {"date": date, "realized_slippage_bps": slip})
    store.append("benchmark_snapshots", {"date": date, "spy_equity": spy})


def test_invalid_when_too_few_days(tmp_path):
    store = _store(tmp_path)
    _day(store, "2026-06-10")
    rep = compare(store)
    assert rep.verdict == "invalid / not comparable"
    assert rep.forward_days == 1


def test_within_expected_range(tmp_path):
    store = _store(tmp_path)
    for i in range(8):
        _day(store, f"2026-06-{10 + i:02d}", equity=10_000.0 + 20 * i,
             spy=10_000.0 + 15 * i)
    rep = compare(store)
    assert rep.forward_days == 8
    assert rep.verdict.startswith("within expected range")
    by = {r.metric: r for r in rep.rows}
    assert by["concentration_top_weight"].status == "within"
    assert by["gross_exposure"].status == "within"
    # return-shaped metrics are informational on a small sample
    assert by["alpha_vs_benchmark_annual_pct"].operational is False
    assert rep.as_dict()["live_eligible"] is False


def test_severely_degraded_on_high_concentration(tmp_path):
    store = _store(tmp_path)
    for i in range(8):
        _day(store, f"2026-06-{10 + i:02d}", top=0.45)
    rep = compare(store)
    assert rep.verdict == "severely degraded"
    by = {r.metric: r for r in rep.rows}
    assert by["concentration_top_weight"].status == "severely_degraded"
