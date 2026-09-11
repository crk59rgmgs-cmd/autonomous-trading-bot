import csv
from datetime import datetime

def log_trade(side, symbol, qty, order_id):
    with open("trade_log.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.utcnow().isoformat(), side, symbol, qty, order_id])

def log_equity(api):
    account = api.get_account()
    equity = float(account.equity)
    last_equity = float(account.last_equity)
    pnl = equity - last_equity

    with open("equity_log.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.utcnow().isoformat(), equity, last_equity, pnl])
