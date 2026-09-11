from alpaca_client import get_client
from strategy import get_signal
from risk import can_open_position
from logger import log_trade, log_equity

SYMBOL = "AAPL"
QTY = 1

def run_bot_once():
    api = get_client()

    bars = api.get_bars(SYMBOL, "1Min", limit=50)
    signal = get_signal(bars)

    if signal == "buy":
        if can_open_position(api):
            order = api.submit_order(
                symbol=SYMBOL,
                qty=QTY,
                side="buy",
                type="market",
                time_in_force="day"
            )
            log_trade("buy", SYMBOL, QTY, order.id)

    elif signal == "sell":
        positions = api.list_positions()
        for p in positions:
            if p.symbol == SYMBOL:
                order = api.submit_order(
                    symbol=SYMBOL,
                    qty=p.qty,
                    side="sell",
                    type="market",
                    time_in_force="day"
                )
                log_trade("sell", SYMBOL, p.qty, order.id)

    log_equity(api)

if __name__ == "__main__":
    run_bot_once()
