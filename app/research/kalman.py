"""Online Kalman filter for a time-varying hedge ratio.

State:        theta_t = [beta_t, alpha_t]      (random walk)
Observation:  y_t = beta_t * x_t + alpha_t + eps,  eps ~ N(0, R)

`delta` controls how fast beta may drift (process noise); small delta =
sluggish but stable beta, large delta = responsive but noisy. The residual
e_t = y_t - (beta x_t + alpha) is the tradeable spread innovation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class KalmanResult:
    betas: np.ndarray
    alphas: np.ndarray
    residuals: np.ndarray        # one-step-ahead prediction errors
    residual_vars: np.ndarray    # innovation variances (for z-scoring)


class KalmanHedgeFilter:
    def __init__(self, delta: float = 1e-5, r: float = 1e-3, beta0: float = 1.0, alpha0: float = 0.0):
        self.q = delta / (1.0 - delta) * np.eye(2)   # process noise covariance
        self.r = r                                    # observation noise variance
        self.theta = np.array([beta0, alpha0], dtype=float)
        self.p = np.eye(2)                            # state covariance

    def update(self, y: float, x: float) -> tuple[float, float, float, float]:
        """One filter step. Returns (beta, alpha, residual, residual_var)."""
        # predict
        self.p = self.p + self.q
        h = np.array([x, 1.0])
        # innovation
        y_hat = float(h @ self.theta)
        residual = y - y_hat
        s = float(h @ self.p @ h) + self.r
        # update
        k = (self.p @ h) / s
        self.theta = self.theta + k * residual
        self.p = self.p - np.outer(k, h) @ self.p
        return float(self.theta[0]), float(self.theta[1]), residual, s

    def filter_series(self, y: np.ndarray, x: np.ndarray) -> KalmanResult:
        y = np.asarray(y, dtype=float)
        x = np.asarray(x, dtype=float)
        if y.shape != x.shape or y.ndim != 1:
            raise ValueError("y and x must be 1-D arrays of equal length")
        n = len(y)
        betas = np.empty(n)
        alphas = np.empty(n)
        residuals = np.empty(n)
        residual_vars = np.empty(n)
        for t in range(n):
            betas[t], alphas[t], residuals[t], residual_vars[t] = self.update(y[t], x[t])
        return KalmanResult(betas, alphas, residuals, residual_vars)
