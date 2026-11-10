"""Corpus case 09. Quant strategy sample.
Required columns: open, high, low, close.
"""
import numpy as np
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["mid_avg"] = df["close"].rolling(11, center=True).apply(
        lambda x: np.mean(x), raw=True
    )
    df["signal"] = (df["close"] < df["mid_avg"]).astype(int)
    df["position"] = df["signal"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change()
    df["pnl"] = df["position"] * df["ret"]
    return df
