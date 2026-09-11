def get_signal(bars):
    if len(bars) < 20:
        return None

    closes = [b.c for b in bars]
    avg20 = sum(closes[-20:]) / 20
    last = closes[-1]

    if last > avg20:
        return "buy"
    if last < avg20:
        return "sell"

    return None
