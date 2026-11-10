#!/usr/bin/env python3
"""backtest-lint corpus builder (Phase 1).
Version: only CORPUS_VERSION below is authoritative - never restate it.

v1.2.0 changelog (post-audit, 2026-09-30, implements HY review):
  H1 ARCHITECTURE: observability is now a construction guarantee. Every
     planted sample is independently re-observed at build time by
     tools/reference_detectors.py (the disease must be measurable in the
     artifact, not merely intended); every clean sample must stay silent.
     Build fails otherwise. This subsumes and generalizes the v1.1.0
     point-fixes (F4's four mirror identities are now 38-sample coverage).
  H2 204 SIGNAL RE-DERIVED: the fingerprint of full-sample normalization
     is the SELF-REFERENTIAL MOMENT IDENTITY (output moments exactly
     (0,1), or exact [0,1] endpoints) - computing those constants requires
     the whole series including the future, so they are impossible under
     causal normalization. Affine shape itself is NOT a signal. Derivation
     lives in det_204's docstring and in the corpus README.
  H3 HONEST TIERS: expected_results entries carry expected.tier.
     verified (deterministic fact) / suspicious (strong fingerprint,
     intent not provable from data alone) / cannot_determine (no pure-data
     fingerprint exists - PRF-201-03/04; a pure-data detector must return
     cannot-determine, and claiming detection there would be fabrication).

v1.2.7 changelog (post-audit, 2026-10-01, closes Cursor round-8 note;
        round-8 verdict: PASS, 0 blockers, 1 note):
  N3 203-02 jump lock SHARPENED to a shape lock: the round-7 pair
     ('>= 1 backward jump' file-wide + value-dups == 30) still admitted
     the variant '30 adjacent copies + a later swap' (2 jumps, 30
     adjacent duplicate stamps, answer-key token still matched).
     verify() now pins the SHAPE exactly: exactly ONE backward jump
     located AT the append boundary (index 399 -> 400), ZERO adjacent
     duplicate stamps, 30 duplicate-by-value rows. Adjacent-copy /
     swap variants fail the build.

v1.2.6 changelog (post-audit, 2026-09-30, closes Cursor round-7 notes;
        round-7 verdict: PASS, 0 blockers, 1 fix + 2 notes):
  F1 PRF-203-02 facts LOCKED, duplicates counted BY VALUE: the 30 copied
     rows are appended at the END, so they are not ADJACENT to their
     originals - det_203 previously reported '0 duplicate stamps' while
     30 timestamps really were duplicated, and verify() never looked at
     profile_case_10 (a single swapped pair still built). det_203
     evidence now includes the value-based duplicate count; the answer
     key pins '<n> duplicate-by-value rows' (derived from the tail
     length); verify() asserts multiset duplicates == 30 AND a backward
     jump at the append boundary. Swapped-pair / no-append regressions
     fail the build.
  N1 202-03 continuation length LOCKED: verify() asserts exactly 30
     post-expiry rows with nonzero volume (202-01/02/04 lengths were
     pinned; 202-03 was not - one reanimated row satisfied the token).
  N2 README banner recall wording aligned with the scoring section:
     recall 100% = 28/28 (denominator = tier verified|suspicious only);
     28/30 is the catchable share of the planted set.

v1.2.5 changelog (post-audit, 2026-09-30, closes Cursor round-6 notes;
        round-6 verdict: PASS, 0 blockers 0 fixes, 2 notes):
  R1 202-02 freeze tokens pinned to DERIVED values (mark 3.0, iv 0.55):
     det_202 now reports 'iv frozen at <v>'; answer key requires both
     exact values; verify() asserts continuation mark AND iv are single
     nonzero values. A 0.0 regression in either fails the build.
  R2 docstring repaired: the v1.2.3/v1.2.4 changelog blocks had been
     written with literal backslash-n sequences glued onto the v1.2.2
     title (introduced by the round-4/5 patch scripts themselves).
v1.2.4 changelog (post-audit, 2026-09-30, closes Cursor round-5 notes;
        round-5 verdict: PASS, 0 blockers 0 fixes, 2 notes):
  R1 dead token revived: PRF-201-02 harness branch now asserts
     evidence_must_include (the down-cliff token was listed in the
     answer key but never read - Cursor probe proved stripping it
     still passed). A stripped down-cliff now fails the build.
  R2 README sample-table row for PRF-201-02 aligned with the derived
     answer-key wording (no more 'exact halving' overclaim).
v1.2.3 changelog (post-audit, 2026-09-30, closes Cursor round-4 notes):
  N1 futures freeze LOCKED: PRF-202-04 evidence token pins the exact
     derived settle (regression to 0.0 fails); verify() asserts the
     frozen settle is a single NONZERO value.
  N2 README single-source: title line no longer restates a version;
     historical F1 row carries a supersession note.
  N3 201-02 direction LOCKED: desc derived from construction (no
     stale '-log2 exact' claim); harness token 'down-cliff' + verify()
     asserts down-cliff residual <5% AND no up-cliff exists, so a
     multiply-by-2 construction fails the build.
v1.2.2 changelog (post-audit, 2026-09-30, closes Cursor round-3 notes;
        round-3 verdict: PASS as Phase 2 gate, notes are drift-class only):
  D1 stale sentences killed at the root: builder/detector docstring
     titles no longer restate the version; superseded v1.1.0 changelog
     facts annotated; PRF-203-03 desc states the asserted count.
  D2 nonzero freeze LOCKED: verify() asserts frozen mark > 0; harness
     token pins the exact derived value (regression to 0.0 fails).
  D3 futures variant observed: det_202 gains a settle-frozen signature;
     PRF-202-04 answer key carries evidence_must_include token.
v1.2.1 changelog (post-audit, 2026-09-30, fixes Cursor round-2 leftovers):
  C1 date off-by-one: 204-03 end date now DERIVED (dates[-1] injected
     into desc) - comments/desc can no longer drift from the artifact.
  C2 verify() now asserts exactly 9 backward jumps (README claim was
     stronger than the code: was jumps > 0).
  C3 202-01 strike 100 -> 80: expiry-bar print is now a NONZERO frozen
     mark (ITM ~5.5) - the freeze signature is actually exercised.
  C4 cannot_determine discipline: harness now asserts EVERY pure-data
     detector is silent on PRF-201-03/04 (was: only profile.201).
  C5 det_202 evidence now includes secondary signatures (nonzero
     post-expiry volume, frozen mark/IV vs moving underlying) so the
     hard 202 variants are actually observed, asserted via
     expected.evidence_must_include.
v1.1.0 changelog (post-audit, 2026-09-29, fixes Cursor Phase-1 audit):
  B1 PRF-203-03: rebuilt so parsed timestamps actually jump backward
     (mixed naive-UTC and +08:00 renderings, string-sorted); builder
     self-check parses and asserts backward jumps [superseded: ==9 in v1.2.1].
  B2 PRF-204-04: relabelled to the true symptom - whole-column scaled by
     full-sample std (column std ~ 1); rolling vol is NOT constant.
  B3 PRF-204-03: real dates ending 2026-06-19 [WRONG then, 06-18 actual;
     derived from dates[-1] since v1.2.1], so the
     meta contract violation (stats as_of 2027-12-31) is well-defined.
  B4 LNT-103-02: pnl now uses signal.shift(1) so centered window is the
     only planted defect (no accidental same-bar fill).
  B5 Label leak: all sample sources, filenames and metas are neutral -
     rule ids, "planted", defect names stripped; mapping lives ONLY in
     expected_results.json (the answer key).
  F1 PRF-202-01: strike aligned at 100 [superseded: 80 in v1.2.1, ITM
     with nonzero frozen mark], instrument derived from the
     real expiry, zombie mark frozen at the exact expiry-bar print.
  F2 CLN-D01 desc now points at PRF-201-01; PRF-201-01 note says 36.50.
  F3 Clean-strategy gate asserts made meaningful (S01 warmup, S03 lag
     invariant); vacuous tautology removed.
  F4 The four mirror identities + timestamp + label-leak checks are
     asserted inside main() so edits that break them fail the build.
  S1 Calendar-day wording fixed (2520 days ~ 6.9y); PRF-201-03 uses
     s0=200 with wedge 96 so prices stay positive.
  S2 PRF-202-04 wording: continuation is 25 bars (not delivery-month end).
  S3 LNT-101-02 column px -> close; shared OHLCV fixture added.

Zero third-party deps (stdlib only). Fixed seeds -> byte-stable.

SSOT: this repository (tests/corpus/expected_results.json)
Iron rules: (1) never touch suite v3.1 / anti-hallucination-core;
            (2) Phase 2 is the hard stop-loss point;
            (3) every output reviewed by the boss before next phase.
"""
from __future__ import annotations

