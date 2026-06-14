"""Trading 212 DEMO setup wizard / pre-flight (operator mission, Phase 6).

A beginner-friendly check that an operator's environment is correctly configured
to run the supervised paper period against the Trading 212 DEMO account. It
verifies the env flags, that keys are present (WITHOUT ever printing them), that
the demo endpoints are reachable, and restates the structural guarantees that
live trading and CFDs cannot be reached from here.

Pure and injectable: the connectivity probe takes an optional pre-built client so
tests can run it fully offline. Secrets are never included in any output — every
detail string is scrubbed of the configured key/secret before it is returned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SetupCheck:
    name: str
    ok: bool
    detail: str                  # NEVER contains secrets (scrubbed)
    severity: str = "required"   # required | optional | info


@dataclass
class SetupCheckResult:
    checks: list[SetupCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks if c.severity == "required")

    def as_dict(self) -> dict:
        return {"ok": self.ok, "live_eligible": False,
                "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail,
                            "severity": c.severity} for c in self.checks]}


def _scrub(text: str, secrets: list[str]) -> str:
    """Defensive: remove any configured secret value from a detail string."""
    out = text or ""
    for s in secrets:
        if s:
            out = out.replace(s, "***")
    return out


def run_setup_check(settings, *, env_path: Path | None = None, client=None,
                    connect: bool = True) -> SetupCheckResult:
    """Evaluate the Trading 212 DEMO setup. Never prints or returns secrets.

    `client` may be injected (tests / reuse); otherwise a DEMO client is built
    only when `connect` is true and keys are present. The live endpoint is never
    constructed here under any configuration."""
    secrets = [settings.trading212_api_key, settings.trading212_api_secret]
    checks: list[SetupCheck] = []

    env_path = env_path or (Path(settings.runtime_dir).parent / ".env")
    checks.append(SetupCheck(
        ".env file present", env_path.exists(),
        "found" if env_path.exists() else "missing — copy .env.example to .env and fill demo keys"))

    checks.append(SetupCheck(
        "TRADING212_ENABLED=true", bool(settings.trading212_enabled),
        "enabled" if settings.trading212_enabled else "set TRADING212_ENABLED=true"))

    is_demo = settings.trading212_mode == "demo"
    checks.append(SetupCheck(
        "TRADING212_MODE=demo", is_demo,
        "demo" if is_demo else f"mode is '{settings.trading212_mode}' — must be 'demo'"))

    checks.append(SetupCheck(
        "TRADING212_ALLOW_DEMO_ORDERS", bool(settings.trading212_allow_demo_orders),
        ("enabled — demo_execute can submit DEMO orders"
         if settings.trading212_allow_demo_orders
         else "disabled — shadow / demo_preview work; demo_execute is blocked until this is true"),
        severity="optional"))

    # This flag is intentionally NEVER consulted by the executor; we still assert
    # it is false so the operator never believes a single env var could enable live.
    checks.append(SetupCheck(
        "TRADING212_ALLOW_LIVE_ORDERS is false", not settings.trading212_allow_live_orders,
        "false — and never consulted; live is hard-blocked regardless"))

    checks.append(SetupCheck(
        "API key present (value hidden)", bool(settings.trading212_api_key),
        "configured" if settings.trading212_api_key else "not set — paste your DEMO API key"))
    checks.append(SetupCheck(
        "API secret present (value hidden)", bool(settings.trading212_api_secret),
        "configured" if settings.trading212_api_secret else "not set — paste your DEMO API secret"))

    have_keys = bool(settings.trading212_api_key and settings.trading212_api_secret)

    # --- connectivity probe (DEMO only) ---
    probe = connect and settings.trading212_enabled and is_demo and have_keys
    if probe:
        if client is None:
            try:
                from app.brokers.trading212.client import Trading212Client
                client = Trading212Client(
                    api_key=settings.trading212_api_key,
                    api_secret=settings.trading212_api_secret,
                    mode="demo", enabled=True, allow_live=False,
                    account_type=settings.trading212_account_type)
            except Exception as exc:  # noqa: BLE001 - report, never raise
                client = None
                checks.append(SetupCheck("DEMO client", False,
                                         _scrub(str(exc), secrets)))
        if client is not None:
            endpoints = [
                ("account endpoint (/equity/account/info)", "get_account"),
                ("cash endpoint (/equity/account/cash)", "get_cash"),
                ("positions endpoint (/equity/portfolio)", "get_positions"),
                ("instruments endpoint (/equity/metadata/instruments)", "get_instruments"),
            ]
            for label, method in endpoints:
                try:
                    fn = getattr(client, method)
                    fn(None) if method == "get_instruments" else fn()
                    checks.append(SetupCheck(label, True, "reachable"))
                except Exception as exc:  # noqa: BLE001
                    checks.append(SetupCheck(label, False, _scrub(str(exc), secrets)))
    else:
        reason = ("keys / TRADING212_ENABLED / demo mode not all set"
                  if not have_keys or not settings.trading212_enabled or not is_demo
                  else "connectivity probe skipped (--no-connect)")
        for label in ("account endpoint", "cash endpoint", "positions endpoint",
                      "instruments endpoint"):
            checks.append(SetupCheck(label, False, f"not probed: {reason}", severity="optional"))

    # --- order permission (structural; no order is placed here) ---
    order_perm = settings.trading212_enabled and is_demo and settings.trading212_allow_demo_orders \
        and have_keys
    checks.append(SetupCheck(
        "demo order permission available", bool(order_perm),
        ("yes — demo_execute may submit (still requires --confirm-demo + the full gate)"
         if order_perm else "no — enable TRADING212_ALLOW_DEMO_ORDERS to allow demo_execute"),
        severity="optional"))

    # --- structural guarantees (always true) ---
    checks.append(SetupCheck(
        "no CFD endpoint used", True,
        "the official Public API is Invest/ISA equities only; CFDs are unsupported"))
    checks.append(SetupCheck(
        "no live endpoint used", True,
        "the client is hard-coded to mode='demo', allow_live=False — the live base URL is unreachable"))

    return SetupCheckResult(checks=checks)
