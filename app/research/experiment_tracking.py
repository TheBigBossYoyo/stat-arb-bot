"""Experiment tracking: every research run becomes a durable, countable record.

Two problems this solves (audit W-02, W-15):

* REPRODUCIBILITY — a result that cannot be traced to code + config + data is
  folklore. Each run records the git commit (and whether the tree was dirty),
  a canonical-JSON config snapshot with its hash, and a fingerprint of the
  exact bars it read (per-symbol span + row counts), so silent data
  restatement is detectable.
* TRIAL COUNTING — multiple-testing corrections (deflated Sharpe, FDR) need
  the number of configurations that were ever evaluated to answer the same
  question. Researchers forget sweeps; the tracker does not. Every run joins
  a `family` (strategy + universe + interval by default) and the family's
  trial count and Sharpe distribution feed `app/research/deflated_sharpe.py`.

Usage (the CLI entry points call this automatically):

    tracker = ExperimentTracker(storage)
    rec = tracker.record(kind="basket", strategy="xsec_momentum",
                         universe="us_stocks_50", interval="1d",
                         config=params, metrics=result.metrics,
                         prices=prices, seed=7, notes="...")
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.logging import get_logger
from app.core.types import utc_now
from app.data.storage import Storage

log = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def git_state(cwd: Path | None = None) -> tuple[str, bool]:
    """(commit hash, dirty?). ("", False) when git is unavailable."""
    root = cwd or _PROJECT_ROOT
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
            text=True, timeout=10, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True,
            text=True, timeout=10, check=True,
        ).stdout.strip()
        return commit, bool(status)
    except (OSError, subprocess.SubprocessError):
        return "", False


def config_hash(config: dict) -> str:
    """Stable short hash of a canonical-JSON config snapshot."""
    canonical = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def data_fingerprint_from_prices(prices) -> tuple[str, datetime | None, datetime | None]:
    """Fingerprint of an in-memory PriceMatrix: per-symbol span, row count and
    first/last closes. Cheap, and any provider restatement that touches the
    window changes it."""
    parts = []
    close = prices.close
    for symbol in close.columns:
        col = close[symbol].dropna()
        if col.empty:
            parts.append(f"{symbol}:empty")
            continue
        parts.append(
            f"{symbol}:{col.index[0]}:{col.index[-1]}:{len(col)}"
            f":{col.iloc[0]:.6g}:{col.iloc[-1]:.6g}"
        )
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]
    idx = prices.index
    start = idx[0].to_pydatetime() if len(idx) else None
    end = idx[-1].to_pydatetime() if len(idx) else None
    return digest, start, end


@dataclass
class ExperimentRecord:
    experiment_id: str
    family: str
    git_commit: str
    git_dirty: bool
    config_hash: str
    data_fingerprint: str
    trial_number: int          # this run's position within its family (1-based)


class ExperimentTracker:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    @staticmethod
    def make_family(strategy: str, universe: str, interval: str) -> str:
        return f"{strategy}|{universe}|{interval}"

    def record(
        self,
        *,
        kind: str,
        strategy: str,
        universe: str = "",
        interval: str = "",
        config: dict | None = None,
        metrics: dict | None = None,
        prices=None,
        seed: int | None = None,
        sample: str = "in_sample",
        family: str | None = None,
        notes: str = "",
    ) -> ExperimentRecord:
        cfg = config or {}
        commit, dirty = git_state()
        cfg_hash = config_hash(cfg)
        if prices is not None:
            fingerprint, data_start, data_end = data_fingerprint_from_prices(prices)
        else:
            fingerprint, data_start, data_end = "", None, None
        fam = family or self.make_family(strategy, universe, interval)
        experiment_id = (
            f"EXP-{utc_now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        )
        self.storage.record_experiment(
            experiment_id=experiment_id,
            created_at=utc_now().replace(tzinfo=None),
            kind=kind,
            strategy=strategy,
            universe=universe,
            interval=interval,
            family=fam,
            git_commit=commit,
            git_dirty=dirty,
            config_json=cfg,
            config_hash=cfg_hash,
            data_fingerprint=fingerprint,
            data_start=data_start,
            data_end=data_end,
            seed=seed,
            sample=sample,
            metrics_json=metrics or {},
            notes=notes,
        )
        trial_number = self.storage.count_experiment_trials(fam)
        if dirty:
            log.warning(
                "experiment %s recorded against a DIRTY working tree — commit "
                "before runs you intend to cite", experiment_id,
            )
        log.info("experiment %s recorded (family=%s, trial #%d)",
                 experiment_id, fam, trial_number)
        return ExperimentRecord(
            experiment_id=experiment_id, family=fam, git_commit=commit,
            git_dirty=dirty, config_hash=cfg_hash, data_fingerprint=fingerprint,
            trial_number=trial_number,
        )
