"""Tests for Phase 5 (supervised shadow/paper recording + TCA)."""

from __future__ import annotations

from app.execution.shadow import (
    PaperBook,
    ShadowCycle,
    ShadowRecorder,
    load_paper_book,
    paper_readiness,
    save_paper_book,
    summarize_period,
)


def test_paper_book_fills_and_equity(tmp_path):
    book = PaperBook(cash=10_000.0)
    book.apply_fill("AAA", "buy", 10, 100.0, fee=1.0)
    assert book.positions["AAA"] == 10
    assert book.cash == 10_000.0 - 1000.0 - 1.0
    assert book.equity({"AAA": 110.0}) == book.cash + 1100.0
    book.apply_fill("AAA", "sell", 10, 110.0, fee=1.0)     # flatten
    assert "AAA" not in book.positions


def test_book_persists(tmp_path):
    save_paper_book(tmp_path, "p", PaperBook(cash=500.0, positions={"X": 2.0}))
    book = load_paper_book(tmp_path, "p", starting_cash=10_000.0)
    assert book.cash == 500.0 and book.positions["X"] == 2.0


def test_recorder_roundtrip_and_summary(tmp_path):
    rec = ShadowRecorder(tmp_path, "long_only_equity")
    for i in range(5):
        rec.record(ShadowCycle(
            ts=f"2026-05-0{i + 1} 00:00:00", product="long_only_equity", mode="shadow",
            equity=10_000 + 100 * i, cash=5000, n_orders=3, n_rejected=0,
            gross_exposure=0.9,
            orders=[{"symbol": "A", "side": "buy", "quantity": 1, "ref_price": 100,
                     "limit_price": None, "target_weight": 0.3, "expected_slippage_bps": 5.0}],
            realized_pnl=100.0 if i else 0.0))
    rows = rec.load()
    assert len(rows) == 5
    summary = summarize_period(rows)
    assert summary["cycles"] == 5
    assert summary["total_orders"] == 15        # 5 cycles x 3 orders each
    assert summary["avg_expected_slippage_bps"] == 5.0
    assert summary["paper_return_pct"] > 0


def test_paper_readiness_requires_period_length():
    short = {"cycles": 3, "reject_rate_pct": 0.0, "avg_expected_slippage_bps": 5.0,
             "paper_return_pct": 5.0}
    ok, reasons = paper_readiness(short, min_cycles=20)
    assert not ok and any("period length" in r for r in reasons)
    long_ok = {"cycles": 25, "reject_rate_pct": 1.0, "avg_expected_slippage_bps": 8.0,
               "paper_return_pct": 4.0}
    assert paper_readiness(long_ok, min_cycles=20)[0]
