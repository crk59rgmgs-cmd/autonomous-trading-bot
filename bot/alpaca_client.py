import os
import alpaca_trade_api as tradeapi

def get_client():
    return tradeapi.REST(
        os.getenv("ALPACA_API_KEY"),
        os.getenv("ALPACA_SECRET_KEY"),
        "https://paper-api.alpaca.markets"
    )
