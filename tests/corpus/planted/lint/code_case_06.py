"""Corpus case 06. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def momentum_position(close: pd.Series, lookback: int) -> pd.Series:
    roc = close / close.shift(lookback) - 1
    return (roc > 0).astype(int)


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["pos"] = momentum_position(df["close"], 20)
    df["ret_open"] = df["open"].pct_change()
    df["pnl"] = df["pos"] * df["ret_open"]
    return df
