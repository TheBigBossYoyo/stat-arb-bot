"""Target-weight smoothing for the long-only book (Phase 1 concentration fix).

The long-only `long_only_xsec_momentum` book clears six of seven readiness gates;
the one failure is *return concentration* — its worst calendar month is 26.1% of
total PnL versus a 25% limit. The honest way to attack that is NOT to delete the
winning month (that just cuts return and proves nothing) but to make the same
edge arrive more evenly: rebalance more gradually so a single jump in target
weights cannot dump the whole book into the names that happen to rip in one
month.

This module implements a small, transparent *family* of weight transforms, each
stateful across rebalances and each preserving the hard long-only constraints:

* **none**           — identity (the unsmoothed baseline).
* **ewma**           — `w_t = alpha*target_t + (1-alpha)*w_{t-1}`. Lower alpha =
                       smoother = slower to chase a new leader. Configurable by
                       `alpha` directly or by a `half_life` in rebalances.
* **capped_change**  — cap the per-name change in weight per rebalance at
                       `max_weight_change`, so no single rebalance can swing more
                       than a fixed budget into/out of a name (a turnover brake).
* **ewma_capped**    — EWMA first, then the per-name change cap (belt and braces).

Every transform re-enforces the constraints AFTER smoothing, because blending or
capping can nudge a name over its cap or the book over its gross target:

* all weights >= 0            (no shorting — Trading 212 Invest/ISA reality)
* per-name weight <= max_weight
* gross sum <= gross_target   (no margin/leverage; cash absorbs the remainder)

Smoothing is OPTIONAL and OFF by default (`method="none"`): nothing changes until
a configuration is selected, and a default is only adopted once the comparison
command (`compare-concentration-fixes`) shows it lowers concentration WITHOUT
breaking out-of-sample Sharpe. Each configuration tested is registered in the
trial tracker as one member of the smoothing parameter family.
"""

from __future__ import annotations

import math
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

SmoothingMethod = Literal["none", "ewma", "capped_change", "ewma_capped"]


class SmoothingConfig(BaseModel):
    """Configuration for one member of the weight-smoothing family."""

    method: SmoothingMethod = "none"
    alpha: float = Field(default=0.5, ge=0.0, le=1.0)   # EWMA blend on the NEW target
    half_life: float | None = None                       # rebalances; overrides alpha if set
    max_weight_change: float = Field(default=0.05, gt=0.0)  # per-name per-rebalance cap

    def effective_alpha(self) -> float:
        """EWMA blend weight on the new target. If `half_life` is set it takes
        precedence: alpha = 1 - 0.5**(1/half_life), the standard EWMA mapping."""
        if self.half_life is not None and self.half_life > 0:
            return 1.0 - 0.5 ** (1.0 / float(self.half_life))
        return float(self.alpha)

    def label(self) -> str:
        if self.method == "none":
            return "none"
        if self.method in ("ewma", "ewma_capped"):
            hl = f"hl{self.half_life:g}" if self.half_life else f"a{self.alpha:g}"
            base = f"{self.method}_{hl}"
            return base + (f"_dc{self.max_weight_change:g}" if self.method == "ewma_capped" else "")
        return f"capped_change_{self.max_weight_change:g}"


def enforce_long_only(weights: pd.Series, *, max_weight: float, gross_target: float) -> pd.Series:
    """Project a weight vector onto the long-only feasible set.

    Order matters: clip negatives to zero, clip each name to its cap, then scale
    the whole book down (never up) so gross <= gross_target. We never scale UP to
    hit the target — that would re-concentrate or re-lever; unused exposure is
    simply held as cash, which is the long-only reality.
    """
    w = weights.clip(lower=0.0)
    if max_weight and max_weight > 0:
        w = w.clip(upper=max_weight)
    gross = float(w.sum())
    if gross_target and gross > gross_target > 0:
        w = w * (gross_target / gross)
    return w


