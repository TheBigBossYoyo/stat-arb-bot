"""Integration tests for the supervised paper DAILY routine (operator mission,
Phase 2). The heavy data/strategy helpers are replaced with small synthetic
inputs so the REAL recording / stop-rule / health / summary path runs offline."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import app.cli.main as cli
import app.execution.paper_supervisor as ps
from app.core.types import utc_now

SYMBOLS = ["AAA", "BBB", "CCC", "DDD", "EEE"]   # 5 names -> 0.20 each, under the 25% cap


def _prices(n: int = 320):
    idx = pd.date_range(end=pd.Timestamp(utc_now().replace(tzinfo=None).date()),
                        periods=n, freq="D")
    rng = np.random.default_rng(3)
    data = {s: 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, n))) for s in SYMBOLS}
    close = pd.DataFrame(data, index=idx)
    return SimpleNamespace(close=close, symbols=list(SYMBOLS), aux={}, index=close.index)


def _benchmarks(n: int = 320):
    idx = pd.date_range(end=pd.Timestamp(utc_now().replace(tzinfo=None).date()),
                        periods=n, freq="D")
    return {"SPY": pd.Series(np.linspace(1.0, 1.08, n), index=idx)}


def _weights_fn(window, aux=None):
    return pd.Series({s: 0.2 for s in SYMBOLS})


@pytest.fixture
def synth(monkeypatch, tmp_path):
    prices, bench = _prices(), _benchmarks()
    monkeypatch.setattr(cli, "_long_only_setup",
                        lambda storage, u, i: ({}, prices, SimpleNamespace(fit_window=300), 5))
    monkeypatch.setattr(cli, "_smoothing_config", lambda defaults, **k: None)
    monkeypatch.setattr(cli, "_build_long_only", lambda *a, **k: (_weights_fn, list(SYMBOLS)))
    monkeypatch.setattr(cli, "_load_benchmarks", lambda storage, i: bench)
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (True, "paper_candidate", None))
    return SimpleNamespace(
        runtime_dir=tmp_path, live_trading_allowed=False, trading212_enabled=False,
        trading212_mode="demo", trading212_api_key="", trading212_api_secret="",
        trading212_account_type="invest", trading212_allow_demo_orders=False)


def test_daily_shadow_records_day(synth):
    res = cli.run_supervised_paper_daily(synth, None, product="long_only_t212", mode="shadow")
    assert res["refused"] is False
    assert res["status_line"] == "Shadow day recorded successfully."
    assert res["state"] in ("IN PROGRESS", "READY FOR FINAL REVIEW")
    assert res["day_info"]["mode"] == "shadow"
    assert res["day_info"]["smoothing_ok"] is True
    assert (synth.runtime_dir / "paper" / "latest_daily_summary.md").exists()


def test_daily_demo_preview_records_day(synth):
    res = cli.run_supervised_paper_daily(synth, None, product="long_only_t212",
                                         mode="demo_preview")
    assert res["refused"] is False
    assert res["status_line"] == "Demo preview recorded successfully."


def test_daily_demo_execute_refused_without_confirm(synth):
    res = cli.run_supervised_paper_daily(synth, None, product="long_only_t212",
                                         mode="demo_execute", confirm_demo=False)
    assert res["refused"] is True
    assert res["terminal"] is False
    assert res["status_line"].startswith("Paper day refused")
    assert "confirm-demo" in res["refusal_reason"]


def test_daily_refused_when_live_enabled(synth):
    synth.live_trading_allowed = True
    res = cli.run_supervised_paper_daily(synth, None, product="long_only_t212", mode="shadow")
    assert res["refused"] is True and res["terminal"] is True
    assert "live" in res["refusal_reason"].lower()


def test_daily_refused_when_not_paper_candidate(synth, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (False, "not_yet", None))
    res = cli.run_supervised_paper_daily(synth, None, product="long_only_t212", mode="shadow")
    assert res["refused"] is True and res["terminal"] is True
    assert "paper_candidate" in res["refusal_reason"]


def test_daily_stamps_session_provenance(synth):
    from app.execution.supervised_paper import SupervisedPaperStore
    cli.run_supervised_paper_daily(synth, None, product="long_only_t212", mode="shadow")
    sess = SupervisedPaperStore(synth.runtime_dir, "long_only_t212").current_session()
    assert sess is not None
    assert sess.config_hash != ""               # provenance was stamped
    assert sess.strategy_version == "long_only_xsec_momentum"
    assert sess.target_days == 90
    assert sess.data_snapshot.startswith("us_stocks_50@")


def test_daily_no_duplicate_same_day(synth):
    from app.execution.supervised_paper import SupervisedPaperStore
    first = cli.run_supervised_paper_daily(synth, None, product="long_only_t212", mode="shadow")
    assert first["already_completed_today"] is False
    second = cli.run_supervised_paper_daily(synth, None, product="long_only_t212", mode="shadow")
    assert second["already_completed_today"] is True
    assert second["refused"] is False
    store = SupervisedPaperStore(synth.runtime_dir, "long_only_t212")
    forward = [r for r in store.load("daily_reports") if not r.get("replay")]
    assert len(forward) == 1                     # the second run recorded nothing


def test_daily_force_overrides_duplicate_guard(synth):
    from app.execution.supervised_paper import SupervisedPaperStore
    cli.run_supervised_paper_daily(synth, None, product="long_only_t212", mode="shadow")
    forced = cli.run_supervised_paper_daily(synth, None, product="long_only_t212",
                                            mode="shadow", force=True)
    assert forced["already_completed_today"] is False
    store = SupervisedPaperStore(synth.runtime_dir, "long_only_t212")
    forward = [r for r in store.load("daily_reports") if not r.get("replay")]
    assert len(forward) == 2                     # --force recorded a second day
