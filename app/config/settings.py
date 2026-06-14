"""Application settings.

All runtime configuration comes from environment variables / a local `.env`
file (never committed). Defaults are chosen so that, with no configuration at
all, the system runs offline in paper mode and cannot place real orders.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONFIG_DIR.parent.parent


class Settings(BaseSettings):
    # env_file and the sqlite default are anchored to the PROJECT ROOT, not
    # the current working directory: `statarb` run from anywhere must find
    # the same .env and the same database (a CWD-relative sqlite path once
    # silently created a fresh empty DB inside .venv/Scripts).
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"

    # --- live trading gate ---------------------------------------------------
    live_trading: bool = False
    confirm_live_trading: bool = False

    # --- storage --------------------------------------------------------------
    database_url: str = "sqlite:///stat_arb.db"
    data_dir: Path = PROJECT_ROOT / "data_store"
    reports_dir: Path = PROJECT_ROOT / "reports"
    logs_dir: Path = PROJECT_ROOT / "logs"
    runtime_dir: Path = PROJECT_ROOT / "runtime"

    # --- Binance ---------------------------------------------------------------
    binance_enabled: bool = False
    binance_mode: Literal["testnet", "live"] = "testnet"
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_use_futures: bool = False
    binance_max_leverage: int = 1

    # --- Trading 212 -----------------------------------------------------------
    trading212_enabled: bool = False
    trading212_mode: Literal["demo", "live"] = "demo"
    trading212_api_key: str = ""
    trading212_api_secret: str = ""
    trading212_account_type: Literal["invest", "isa"] = "invest"
    # Demo order submission requires this explicit flag (Phase 5). Live order
    # submission is HARD-BLOCKED for this product: trading212_allow_live_orders
    # is never consulted by the demo executor — it exists only so an operator
    # cannot believe a single env var would enable live (it would not).
    trading212_allow_demo_orders: bool = False
    trading212_allow_live_orders: bool = False

    # --- research data provider -------------------------------------------------
    data_provider: str = "binance"
    data_provider_api_key: str = ""

    # --- dashboard ----------------------------------------------------------------
    # READ-ONLY by default: every control endpoint returns 403 unless enabled.
    dashboard_controls_enabled: bool = False
    # optional bearer token; empty = local-only unauthenticated (bind 127.0.0.1!)
    dashboard_token: str = ""

    # --- risk limit overrides (see config/risk_limits.yaml for the full set) -----
    # None = no override: config/risk_limits.yaml is the source of truth. Set an
    # env var only to deliberately tighten/loosen a limit for this deployment.
    max_daily_loss_pct: float | None = None
    max_total_drawdown_pct: float | None = None
    max_gross_exposure: float | None = None
    max_net_exposure: float | None = None
    max_notional_per_trade: float | None = None
    max_open_pairs: int | None = None
    max_trades_per_day: int | None = None

    @field_validator("database_url")
    @classmethod
    def _anchor_relative_sqlite(cls, value: str) -> str:
        """Resolve relative sqlite paths against the project root."""
        prefix = "sqlite:///"
        if value.startswith(prefix):
            raw = value[len(prefix):]
            if raw and not Path(raw).is_absolute():
                return f"{prefix}{(PROJECT_ROOT / raw).as_posix()}"
        return value

    @property
    def live_trading_allowed(self) -> bool:
        """Both env flags must be set; the CLI additionally requires --confirm-live."""
        return self.live_trading and self.confirm_live_trading

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.reports_dir, self.logs_dir, self.runtime_dir):
            Path(d).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
