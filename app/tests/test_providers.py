"""Daily data provider parsers (no network)."""

from __future__ import annotations

from app.data.providers_stooq import parse_stooq_csv
from app.data.providers_yahoo import parse_chart_json


def test_yahoo_chart_parsing():
    payload = {"chart": {"result": [{
        "timestamp": [1717545600, 1717632000],
        "indicators": {"quote": [{
            "open": [100.0, 101.0], "high": [102.0, 103.0],
            "low": [99.0, 100.5], "close": [101.5, 102.5],
            "volume": [1000, None],          # FX rows often have null volume
        }]},
    }]}}
    df = parse_chart_json(payload)
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume", "adj_close"]
    assert len(df) == 2
    assert df["volume"].iloc[1] == 0.0
    assert df["adj_close"].isna().all()      # no adjclose block in this payload
    assert df["ts"].dt.hour.eq(0).all()      # normalized to dates


def test_yahoo_empty_result():
    assert parse_chart_json({"chart": {"result": None}}).empty
    assert parse_chart_json({}).empty


def test_stooq_csv_parsing():
    csv = "Date,Open,High,Low,Close,Volume\n2026-01-02,10,11,9,10.5,1234\n2026-01-03,10.5,12,10,11,2345\n"
    df = parse_stooq_csv(csv)
    assert len(df) == 2
    assert df["close"].iloc[-1] == 11.0


def test_stooq_csv_without_volume_and_no_data():
    fx = "Date,Open,High,Low,Close\n2026-01-02,1.10,1.11,1.09,1.105\n"
    df = parse_stooq_csv(fx)
    assert df["volume"].iloc[0] == 0.0
    assert parse_stooq_csv("No data").empty
    assert parse_stooq_csv("<html>challenge</html>").empty
