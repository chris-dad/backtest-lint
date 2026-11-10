"""Corpus case 02. Quant strategy sample.
Required columns: open, high, low, close.
"""
import numpy as np
import pandas as pd


def _compute_entry(px, ref):
    return np.where(px > ref, 1, 0)


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ref"] = out["close"].rolling(10).mean()
    out["pos"] = _compute_entry(out["close"], out["ref"])
    out["bar_ret"] = out["close"].pct_change()
    out["strat_ret"] = out["pos"] * out["bar_ret"]
    return out
