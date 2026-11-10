"""research_kit start_by_year: start-from-each-year sensitivity table
(spec v1.0 s4.3). Pure post-processing on equity levels only."""
from __future__ import annotations

import math
from statistics import stdev

from equity_io import KitInputError

DAYS_PER_YEAR = 365.25


def _cagr(v0: float, v1: float, days: int) -> float | None:
    if days <= 0 or v0 <= 0 or v1 <= 0:
        raise KitInputError(
            f"cagr needs positive levels and >= 1 day span (v0={v0!r}, "
            f"v1={v1!r}, days={days})")
    return (v1 / v0) ** (DAYS_PER_YEAR / days) - 1.0


def _maxdd(levels: list[float]) -> float:
    peak = levels[0]
    dd = 0.0
    for v in levels:
        peak = max(peak, v)
        dd = min(dd, v / peak - 1.0)
    return dd


def _sharpe_ann(levels: list[float], ann: int) -> float:
    rets = [b / a - 1.0 for a, b in zip(levels, levels[1:])]
    if len(rets) < 2:
        raise KitInputError("sharpe needs >= 2 daily returns")
    s = stdev(rets)
    if s <= 0:
        raise KitInputError("zero-variance returns: sharpe undefined")
    return (sum(rets) / len(rets)) / s * math.sqrt(ann)


def start_from_each_year(rows: list[dict], ann: int) -> dict:
    """rows: equity rows sorted by date with 'date' + 'strategy_net'.
    One row per distinct starting year: CAGR / MaxDD / annualized Sharpe
    from that year's first day (base = that day's level). Whole-sample
    row = the first year's start. fragile = any start with CAGR <= 0."""
    years = sorted({r["date"].year for r in rows})
    starts = []
    for y in years:
        sub = [r for r in rows if r["date"].year >= y]
        levels = [r["strategy_net"] for r in sub]
        days = (sub[-1]["date"] - sub[0]["date"]).days
        if len(sub) < 2 or days == 0:
            # single-row window: growth metrics are undefined - report
            # the window honestly instead of raising (spec s4.3)
            starts.append({"start_year": y, "days": days,
                           "n_rows": len(sub), "cagr": None,
                           "max_drawdown": 0.0, "sharpe_ann": None,
                           "fragile": False,
                           "note": "single-row window: growth metrics "
                                   "undefined"})
            continue
        cagr = _cagr(levels[0], levels[-1], days)
        starts.append({
            "start_year": y, "days": days, "n_rows": len(sub),
            "cagr": cagr, "max_drawdown": _maxdd(levels),
            "sharpe_ann": _sharpe_ann(levels, ann),
            "fragile": cagr <= 0.0,
        })
    return {"starts": starts, "fragile": any(s["fragile"] for s in starts),
            "tier": "verified"}
