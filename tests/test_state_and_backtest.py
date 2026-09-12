import json

from bot.backtest import run_backtest
from bot.state import (
    DEFAULT_STATE, load_state, save_state, update_peak_equity,
)


# --- state ---------------------------------------------------------------

def test_load_state_missing_file_returns_defaults(tmp_path):
    state = load_state(tmp_path / "nope.json")
    assert state == DEFAULT_STATE


def test_load_state_corrupt_file_returns_defaults(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not valid json")
    assert load_state(path)["peak_equity"] == 0.0


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    state = load_state(path)
    update_peak_equity(state, 1234.5)
    save_state(state, path)

    reloaded = load_state(path)
    assert reloaded["peak_equity"] == 1234.5
    assert reloaded["last_run"] is not None


def test_peak_equity_only_ratchets_up(tmp_path):
    state = dict(DEFAULT_STATE)
    assert update_peak_equity(state, 100.0) == 100.0
    assert update_peak_equity(state, 50.0) == 100.0
    assert update_peak_equity(state, 150.0) == 150.0


def test_save_state_leaves_no_temp_file(tmp_path):
    path = tmp_path / "state.json"
    save_state(dict(DEFAULT_STATE), path)
    assert path.exists()
    assert not (tmp_path / "state.json.tmp").exists()


# --- backtest ------------------------------------------------------------

def test_backtest_flat_market_makes_no_trades():
    result = run_backtest([100.0] * 300)
    assert result.trades == 0
    assert result.return_pct == 0.0


def test_backtest_insufficient_data_is_safe():
    result = run_backtest([100.0, 101.0])
    assert result.trades == 0
    assert result.bars == 2


def test_backtest_uptrend_is_profitable():
    closes = [100 * (1.01 ** i) for i in range(300)]
    result = run_backtest(closes, rsi_overbought=200, fee_pct=0.0)
    assert result.trades > 0
    assert result.return_pct > 0


def test_backtest_reports_win_rate():
    closes = [100 * (1.01 ** i) for i in range(300)]
    result = run_backtest(closes, rsi_overbought=200, fee_pct=0.0)
    assert 0 <= result.win_rate <= 100
    assert "Backtest" in result.summary()


def test_backtest_fees_reduce_return():
    closes = [100 * (1.01 ** i) for i in range(300)]
    free = run_backtest(closes, rsi_overbought=200, fee_pct=0.0)
    costly = run_backtest(closes, rsi_overbought=200, fee_pct=0.01)
    assert costly.return_pct < free.return_pct
