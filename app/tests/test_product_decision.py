"""Tests for the Phase 6 product-decision scoring."""

from __future__ import annotations

from app.research.product_decision import ProductStatus


def _p(pid, kind, risk, passed, total):
    return ProductStatus(product_id=pid, name=pid, venue="", asset_class="x",
                         requires_short=False, requires_leverage=False,
                         venue_connected=(kind in ("testnet", "live")),
                         venue_kind=kind, gates_passed=passed, gates_total=total,
                         risk_level=risk, status="not_yet")


def test_long_only_outscores_extreme_crypto_when_both_not_yet():
    # long-only: official venue (not wired), high risk, 6/7
    lo = _p("long_only", "official_not_wired", "high", 6, 7)
    # crypto: testnet only, extreme risk, 5/6
    cr = _p("crypto", "testnet", "extreme", 5, 6)
    assert lo.score > cr.score        # the safer real-venue book leads


def test_no_venue_penalized_hardest():
    none_venue = _p("mn", "none", "medium", 4, 4)       # perfect gates, no venue
    official = _p("lo", "official_not_wired", "high", 4, 4)
    assert official.score > none_venue.score
