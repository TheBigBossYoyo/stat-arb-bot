"""Alpha registry: the single source of truth for what each strategy IS,
what it claims, and how far up the promotion pipeline it has earned its way.

The registry file (app/config/alpha_registry.yaml) is YAML on purpose: it is
versioned with the code, diffs are human-reviewable, and promotion history is
an append-only audit trail inside each entry.

Pipeline (see STRATEGY_ACCEPTANCE_CRITERIA.md):

    idea -> research -> backtest -> walk_forward -> stress -> paper
         -> shadow_live -> live_tiny -> live_scaled
    (any stage) -> rejected | retired

Hard rules enforced here, before any governance gates run:

* transitions move ONE stage forward at a time (no skipping), or to
  rejected/retired from anywhere;
* every transition records who/when/why (append-only history);
* promotion into any live stage is BLOCKED in code until the governance
  gate module exists and passes — no human typo can promote to live;
* promotion past `paper` is blocked while `executable_venues` is empty:
  a strategy no connected broker can hold does not get a live pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.core.logging import audit, get_logger
from app.core.types import utc_now

log = get_logger(__name__)

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "alpha_registry.yaml"

PIPELINE = [
    "idea", "research", "backtest", "walk_forward", "stress", "paper",
    "shadow_live", "live_tiny", "live_scaled",
]
TERMINAL = ["rejected", "retired"]
LIVE_STAGES = {"shadow_live", "live_tiny", "live_scaled"}
STATUSES = PIPELINE + TERMINAL


class RegistryError(Exception):
    pass


@dataclass
class Alpha:
    alpha_id: str
    name: str
    hypothesis: str
    asset_class: str
    universe: str
    horizon: str
    rebalance: str
    status: str = "idea"
    required_data: list[str] = field(default_factory=list)
    expected_capacity: str = ""
    expected_turnover: str = ""
    known_risks: list[str] = field(default_factory=list)
    requires_short: bool = False
    requires_leverage: bool = False
    executable_venues: list[str] = field(default_factory=list)
    experiment_ids: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "alpha_id"}


class AlphaRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or REGISTRY_PATH
        self._alphas: dict[str, Alpha] = {}
        self.load()

    # -- persistence -----------------------------------------------------------

    def load(self) -> None:
        self._alphas = {}
        if not self.path.exists():
            return
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        for alpha_id, body in (raw.get("alphas") or {}).items():
            known = set(Alpha.__dataclass_fields__) - {"alpha_id"}
            self._alphas[alpha_id] = Alpha(
                alpha_id=alpha_id, **{k: v for k, v in (body or {}).items() if k in known}
            )

    def save(self) -> None:
        payload = {"alphas": {a.alpha_id: a.to_dict() for a in self._alphas.values()}}
        self.path.write_text(
            "# Alpha registry — managed by `statarb alpha-registry`; hand-edits allowed\n"
            "# but promotion history is append-only. See STRATEGY_ACCEPTANCE_CRITERIA.md.\n"
            + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )

    # -- access ----------------------------------------------------------------

    def list(self, status: str | None = None) -> list[Alpha]:
        alphas = sorted(self._alphas.values(), key=lambda a: a.alpha_id)
        if status:
            alphas = [a for a in alphas if a.status == status]
        return alphas

    def get(self, alpha_id: str) -> Alpha:
        try:
            return self._alphas[alpha_id]
        except KeyError as exc:
            raise RegistryError(
                f"unknown alpha {alpha_id!r}; ids: {sorted(self._alphas)}") from exc

    def add(self, alpha: Alpha) -> None:
        if alpha.alpha_id in self._alphas:
            raise RegistryError(f"alpha {alpha.alpha_id!r} already exists")
        if alpha.status not in STATUSES:
            raise RegistryError(f"invalid status {alpha.status!r}")
        alpha.history.append(self._event(None, alpha.status, "registered"))
        self._alphas[alpha.alpha_id] = alpha
        self.save()

    def link_experiment(self, alpha_id: str, experiment_id: str) -> None:
        alpha = self.get(alpha_id)
        if experiment_id not in alpha.experiment_ids:
            alpha.experiment_ids.append(experiment_id)
            self.save()

    # -- transitions -------------------------------------------------------------

    def promote(self, alpha_id: str, to: str, *, by: str = "operator",
                reason: str = "") -> Alpha:
        alpha = self.get(alpha_id)
        if to not in STATUSES:
            raise RegistryError(f"invalid target status {to!r}; choose from {STATUSES}")
        if to in TERMINAL:
            return self._terminate(alpha, to, by=by, reason=reason)
        if alpha.status in TERMINAL:
            raise RegistryError(
                f"{alpha_id} is {alpha.status}; reinstate deliberately by editing "
                "the registry with a recorded reason, not via promote")
        cur_i = PIPELINE.index(alpha.status)
        new_i = PIPELINE.index(to)
        if new_i != cur_i + 1:
            raise RegistryError(
                f"{alpha_id}: {alpha.status} -> {to} skips stages; promotion moves "
                f"one stage at a time (next: {PIPELINE[cur_i + 1] if cur_i + 1 < len(PIPELINE) else 'none'})")
        if to in LIVE_STAGES:
            raise RegistryError(
                f"{alpha_id}: promotion to {to!r} is BLOCKED — the governance gate "
                "module (app/governance) must pass first, and it does not exist yet. "
                "No strategy goes live by registry edit.")
        if PIPELINE.index(to) > PIPELINE.index("paper") and not alpha.executable_venues:
            raise RegistryError(
                f"{alpha_id}: no executable venue — a strategy no connected broker "
                "can hold does not get a live pipeline (venue gate)")
        if not reason:
            raise RegistryError("a promotion reason is required (cite experiment IDs)")
        alpha.history.append(self._event(alpha.status, to, reason, by=by))
        alpha.status = to
        self.save()
        audit("alpha_promoted", alpha_id=alpha_id, to=to, by=by, reason=reason)
        return alpha

    def reject(self, alpha_id: str, *, reason: str, by: str = "operator") -> Alpha:
        if not reason:
            raise RegistryError("a rejection reason is required")
        return self._terminate(self.get(alpha_id), "rejected", by=by, reason=reason)

    def retire(self, alpha_id: str, *, reason: str, by: str = "operator") -> Alpha:
        if not reason:
            raise RegistryError("a retirement reason is required")
        return self._terminate(self.get(alpha_id), "retired", by=by, reason=reason)

    def _terminate(self, alpha: Alpha, to: str, *, by: str, reason: str) -> Alpha:
        alpha.history.append(self._event(alpha.status, to, reason, by=by))
        alpha.status = to
        self.save()
        audit("alpha_terminated", alpha_id=alpha.alpha_id, to=to, by=by, reason=reason)
        return alpha

    @staticmethod
    def _event(frm: str | None, to: str, reason: str, by: str = "operator") -> dict:
        return {"ts": utc_now().isoformat(), "from": frm, "to": to,
                "by": by, "reason": reason}
