"""Corpus case 04. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def compute_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).rolling(period).mean()
    dn = (-delta.clip(upper=0)).rolling(period).mean()
    rs = up / dn
    return 100 - 100 / (1 + rs)


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rsi"] = compute_rsi(df["close"], 14)
    df["position"] = (df["rsi"] < 30).astype(int)
    df["oo_ret"] = df["open"].pct_change()
    df["pnl"] = df["position"] * df["oo_ret"]
    return df
