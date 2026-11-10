"""research_kit timing_shuffle: re-time the exposure schedule (s4.1).

Question answered: is the strategy's CAGR better than what the SAME
run/gap schedule achieves at RANDOM alignments against the benchmark?
Method (documented, spec v1.0 s4.1):
  pseudo strategy on day t: r_t = exposure_t * benchmark_return_t
  (benchmark return realized INTO day t; exposure held on day t).
  The ORIGINAL pseudo CAGR (real alignment) is compared against the
  distribution of pseudo CAGRs where the run blocks are re-placed.
  Apples-to-apples: both sides use the identical pseudo construction.

Shuffle mechanics (conservation asserted in selftest):
  series = [g0] + run_1 + [g1] + ... + run_N + [gN]   (runs = maximal
  exposure > 0 segments). A shuffle permutes the run blocks' ORDER and
  the gap-length multiset positions. Invariants: series length, run
  count, run-length multiset, and the exact multiset of exposure values
  (permutation) are all preserved; same seed -> identical output.
"""
from __future__ import annotations

import random

from equity_io import KitInputError

DAYS_PER_YEAR = 365.25  # actual date-span CAGR, calendar-agnostic


def extract_runs(values: list[float]) -> list[tuple[int, int]]:
    """Maximal consecutive >0 segments as (start_index, length)."""
    runs: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(values):
        if v > 0 and start is None:
            start = i
        elif v <= 0 and start is not None:
            runs.append((start, i - start))
            start = None
    if start is not None:
        runs.append((start, len(values) - start))
    return runs


def shuffle_exposure(values: list[float], seed: int) -> list[float]:
    """Re-place run blocks + gap-length multiset. Exact permutation of
    the input multiset; same seed -> identical output (asserted)."""
    runs = extract_runs(values)
    if not runs:
        raise KitInputError(
            "timing shuffle needs >= 1 run (exposure > 0 segment); "
            "all-zero exposure has nothing to re-time")
    blocks = [values[s:s + ln] for s, ln in runs]
    gap_lens = []
    prev_end = 0
    for s, ln in runs:
        gap_lens.append(s - prev_end)
        prev_end = s + ln
    gap_lens.append(len(values) - prev_end)
    rng = random.Random(seed)
    rng.shuffle(blocks)
    rng.shuffle(gap_lens)
    out: list[float] = []
    for i, blk in enumerate(blocks):
        out.extend([0.0] * gap_lens[i])
        out.extend(blk)
    out.extend([0.0] * gap_lens[-1])
    return out


def pseudo_cagr(exposure: list[float], bench_rets: list[float],
                days: int) -> float:
    """CAGR of the pseudo strategy exp_t * r_t over `days` calendar days.
    Ruin (level <= 0) returns -1.0 (documented; still a valid draw)."""
    if len(exposure) != len(bench_rets):
        raise KitInputError(
            f"exposure/returns length mismatch: {len(exposure)} vs "
            f"{len(bench_rets)}")
    if days <= 0:
        raise KitInputError(f"span must be >= 1 day, got {days}")
    level = 1.0
    for e, r in zip(exposure, bench_rets):
        level *= 1.0 + e * r
    if level <= 0:
        return -1.0
    return level ** (DAYS_PER_YEAR / days) - 1.0


def luck_test(bench_rets: list[float], exposure: list[float], days: int,
              seed: int = 42, perms: int = 200) -> dict:
    """One-sided p-value: fraction of re-timed pseudo CAGRs >= the
    original alignment's pseudo CAGR. Lower p => timing skill less
    likely to be luck."""
    if perms < 1:
        raise KitInputError(f"perms must be >= 1, got {perms}")
    if not extract_runs(exposure):
        return {"tier": "cannot_run", "reason": "all-zero exposure"}
    orig = pseudo_cagr(exposure, bench_rets, days)
    dist = [pseudo_cagr(shuffle_exposure(exposure, seed + i), bench_rets,
                        days) for i in range(perms)]
    ge = sum(1 for x in dist if x >= orig)
    dist_sorted = sorted(dist)
    return {"tier": "verified", "perms": perms, "seed": seed,
            "original_pseudo_cagr": orig,
            "shuffled_cagr_dist": dist_sorted,
            "p_value": ge / perms,
            "runs": len(extract_runs(exposure))}
