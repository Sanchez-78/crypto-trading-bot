from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_dashboard_pnl_formatter_keeps_loss_sign():
    source = (REPO / "src/services/dashboard_web.py").read_text(encoding="utf-8")
    assert "value > 0 ? '+' : value < 0 ? '-' : ''" in source
    assert "value >= 0 ? '+' : ''" not in source


def test_real_trading_config_uses_valid_mode_but_remains_unconfirmed():
    source = (REPO / "config_real_trading.env").read_text(encoding="utf-8")
    assert "TRADING_MODE=live_real" in source
    assert "TRADING_MODE=real_live" not in source
    assert "ENABLE_REAL_ORDERS=false" in source
    assert "LIVE_TRADING_CONFIRMED=false" in source


def test_timeout_fallback_never_uses_symbol_as_position_id():
    source = (REPO / "bot2/main.py").read_text(encoding="utf-8")
    assert 'pos.get("trade_id") or pos.get("position_id")' in source
    assert 'pos.get("position_id", sym)' not in source


def test_deployment_verifier_requires_training_mode():
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    verifier = (REPO / "scripts/verify_p0_3_deployment.sh").read_text(
        encoding="utf-8"
    )
    assert "TRADING_MODE=paper_train" in example
    assert "PAPER_DATA_COLLECTION_ONLY=0" in example
    assert 'grep -q "TRADING_MODE=paper_train" .env.example' in verifier
    assert 'grep -q "PAPER_DATA_COLLECTION_ONLY=0" .env.example' in verifier
