"""research_kit search_perm: search-over-noise harness + adapter
protocol (spec v1.0 s4.4).

The HARNESS owns fake-price generation and the best-of-N comparison.
The ADAPTER is the strategy engine's own search:
`run_search(data) -> {"cagr": float, ...}` - the repo embeds NO
strategy logic; the DM adapter lands in Phase 5.

Fake-price semantics (Gate A ruling 2026-10-06, v0.1.1): the block
shuffle permutes blocks of the RETURN series and recompounds them into
fake prices. Strategies consume returns, so the fake series must
preserve the exact return multiset and break autocorrelation - NOT the
price-level multiset (block boundaries on levels used to splice new
jumps: |return| max inflated 0.026 -> 0.048 in Cursor's probe).
Given positive finite input levels, rebuilt closes stay > 0 (1+r > 0)
and NaN-free (both asserted in selftest; return multiset conservation
is asserted to 1e-9 because recompounding reintroduces fp noise).

Known issues resolved (v0.1.2, Phase 5 wiring): real_vs_noise counts
failed trials as ">= real" (m-10, conservative side). The --blocks
option is consumed by check() through the run.json-declared adapter
(m-11).
"""
from __future__ import annotations

import random
from statistics import median

from equity_io import KitInputError


def block_shuffle(levels: list[float], block: int,
                  seed: int) -> list[float]:
    """Fake prices from `levels`: permute fixed-length blocks of the
    RETURN series (last partial block included), then recompound from
    levels[0]. Return multiset preserved (to fp recompounding error),
    price levels deliberately NOT. Same seed -> identical output."""
    if not isinstance(block, int) or isinstance(block, bool) or block < 1:
        raise KitInputError(f"block must be int >= 1, got {block!r}")
    if len(levels) < 2:
        raise KitInputError(
            "block_shuffle needs >= 2 levels to form returns")
    if any(l <= 0 for l in levels):
        raise KitInputError(
            "block_shuffle needs positive price levels")
    rets = [b / a - 1.0 for a, b in zip(levels, levels[1:])]
    blocks = [rets[i:i + block] for i in range(0, len(rets), block)]
    random.Random(seed).shuffle(blocks)
    out = [levels[0]]
    for r in (x for b in blocks for x in b):
        out.append(out[-1] * (1.0 + r))
    return out


def best_of_n(adapter, base_data: list[float], n: int, block: int,
              seed: int) -> dict:
    """Run the adapter's search on n fake datasets; return the noise
    best-of-N distribution. All trials failing = structural (fail-
    closed); individual trial errors are counted and sampled (an adapter
    that only survives easy shuffles must be visible)."""
    if n < 1:
        raise KitInputError(f"n must be >= 1, got {n}")
    results: list[float] = []
    errors: list[str] = []
    for i in range(n):
        data = block_shuffle(base_data, block, seed + i)
        try:
            res = adapter(data)
            results.append(float(res["cagr"]))
        except Exception as e:  # noqa: BLE001 - trial errors are data
            errors.append(f"trial {i}: {type(e).__name__}: {e}")
    if not results:
        raise KitInputError(
            f"all {n} search trials failed; first error: {errors[0]}")
    results.sort()
    return {"n": n, "failed_trials": len(errors),
            "error_samples": errors[:3], "dist": results,
            "noise_best": results[-1], "noise_median": median(results),
            "tier": "verified" if not errors else "cannot_determine"}


def real_vs_noise(real_cagr: float, noise: dict) -> dict:
    """p-value: fraction of noise best-of-N results >= the real search
    result. High p => the search finds 'alpha' on noise just as well.
    m-10 close-out (v0.1.2, Phase 5): FAILED trials count as
    ">= real" (the conservative side - failures inflate p, never
    deflate it), so the denominator stays n and a fragile adapter that
    only survives easy shuffles cannot look better than noise."""
    ge = sum(1 for x in noise["dist"] if x >= real_cagr)
    ge += noise.get("failed_trials", 0)
    return {"real_cagr": real_cagr, "p_value": ge / noise["n"],
            "tier": noise["tier"]}
