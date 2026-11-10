"""Corpus case 08. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def smooth(series: pd.Series, **roll_kwargs) -> pd.Series:
    return series.rolling(**roll_kwargs).mean()


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["smoothed"] = smooth(df["close"], window=20, center=True)
    df["signal"] = (df["close"] > df["smoothed"]).astype(int)
    df["position"] = df["signal"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change()
    df["pnl"] = df["position"] * df["ret"]
    return df
