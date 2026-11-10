"""Corpus case 11. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["fwd_close"] = df["close"].shift(-5)
    df["label"] = (df["fwd_close"] > df["close"]).astype(int)
    df["position"] = df["label"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change()
    df["pnl"] = df["position"] * df["ret"]
    return df
