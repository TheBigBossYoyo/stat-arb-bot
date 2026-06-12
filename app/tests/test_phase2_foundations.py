"""Tests for the Phase 2-3 foundations: experiment tracking, alpha registry,
data audit, and the dividend-adjustment (total-return) data path."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data.storage import Storage


@pytest.fixture
def storage(tmp_path) -> Storage:
    s = Storage(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    s.init_db()
    return s


def _daily_bars(n: int = 300, start: str = "2024-01-01", price0: float = 100.0,
                seed: int = 3, dividends: dict[int, float] | None = None) -> pd.DataFrame:
    """Synthetic daily bars on a weekday calendar with optional cash dividends.

    Raw close drops by the dividend on ex-date; adj_close is the total-return
    series (back-adjusted), mirroring what Yahoo serves.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n)
    total_ret = np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    adj = price0 * total_ret / total_ret[0]
    raw = adj.copy()
    for i, amount in (dividends or {}).items():
        # before the ex-date the raw price carries the not-yet-paid dividend,
        # so it sits ABOVE the back-adjusted series and drops by ~amount at i
        raw[:i] *= (adj[i] + amount) / adj[i]
    return pd.DataFrame({
        "ts": dates, "open": raw * 0.999, "high": raw * 1.01, "low": raw * 0.99,
        "close": raw, "volume": 1e6, "adj_close": adj,
    })


# -- experiment tracking -------------------------------------------------------


def test_experiment_record_and_trial_count(storage):
    from app.research.experiment_tracking import ExperimentTracker

    tracker = ExperimentTracker(storage)
    rec1 = tracker.record(kind="basket", strategy="xsmom", universe="u", interval="1d",
                          config={"a": 1}, metrics={"sharpe": 1.2})
    rec2 = tracker.record(kind="basket", strategy="xsmom", universe="u", interval="1d",
                          config={"a": 2}, metrics={"sharpe": 0.4})
    assert rec1.trial_number == 1 and rec2.trial_number == 2
    assert rec1.family == rec2.family == "xsmom|u|1d"
    assert storage.count_experiment_trials("xsmom|u|1d") == 2
    assert sorted(storage.experiment_family_sharpes("xsmom|u|1d")) == [0.4, 1.2]
    row = storage.get_experiment(rec1.experiment_id)
    assert row is not None and row.config_hash == rec1.config_hash


def test_config_hash_is_canonical():
    from app.research.experiment_tracking import config_hash

    assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})
    assert config_hash({"a": 1}) != config_hash({"a": 2})


def test_data_fingerprint_detects_restatement(storage):
    from app.data.market_data import build_price_matrix
    from app.research.experiment_tracking import data_fingerprint_from_prices

    for sym, seed in (("AAA", 1), ("BBB", 2)):
        storage.upsert_bars(_daily_bars(seed=seed), source="test", symbol=sym, interval="1d")
    prices = build_price_matrix(storage, ["AAA", "BBB"], "1d", min_rows=10)
    fp1, start, end = data_fingerprint_from_prices(prices)
    assert fp1 and start is not None and end is not None
    prices.close.iloc[-1, 0] *= 1.001               # provider restates one close
    fp2, *_ = data_fingerprint_from_prices(prices)
    assert fp1 != fp2


# -- alpha registry --------------------------------------------------------------


@pytest.fixture
def registry(tmp_path):
    from app.research.alpha_registry import Alpha, AlphaRegistry

    reg = AlphaRegistry(path=tmp_path / "registry.yaml")
    reg.add(Alpha(
        alpha_id="test_alpha", name="Test", hypothesis="h", asset_class="equity",
        universe="u", horizon="d", rebalance="daily", status="research",
        requires_short=True,
    ))
    return reg


def test_registry_promote_one_stage(registry):
    a = registry.promote("test_alpha", "backtest", reason="EXP-1 positive")
    assert a.status == "backtest"
    assert a.history[-1]["to"] == "backtest"


def test_registry_refuses_stage_skip(registry):
    from app.research.alpha_registry import RegistryError

    with pytest.raises(RegistryError, match="skips stages"):
        registry.promote("test_alpha", "paper", reason="nope")


