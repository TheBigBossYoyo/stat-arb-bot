"""Tests for the Trading 212 DEMO setup check (operator mission, Phase 6).

The critical property: secrets are NEVER included in any output, even when an
endpoint error message contains them."""

from __future__ import annotations

from types import SimpleNamespace

from app.brokers.trading212.setup_check import run_setup_check

API_KEY = "SECRETKEY123ABC"
API_SECRET = "SECRETSECRET456XYZ"


def _settings(tmp_path, **over):
    base = dict(trading212_api_key=API_KEY, trading212_api_secret=API_SECRET,
                trading212_enabled=True, trading212_mode="demo",
                trading212_account_type="invest", trading212_allow_demo_orders=True,
                trading212_allow_live_orders=False, runtime_dir=tmp_path)
    base.update(over)
    return SimpleNamespace(**base)


class _OkClient:
    def get_account(self):
        return {"cash": 1.0}

    def get_cash(self):
        return 1.0

    def get_positions(self):
        return []

    def get_instruments(self, symbols=None):
        return []


class _LeakyClient:
    """Every call raises with the secret embedded — to test scrubbing."""

    def get_account(self):
        raise RuntimeError(f"401 unauthorized key={API_KEY}")

    def get_cash(self):
        raise RuntimeError(f"403 secret={API_SECRET}")

    def get_positions(self):
        raise RuntimeError(f"boom {API_KEY}")

    def get_instruments(self, symbols=None):
        raise RuntimeError(f"boom {API_SECRET}")


def test_never_prints_secrets_even_on_errors(tmp_path):
    env = tmp_path / ".env"
    env.write_text("x", encoding="utf-8")
    result = run_setup_check(_settings(tmp_path), env_path=env, client=_LeakyClient(), connect=True)
    blob = "\n".join(f"{c.name} {c.detail}" for c in result.checks)
    assert API_KEY not in blob
    assert API_SECRET not in blob
    # the literal key value is never echoed even on the "present" checks
    key_check = next(c for c in result.checks if c.name.startswith("API key"))
    assert key_check.ok is True and API_KEY not in key_check.detail


def test_required_checks_pass_with_good_setup(tmp_path):
    env = tmp_path / ".env"
    env.write_text("x", encoding="utf-8")
    result = run_setup_check(_settings(tmp_path), env_path=env, client=_OkClient(), connect=True)
    assert result.ok is True
    assert result.as_dict()["live_eligible"] is False
    names = {c.name: c for c in result.checks}
    assert names["account endpoint (/equity/account/info)"].ok is True
    assert names["no live endpoint used"].ok is True


def test_missing_env_and_disabled_fails_required(tmp_path):
    result = run_setup_check(_settings(tmp_path, trading212_enabled=False,
                                       trading212_api_key="", trading212_api_secret=""),
                             env_path=tmp_path / "absent.env", connect=True)
    assert result.ok is False
    names = {c.name: c for c in result.checks}
    assert names[".env file present"].ok is False
    assert names["TRADING212_ENABLED=true"].ok is False