import csv
import json
import math
import random
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / "tests" / "corpus"
CORPUS_VERSION = "1.2.7"
GENERATED_ON = "2026-10-01"
SSOT = "this repository (tests/corpus/expected_results.json)"

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def gbm_path(seed: int, n: int, s0: float = 100.0, mu: float = 0.08,
             sigma: float = 0.20, dt: float = 1.0 / 252.0) -> list[float]:
    rng = random.Random(seed)
    path = [s0]
    for _ in range(n - 1):
        z = rng.gauss(0.0, 1.0)
        path.append(path[-1] * math.exp((mu - 0.5 * sigma ** 2) * dt
                                        + sigma * math.sqrt(dt) * z))
    return path


def dates_from(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([header] + rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_meta(path: Path, meta: dict) -> None:
    path.with_suffix(path.suffix + ".meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def base_meta(case_id: str, seed: int, columns: list[str], rows: int) -> dict:
    return {"case_id": case_id, "seed": seed, "columns": columns,
            "rows": rows, "generated": GENERATED_ON,
            "builder_version": CORPUS_VERSION}


# ==========================================================================
# 1. Planted LINT samples (15) - neutral filenames, neutral docstrings.
#    Rule mapping lives ONLY in expected_results.json.
#    Order: cases 01-03, 04-06, 07-09, 10-12, 13-15 map to the five
#    rule families in ascending order.
# ==========================================================================

LINT_CASES: list[dict] = []

LINT_CASES.append(dict(
    sid="LNT-101-01", file="code_case_01.py", rule="lint.101",
    variant="baseline",
    desc="signal[t] 由 bar t close 算出，pnl 直接乘同 bar ret（close-to-close），同 bar 成交",
    src='''"""Corpus case 01. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma"] = df["close"].rolling(20).mean()
    df["signal"] = (df["close"] > df["ma"]).astype(int)
    df["position"] = df["signal"]
    df["ret"] = df["close"].pct_change()
    df["pnl"] = df["position"] * df["ret"]
    return df
'''))

LINT_CASES.append(dict(
    sid="LNT-101-02", file="code_case_02.py", rule="lint.101",
    variant="alias+function-wrap",
    desc="列名规范化后仍是 signal[t] × ret[t] 同 bar 对齐，入场判断封装进独立函数",
    src='''"""Corpus case 02. Quant strategy sample.
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
'''))

LINT_CASES.append(dict(
    sid="LNT-101-03", file="code_case_03.py", rule="lint.101",
    variant="loop",
    desc="循环形态：bar i close 突破 bar i-1 high 决策，成交记在 bar i 收盘",
    src='''"""Corpus case 03. Quant strategy sample.
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
'''))

LINT_CASES.append(dict(
    sid="LNT-102-01", file="code_case_04.py", rule="lint.102",
    variant="baseline",
    desc="position 未 shift 直接乘 open-to-open ret（bar t close 信息在 bar t open 之后才存在）",
    src='''"""Corpus case 04. Quant strategy sample.
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
'''))

LINT_CASES.append(dict(
    sid="LNT-102-02", file="code_case_05.py", rule="lint.102",
    variant="zscore",
    desc="rolling z-score 未滞后，pnl 用同 bar open ret",
    src='''"""Corpus case 05. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    win = 50
    mean_ = df["close"].rolling(win).mean()
    std_ = df["close"].rolling(win).std()
    z = (df["close"] - mean_) / std_
    df["position"] = (z < -2.0).astype(int)
    df["pnl"] = df["position"] * df["open"].pct_change()
    return df
'''))

LINT_CASES.append(dict(
    sid="LNT-102-03", file="code_case_06.py", rule="lint.102",
    variant="helper-wrap",
    desc="信号函数封装进 helper，pnl 仍与同 bar open ret 对齐",
    src='''"""Corpus case 06. Quant strategy sample.
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
'''))

LINT_CASES.append(dict(
    sid="LNT-103-01", file="code_case_07.py", rule="lint.103",
    variant="baseline",
    desc="rolling(center=True) 生成趋势信号；pnl 已 shift(1)，居中窗口是唯一缺陷",
    src='''"""Corpus case 07. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["trend"] = df["close"].rolling(21, center=True).mean()
    df["signal"] = (df["close"] > df["trend"]).astype(int)
    df["position"] = df["signal"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change()
    df["pnl"] = df["position"] * df["ret"]
    return df
'''))

LINT_CASES.append(dict(
    sid="LNT-103-02", file="code_case_08.py", rule="lint.103",
    variant="kwargs",
    desc="center=True 藏在 **kwargs 透传里；pnl 已 shift(1)，与 103-01/03 同构隔离",
    src='''"""Corpus case 08. Quant strategy sample.
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
'''))

LINT_CASES.append(dict(
    sid="LNT-103-03", file="code_case_09.py", rule="lint.103",
    variant="apply",
    desc="rolling(center=True).apply 自定义函数；pnl 已 shift(1)",
    src='''"""Corpus case 09. Quant strategy sample.
Required columns: open, high, low, close.
"""
import numpy as np
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["mid_avg"] = df["close"].rolling(11, center=True).apply(
        lambda x: np.mean(x), raw=True
    )
    df["signal"] = (df["close"] < df["mid_avg"]).astype(int)
    df["position"] = df["signal"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change()
    df["pnl"] = df["position"] * df["ret"]
    return df
'''))

LINT_CASES.append(dict(
    sid="LNT-104-01", file="code_case_10.py", rule="lint.104",
    variant="baseline",
    desc="用序列末端值归一化全历史价格",
    src='''"""Corpus case 10. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["norm_px"] = df["close"] / df["close"].iloc[-1]
    df["signal"] = (df["norm_px"] > 0.9).astype(int)
    df["position"] = df["signal"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change()
    df["pnl"] = df["position"] * df["ret"]
    return df
'''))

LINT_CASES.append(dict(
    sid="LNT-104-02", file="code_case_11.py", rule="lint.104",
    variant="neg-shift",
    desc="shift(-5) 把 5 根之后的收盘价拉回当期做标签",
    src='''"""Corpus case 11. Quant strategy sample.
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
'''))

LINT_CASES.append(dict(
    sid="LNT-104-03", file="code_case_12.py", rule="lint.104",
    variant="tail-stats",
    desc="序列末端标量与尾部窗口统计量回流到历史仓位缩放",
    src='''"""Corpus case 12. Quant strategy sample.
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
'''))

LINT_CASES.append(dict(
    sid="LNT-105-01", file="code_case_13.py", rule="lint.105",
    variant="baseline",
    desc="回测主函数零断言：无 NaN 门、无守恒检查、无仓位域检查",
    src='''"""Corpus case 13. Quant strategy sample.
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
    return df
'''))

LINT_CASES.append(dict(
    sid="LNT-105-02", file="code_case_14.py", rule="lint.105",
    variant="commented-out",
    desc="断言全部被注释，只剩 print 汇报",
    src='''"""Corpus case 14. Quant strategy sample.
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
'''))

LINT_CASES.append(dict(
    sid="LNT-105-03", file="code_case_15.py", rule="lint.105",
    variant="vacuous",
    desc="断言形式上存在但恒真，无守恒语义",
    src='''"""Corpus case 15. Quant strategy sample.
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
    assert True
    assert df is not None
    return df
'''))

# ==========================================================================
# 2. Clean strategy samples (3) - neutral filenames; meaningful gate asserts.
# ==========================================================================

CLEAN_STRATEGY_CASES: list[dict] = []

CLEAN_STRATEGY_CASES.append(dict(
    sid="CLN-S01", file="strategy_case_A.py",
    desc="SMA 金叉：signal.shift(1) 严格 T+1；断言含 NaN 门、仓位域、warmup 期零仓位",
    src='''"""Corpus case A. Quant strategy sample.
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
'''))

CLEAN_STRATEGY_CASES.append(dict(
    sid="CLN-S02", file="strategy_case_B.py",
    desc="ROC 动量：信号比较 shift(20) 前价格且 position 再 shift(1)；断言含首 bar 平仓",
    src='''"""Corpus case B. Quant strategy sample.
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
'''))

CLEAN_STRATEGY_CASES.append(dict(
    sid="CLN-S03", file="strategy_case_C.py",
    desc="唐奇安通道：通道 shift(1) 冻结在上一根，position 再 shift(1)；断言含 T+1 滞后不变量",
    src='''"""Corpus case C. Quant strategy sample.
Required columns: open, high, low, close.
"""
import pandas as pd


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["upper"] = df["high"].rolling(20).max().shift(1)
    df["lower"] = df["low"].rolling(20).min().shift(1)
    df["signal"] = ((df["close"] > df["upper"]).astype(int)
                    - (df["close"] < df["lower"]).astype(int))
    df["position"] = df["signal"].shift(1).fillna(0)
    df["ret"] = df["close"].pct_change().fillna(0)
    df["pnl"] = df["position"] * df["ret"]
    # Gates.
    assert df["pnl"].notna().all(), "NaN in pnl stream"
    assert df["position"].isin([-1, 0, 1]).all(), "position must be -1/0/1"
    # T+1 invariant: today's position equals yesterday's signal.
    lag_ok = df["position"] == df["signal"].shift(1).fillna(0)
    assert lag_ok.all(), "position lag misaligned"
    return df
'''))

# ==========================================================================
# 3. Profile data cases. Filenames neutral; construction truth lives in
#    expected_results.json. Metas carry only contract/reference fields.
# ==========================================================================

PROFILE_RESULTS: list[dict] = []
CLEAN_DATA_RESULTS: list[dict] = []


def build_mirror_201() -> None:
    """Mirror pair: data_case_01 (raw, clean) / profile_case_01 (fwd-adjusted)."""
    n = 2520  # calendar-day stepping, ~6.9 years
    raw = gbm_path(seed=201, n=n)
    dates = dates_from(date(2016, 1, 4), n)
    dividends = []
    for i in range(1, 11):
        ex_idx = 252 * i - 1  # keep inside [0, n-1]
        dividends.append({"ex_date": dates[ex_idx].isoformat(),
                          "ex_index": ex_idx, "amount": round(2.0 + 0.3 * i, 2)})

    header = ["date", "close"]
    rows_v1 = [[d.isoformat(), round(p, 6)] for d, p in zip(dates, raw)]
    p1 = CORPUS / "clean" / "data" / "data_case_01.csv"
    write_csv(p1, header, rows_v1)
    m1 = base_meta("data_case_01", 201, header, len(rows_v1))
    m1["adjusted_price_mode"] = "raw"
    m1["dividend_events"] = dividends  # reference table for the verified tier
    write_meta(p1, m1)
    CLEAN_DATA_RESULTS.append({
        "id": "CLN-D01", "path": "clean/data/data_case_01.csv",
        "module": "profile", "rule": None,
        "expected": {"caught": False, "rules": []},
        "desc": "镜像 v1：raw 未复权 GBM + 分红事件表参照（对应 PRF-201-01，种子 201）"})

    cum_after = [0.0] * n
    running = 0.0
    for i in range(n - 1, -1, -1):
        cum_after[i] = running
        for dv in dividends:
            if dv["ex_index"] == i:
                running += dv["amount"]
    rows_v2 = [[d.isoformat(), round(p - c, 6)]
               for d, p, c in zip(dates, raw, cum_after)]
    p2 = CORPUS / "planted" / "profile" / "profile_case_01.csv"
    write_csv(p2, header, rows_v2)
    m2 = base_meta("profile_case_01", 201, header, len(rows_v2))
    m2["adjusted_price_mode"] = "unknown"
    write_meta(p2, m2)
    PROFILE_RESULTS.append({
        "id": "PRF-201-01", "path": "planted/profile/profile_case_01.csv",
        "module": "profile", "rule": "profile.201",
        "expected": {"caught": True, "rules": ["profile.201"],
                     "tier": "verified"},
        "desc": "镜像 v2：同种子前复权倒推（老价格被累计分红 36.50 压低；v1 放行 / v2 报警）。tier=verified：有参照序列+事件表时可确定性判定"})


def build_profile_201_rest() -> None:
    # PRF-201-02: 1:2 split half-cliff, hidden events.
    # Raw (unadjusted) vendor data around a 1:2 split: price HALVES on the
    # ex-date -> a DOWN-cliff at the midpoint whose split-residual stays
    # within daily noise (<5%), with no event table to explain it (that
    # missing table is the planted disease). Direction is LOCKED in verify().
    n = 1000
    raw = gbm_path(seed=2012, n=n)
    split_idx = n // 2
    rows = [[i, round(p if i < split_idx else p / 2.0, 6)]
            for i, p in enumerate(raw)]
    p = CORPUS / "planted" / "profile" / "profile_case_02.csv"
    write_csv(p, ["t", "close"], rows)
    write_meta(p, base_meta("profile_case_02", 2012, ["t", "close"], len(rows)))
    PROFILE_RESULTS.append({
        "id": "PRF-201-02", "path": "planted/profile/profile_case_02.csv",
        "module": "profile", "rule": "profile.201",
        "expected": {"caught": True, "rules": ["profile.201"],
                     "tier": "suspicious",
                     "evidence_must_include": ["down-cliff"]},
        "desc": "送股 1:2 原始价：除权日（构造中点）价格减半为下断崖，扣除拆分后的残差在当日噪声内（<5%），方向为下（DOWN），事件表被隐藏。tier=suspicious：断崖指纹强但数据本身无法证明意图"})

    # PRF-201-03: linear wedge subtraction (s0=200, wedge 96 -> stays positive).
    n = 5040  # calendar-day stepping, ~13.8 years
    raw = gbm_path(seed=2013, n=n, s0=200.0)
    total = 96.0
    rows = [[i, round(p - total * (n - i) / n, 6)] for i, p in enumerate(raw)]
    p = CORPUS / "planted" / "profile" / "profile_case_03.csv"
    write_csv(p, ["t", "close"], rows)
    write_meta(p, base_meta("profile_case_03", 2013, ["t", "close"], len(rows)))
    PROFILE_RESULTS.append({
        "id": "PRF-201-03", "path": "planted/profile/profile_case_03.csv",
        "module": "profile", "rule": "profile.201",
        "expected": {"caught": False, "rules": [], "tier": "cannot_determine",
                     "note": "discipline sample: no pure-data fingerprint "
                             "exists; a pure-data detector MUST return "
                             "cannot-determine. Catchable only with "
                             "reference data (raw series / event table)."},
        "desc": "楔形累积减值（s0=200，价格保持为正）。tier=cannot_determine：无参照时与长期低漂移走势不可区分，诚实分级样本——纯数据检测器报'无法判定'才是正确行为"})

    # PRF-201-04: adjusted series + meta contract field claiming raw.
    n = 800
    raw = gbm_path(seed=2014, n=n)
    rows = [[i, round(p - 40.0 * (n - i) / n, 6)] for i, p in enumerate(raw)]
    p = CORPUS / "planted" / "profile" / "profile_case_04.csv"
    write_csv(p, ["t", "close"], rows)
    m = base_meta("profile_case_04", 2014, ["t", "close"], len(rows))
    m["adjusted_price_mode"] = "raw"  # contract field lies about the series
    write_meta(p, m)
    PROFILE_RESULTS.append({
        "id": "PRF-201-04", "path": "planted/profile/profile_case_04.csv",
        "module": "profile", "rule": "profile.201",
        "expected": {"caught": False, "rules": [], "tier": "cannot_determine",
                     "note": "discipline sample: the contract field claim "
                             "'raw' is unverifiable without reference; a "
                             "pure-data detector MUST return cannot-determine."},
        "desc": "前复权序列 + 契约字段谎称 raw。tier=cannot_determine：契约声明无法用纯数据证伪，需参照数据交叉核对"})


def build_mirror_202() -> None:
    """Mirror pair: data_case_02 (truncated) / profile_case_05 (continuation)."""
    seed = 202
    n = 700
    underlying = gbm_path(seed=seed, n=n, s0=100.0)
    dates = dates_from(date(2023, 8, 1), n)
    expiry_idx = 600
    expiry = dates[expiry_idx]
    strike, cp = 80, "call"  # ITM at expiry (underlying ~85.5): frozen
    instr = f"SYN-{expiry:%y%m%d}-{strike}-C"  # mark is nonzero
    header = ["trade_date", "instrument", "expiry", "strike", "cp",
              "mark", "volume", "open_interest", "underlying"]

    def chain_rows(zombie_tail: int) -> list[list]:
        rows = []
        last_mark = None
        for i in range(n):
            px = underlying[i]
            intrinsic = max(px - strike, 0.0)
            ttm = max(expiry_idx - i, 0)
            mark = intrinsic + 8.0 * math.sqrt(ttm / 252.0) * (px / strike)
            if i <= expiry_idx:
                if i == expiry_idx:
                    last_mark = round(mark, 4)  # freeze at the expiry-bar print
                rows.append([dates[i].isoformat(), instr, expiry.isoformat(),
                             strike, cp, round(mark, 4),
                             int(50 + 30 * math.sin(i / 7)), 1200,
                             round(px, 2)])
            elif i <= expiry_idx + zombie_tail:
                rows.append([dates[i].isoformat(), instr, expiry.isoformat(),
                             strike, cp, last_mark, 0, 1200, round(px, 2)])
        return rows

    frozen_mark = round(max(underlying[expiry_idx] - strike, 0.0), 4)
    p1 = CORPUS / "clean" / "data" / "data_case_02.csv"
    write_csv(p1, header, chain_rows(zombie_tail=0))
    m1 = base_meta("data_case_02", seed, header, 601)
    m1["expiry"] = expiry.isoformat()
    write_meta(p1, m1)
    CLEAN_DATA_RESULTS.append({
        "id": "CLN-D02", "path": "clean/data/data_case_02.csv",
        "module": "profile", "rule": None,
        "expected": {"caught": False, "rules": []},
        "desc": "镜像 v1：期权链严格截断在到期日（对应 PRF-202-01，种子 202）"})

    p2 = CORPUS / "planted" / "profile" / "profile_case_05.csv"
    write_csv(p2, header, chain_rows(zombie_tail=90))
    m2 = base_meta("profile_case_05", seed, header, 691)
    m2["expiry"] = expiry.isoformat()
    write_meta(p2, m2)
    PROFILE_RESULTS.append({
        "id": "PRF-202-01", "path": "planted/profile/profile_case_05.csv",
        "module": "profile", "rule": "profile.202",
        "expected": {"caught": True, "rules": ["profile.202"], "tier": "verified",
                     "evidence_must_include": [f"mark frozen at {frozen_mark}"]},
        "desc": f"镜像 v2：到期后 90 天延续行（strike {strike} 到期日 ITM：mark 冻结在到期日打印值 {frozen_mark}，非零已锁，冻结签名真实可观测），mark 冻结在到期日打印值、量 0、OI 僵死"})


def build_profile_202_rest() -> None:
    # PRF-202-02: frozen mark + frozen IV, positive stale OI.
    frozen_mark2, frozen_iv2 = 3.0, 0.55  # single source of truth (N1 lock)
    seed, n = 2022, 500
    underlying = gbm_path(seed=seed, n=n, s0=30000)
    dates = dates_from(date(2024, 2, 1), n)
    expiry_idx, expiry = 400, dates[400]
    instr = f"SYN-{expiry:%y%m%d}-60000-C"
    header = ["trade_date", "instrument", "expiry", "strike", "cp",
              "mark", "iv", "volume", "open_interest", "underlying"]
    rows = []
    rng = random.Random(seed + 7)
    for i in range(n):
        px = underlying[i]
        if i <= expiry_idx:
            ttm = max(expiry_idx - i, 0)
            mark = 3.0 + 5.0 * math.sqrt(ttm / 252.0)
            iv = 0.55 + 0.02 * rng.gauss(0, 1)
            rows.append([dates[i].isoformat(), instr, expiry.isoformat(), 60000,
                         "call", round(mark, 4), round(iv, 4),
                         int(10 + 5 * rng.random()), 300, round(px, 2)])
        elif i <= expiry_idx + 60:
            rows.append([dates[i].isoformat(), instr, expiry.isoformat(), 60000,
                         "call", frozen_mark2, frozen_iv2, 0, 300, round(px, 2)])
    p = CORPUS / "planted" / "profile" / "profile_case_06.csv"
    write_csv(p, header, rows)
    m = base_meta("profile_case_06", seed, header, len(rows))
    m["expiry"] = expiry.isoformat()
    write_meta(p, m)
    PROFILE_RESULTS.append({
        "id": "PRF-202-02", "path": "planted/profile/profile_case_06.csv",
        "module": "profile", "rule": "profile.202",
        "expected": {"caught": True, "rules": ["profile.202"], "tier": "verified",
                     "evidence_must_include": [f"mark frozen at {frozen_mark2}",
                                               f"iv frozen at {frozen_iv2}"]},
        "desc": f"到期后延续 60 行：mark 冻结在 {frozen_mark2}、IV 冻结在 {frozen_iv2}（均非零已锁）、OI 僵死为正（价格层面更难察觉的变体）"})

    # PRF-202-03: reanimated rows with small nonzero volume.
    seed, n = 2023, 450
    underlying = gbm_path(seed=seed, n=n, s0=100.0)
    dates = dates_from(date(2024, 5, 1), n)
    expiry_idx, expiry = 380, dates[380]
    instr = f"SYN-{expiry:%y%m%d}-100-C"
    header = ["trade_date", "instrument", "expiry", "strike", "cp",
              "mark", "volume", "open_interest", "underlying"]
    rows = []
    rng = random.Random(seed + 11)
    for i in range(n):
        px = underlying[i]
        if i <= expiry_idx:
            ttm = max(expiry_idx - i, 0)
            mark = max(px - 100.0, 0.0) + 4.0 * math.sqrt(ttm / 252.0)
            rows.append([dates[i].isoformat(), instr, expiry.isoformat(), 100,
                         "call", round(mark, 4), int(80 + 20 * rng.random()),
                         900, round(px, 2)])
        elif i <= expiry_idx + 30:
            mark = max(underlying[expiry_idx] - 100.0, 0.0)
            rows.append([dates[i].isoformat(), instr, expiry.isoformat(), 100,
                         "call", round(mark, 4), int(1 + 3 * rng.random()),
                         900, round(px, 2)])
    p = CORPUS / "planted" / "profile" / "profile_case_07.csv"
    write_csv(p, header, rows)
    m = base_meta("profile_case_07", seed, header, len(rows))
    m["expiry"] = expiry.isoformat()
    write_meta(p, m)
    PROFILE_RESULTS.append({
        "id": "PRF-202-03", "path": "planted/profile/profile_case_07.csv",
        "module": "profile", "rule": "profile.202",
        "expected": {"caught": True, "rules": ["profile.202"], "tier": "verified",
                     "evidence_must_include": ["nonzero volume"]},
        "desc": "到期后延续 30 行且带少量非零成交量（边界错位 + 伪装变体）"})

    # PRF-202-04: frozen settle for 25 bars past expiry.
    seed, n = 2024, 600
    underlying = gbm_path(seed=seed, n=n, s0=4500.0)
    dates = dates_from(date(2023, 1, 2), n)
    expiry_idx, expiry = 480, dates[480]
    instr = f"SYN-{expiry:%y%m%d}-FUT"
    header = ["trade_date", "instrument", "expiry", "settle", "volume",
              "open_interest", "underlying"]
    rows = []
    for i in range(n):
        if i <= expiry_idx:
            rows.append([dates[i].isoformat(), instr, expiry.isoformat(),
                         round(underlying[i], 2), int(1000 + i % 97), 8000,
                         round(underlying[i], 2)])
        elif i <= expiry_idx + 25:
            rows.append([dates[i].isoformat(), instr, expiry.isoformat(),
                         round(underlying[expiry_idx], 2), 0, 8000,
                         round(underlying[i], 2)])
    frozen_settle = round(underlying[expiry_idx], 2)  # single source of truth
    p = CORPUS / "planted" / "profile" / "profile_case_08.csv"
    write_csv(p, header, rows)
    m = base_meta("profile_case_08", seed, header, len(rows))
    m["expiry"] = expiry.isoformat()
    write_meta(p, m)
    PROFILE_RESULTS.append({
        "id": "PRF-202-04", "path": "planted/profile/profile_case_08.csv",
        "module": "profile", "rule": "profile.202",
        "expected": {"caught": True, "rules": ["profile.202"], "tier": "verified",
                     "evidence_must_include": [f"settle frozen at {frozen_settle}"]},
        "desc": f"到期后延续 25 行：结算价冻结在到期日值 {frozen_settle}（非零已锁）、量 0"})


def build_mirror_203() -> None:
    """Mirror pair: data_case_03 (monotonic) / profile_case_09 (shuffled)."""
    seed, n = 203, 500
    px = gbm_path(seed=seed, n=n, s0=50.0)
    dates = dates_from(date(2024, 1, 1), n)
    header = ["timestamp", "close"]

    p1 = CORPUS / "clean" / "data" / "data_case_03.csv"
    rows1 = [[d.isoformat(), round(p, 6)] for d, p in zip(dates, px)]
    write_csv(p1, header, rows1)
    write_meta(p1, base_meta("data_case_03", seed, header, len(rows1)))
    CLEAN_DATA_RESULTS.append({
        "id": "CLN-D03", "path": "clean/data/data_case_03.csv",
        "module": "profile", "rule": None,
        "expected": {"caught": False, "rules": []},
        "desc": "镜像 v1：时间戳严格单调递增（对应 PRF-203-01，种子 203）"})

    rows2 = [list(r) for r in rows1]
    rng = random.Random(seed + 3)
    for _ in range(12):
        i = rng.randrange(50, n - 60)
        j = i + rng.randrange(20, 50)
        rows2[i], rows2[j] = rows2[j], rows2[i]
    p2 = CORPUS / "planted" / "profile" / "profile_case_09.csv"
    write_csv(p2, header, rows2)
    write_meta(p2, base_meta("profile_case_09", seed, header, len(rows2)))
    PROFILE_RESULTS.append({
        "id": "PRF-203-01", "path": "planted/profile/profile_case_09.csv",
        "module": "profile", "rule": "profile.203",
        "expected": {"caught": True, "rules": ["profile.203"], "tier": "verified"},
        "desc": "镜像 v2：12 对行乱序（行多重集合与 v1 相同，顺序被破坏）"})


def build_profile_203_rest() -> None:
    # PRF-203-02: duplicate timestamps appended at end.
    # Round-7 Fix: the copies are NOT adjacent to their originals, so an
    # adjacent-equality counter sees 0 duplicate stamps. The disease is
    # counted BY VALUE (30 stamps appear twice); facts locked in verify().
    seed, n = 2032, 400
    px = gbm_path(seed=seed, n=n, s0=80.0)
    dates = dates_from(date(2024, 3, 1), n)
    rows = [[d.isoformat(), round(p, 6)] for d, p in zip(dates, px)]
    tail = rows[100:130]  # 30 old rows resurrected at the end
    rows = rows + tail
    dup_rows = len(tail)  # single source of truth for the locked count
    p = CORPUS / "planted" / "profile" / "profile_case_10.csv"
    write_csv(p, ["timestamp", "close"], rows)
    write_meta(p, base_meta("profile_case_10", seed, ["timestamp", "close"],
                            len(rows)))
    PROFILE_RESULTS.append({
        "id": "PRF-203-02", "path": "planted/profile/profile_case_10.csv",
        "module": "profile", "rule": "profile.203",
        "expected": {"caught": True, "rules": ["profile.203"], "tier": "verified",
                     "evidence_must_include": [f"{dup_rows} duplicate-by-value rows"]},
        "desc": f"末尾追加 {dup_rows} 行重复时间戳（老日期复活）；按值计数重复（非相邻对），精确 token 已钉"})

    # PRF-203-03: parsed timestamps actually move backward.
    # Normal rows: UTC stamps "...T23:00:00Z" (instant: that day 23:00Z).
    # For every 37th day we KEEP the normal row and ADD one extra row:
    # that day rendered as next-day local "+08:00" -> instant is 21:00Z of
    # the SAME day, i.e. 2h EARLIER than the preceding normal row. String
    # sort preserves the wrong-for-parse order, so parsed time jumps back.
    seed, n = 2033, 300
    px = gbm_path(seed=seed, n=n, s0=25.0)
    dates = dates_from(date(2024, 6, 1), n)
    rows = []
    flagged = 0
    for i, (d, p_) in enumerate(zip(dates, px)):
        rows.append([d.isoformat() + "T23:00:00Z", round(p_, 6)])
        if i % 37 == 0:
            rows.append([(d + timedelta(days=1)).isoformat()
                         + "T05:00:00+08:00", round(p_, 6)])
            flagged += 1
    rows.sort(key=lambda r: r[0])
    p = CORPUS / "planted" / "profile" / "profile_case_11.csv"
    write_csv(p, ["timestamp", "close"], rows)
    write_meta(p, base_meta("profile_case_11", seed, ["timestamp", "close"],
                            len(rows)))
    PROFILE_RESULTS.append({
        "id": "PRF-203-03", "path": "planted/profile/profile_case_11.csv",
        "module": "profile", "rule": "profile.203",
        "expected": {"caught": True, "rules": ["profile.203"], "tier": "verified"},
        "desc": f"naive UTC 与 +08:00 时间戳混用：按字符串排序落盘后，解析出的时刻在 {flagged} 个标记日各出现一次 2 小时回跳（构建器自检断言回跳数 == {flagged}）"})


def build_mirror_204() -> None:
    """Mirror pair: data_case_04 (raw) / profile_case_12 (full-sample z-score)."""
    seed, n = 204, 1000
    px = gbm_path(seed=seed, n=n, s0=120.0)
    header = ["t", "close"]

    p1 = CORPUS / "clean" / "data" / "data_case_04.csv"
    rows1 = [[i, round(p, 6)] for i, p in enumerate(px)]
    write_csv(p1, header, rows1)
    m1 = base_meta("data_case_04", seed, header, len(rows1))
    m1["adjusted_price_mode"] = "raw"
    write_meta(p1, m1)
    CLEAN_DATA_RESULTS.append({
        "id": "CLN-D04", "path": "clean/data/data_case_04.csv",
        "module": "profile", "rule": None,
        "expected": {"caught": False, "rules": []},
        "desc": "镜像 v1：raw 价格（对应 PRF-204-01，种子 204）"})

    mu = sum(px) / n
    var = sum((p - mu) ** 2 for p in px) / n
    sd = math.sqrt(var)
    rows2 = [[i, round((p - mu) / sd, 8)] for i, p in enumerate(px)]
    p2 = CORPUS / "planted" / "profile" / "profile_case_12.csv"
    write_csv(p2, header, rows2)
    m2 = base_meta("profile_case_12", seed, header, len(rows2))
    m2["column_semantics"] = "price"
    write_meta(p2, m2)
    PROFILE_RESULTS.append({
        "id": "PRF-204-01", "path": "planted/profile/profile_case_12.csv",
        "module": "profile", "rule": "profile.204",
        "expected": {"caught": True, "rules": ["profile.204"], "tier": "suspicious"},
        "desc": "镜像 v2：价格列被全样本 z-score 归一（population std=1.000000；v1 放行 / v2 报警）"})


def build_profile_204_rest() -> None:
    # PRF-204-02: full-sample min-max to exactly [0, 1].
    seed, n = 2042, 700
    px = gbm_path(seed=seed, n=n, s0=60.0)
    lo, hi = min(px), max(px)
    rows = [[i, round((p - lo) / (hi - lo), 8)] for i, p in enumerate(px)]
    p = CORPUS / "planted" / "profile" / "profile_case_13.csv"
    write_csv(p, ["t", "close"], rows)
    m = base_meta("profile_case_13", seed, ["t", "close"], len(rows))
    m["column_semantics"] = "price"
    write_meta(p, m)
    PROFILE_RESULTS.append({
        "id": "PRF-204-02", "path": "planted/profile/profile_case_13.csv",
        "module": "profile", "rule": "profile.204",
        "expected": {"caught": True, "rules": ["profile.204"], "tier": "suspicious"},
        "desc": "全样本 min-max：值域恰为 [0,1] 且 0.0/1.0 端点各精确出现一次（线索特征，判定需分级）"})

    # PRF-204-03: contract violation now well-defined - real dates present.
    seed, n = 2043, 900  # 2024-01-01 + 899 calendar days (end derived below)
    px = gbm_path(seed=seed, n=n, s0=90.0)
    dates = dates_from(date(2024, 1, 1), n)
    rows = [[d.isoformat(), round(p, 6)] for d, p in zip(dates, px)]
    end_date = dates[-1].isoformat()  # single source of truth for desc
    mu = sum(px) / n
    p = CORPUS / "planted" / "profile" / "profile_case_14.csv"
    write_csv(p, ["date", "close"], rows)
    m = base_meta("profile_case_14", seed, ["date", "close"], len(rows))
    m["adjusted_price_mode"] = "raw"
    m["stats"] = {"mean": round(mu, 6), "std": None,
                  "as_of": "2027-12-31", "window": "full_sample"}
    write_meta(p, m)
    PROFILE_RESULTS.append({
        "id": "PRF-204-03", "path": "planted/profile/profile_case_14.csv",
        "module": "profile", "rule": "profile.204",
        "expected": {"caught": True, "rules": ["profile.204"], "tier": "verified"},
        "desc": f"数据契约违规：序列带真实日期（止于 {end_date}），meta 统计量声明 as_of=2027-12-31（超出数据末端 1.5 年）且 window=full_sample"})

    # PRF-204-04: whole-column scaled by full-sample std (column std ~ 1).
    seed, n = 2044, 900
    px = gbm_path(seed=seed, n=n, s0=100.0, sigma=0.35)
    rets = [0.0] + [px[i] / px[i - 1] - 1 for i in range(1, n)]
    mu = sum(rets) / n
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / n)
    rows = [[i, round(r / sd, 8)] for i, r in enumerate(rets)]
    p = CORPUS / "planted" / "profile" / "profile_case_15.csv"
    write_csv(p, ["t", "ret"], rows)
    m = base_meta("profile_case_15", seed, ["t", "ret"], len(rows))
    m["column_semantics"] = "return"
    write_meta(p, m)
    PROFILE_RESULTS.append({
        "id": "PRF-204-04", "path": "planted/profile/profile_case_15.csv",
        "module": "profile", "rule": "profile.204",
        "expected": {"caught": True, "rules": ["profile.204"], "tier": "suspicious"},
        "desc": "收益率列整体除以全样本 std：全列 std≈1（滚动波动率并不为常数；可检症状是列级统计量，判定需分级为可疑而非确定性证明）"})


def build_clean_data_pure() -> None:
    """data_case_05: pure synthetic GBM, clean by construction."""
    seed, n = 999, 600
    px = gbm_path(seed=seed, n=n, s0=75.0)
    p = CORPUS / "clean" / "data" / "data_case_05.csv"
    write_csv(p, ["t", "close"], [[i, round(v, 6)] for i, v in enumerate(px)])
    m = base_meta("data_case_05", seed, ["t", "close"], n)
    m["adjusted_price_mode"] = "raw"
    write_meta(p, m)
    CLEAN_DATA_RESULTS.append({
        "id": "CLN-D05", "path": "clean/data/data_case_05.csv",
        "module": "profile", "rule": None,
        "expected": {"caught": False, "rules": []},
        "desc": "纯合成 GBM 无事件无归一（干净由构造保证）"})


def build_fixture() -> None:
    """Shared OHLCV fixture so strategy cases are runnable as-is."""
    seed, n = 777, 600
    close = gbm_path(seed=seed, n=n, s0=100.0)
    rng = random.Random(seed + 1)
    rows = []
    for i, c in enumerate(close):
        o = close[i - 1] if i > 0 else c
        hi = max(o, c) * (1 + abs(rng.gauss(0, 0.004)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.004)))
        rows.append([i, (date(2024, 1, 1) + timedelta(days=i)).isoformat(),
                     round(o, 6), round(hi, 6), round(lo, 6), round(c, 6),
                     int(1000 + 100 * rng.random())])
    p = CORPUS / "fixtures" / "ohlcv_daily.csv"
    write_csv(p, ["t", "date", "open", "high", "low", "close", "volume"], rows)


# ==========================================================================
# 4. Build-time verification (F4: broken identities fail the build)
# ==========================================================================

def _load(path: Path) -> list[list]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.reader(f))[1:]