def test_registry_blocks_live_states(registry):
    from app.research.alpha_registry import RegistryError

    for stage in ("backtest", "walk_forward", "stress", "paper"):
        registry.promote("test_alpha", stage, reason="x")
    with pytest.raises(RegistryError, match="BLOCKED"):
        registry.promote("test_alpha", "shadow_live", reason="looks great")


def test_registry_requires_reason(registry):
    from app.research.alpha_registry import RegistryError

    with pytest.raises(RegistryError, match="reason"):
        registry.promote("test_alpha", "backtest", reason="")


def test_registry_reject_is_terminal_and_kept(registry, tmp_path):
    from app.research.alpha_registry import AlphaRegistry, RegistryError

    registry.reject("test_alpha", reason="failed OOS")
    reloaded = AlphaRegistry(path=tmp_path / "registry.yaml")
    a = reloaded.get("test_alpha")
    assert a.status == "rejected"
    assert a.history[-1]["reason"] == "failed OOS"
    with pytest.raises(RegistryError):
        reloaded.promote("test_alpha", "research", reason="zombie")


def test_seeded_registry_loads_and_blocks_flagship_live():
    """The repo's real registry must parse, and the flagship must be nowhere
    near a live stage (no executable venue for its short book)."""
    from app.research.alpha_registry import LIVE_STAGES, AlphaRegistry

    reg = AlphaRegistry()
    flagship = reg.get("flagship_daily_ensemble")
    assert flagship.status not in LIVE_STAGES
    assert flagship.executable_venues == []
    assert {a.alpha_id for a in reg.list(status="rejected")} >= {
        "pca_stat_arb", "sector_stat_arb", "xsec_reversion"}


# -- data audit -------------------------------------------------------------------


def test_data_audit_flags_survivorship_and_verdict(storage):
    from app.data.data_audit import audit_universe

    symbols = ["AAA", "BBB"]
    for i, sym in enumerate(symbols):
        storage.upsert_bars(_daily_bars(seed=i), source="yahoo", symbol=sym, interval="1d")
    rep = audit_universe(storage, "us_stocks_50", "1d", source="yahoo", symbols=symbols)
    assert rep.survivorship == "static_survivor"
    assert rep.verdict == "research_only"
    assert any("survivorship" in r for r in rep.verdict_reasons)
    md = rep.to_markdown()
    assert "RESEARCH_ONLY" in md and "AAA" in md


def test_data_audit_hard_fails_broken_symbol(storage):
    from app.data.data_audit import audit_universe

    good = _daily_bars(n=300)
    broken = _daily_bars(n=300).iloc[::4]           # 75% of bars missing
    storage.upsert_bars(good, source="yahoo", symbol="GOOD", interval="1d")
    storage.upsert_bars(broken, source="yahoo", symbol="BROKEN", interval="1d")
    rep = audit_universe(storage, "us_stocks_50", "1d", source="yahoo",
                         symbols=["GOOD", "BROKEN"])
    assert rep.verdict == "not_acceptable"
    assert any("BROKEN" in r for r in rep.verdict_reasons)


def test_data_audit_reports_missing_adjustment(storage):
    from app.data.data_audit import audit_universe

    bars = _daily_bars(n=300).drop(columns=["adj_close"])
    storage.upsert_bars(bars, source="yahoo", symbol="NOADJ", interval="1d")
    rep = audit_universe(storage, "us_stocks_50", "1d", source="yahoo", symbols=["NOADJ"])
    assert rep.adj_coverage_pct < 1.0
    assert any("dividend adjustment" in r for r in rep.verdict_reasons)


def test_audit_symbol_detects_stale_run():
    from app.data.data_audit import audit_symbol

    df = _daily_bars(n=100)
    df.loc[40:60, "close"] = df.loc[40, "close"]    # 20 flat closes
    a = audit_symbol(df, "FLAT", "1d", "equity", max_missing_pct=6.0)
    assert a.max_stale_run >= 5
    assert any("identical closes" in i for i in a.issues)


# -- dividend adjustment (total-return) data path ---------------------------------


