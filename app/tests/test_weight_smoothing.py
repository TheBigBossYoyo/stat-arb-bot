"""Tests for Phase 1 target-weight smoothing (long-only concentration fix)."""

import math

import numpy as np
import pandas as pd
import pytest

from app.strategies.weight_smoothing import (
    SmoothingConfig,
    SmoothingWeightFn,
    WeightSmoother,
    enforce_long_only,
    make_smoother,
    smoothing_family,
)

# --- config / alpha mapping ---------------------------------------------------

def test_half_life_maps_to_alpha():
    assert math.isclose(SmoothingConfig(half_life=1.0).effective_alpha(), 0.5)
    # longer half-life => smaller alpha => smoother
    assert SmoothingConfig(half_life=5.0).effective_alpha() < SmoothingConfig(half_life=2.0).effective_alpha()
    # half_life overrides alpha when set
    assert SmoothingConfig(alpha=0.9, half_life=3.0).effective_alpha() < 0.9


def test_alpha_used_when_no_half_life():
    assert SmoothingConfig(method="ewma", alpha=0.7).effective_alpha() == 0.7


def test_labels_are_distinct():
    labels = {c.label() for c in smoothing_family()}
    assert "none" in labels
    assert any(lbl.startswith("ewma_") for lbl in labels)
    assert len(labels) == len(smoothing_family())  # no collisions


# --- enforce_long_only --------------------------------------------------------

def test_enforce_clips_shorts_caps_and_gross():
    w = pd.Series({"A": 0.6, "B": -0.3, "C": 0.7})
    out = enforce_long_only(w, max_weight=0.25, gross_target=1.0)
    assert (out >= -1e-12).all()                 # no shorts
    assert out.max() <= 0.25 + 1e-9              # per-name cap binds
    assert out.sum() <= 1.0 + 1e-9              # never levered


def test_enforce_never_scales_up():
    # already feasible and below target: must NOT inflate to the gross target
    w = pd.Series({"A": 0.1, "B": 0.1})
    out = enforce_long_only(w, max_weight=0.5, gross_target=1.0)
    assert out.sum() == pytest.approx(0.2)


# --- EWMA blend ---------------------------------------------------------------

def test_ewma_first_call_passthrough_then_blends():
    sm = WeightSmoother(SmoothingConfig(method="ewma", alpha=0.5),
                        max_weight=1.0, gross_target=1.0)
    a = pd.Series({"X": 1.0, "Y": 0.0})
    out1 = sm.smooth(a)
    assert out1["X"] == pytest.approx(1.0)       # first call: passthrough
    b = pd.Series({"X": 0.0, "Y": 1.0})
    out2 = sm.smooth(b)
    # 0.5*new + 0.5*prev
    assert out2["X"] == pytest.approx(0.5)
    assert out2["Y"] == pytest.approx(0.5)


def test_ewma_alpha_one_is_identity_after_enforce():
    sm = WeightSmoother(SmoothingConfig(method="ewma", alpha=1.0),
                        max_weight=1.0, gross_target=1.0)
    sm.smooth(pd.Series({"X": 0.2, "Y": 0.3}))
    out = sm.smooth(pd.Series({"X": 0.4, "Y": 0.1}))
    assert out["X"] == pytest.approx(0.4)
    assert out["Y"] == pytest.approx(0.1)


def test_none_method_is_passthrough_through_enforce():
    sm = WeightSmoother(SmoothingConfig(method="none"), max_weight=1.0, gross_target=1.0)
    out = sm.smooth(pd.Series({"X": 0.3, "Y": 0.2}))
    assert out["X"] == pytest.approx(0.3)


# --- capped change ------------------------------------------------------------

def test_capped_change_limits_per_name_move():
    sm = WeightSmoother(SmoothingConfig(method="capped_change", max_weight_change=0.05),
                        max_weight=1.0, gross_target=1.0)
    sm.smooth(pd.Series({"A": 0.0, "B": 0.0}))
    out = sm.smooth(pd.Series({"A": 0.5, "B": 0.0}))   # wants +0.5, capped to +0.05
    assert out["A"] == pytest.approx(0.05)


# --- constraints preserved on random targets ----------------------------------

def test_smoothing_preserves_long_only_on_random_targets():
    rng = np.random.default_rng(0)
    sm = WeightSmoother(SmoothingConfig(method="ewma", alpha=0.5),
                        max_weight=0.20, gross_target=1.0)
    cols = [f"A{i}" for i in range(10)]
    for _ in range(20):
        raw = pd.Series(rng.random(10), index=cols)
        target = raw / raw.sum()                  # sums to 1
        out = sm.smooth(target)
        assert (out >= -1e-12).all()             # never short
        assert out.max() <= 0.20 + 1e-9          # per-name cap
        assert out.sum() <= 1.0 + 1e-9           # never levered


# --- engine-compatible wrapper ------------------------------------------------

def test_smoothing_weight_fn_wraps_and_forwards_aux():
    class Inner:
        wants_aux = True

        def __call__(self, close_window, aux=None):
            assert aux == {"k": 1}
            return pd.Series({"A": 0.5, "B": 0.5})

    wrapped = SmoothingWeightFn(Inner(), SmoothingConfig(method="ewma", alpha=0.5),
                               max_weight=1.0, gross_target=1.0)
    assert wrapped.wants_aux is True
    out = wrapped(pd.DataFrame(), aux={"k": 1})
    assert out.sum() == pytest.approx(1.0)


def test_make_smoother_accepts_str_and_dict():
    assert make_smoother("ewma").config.method == "ewma"
    assert make_smoother({"method": "ewma", "alpha": 0.3}).config.alpha == 0.3
    assert make_smoother(None).config.method == "none"
