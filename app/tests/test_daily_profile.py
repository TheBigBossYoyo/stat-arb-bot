"""The `daily:` profile in strategy_defaults.yaml must override 15m-tuned
parameters on 1d bars and leave other intervals untouched."""

from __future__ import annotations

from app.cli.main import _bars_per_year, _strategy_defaults


def test_daily_profile_merges_over_base_sections():
    base = _strategy_defaults("15m")
    daily = _strategy_defaults("1d")
    # overridden: crypto cost model does not apply to liquid large caps
    assert daily["basket"]["cost_bps"] < base["basket"]["cost_bps"]
    assert daily["momentum"]["tsmom_lookback_bars"] == 252
    assert daily["walk_forward"]["train_bars"] == 504
    # inherited: keys absent from the daily profile keep their base values
    assert daily["zscore_signal"]["entry_z"] == base["zscore_signal"]["entry_z"]
    assert daily["basket"]["s_entry"] == base["basket"]["s_entry"]


def test_daily_profile_key_never_leaks_into_sections():
    for interval in ("15m", "1d", None):
        assert "daily" not in _strategy_defaults(interval)


def test_bars_per_year_only_for_exchange_calendar_dailies():
    assert _bars_per_year("us_stocks_50", "1d") == 252.0
    assert _bars_per_year("fx_majors", "1d") == 252.0
    # crypto trades 24/7 — even on daily bars a year has ~365 of them
    assert _bars_per_year("crypto_top_10", "1d") is None
    assert _bars_per_year("us_stocks_50", "15m") is None