def test_yahoo_parser_extracts_adjclose():
    from app.data.providers_yahoo import parse_chart_json

    payload = {"chart": {"result": [{
        "timestamp": [1700000000, 1700086400],
        "indicators": {
            "quote": [{"open": [10.0, 10.1], "high": [10.2, 10.3],
                       "low": [9.9, 10.0], "close": [10.1, 10.2],
                       "volume": [1000, 1100]}],
            "adjclose": [{"adjclose": [9.5, 9.6]}],
        },
    }]}}
    df = parse_chart_json(payload)
    assert list(df["adj_close"]) == [9.5, 9.6]
    # missing adjclose block must not break parsing (crypto/FX payloads)
    del payload["chart"]["result"][0]["indicators"]["adjclose"]
    df2 = parse_chart_json(payload)
    assert df2["adj_close"].isna().all()


def test_upsert_backfills_adj_close_on_conflict(storage):
    bars = _daily_bars(n=50)
    raw_only = bars.drop(columns=["adj_close"])
    storage.upsert_bars(raw_only, source="yahoo", symbol="KO", interval="1d")
    loaded = storage.load_bars(["KO"], "1d")
    assert loaded["adj_close"].isna().all()
    # re-download now carries adj_close: existing rows must gain it
    storage.upsert_bars(bars, source="yahoo", symbol="KO", interval="1d")
    loaded = storage.load_bars(["KO"], "1d")
    assert loaded["adj_close"].notna().all()
    # raw prices were NOT restated
    assert np.allclose(loaded["close"].to_numpy(), bars["close"].to_numpy())


def test_adjusted_matrix_neutralizes_dividend_drop(storage):
    """Research returns must be identical whether a payout came as a dividend
    (raw price drops, adj smooth) or as price appreciation — that is the whole
    point of total-return adjustment (audit W-05)."""
    from app.data.market_data import build_price_matrix

    div_bars = _daily_bars(n=200, dividends={100: 5.0})
    plain = _daily_bars(n=200, seed=9)
    storage.upsert_bars(div_bars, source="yahoo", symbol="DIV", interval="1d")
    storage.upsert_bars(plain, source="yahoo", symbol="PLN", interval="1d")

    raw = build_price_matrix(storage, ["DIV", "PLN"], "1d", min_rows=10, adjusted=False)
    adj = build_price_matrix(storage, ["DIV", "PLN"], "1d", min_rows=10, adjusted=True)
    assert not raw.adjusted and adj.adjusted
    assert adj.adjustment_coverage == pytest.approx(1.0)

    # raw series shows a phantom ~ -5/price return at the ex-date; adjusted does not
    ex_loc = 100
    raw_ret = raw.close["DIV"].pct_change().iloc[ex_loc]
    adj_ret = adj.close["DIV"].pct_change().iloc[ex_loc]
    expected_drop = -5.0 / raw.close["DIV"].iloc[ex_loc - 1]
    assert raw_ret < adj_ret                       # dividend drop visible in raw only
    assert raw_ret - adj_ret == pytest.approx(expected_drop, rel=0.05)
    # adjusted series equals the true total-return path
    assert np.allclose(adj.close["DIV"].to_numpy(),
                       div_bars["adj_close"].to_numpy(), rtol=1e-9)


def test_adjusted_matrix_partial_coverage_keeps_raw_and_reports(storage):
    from app.data.market_data import build_price_matrix

    with_adj = _daily_bars(n=150)
    without = _daily_bars(n=150, seed=5).drop(columns=["adj_close"])
    storage.upsert_bars(with_adj, source="yahoo", symbol="HASADJ", interval="1d")
    storage.upsert_bars(without, source="yahoo", symbol="NOADJ", interval="1d")
    m = build_price_matrix(storage, ["HASADJ", "NOADJ"], "1d", min_rows=10, adjusted=True)
    assert 0.0 < m.adjustment_coverage < 1.0
    assert np.allclose(m.close["NOADJ"].to_numpy(), without["close"].to_numpy())


def test_default_adjusted_helper():
    from app.cli.main import _default_adjusted

    assert _default_adjusted("us_stocks_50", "1d") is True
    assert _default_adjusted("crypto_top_10", "15m") is False
    assert _default_adjusted("crypto_top_10", "1d") is False
    assert _default_adjusted("synthetic_demo", "1d") is False


def test_universe_meta_defaults_to_survivor():
    from app.data.universe import get_universe_meta

    assert get_universe_meta("us_stocks_50").survivorship == "static_survivor"
    assert get_universe_meta("synthetic_demo").survivorship == "not_applicable"
    assert get_universe_meta("some_adhoc_list").survivorship == "static_survivor"
