"""Corpus case 07. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["trend"] = df["close"].rolling(21, center=True).mean()
    df["signal"] = (df["close"] > df["trend"]).astype(int)
    df["position"] = df["signal"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change()
    df["pnl"] = df["position"] * df["ret"]
    return df
