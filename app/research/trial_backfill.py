"""Historical trial back-fill + selection-group statistics (Phase 2).

The deflated Sharpe is only honest if it knows how many configurations were
actually searched. The experiment tracker started counting late, so it sees ~1
trial for a flagship that took ~50 configs to find. This module back-fills the
documented historical trials (from `app/config/research_trials.yaml`, every
entry cited to docs/) into the experiment registry, grouped into *selection
families* — the set of configs evaluated for the same decision — so the
deflation in `deflated-sharpe-report` corrects for the real search.

Idempotent: each manifest trial gets a deterministic `BACKFILL-<id>` experiment
id, so re-running inserts nothing new. Trials carry `backfilled: true` and their
source citation in the config snapshot, and never claim a git commit.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.types import utc_now
from app.data.storage import Storage
from app.research.experiment_tracking import ExperimentTracker, config_hash

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "config" / "research_trials.yaml"


@dataclass
class Trial:
    trial_id: str
    group: str
    strategy: str
    universe: str
    interval: str
    sharpe: float | None
    return_pct: float | None
    source: str


def load_trial_manifest(path: Path | None = None) -> tuple[dict, list[Trial]]:
    """Parse the manifest, expanding any `count: N` entry into N counted trials
    and inheriting universe/interval from the group when not set per-trial."""
    raw = yaml.safe_load((path or MANIFEST_PATH).read_text(encoding="utf-8"))
    groups = raw.get("groups", {})
    trials: list[Trial] = []
    for t in raw.get("trials", []):
        gmeta = groups.get(t["group"], {})
        universe = t.get("universe", gmeta.get("universe", ""))
        interval = t.get("interval", gmeta.get("interval", ""))
        count = int(t.get("count", 1))
        for i in range(count):
            tid = t["id"] if count == 1 else f"{t['id']}_{i + 1}"
            trials.append(Trial(
                trial_id=tid, group=t["group"], strategy=t["strategy"],
                universe=universe, interval=interval,
                sharpe=t.get("sharpe"), return_pct=t.get("return_pct"),
                source=t.get("source", ""),
            ))
    return groups, trials


def backfill_trials(storage: Storage, path: Path | None = None) -> dict:
    """Insert any manifest trial not already in the registry. Idempotent."""
    _groups, trials = load_trial_manifest(path)
    existing = {r.experiment_id for r in storage.list_experiments(limit=1_000_000)}
    inserted = skipped = 0
    by_group: dict[str, int] = {}
    for t in trials:
        by_group[t.group] = by_group.get(t.group, 0) + 1
        exp_id = f"BACKFILL-{t.trial_id}"
        if exp_id in existing:
            skipped += 1
            continue
        metrics: dict = {}
        if t.sharpe is not None:
            metrics["sharpe"] = t.sharpe
        if t.return_pct is not None:
            metrics["total_return_pct"] = t.return_pct
        cfg = {"group": t.group, "backfilled": True, "source": t.source,
               "trial_id": t.trial_id}
        storage.record_experiment(
            experiment_id=exp_id, created_at=utc_now().replace(tzinfo=None),
            kind="backfill", strategy=t.strategy, universe=t.universe,
            interval=t.interval,
            family=ExperimentTracker.make_family(t.strategy, t.universe, t.interval),
            git_commit="", git_dirty=False, config_json=cfg, config_hash=config_hash(cfg),
            data_fingerprint="", data_start=None, data_end=None, seed=None,
            sample="in_sample", metrics_json=metrics, notes=f"backfilled trial: {t.source}",
        )
        inserted += 1
    return {"inserted": inserted, "skipped": skipped,
            "total_manifest_trials": len(trials), "by_group": by_group}


def _experiment_group(row) -> str | None:
    try:
        return json.loads(row.config_json or "{}").get("group")
    except (TypeError, ValueError):
        return None


@dataclass
class GroupStats:
    group: str
    n_trials: int
    sharpes: list[float]
    best_sharpe: float | None
    mean_sharpe: float | None
    std_sharpe: float | None

    def summary(self) -> str:
        if not self.sharpes:
            return f"{self.group}: {self.n_trials} trials (no Sharpes recorded)"
        return (f"{self.group}: {self.n_trials} trials | best Sharpe "
                f"{self.best_sharpe:.2f} | mean {self.mean_sharpe:.2f} | "
                f"std {self.std_sharpe:.2f} ({len(self.sharpes)} with Sharpe)")


def group_stats(storage: Storage, group: str) -> GroupStats:
    """Trial count (all) + Sharpe distribution (recorded subset) for a selection
    group. The count drives n_trials; the dispersion drives E[max Sharpe]."""
    sharpes: list[float] = []
    n = 0
    for row in storage.list_experiments(limit=1_000_000):
        if _experiment_group(row) != group:
            continue
        n += 1
        try:
            s = json.loads(row.metrics_json or "{}").get("sharpe")
        except (TypeError, ValueError):
            s = None
        if s is not None:
            sharpes.append(float(s))
    return GroupStats(
        group=group, n_trials=n, sharpes=sharpes,
        best_sharpe=max(sharpes) if sharpes else None,
        mean_sharpe=statistics.fmean(sharpes) if sharpes else None,
        std_sharpe=statistics.stdev(sharpes) if len(sharpes) >= 2 else None,
    )


def all_groups(storage: Storage) -> list[str]:
    seen: set[str] = set()
    for row in storage.list_experiments(limit=1_000_000):
        g = _experiment_group(row)
        if g:
            seen.add(g)
    return sorted(seen)


def strategy_group(strategy: str, path: Path | None = None) -> str | None:
    """Which selection group a strategy's trials belong to (first match)."""
    _groups, trials = load_trial_manifest(path)
    for t in trials:
        if t.strategy == strategy:
            return t.group
    return None
