"""Corpus case 12. Quant strategy sample.
Required columns: open, high, low, close.
"""
import numpy as np
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    end_anchor = df["close"].values[-1]
    tail_vol = df["close"].pct_change().iloc[-250:].std()
    df["scaled_signal"] = (df["close"] / end_anchor) / tail_vol
    df["position"] = (df["scaled_signal"] > 1.0).astype(int)
    df["position"] = df["position"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change()
    df["pnl"] = df["position"] * df["ret"]
    return df
