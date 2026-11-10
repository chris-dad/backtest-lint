"""Corpus case 03. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    positions = []
    for i in range(1, len(df)):
        if df["close"].iloc[i] > df["high"].iloc[i - 1]:
            pos = 1
        else:
            pos = 0
        positions.append(pos)
    df = df.copy()
    df["position"] = [0] + positions
    df["pnl"] = df["position"] * df["close"].pct_change()
    return df
