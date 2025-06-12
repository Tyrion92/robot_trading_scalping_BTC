import datetime
import sys

sys.path.append("./robot_trading_scalping_BTC-main")
import asyncio
from utilities.bitget_perp import PerpBitget
from secret import ACCOUNTS
import ta

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def main():
    # === Configuration ===
    account = ACCOUNTS["bitget1"]
    pair = "BTC/USDT"
    tf = "5m"
    risk_pct = 0.05  # 5% of capital at risk per trade
    margin_mode = "isolated"  # futures margin mode
    leverage = 1  # no leverage

    # Initialize exchange client
    exchange = PerpBitget(
        public_api=account["public_api"],
        secret_api=account["secret_api"],
        password=account["password"],
    )

    print(f"--- Execution started at {datetime.datetime.now()} ---")
    try:
        # Load markets and set margin/leverage
        await exchange.load_markets()
        await exchange.set_margin_mode_and_leverage(pair, margin_mode, leverage)

        # Fetch OHLCV data
        df = await exchange.get_last_ohlcv(pair, tf, limit=50)

        # Calculate indicators
        df["ema8"] = ta.trend.ema_indicator(close=df["close"], window=8)
        df["ema21"] = ta.trend.ema_indicator(close=df["close"], window=21)
        df["rsi"] = ta.momentum.rsi(close=df["close"], window=14)
        df["atr"] = ta.volatility.average_true_range(
            high=df["high"], low=df["low"], close=df["close"], window=14
        )

        # Use the last closed candle for signal
        prev = df.iloc[-2]
        curr = df.iloc[-1]

        # Check for bullish EMA crossover + RSI in [50,70]
        ema_cross = prev["ema8"] < prev["ema21"] and curr["ema8"] > curr["ema21"]
        rsi_ok = 50 < curr["rsi"] < 70

        # Cancel any existing orders
        await exchange.cancel_trigger_orders(pair)
        await exchange.cancel_orders(pair)

        # Check existing positions
        positions = await exchange.get_open_positions([pair])

        # If no position and entry signal
        if ema_cross and rsi_ok and not positions:
            entry_price = curr["close"]
            atr = curr["atr"]
            stop_price = entry_price - 0.4 * atr
            tp_price = entry_price + 1.1 * atr

            # Calculate position size based on risk
            balance = await exchange.get_balance()
            capital = balance.total
            size = (capital * risk_pct) / (entry_price - stop_price)
            size = exchange.amount_to_precision(pair, size)

            print(f"Placing market BUY: size={size}, price={entry_price}")
            # Entry market order
            await exchange.place_order(
                pair=pair,
                side="buy",
                price=None,
                size=size,
                type="market",
                reduce=False,
                margin_mode=margin_mode,
            )

            # Stop-loss trigger order (market)
            sl_price = exchange.price_to_precision(pair, stop_price)
            print(f"Setting Stop Loss at {sl_price}")
            await exchange.place_trigger_order(
                pair=pair,
                side="sell",
                price=None,
                trigger_price=sl_price,
                size=size,
                type="market",
                reduce=True,
                margin_mode=margin_mode,
            )

            # Take-profit trigger order (limit)
            tp_prec = exchange.price_to_precision(pair, tp_price)
            print(f"Setting Take Profit at {tp_prec}")
            await exchange.place_trigger_order(
                pair=pair,
                side="sell",
                price=tp_prec,
                trigger_price=tp_prec,
                size=size,
                type="limit",
                reduce=True,
                margin_mode=margin_mode,
            )
        else:
            print("No entry signal or position already open.")

        await exchange.close()
        print(f"--- Execution finished at {datetime.datetime.now()} ---")
    except Exception as e:
        await exchange.close()
        print("Error during execution:", e)
        raise


if __name__ == "__main__":
    asyncio.run(main())
