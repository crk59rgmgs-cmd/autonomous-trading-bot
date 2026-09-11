def can_open_position(api, max_exposure_pct=0.5):
    account = api.get_account()
    equity = float(account.equity)

    positions = api.list_positions()
    total_value = sum(float(p.market_value) for p in positions)

    return (total_value / equity) < max_exposure_pct
