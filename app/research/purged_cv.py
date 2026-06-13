"""Purged k-fold cross-validation with an embargo (audit W-08).

The ML alpha sleeve uses overlapping forward-return labels: a label at date t
spans [t, t+horizon]. Naive k-fold CV then leaks — a training row whose label
window overlaps a test row's label window shares information, so the test fold
is not truly out of sample, and CV scores are optimistic. Lopez de Prado's fix
(Advances in Financial Machine Learning, ch. 7):

* PURGE training observations whose label window overlaps the test fold;
* EMBARGO a further band of training observations immediately after the test
  fold, because serial correlation leaks forward even without label overlap.

This module provides the index splitter and a small helper that scores a model
with purged CV and reports the naive-CV-minus-purged gap — the gap is the
leakage the audit asked us to surface.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np


@dataclass
class PurgedSplit:
    train_idx: np.ndarray
    test_idx: np.ndarray


def purged_kfold_indices(
    n: int,
    *,
    n_splits: int = 5,
    label_span: int = 1,
    embargo: int = 0,
) -> Iterator[PurgedSplit]:
    """Yield (train, test) index arrays for `n` time-ordered observations.

    `label_span`: how many observations forward each label depends on (the ML
        sleeve's `forward_bars`). Training rows within `label_span` of the test
        block on either side are purged.
    `embargo`: extra rows after the test block to drop from training.
    """
    if n_splits < 2 or n < n_splits:
        raise ValueError("need n_splits >= 2 and n >= n_splits")
    indices = np.arange(n)
    fold_bounds = np.array_split(indices, n_splits)
    for test_block in fold_bounds:
        if len(test_block) == 0:
            continue
        t0, t1 = test_block[0], test_block[-1]
        # purge: drop training rows whose label window [i, i+label_span] could
        # overlap the test block, and rows the test labels reach back into
        lo = t0 - label_span
        hi = t1 + label_span + embargo
        train_mask = (indices < lo) | (indices > hi)
        train_idx = indices[train_mask]
        if len(train_idx) == 0:
            continue
        yield PurgedSplit(train_idx=train_idx, test_idx=test_block)


@dataclass
class PurgedCVResult:
    purged_score: float
    naive_score: float
    leakage_gap: float            # naive - purged (optimism removed by purging)
    n_splits: int
    per_fold_purged: list[float]

    def summary(self) -> str:
        return (
            f"purged CV score {self.purged_score:.4f} vs naive {self.naive_score:.4f} "
            f"(leakage gap {self.leakage_gap:+.4f} over {self.n_splits} folds)"
        )


def cross_val_score_purged(
    fit_predict_score,
    n: int,
    *,
    n_splits: int = 5,
    label_span: int = 1,
    embargo: int = 0,
) -> PurgedCVResult:
    """Run both purged and naive k-fold and report the gap.

    `fit_predict_score(train_idx, test_idx) -> float` trains on train_idx and
    returns a score (e.g. rank-IC, R^2, hit rate) on test_idx. It is called
    once per fold for each scheme.
    """
    purged = [
        fit_predict_score(s.train_idx, s.test_idx)
        for s in purged_kfold_indices(n, n_splits=n_splits,
                                      label_span=label_span, embargo=embargo)
    ]
    # naive: same test blocks, but train = everything else (no purge/embargo)
    naive = []
    indices = np.arange(n)
    for test_block in np.array_split(indices, n_splits):
        if len(test_block) == 0:
            continue
        train_idx = np.setdiff1d(indices, test_block, assume_unique=True)
        naive.append(fit_predict_score(train_idx, test_block))
    purged_mean = float(np.mean(purged)) if purged else float("nan")
    naive_mean = float(np.mean(naive)) if naive else float("nan")
    return PurgedCVResult(
        purged_score=purged_mean,
        naive_score=naive_mean,
        leakage_gap=naive_mean - purged_mean,
        n_splits=n_splits,
        per_fold_purged=purged,
    )
