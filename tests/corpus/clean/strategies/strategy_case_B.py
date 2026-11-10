"""Corpus case B. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    lookback = 20
    roc = df["close"] / df["close"].shift(lookback) - 1
    df["signal"] = (roc > 0).astype(int)
    df["position"] = df["signal"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change().fillna(0)
    df["pnl"] = df["position"] * df["ret"]
    # Gates.
    assert df["pnl"].notna().all(), "NaN in pnl stream"
    assert df["position"].isin([0, 1]).all(), "position must be long/flat"
    assert df["position"].iloc[0] == 0, "first bar must be flat"
    return df
