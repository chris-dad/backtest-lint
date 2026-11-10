"""Corpus case C. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["upper"] = df["high"].rolling(20).max().shift(1)
    df["lower"] = df["low"].rolling(20).min().shift(1)
    df["signal"] = ((df["close"] > df["upper"]).astype(int)
                    - (df["close"] < df["lower"]).astype(int))
    df["position"] = df["signal"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change().fillna(0)
    df["pnl"] = df["position"] * df["ret"]
    # Gates.
    assert df["pnl"].notna().all(), "NaN in pnl stream"
    assert df["position"].isin([-1, 0, 1]).all(), "position must be -1/0/1"
    # T+1 invariant: today's position equals yesterday's signal.
    lag_ok = df["position"] == df["signal"].shift(1).fillna(0)
    assert lag_ok.all(), "position lag misaligned"
    return df
