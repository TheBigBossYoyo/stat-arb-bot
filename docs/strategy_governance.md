# Strategy governance

How a strategy moves from idea to capital — and, more often, how it gets
stopped. The contract is [`STRATEGY_ACCEPTANCE_CRITERIA.md`](../STRATEGY_ACCEPTANCE_CRITERIA.md);
this is the operator's guide to the machinery that enforces it.

## The pipeline

```
idea → research → backtest → walk_forward → stress → paper
     → shadow_live → live_tiny → live_scaled        (or → rejected / retired)
```

Two layers enforce promotion:

1. **Structural** (`app/research/alpha_registry.py`): one stage at a time,
   append-only history, live stages hard-blocked, venue gate (no executable
   venue → no live pipeline). Edits are auditable YAML.
2. **Evidence** (`app/governance/gates.py` + `promotion.py`): a transition only
   succeeds if every gate for that stage passes, evaluated from *recorded*
   evidence (validation reports, data audit). Missing evidence fails the gate —
   unproven claims do not advance.

Live promotion needs BOTH all gates green AND an explicit, audited
`allow_live_override` — the structural block exists to stop ungated live
promotion, never to be bypassed silently.

## Commands

```bash
statarb alpha-registry list                 # all alphas + status + venues
statarb alpha-registry show <id>            # full record + promotion history
statarb governance-report <id> --to stress  # gate verdict for a transition
statarb alpha-registry promote <id> --to walk_forward --reason "EXP-... OOS 0.9"
statarb alpha-registry reject <id> --reason "failed OOS"
```

`governance-report` reads the latest `validate-ensemble` and `data-audit`
reports to assemble evidence; run those first.

## Automatic demotion (`app/governance/retirement.py`)

Promotion is manual and slow; demotion is automatic and fast. A live strategy
is demoted/retired on: rolling-60d Sharpe below the OOS 5th percentile (decay),
realized slippage > 2× model for 10 days (critical), 15 days of unexplained
tracking error, a red data-quality verdict, a venue-capability loss (critical →
flatten), or a self-caused risk breach (critical). Two triggers, or one
critical, retires.

## Where things stand today

Every strategy is at its honest stage (`alpha-registry list`). The flagship is
at **`backtest`** and blocked from `walk_forward` by the return-concentration
gate. Nothing is at any live stage, and the flagship has no executable venue, so
the venue gate alone would stop it regardless.