def verify(all_samples: list[dict]) -> None:
    import reference_detectors as rd  # sibling module in tools/

    # ---- Mirror identities (v1.1.0 F4, retained) -------------------------
    # Mirror 201: diff(t0) == total dividends; diff(t_end) == 0.
    v1 = _load(CORPUS / "clean/data/data_case_01.csv")
    v2 = _load(CORPUS / "planted/profile/profile_case_01.csv")
    meta = json.loads((CORPUS / "clean/data/data_case_01.csv.meta.json")
                      .read_text(encoding="utf-8"))
    total_div = sum(d["amount"] for d in meta["dividend_events"])
    assert abs((float(v1[0][1]) - float(v2[0][1])) - total_div) < 1e-6
    assert abs(float(v1[-1][1]) - float(v2[-1][1])) < 1e-6

    # Mirror 202: v1 == v2 prefix; exactly 90 continuation rows, frozen mark.
    v1 = _load(CORPUS / "clean/data/data_case_02.csv")
    v2 = _load(CORPUS / "planted/profile/profile_case_05.csv")
    assert v1 == v2[:len(v1)] and len(v2) - len(v1) == 90
    marks = {r[5] for r in v2[len(v1):]}
    assert len(marks) == 1, "continuation marks must be frozen at one value"
    assert float(next(iter(marks))) > 0, (  # nonzero freeze is LOCKED
        f"frozen mark must be nonzero (strike ITM at expiry), "
        f"got {next(iter(marks))}")

    # Futures sample: frozen settle must be a single NONZERO value (N1 lock).
    v = _load(CORPUS / "planted/profile/profile_case_08.csv")
    mf = json.loads((CORPUS / "planted/profile/profile_case_08.csv.meta.json")
                    .read_text(encoding="utf-8"))
    post = [r for r in v if r[0] > mf["expiry"]]
    assert len(post) == 25, f"futures continuation must be 25 rows, got {len(post)}"
    settles = {r[3] for r in post}
    assert len(settles) == 1 and float(next(iter(settles))) > 0, (
        f"futures frozen settle must be a single nonzero value, got {settles}")

    # Option sample 202-02: frozen mark AND iv must be single NONZERO
    # values (N1 lock - same class as the futures settle lock).
    v = _load(CORPUS / "planted/profile/profile_case_06.csv")
    mo = json.loads((CORPUS / "planted/profile/profile_case_06.csv.meta.json")
                    .read_text(encoding="utf-8"))
    posto = [r for r in v if r[0] > mo["expiry"]]
    assert len(posto) == 60, f"202-02 continuation must be 60 rows, got {len(posto)}"
    marks2 = {r[5] for r in posto}
    ivs2 = {r[6] for r in posto}
    assert len(marks2) == 1 and float(next(iter(marks2))) > 0, (
        f"202-02 frozen mark must be a single nonzero value, got {marks2}")
    assert len(ivs2) == 1 and float(next(iter(ivs2))) > 0, (
        f"202-02 frozen iv must be a single nonzero value, got {ivs2}")

    # Option sample 202-03: continuation length + nonzero volume LOCKED
    # (round-7 N1: continuation length was pinned for 202-01/02/04 but not
    # here - a single post-expiry row with nonzero volume satisfied the
    # evidence token).
    v = _load(CORPUS / "planted/profile/profile_case_07.csv")
    mo7 = json.loads((CORPUS / "planted/profile/profile_case_07.csv.meta.json")
                     .read_text(encoding="utf-8"))
    post7 = [r for r in v if r[0] > mo7["expiry"]]
    assert len(post7) == 30, f"202-03 continuation must be 30 rows, got {len(post7)}"
    assert all(int(r[6]) > 0 for r in post7), (
        "202-03 post-expiry volume must be nonzero in every row")

    # Mirror 203: multiset equality; v1 strictly monotonic.
    v1 = _load(CORPUS / "clean/data/data_case_03.csv")
    v2 = _load(CORPUS / "planted/profile/profile_case_09.csv")
    assert sorted(map(tuple, v1)) == sorted(map(tuple, v2))
    assert v1 == sorted(v1, key=lambda r: r[0])

    # Mirror 204: z-scored column has population mean 0 / std 1.
    v2 = _load(CORPUS / "planted/profile/profile_case_12.csv")
    vals = [float(r[1]) for r in v2]
    m = sum(vals) / len(vals)
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))
    assert abs(m) < 1e-9 and abs(sd - 1.0) < 1e-6

    # 203-03: parsed timestamps must contain backward jumps (>0).
    v = _load(CORPUS / "planted/profile/profile_case_11.csv")
    ts = [datetime.fromisoformat(r[0].replace("Z", "+00:00")) for r in v]
    jumps = sum(1 for a, b in zip(ts, ts[1:]) if b < a)
    assert jumps == 9, (  # README claims 9 - code must match the claim
        f"PRF-203-03 must contain exactly 9 backward jumps, got {jumps}")

    # 203-02: value-based duplicate stamps LOCKED (round-7 Fix, sharpened
    # in round-8 N3). The disease SHAPE is: 30 copies appended at the END,
    # non-adjacent to their originals. A file-wide '>= 1 backward jump' +
    # 'value dups == 30' pair still admits '30 adjacent copies + a later
    # swap' (2 jumps, 30 adjacent dup stamps, token still matches). Pin
    # the shape exactly: ONE backward jump located AT the append boundary
    # (index 399 -> 400), ZERO adjacent duplicate stamps, 30 by value.
    v = _load(CORPUS / "planted/profile/profile_case_10.csv")
    ts10 = [r[0] for r in v]
    dup_by_value = len(ts10) - len(set(ts10))
    assert dup_by_value == 30, (
        f"PRF-203-02 must contain exactly 30 duplicate-by-value stamps, "
        f"got {dup_by_value}")
    dt10 = [datetime.fromisoformat(t) for t in ts10]
    adj_dup10 = sum(1 for a, b in zip(dt10, dt10[1:]) if b == a)
    assert adj_dup10 == 0, (
        f"PRF-203-02 duplicates must be non-adjacent (end-append shape), "
        f"got {adj_dup10} adjacent duplicate stamps")
    back_idx10 = [i for i in range(len(dt10) - 1) if dt10[i + 1] < dt10[i]]
    assert back_idx10 == [399], (
        f"PRF-203-02 must have exactly one backward jump AT the append "
        f"boundary (index 399), got jumps at {back_idx10}")

    # 201-02: direction LOCKED (N3). The extreme move must be a DOWN halving
    # with split-residual <5%; an UP-cliff must NOT exist anywhere, so a
    # construction that multiplies by 2 instead of dividing fails the build.
    v = _load(CORPUS / "planted/profile/profile_case_02.csv")
    px02 = [float(r[1]) for r in v]
    lr02 = [math.log(px02[i + 1] / px02[i]) for i in range(len(px02) - 1)]
    i_min = lr02.index(min(lr02))
    resid_down = math.log(2.0 * px02[i_min + 1] / px02[i_min])
    assert abs(resid_down) < 0.05, (
        f"201-02 down-cliff residual {resid_down:+.4f} outside daily noise")
    i_max = lr02.index(max(lr02))
    resid_up = math.log(px02[i_max + 1] / px02[i_max] / 2.0)
    assert abs(resid_up) >= 0.05, (
        "201-02 must NOT contain an up-cliff (direction locked)")

    # 204-03: meta as_of must be beyond the last data date.
    v = _load(CORPUS / "planted/profile/profile_case_14.csv")
    m = json.loads((CORPUS / "planted/profile/profile_case_14.csv.meta.json")
                   .read_text(encoding="utf-8"))
    last_date = datetime.fromisoformat(v[-1][0]).date()
    assert datetime.fromisoformat(m["stats"]["as_of"]).date() > last_date

    # Label-leak scan: generated sources and metas stay neutral.
    forbidden = ["bug", "lint.1", "profile.2", "planted", "zombie", "僵尸",
                 "前复权", "cheat", "defect", "lookahead", "same-bar",
                 "same bar", "leak"]
    for path in CORPUS.rglob("*"):
        if path.suffix not in (".py", ".json") or "expected_results" in path.name:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for tok in forbidden:
            assert tok not in text, f"label leak '{tok}' in {path.name}"

    # ---- Observability harness (v1.2.0 H1, HY-2) ------------------------
    # Independent re-observation of every sample by reference detectors:
    #   planted  -> the disease must be MEASURABLE in the artifact at the
    #               expected tier (build fails if the intent did not land);
    #   clean    -> every detector must stay silent (zero false positives
    #               is also a construction guarantee);
    #   cannot_determine discipline samples -> pure-data detectors must NOT
    #               flag them (claiming detection there would be fabrication).
    for s in all_samples:
        path = CORPUS / s["path"]
        sid, exp = s["id"], s["expected"]

        if s["module"] == "lint":
            res = rd.det_lint(path.read_text(encoding="utf-8"))
            if exp["caught"]:
                assert s["rule"] in res["fired"], (
                    f"{sid}: planted rule {s['rule']} not re-observed "
                    f"(fired={res['fired']}, evidence={res['evidence']})")
            else:
                assert not res["fired"], f"{sid}: clean sample fired {res['fired']}"
            continue

        rows = rd.load_rows(path)
        meta = rd.load_meta(path.with_suffix(path.suffix + ".meta.json"))

        if not exp["caught"]:
            if exp.get("tier") == "cannot_determine":
                fired = [vv for vv in rd.profile_sweep(rows, meta) if vv["fired"]]
                assert not fired, (  # README: EVERY pure-data detector silent
                    f"{sid}: cannot_determine discipline sample fired "
                    f"{[(vv['rule'], vv['evidence']) for vv in fired]}")
            else:
                fired = [vv for vv in rd.profile_sweep(rows, meta) if vv["fired"]]
                assert not fired, (
                    f"{sid}: clean data fired "
                    f"{[(vv['rule'], vv['evidence']) for vv in fired]}")
            continue

        tier = exp["tier"]
        if sid == "PRF-201-01":
            ref = CORPUS / "clean/data/data_case_01.csv"
            vv = rd.det_201_reference(
                rows, rd.load_rows(ref),
                rd.load_meta(str(ref) + ".meta.json")["dividend_events"])
            assert vv["fired"] and vv["tier"] == tier, f"{sid}: {vv}"
        elif sid == "PRF-201-02":
            vv = rd.det_201_cliff(rows)
            assert vv["fired"] and vv["tier"] == tier, f"{sid}: {vv}"
            for tok in exp.get("evidence_must_include", []):  # R1: token now read
                assert tok in vv["evidence"], (
                    f"{sid}: evidence token {tok!r} not observed in {vv['evidence']!r}")
        else:
            fired = [vv for vv in rd.profile_sweep(rows, meta)
                     if vv["fired"] and vv["rule"] == s["rule"]]
            assert fired, f"{sid}: planted rule {s['rule']} not re-observed"
            assert any(vv["tier"] == tier for vv in fired), (
                f"{sid}: expected tier {tier}, "
                f"got {[(vv['tier'], vv['evidence']) for vv in fired]}")
            for tok in exp.get("evidence_must_include", []):
                assert any(tok in vv["evidence"] for vv in fired), (
                    f"{sid}: evidence token {tok!r} not observed")


