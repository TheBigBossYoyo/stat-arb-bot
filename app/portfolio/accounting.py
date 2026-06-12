"""Cash ledger: every cash movement (fills, fees, FX, transfers) as an entry.

The ledger is the accounting source of truth the broker balance is
reconciled against — if ledger balance and broker cash diverge, something
was missed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EntryKind(str, Enum):
    FILL = "fill"            # signed cash impact of a trade
    FEE = "fee"
    FX = "fx"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    DIVIDEND = "dividend"


@dataclass(frozen=True)
class LedgerEntry:
    ts: datetime
    kind: EntryKind
    amount: float            # signed, in `currency`
    currency: str = "USDT"
    symbol: str = ""
    note: str = ""


@dataclass
class CashLedger:
    entries: list[LedgerEntry] = field(default_factory=list)

    def record(self, entry: LedgerEntry) -> None:
        self.entries.append(entry)

    def record_fill(self, ts: datetime, symbol: str, cash_delta: float, fee: float,
                    currency: str = "USDT") -> None:
        self.record(LedgerEntry(ts, EntryKind.FILL, cash_delta, currency, symbol))
        if fee:
            self.record(LedgerEntry(ts, EntryKind.FEE, -abs(fee), currency, symbol))

    def balance(self, currency: str = "USDT") -> float:
        return sum(e.amount for e in self.entries if e.currency == currency)

    def total_fees(self, currency: str = "USDT") -> float:
        return -sum(
            e.amount for e in self.entries
            if e.kind is EntryKind.FEE and e.currency == currency
        )
