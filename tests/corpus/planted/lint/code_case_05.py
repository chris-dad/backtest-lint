"""Corpus case 05. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    win = 50
    mean_ = df["close"].rolling(win).mean()
    std_ = df["close"].rolling(win).std()
    z = (df["close"] - mean_) / std_
    df["position"] = (z < -2.0).astype(int)
    df["pnl"] = df["position"] * df["open"].pct_change()
    return df