# ==========================================================================
# 5. Assemble
# ==========================================================================

def main() -> None:
    # Clean rebuild (repo-internal artifacts only).
    if CORPUS.exists():
        for sub in ["clean", "planted", "fixtures"]:
            shutil.rmtree(CORPUS / sub, ignore_errors=True)
        (CORPUS / "expected_results.json").unlink(missing_ok=True)

    lint_results = []
    for spec in LINT_CASES:
        write_text(CORPUS / "planted" / "lint" / spec["file"], spec["src"])
        lint_results.append({
            "id": spec["sid"], "path": f"planted/lint/{spec['file']}",
            "module": "lint", "rule": spec["rule"], "variant": spec["variant"],
            "expected": {"caught": True, "rules": [spec["rule"]],
                         "tier": "verified"},
            "desc": spec["desc"],
        })

    clean_strategy_results = []
    for spec in CLEAN_STRATEGY_CASES:
        write_text(CORPUS / "clean" / "strategies" / spec["file"], spec["src"])
        clean_strategy_results.append({
            "id": spec["sid"], "path": f"clean/strategies/{spec['file']}",
            "module": "lint", "rule": None,
            "expected": {"caught": False, "rules": []},
            "desc": spec["desc"],
        })

    build_fixture()
    build_mirror_201()
    build_profile_201_rest()
    build_mirror_202()
    build_profile_202_rest()
    build_mirror_203()
    build_profile_203_rest()
    build_mirror_204()
    build_profile_204_rest()
    build_clean_data_pure()

    all_samples = (clean_strategy_results + CLEAN_DATA_RESULTS
                   + lint_results + PROFILE_RESULTS)

    expected = {
        "corpus_version": CORPUS_VERSION,
        "generated": GENERATED_ON,
        "ssot": SSOT,
        "conventions": {
            "sample_ids": "CLN-### clean | LNT-### planted lint | PRF-### planted profile",
            "neutral_files": "filenames and file contents carry NO rule ids or "
                             "category hints; the mapping lives only in this file",
            "mirror_pairs": "v1 (clean) and v2 (planted) share the same seed; "
                            "detector MUST accept v1 and flag v2",
            "verdict_schema": "expected = {caught: bool, rules: [rule ids]}",
            "rule_ids": ["lint.101", "lint.102", "lint.103", "lint.104",
                         "lint.105", "profile.201", "profile.202",
                         "profile.203", "profile.204"],
            "verdict_tiers_on_real_data": "corpus expectations are deterministic "
                                          "because samples are constructed; on real "
                                          "data the profiler must emit graded verdicts: "
                                          "verified / suspicious / cannot-determine",
            "tier_schema": "planted samples carry expected.tier: verified "
                           "(deterministic fact from artifact/contract/reference) | "
                           "suspicious (strong fingerprint, intent not provable "
                           "from data alone) | cannot_determine (no pure-data "
                           "fingerprint exists; PRF-201-03/04 are discipline "
                           "samples - a pure-data detector returning cannot-"
                           "determine for them is CORRECT, claiming detection "
                           "would be fabrication)",
            "observability_guarantee": "every planted disease is independently "
                                       "re-observed in its artifact at build time "
                                       "by tools/reference_detectors.py; every "
                                       "clean sample must be silent; the build "
                                       "fails otherwise",
            "acceptance": "known-mode recall 100% on planted samples with tier "
                          "verified|suspicious; 0 false positives on clean; "
                          "cannot_determine samples assert honest non-detection",
        },
        "counts": {
            "clean_strategies": len(clean_strategy_results),
            "clean_data": len(CLEAN_DATA_RESULTS),
            "planted_lint": len(lint_results),
            "planted_profile": len(PROFILE_RESULTS),
            "total": len(all_samples),
            "planted_total": len(lint_results) + len(PROFILE_RESULTS),
            "planted_catchable_pure_data":
                sum(1 for s in all_samples
                    if s["expected"]["caught"]
                    and s["expected"].get("tier") in ("verified", "suspicious")),
        },
        "samples": all_samples,
    }
    (CORPUS / "expected_results.json").write_text(
        json.dumps(expected, indent=2, ensure_ascii=False), encoding="utf-8")

    verify(all_samples)
    print(f"corpus v{CORPUS_VERSION} built and verified: "
          f"{len(all_samples)} samples "
          f"(planted={expected['counts']['planted_total']})")


if __name__ == "__main__":
    main()