class WeightSmoother:
    """Stateful target-weight smoother applied once per rebalance.

    Holds the previously *emitted* (post-smoothing) book so the next blend is
    against what was actually held, not against an un-smoothed target. The first
    call passes through (no prior book to blend with). Constraints are re-enforced
    after every transform so the emitted book is always long-only and un-levered.
    """

    def __init__(self, config: SmoothingConfig | None = None, *,
                 max_weight: float = 0.20, gross_target: float = 1.0) -> None:
        self.config = config or SmoothingConfig()
        self.max_weight = max_weight
        self.gross_target = gross_target
        self._prev: pd.Series | None = None

    def reset(self) -> None:
        self._prev = None

    def smooth(self, target: pd.Series) -> pd.Series:
        cfg = self.config
        target = target.fillna(0.0)
        if cfg.method == "none":
            out = target
        else:
            prev = (self._prev.reindex(target.index).fillna(0.0)
                    if self._prev is not None else target)
            out = target
            if cfg.method in ("ewma", "ewma_capped"):
                a = cfg.effective_alpha()
                out = a * target + (1.0 - a) * prev
            if cfg.method in ("capped_change", "ewma_capped"):
                # cap the per-name move relative to the previous emitted book
                ref = prev if cfg.method == "capped_change" else prev
                delta = (out - ref).clip(lower=-cfg.max_weight_change,
                                         upper=cfg.max_weight_change)
                out = ref + delta
        out = enforce_long_only(out, max_weight=self.max_weight, gross_target=self.gross_target)
        self._prev = out.copy()
        return out


def make_smoother(config: SmoothingConfig | dict | str | None, *,
                  max_weight: float = 0.20, gross_target: float = 1.0) -> WeightSmoother:
    """Build a WeightSmoother from a config, a dict, a method name, or None."""
    if config is None:
        cfg = SmoothingConfig()
    elif isinstance(config, str):
        cfg = SmoothingConfig(method=config)  # type: ignore[arg-type]
    elif isinstance(config, dict):
        cfg = SmoothingConfig(**config)
    else:
        cfg = config
    return WeightSmoother(cfg, max_weight=max_weight, gross_target=gross_target)


class SmoothingWeightFn:
    """Wrap a (possibly aux-consuming) long-only weight fn with a stateful
    smoother. Compatible with the basket / long-only engine: forwards `aux` when
    the inner fn wants it and re-exposes `wants_aux`."""

    def __init__(self, inner: object, config: SmoothingConfig | None = None, *,
                 max_weight: float = 0.20, gross_target: float = 1.0) -> None:
        self.inner = inner
        self.smoother = WeightSmoother(config, max_weight=max_weight, gross_target=gross_target)
        self.wants_aux = bool(getattr(inner, "wants_aux", False))

    def __call__(self, close_window: pd.DataFrame, aux: dict | None = None) -> pd.Series:
        if getattr(self.inner, "wants_aux", False):
            weights = self.inner(close_window, aux=aux)
        else:
            weights = self.inner(close_window)
        return self.smoother.smooth(weights)

    def sleeve_allocations(self):  # pragma: no cover - passthrough for ensembles
        return self.inner.sleeve_allocations()


def smoothing_family(alphas: tuple[float, ...] = (0.7, 0.5, 0.35),
                     half_lives: tuple[float, ...] = (2.0, 3.0, 5.0),
                     change_caps: tuple[float, ...] = (0.05, 0.03)) -> list[SmoothingConfig]:
    """The parameter family swept by the comparison command and registered in the
    trial tracker. A deliberately small, economically-motivated grid — NOT an
    open-ended hunt: a few EWMA half-lives, a couple of alphas, a couple of
    per-name change caps, plus the unsmoothed baseline."""
    family: list[SmoothingConfig] = [SmoothingConfig(method="none")]
    family += [SmoothingConfig(method="ewma", half_life=hl) for hl in half_lives]
    family += [SmoothingConfig(method="ewma", alpha=a) for a in alphas]
    family += [SmoothingConfig(method="capped_change", max_weight_change=c) for c in change_caps]
    family += [SmoothingConfig(method="ewma_capped", half_life=3.0, max_weight_change=c)
               for c in change_caps]
    return family


def _assert_halflife_alpha_consistency() -> None:  # pragma: no cover - sanity doc
    """half_life of 1 rebalance => alpha 0.5 (one-step half decay)."""
    assert math.isclose(SmoothingConfig(half_life=1.0).effective_alpha(), 0.5)
