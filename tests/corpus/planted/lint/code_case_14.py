"""Corpus case 14. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma"] = df["close"].rolling(20).mean()
    df["signal"] = (df["close"] > df["ma"]).astype(int)
    df["position"] = df["signal"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change()
    df["pnl"] = df["position"] * df["ret"]
    # assert df["pnl"].notna().all(), "NaN in pnl"
    # assert df["position"].isin([0, 1]).all(), "position domain"
    print("pnl total:", df["pnl"].sum())
    return df
