"""research_kit diagnostics: honest metric family (spec v1.0 s4.5).

Underwater-days family, cost drag, time in market, worst month/year,
positive-year fraction, alpha/beta. All pure functions over the equity
rows (+ optional exposure); every metric has a hand-computed control in
the selftest.
"""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean

from equity_io import KitInputError

DD_LEVELS = (5.0, 20.0, 30.0)  # percent; asserted in selftest


def daily_returns(levels: list[float]) -> list[float]:
    rets = [b / a - 1.0 for a, b in zip(levels, levels[1:])]
    if any(not math.isfinite(r) for r in rets):
        raise KitInputError("non-finite daily return (poison guard)")
    return rets


def underwater(rows: list[dict]) -> dict:
    """For each DD level X in DD_LEVELS: total days below -X% from a
    running peak + the longest consecutive stretch (in rows/days)."""
    levels = [r["strategy_net"] for r in rows]
    peak = levels[0]
    fracs = []
    for v in levels:
        peak = max(peak, v)
        fracs.append(v / peak - 1.0)
    out = {}
    for x in DD_LEVELS:
        flags = [f < -x / 100.0 for f in fracs]
        total = sum(flags)
        longest = cur = 0
        for f in flags:
            cur = cur + 1 if f else 0
            longest = max(longest, cur)
        out[f"{x:g}%"] = {"days_below": total, "longest_stretch": longest}
    return {"underwater": out, "max_drawdown": min(fracs), "tier":
            "verified"}


def cost_drag(rows: list[dict], days: int) -> dict:
    """Annualized CAGR(gross) - CAGR(net), in percentage points."""
    g = _cagr_rows([r["strategy_gross"] for r in rows], days)
    n = _cagr_rows([r["strategy_net"] for r in rows], days)
    return {"cost_drag": g - n, "cagr_gross": g, "cagr_net": n,
            "tier": "verified"}


def _cagr_rows(levels: list[float], days: int) -> float:
    v0, v1 = levels[0], levels[-1]
    if v0 <= 0 or v1 <= 0:
        raise KitInputError("cagr needs positive equity levels")
    if days <= 0:
        raise KitInputError(f"span must be >= 1 day, got {days}")
    return (v1 / v0) ** (365.25 / days) - 1.0


def time_in_market(exposure_values: list[float]) -> dict:
    return {"time_in_market": mean(exposure_values), "tier": "verified"}


def worst_period(rows: list[dict]) -> dict:
    """Worst calendar month and year by compounded net return."""
    rets = daily_returns([r["strategy_net"] for r in rows])
    # rets[t] is the return INTO rows[t+1]['date']
    month_acc: dict[str, float] = defaultdict(lambda: 1.0)
    year_acc: dict[int, float] = defaultdict(lambda: 1.0)
    for r, ret in zip(rows[1:], rets):
        d = r["date"]
        month_acc[f"{d.year:04d}-{d.month:02d}"] *= 1.0 + ret
        year_acc[d.year] *= 1.0 + ret
    worst_month = min(month_acc.items(), key=lambda kv: kv[1])
    worst_year = min(year_acc.items(), key=lambda kv: kv[1])
    return {"worst_month": {"period": worst_month[0],
                            "return": worst_month[1] - 1.0},
            "worst_year": {"period": str(worst_year[0]),
                           "return": worst_year[1] - 1.0},
            "n_months": len(month_acc), "n_years": len(year_acc),
            "tier": "verified"}


def positive_years(rows: list[dict]) -> dict:
    rets = daily_returns([r["strategy_net"] for r in rows])
    year_acc: dict[int, float] = defaultdict(lambda: 1.0)
    for r, ret in zip(rows[1:], rets):
        year_acc[r["date"].year] *= 1.0 + ret
    years = {y: v - 1.0 for y, v in sorted(year_acc.items())}
    pos = sum(1 for v in years.values() if v > 0)
    return {"years": years, "positive_count": pos,
            "positive_fraction": pos / len(years), "tier": "verified"}


def alpha_beta(strat_rets: list[float], mkt_rets: list[float],
               ann: int) -> dict:
    """OLS of strategy daily returns on benchmark daily returns; alpha
    reported daily and annualized ((1+a)^ann - 1)."""
    if len(strat_rets) != len(mkt_rets) or len(strat_rets) < 2:
        raise KitInputError(
            f"alpha/beta need equal-length series with >= 2 points "
            f"({len(strat_rets)} vs {len(mkt_rets)})")
    ms = mean(mkt_rets)
    ss = mean(strat_rets)
    var_m = sum((m - ms) ** 2 for m in mkt_rets)
    if var_m <= 0:
        raise KitInputError(
            "zero-variance benchmark: beta undefined (fail-closed)")
    beta = sum((s - ss) * (m - ms)
               for s, m in zip(strat_rets, mkt_rets)) / var_m
    alpha_d = ss - beta * ms
    return {"beta": beta, "alpha_daily": alpha_d,
            "alpha_ann": (1.0 + alpha_d) ** ann - 1.0, "tier": "verified"}
