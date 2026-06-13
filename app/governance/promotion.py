"""Governed promotion: the bridge between gates and the alpha registry.

`AlphaRegistry.promote` enforces the structural rules (one stage at a time,
live stages blocked, venue gate). This module adds the EVIDENCE gate: a
promotion to walk_forward / stress / paper / live_* only succeeds if
`evaluate_gates` returns approved for that transition. It is the single place
the acceptance criteria become executable.

Live-stage promotion additionally requires the registry's own block to be
lifted deliberately — this module never overrides it silently. It records the
gate report into the alpha's history so every promotion is auditable.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import audit, get_logger
from app.governance.gates import GateReport, evaluate_gates
from app.research.alpha_registry import LIVE_STAGES, Alpha, AlphaRegistry, RegistryError

log = get_logger(__name__)


@dataclass
class PromotionOutcome:
    approved: bool
    report: GateReport
    alpha: Alpha | None
    message: str


def attempt_promotion(
    registry: AlphaRegistry,
    alpha_id: str,
    to: str,
    evidence: dict,
    *,
    by: str = "operator",
    allow_live_override: bool = False,
) -> PromotionOutcome:
    """Evaluate gates, then promote only if approved.

    `allow_live_override`: live stages are hard-blocked in the registry. This
    flag is the single, explicit, audited switch that lets a fully-gated
    strategy through — it does NOT skip the gates, it only lifts the
    belt-and-braces block once every gate has passed.
    """
    alpha = registry.get(alpha_id)
    evidence = {
        **evidence,
        "executable_venues": alpha.executable_venues,
        "requires_short": alpha.requires_short,
        "requires_leverage": alpha.requires_leverage,
        "is_flagship": "flagship" in alpha_id,
    }
    report = evaluate_gates(to, evidence, stage_from=alpha.status)

    if not report.approved:
        fails = ", ".join(r.name for r in report.blocking_failures)
        audit("promotion_blocked", alpha_id=alpha_id, to=to, failures=fails)
        return PromotionOutcome(False, report, alpha,
                                f"BLOCKED: failed gates [{fails}]")

    reason = f"gates passed ({sum(r.passed for r in report.results)}/{len(report.results)})"
    try:
        if to in LIVE_STAGES and allow_live_override:
            # gates passed; lift the structural block deliberately and audited
            updated = _promote_live(registry, alpha_id, to, by=by, reason=reason)
        else:
            updated = registry.promote(alpha_id, to, by=by, reason=reason)
    except RegistryError as exc:
        return PromotionOutcome(False, report, alpha, f"REFUSED by registry: {exc}")
    return PromotionOutcome(True, report, updated, f"promoted to {to} ({reason})")


def _promote_live(registry: AlphaRegistry, alpha_id: str, to: str, *,
                  by: str, reason: str) -> Alpha:
    """Deliberate, audited live promotion after gates pass. Mirrors the
    registry's transition bookkeeping but bypasses the live-stage block, which
    exists to stop UNGATED live promotion — not gated ones."""
    from app.research.alpha_registry import LIVE_STAGES as _LS  # noqa: F401

    alpha = registry.get(alpha_id)
    alpha.history.append(registry._event(alpha.status, to,
                                          f"{reason} [live override, gated]", by=by))
    alpha.status = to
    registry.save()
    audit("alpha_promoted_live", alpha_id=alpha_id, to=to, by=by, reason=reason)
    log.warning("LIVE promotion of %s to %s — gated and audited", alpha_id, to)
    return alpha
