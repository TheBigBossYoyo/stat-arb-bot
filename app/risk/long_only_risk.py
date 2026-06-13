"""Long-only / no-margin risk model for Trading 212 Invest/ISA (Path A).

The Invest/ISA account has three hard, non-negotiable constraints that the risk
model enforces *before* any order is planned:

* **No shorting** — every position weight must be >= 0.
* **No margin / no leverage** — gross exposure must be <= 1.0 (you can only buy
  with settled cash; you cannot borrow buying power).
* **Per-name and per-sector caps** — concentration control carried over from
  Phase 1 (a long-only book is even more exposed to single-name blow-ups
  because it cannot hedge).

`enforce` projects any target book onto the feasible set and reports what it had
to change; `validate` raises if a book is structurally illegal (a negative
weight reaching this layer is a bug upstream and must fail loudly).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.core.exceptions import CapabilityError


@dataclass
class LongOnlyConstraints:
    max_position: float = 0.20        # per-name cap (fraction of equity)
    max_gross: float = 1.0            # no leverage: total invested <= equity
    max_sector: float = 0.40          # per-sector cap (fraction of equity)
    min_cash_buffer: float = 0.0      # keep this fraction in cash (settlement)
    max_names: int = 0                # 0 = unlimited; else keep the largest N
    sectors: dict[str, str] = field(default_factory=dict)


@dataclass
class EnforcementResult:
    weights: pd.Series
    changed: bool
    violations: list[str]


class LongOnlyRiskModel:
    def __init__(self, constraints: LongOnlyConstraints | None = None) -> None:
        self.c = constraints or LongOnlyConstraints()

    def validate(self, weights: pd.Series) -> None:
        """Raise on a structurally illegal book (short or levered). This is a
        safety net: it should never trigger if the strategies are correct."""
        if (weights < -1e-9).any():
            shorts = list(weights[weights < -1e-9].index)
            raise CapabilityError(
                f"long-only venue: negative weight on {shorts} — shorting is "
                f"impossible on Trading 212 Invest/ISA")
        gross = float(weights.clip(lower=0).sum())
        if gross > self.c.max_gross + 1e-6:
            raise CapabilityError(
                f"no-margin venue: gross {gross:.3f} > {self.c.max_gross} — "
                f"cannot buy on leverage on Invest/ISA")

    def enforce(self, weights: pd.Series) -> EnforcementResult:
        """Project `weights` onto the feasible long-only / no-margin set."""
        c = self.c
        violations: list[str] = []
        original = weights.copy()
        w = weights.clip(lower=0.0)        # no shorts
        if (weights < -1e-9).any():
            violations.append("clipped negative (short) weights to 0")

        capped = w.clip(upper=c.max_position)
        if not capped.equals(w):
            violations.append(f"capped {(w > c.max_position).sum()} name(s) at "
                              f"{c.max_position:.0%}")
        w = capped

        if c.max_names and (w > 0).sum() > c.max_names:    # keep the largest N
            keep = w.nlargest(c.max_names).index
            w = w.where(w.index.isin(keep), 0.0)
            violations.append(f"trimmed to top {c.max_names} names")

        if c.sectors:                      # per-sector cap
            by_sector: dict[str, list[str]] = {}
            for sym in w.index:
                by_sector.setdefault(c.sectors.get(sym, "other"), []).append(sym)
            for names in by_sector.values():
                sec = float(w[names].sum())
                if sec > c.max_sector > 0:
                    w[names] = w[names] * (c.max_sector / sec)
                    violations.append("scaled an over-weight sector")

        max_gross = c.max_gross * (1.0 - c.min_cash_buffer)
        gross = float(w.sum())
        if gross > max_gross > 0:           # no leverage; cash absorbs remainder
            w = w * (max_gross / gross)
            violations.append(f"scaled book to gross {max_gross:.2f} (no margin)")

        changed = not w.reindex(original.index).fillna(0.0).round(9).equals(
            original.clip(lower=0).round(9))
        return EnforcementResult(weights=w, changed=changed, violations=violations)
