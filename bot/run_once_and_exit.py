from alpaca_client import get_client
from strategy import get_signal
from risk import can_open_position
from logger import log_trade, log_equity

SYMBOL = "BTCUSD"
QTY = 0.0001  # small crypto size

def run_bot_once():
    api = get_client()

    try:
        # Crypto returns bars 24/7 — this will ALWAYS have data
        bars = api.get_bars(SYMBOL, "1Hour", limit=50)
    except Exception as e:
        with open("trading-bot-log.txt", "a") as f:
            f.write(f"Error fetching bars: {e}\n")
        return

    if not bars:
        with open("trading-bot-log.txt", "a") as f:
            f.write("No bars returned from Alpaca.\n")
        return

    signal = get_signal(bars)

    try:
        if signal == "buy":
            if can_open_position(api):
                order = api.submit_order(
                    symbol=SYMBOL,
                    qty=QTY,
                    side="buy",
                    type="market",
                    time_in_force="gtc"
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
                        time_in_force="gtc"
                    )
                    log_trade("sell", SYMBOL, p.qty, order.id)

        log_equity(api)

    except Exception as e:
        with open("trading-bot-log.txt", "a") as f:
            f.write(f"Error submitting order or logging equity: {e}\n")

if __name__ == "__main__":
    run_bot_once()
