"""Slippage models. Fills always move against you."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.types import Side


class SlippageModel(ABC):
    @abstractmethod
    def fill_price(self, side: Side, ref_price: float, quantity: float = 0.0) -> float: ...

    @abstractmethod
    def expected_bps(self, notional: float) -> float: ...


class FixedBpsSlippage(SlippageModel):
    def __init__(self, bps: float = 5.0) -> None:
        self.bps = bps

    def fill_price(self, side: Side, ref_price: float, quantity: float = 0.0) -> float:
        return ref_price * (1.0 + side.sign * self.bps / 10_000.0)

    def expected_bps(self, notional: float) -> float:
        return self.bps


class VolumeAwareSlippage(SlippageModel):
    """Fixed spread cost plus square-root market impact vs. typical bar volume."""

    def __init__(self, base_bps: float = 5.0, impact_coeff: float = 10.0,
                 typical_bar_notional: float = 1_000_000.0) -> None:
        self.base_bps = base_bps
        self.impact_coeff = impact_coeff
        self.typical_bar_notional = typical_bar_notional

    def expected_bps(self, notional: float) -> float:
        participation = notional / max(self.typical_bar_notional, 1.0)
        return self.base_bps + self.impact_coeff * participation**0.5

    def fill_price(self, side: Side, ref_price: float, quantity: float = 0.0) -> float:
        bps = self.expected_bps(abs(quantity) * ref_price)
        return ref_price * (1.0 + side.sign * bps / 10_000.0)
