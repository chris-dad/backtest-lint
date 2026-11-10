"""Corpus case A. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma_fast"] = df["close"].rolling(20).mean()
    df["ma_slow"] = df["close"].rolling(60).mean()
    df["signal"] = (df["ma_fast"] > df["ma_slow"]).astype(int)
    df["position"] = df["signal"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change().fillna(0)
    df["pnl"] = df["position"] * df["ret"]
    # Gates.
    assert df["pnl"].notna().all(), "NaN in pnl stream"
    assert df["position"].isin([0, 1]).all(), "position must be long/flat"
    # No signal can exist before the slow MA window completes.
    assert df["position"].iloc[:60].sum() == 0, "position during warmup"
    return df
