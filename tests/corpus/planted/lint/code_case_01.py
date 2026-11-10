"""Corpus case 01. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma"] = df["close"].rolling(20).mean()
    df["signal"] = (df["close"] > df["ma"]).astype(int)
    df["position"] = df["signal"]
    df["ret"] = df["close"].pct_change()
    df["pnl"] = df["position"] * df["ret"]
    return df
