"""research_kit CLI (Phase 4): check <run_folder> / selftest.

Run directly (stdlib only):
  python3 tools/research_kit/cli.py check <run_folder>
        [--seed N] [--perms N] [--blocks K]
        -> results JSON (exit 0) / structural error JSON (exit 2)
  python3 tools/research_kit/cli.py selftest
        -> built-in positive+negative controls (exit 0 all pass / 1 fail)

Exit codes: 0 = checked (individual tests may report cannot_run, which
is a RESULT, not an error); 2 = structural (guard blocks the folder /
missing required fields / broken shapes). Never a traceback.
"""
from __future__ import annotations

import json
import math
import random
import statistics
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _PKG_DIR.parent
for _p in (str(_PKG_DIR), str(_TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from equity_io import (ANN_FACTOR, KitInputError, load_run_folder,  # noqa: E402
                       guard_precheck)
import diagnostics  # noqa: E402
import haircut  # noqa: E402
import search_perm  # noqa: E402
import start_by_year  # noqa: E402
import timing_shuffle  # noqa: E402
from research_kit import RKIT_VERSION, SPEC_VERSION  # noqa: E402

REGISTRY_VERSION = "0.1.0"  # bump with any registry change


# --------------------------------------------------------------------------
# Test builders. Signature: builder(ctx, opts) -> result dict. Register a
# new test by appending to TEST_REGISTRY (spec v1.0 s1: registration).
# --------------------------------------------------------------------------

def _t_haircut(ctx: dict, opts: dict) -> dict:
    rets = diagnostics.daily_returns(
        [r["strategy_net"] for r in ctx["equity"]])
    # Gate A M-1 (v0.1.1): the optional run.json field variant_srs must
    # reach the DSR math. Missing key -> proxy inside haircut; present
    # but invalid -> KitInputError (exit 2), never a silent fallback.
    return haircut.deflated_sharpe(
        rets, ctx["run"]["tried_variants"],
        variant_srs=ctx["run"].get("variant_srs"))


def _t_timing_shuffle(ctx: dict, opts: dict) -> dict:
    if ctx["exposure"] is None:
        return {"tier": "cannot_run",
                "reason": f"no daily exposure series available "
                          f"(source: {ctx['exposure_source']}); provide "
                          f"exposure.csv for a verified timing shuffle"}
    equity = ctx["equity"]
    bench_rets = diagnostics.daily_returns(
        [r["benchmark"] for r in equity])
    exposure = [r["exposure"] for r in ctx["exposure"]][1:]  # align to rets
    days = (equity[-1]["date"] - equity[0]["date"]).days
    out = timing_shuffle.luck_test(bench_rets, exposure, days,
                                   seed=opts["seed"], perms=opts["perms"])
    # Gate A m-2 (v0.1.1): the strategy's real calendar net CAGR sits
    # next to the pseudo CAGR (same luck_test payload; key
    # original_pseudo_cagr unchanged). Both sides of the p-value stay
    # pseudo-constructed; this key is for reading, not the p-value.
    out["strategy_net_cagr"] = (
        equity[-1]["strategy_net"] / equity[0]["strategy_net"]
    ) ** (timing_shuffle.DAYS_PER_YEAR / days) - 1.0
    return out


def _t_start_by_year(ctx: dict, opts: dict) -> dict:
    ann = ANN_FACTOR[ctx["run"]["calendar"]]
    return start_by_year.start_from_each_year(ctx["equity"], ann)


def _load_search_adapter(decl) -> object:
    """m-11 (v0.1.2): load the strategy engine's own run_search module,
    declared in run.json `search_adapter` (path string or {"path": ...}).
    Relative paths resolve against CWD (repo root when run from there).
    The repo embeds no strategy - the adapter is external code by design
    (spec v1.0 s4.4); load/protocol failures are structural (exit 2)."""
    import importlib.util
    path = decl if isinstance(decl, str) else decl["path"]
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = _TOOLS_DIR.parent / path  # repo root fallback
    if not p.is_file():
        raise KitInputError(f"search_adapter module not found: {path!r}")
    spec = importlib.util.spec_from_file_location("rk_search_adapter", p)
    if spec is None or spec.loader is None:
        raise KitInputError(f"search_adapter not importable: {path!r}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, "run_search", None)):
        raise KitInputError(
            f"search_adapter {path!r} exposes no callable run_search")
    return mod


def _t_search_perm(ctx: dict, opts: dict) -> dict:
    decl = ctx["run"].get("search_adapter")
    if not decl:
        return {"tier": "cannot_run",
                "reason": "no search adapter declared in run.json "
                          "(search_adapter key); declare the strategy "
                          "engine's run_search module to run the "
                          "best-of-N permutation test (spec v1.0 s4.4)"}
    mod = _load_search_adapter(decl)
    base = [r["benchmark"] for r in ctx["equity"]]  # real price series
    real = mod.run_search(base)
    real_cagr = float(real["cagr"])  # non-numeric -> TypeError -> exit 2
    noise = search_perm.best_of_n(mod.run_search, base, opts["perms"],
                                  opts["blocks"], opts["seed"])
    rvn = search_perm.real_vs_noise(real_cagr, noise)
    return {"tier": rvn["tier"], "real_cagr": real_cagr,
            "real_params": real.get("params"),
            "noise_n": noise["n"],
            "noise_failed_trials": noise["failed_trials"],
            "noise_best": noise["noise_best"],
            "noise_median": noise["noise_median"],
            "p_value": rvn["p_value"],
            "blocks": opts["blocks"], "seed": opts["seed"],
            "adapter": (decl if isinstance(decl, str)
                        else decl.get("path"))}


def _t_diagnostics(ctx: dict, opts: dict) -> dict:
    equity = ctx["equity"]
    ann = ANN_FACTOR[ctx["run"]["calendar"]]
    days = (equity[-1]["date"] - equity[0]["date"]).days
    out: dict = {}
    out["underwater_family"] = diagnostics.underwater(equity)
    out["cost_drag"] = diagnostics.cost_drag(equity, days)
    out["worst_period"] = diagnostics.worst_period(equity)
    out["positive_years"] = diagnostics.positive_years(equity)
    strat_rets = diagnostics.daily_returns(
        [r["strategy_net"] for r in equity])
    mkt_rets = diagnostics.daily_returns([r["benchmark"] for r in equity])
    out["alpha_beta"] = diagnostics.alpha_beta(strat_rets, mkt_rets, ann)
    if ctx["exposure"] is not None:
        out["time_in_market"] = diagnostics.time_in_market(
            [r["exposure"] for r in ctx["exposure"]])
    else:
        out["time_in_market"] = {"tier": "cannot_run",
                                 "reason": "no daily exposure series "
                                           f"(source: "
                                           f"{ctx['exposure_source']})"}
    return {"metrics": out, "tier": "verified"}


TEST_REGISTRY = [
    ("multiple_tries_haircut", _t_haircut),
    ("timing_shuffle", _t_timing_shuffle),
    ("start_from_each_year", _t_start_by_year),
    ("search_permutation", _t_search_perm),
    ("diagnostics", _t_diagnostics),
]


def _validate_opts(seed: int, perms: int, blocks: int) -> None:
    """Gate A m-3 (v0.1.1): opts are validated at the check() entry -
    an invalid --perms/--seed/--blocks must exit 2 even when the test
    that consumes it would report cannot_run (no silent -3)."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise KitInputError(f"seed must be an integer, got {seed!r}")
    for name, v in (("perms", perms), ("blocks", blocks)):
        if isinstance(v, bool) or not isinstance(v, int):
            raise KitInputError(f"{name} must be an integer, got {v!r}")
        if v < 1:
            raise KitInputError(f"{name} must be >= 1, got {v!r}")


def check(folder: Path, seed: int = 42, perms: int = 200,
          blocks: int = 20) -> tuple[dict, int]:
    _validate_opts(seed, perms, blocks)    # m-3: before any folder I/O
    guard_precheck(folder)                 # m-7: guard first - a blocked
    ctx = load_run_folder(folder)          # folder is refused before its
    # equity/exposure tables get parsed (KitInputError -> exit 2)
    opts = {"seed": seed, "perms": perms, "blocks": blocks}
    results = {}
    for name, builder in TEST_REGISTRY:
        results[name] = builder(ctx, opts)
    cannot = sorted(n for n, r in results.items()
                    if isinstance(r, dict) and r.get("tier") == "cannot_run")
    payload = {
        "tool": "research_kit", "version": RKIT_VERSION,
        "spec_version": SPEC_VERSION, "registry_version": REGISTRY_VERSION,
        "command": "check", "run_folder": str(folder),
        "calendar": ctx["run"]["calendar"],
        "benchmark": ctx["run"]["benchmark"],
        "tried_variants": ctx["run"]["tried_variants"],
        "exposure_source": ctx["exposure_source"],
        "opts": opts, "results": results,
        "cannot_run_tests": cannot,
        "status": "checked",
    }
    return payload, 0


# --------------------------------------------------------------------------
# Selftest: positive + negative controls, temp fixtures (declaration ==
# assertion). Same style as holdout_guard.
# --------------------------------------------------------------------------

def _mk_run(folder: Path, run: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.json").write_text(json.dumps(run, ensure_ascii=False,
                                                indent=2), encoding="utf-8")


def _mk_equity(folder: Path, rows: list[tuple[str, float, float, float]],
               header: str = "date,strategy_net,strategy_gross,benchmark") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    lines = [header] + [f"{d},{a},{b},{c}" for d, a, b, c in rows]
    (folder / "equity.csv").write_text("\n".join(lines) + "\n",
                                       encoding="utf-8")


def _mk_exposure(folder: Path, values: list[float],
                 dates: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["date,exposure"] + [f"{d},{v}" for d, v in zip(dates, values)]
    (folder / "exposure.csv").write_text("\n".join(lines) + "\n",
                                         encoding="utf-8")


def _base_run(**over) -> dict:
    run = {"calendar": "crypto", "benchmark": "ASSET-BUY-HOLD",
           "period": {"start": "2024-01-01", "end": "2025-12-31"},
           "data_source": "fixture", "costs": {"taker_bps": 10},
           "tried_variants": 13, "holdout": None}
    run.update(over)
    return run


def _demo_rows(n: int = 400, seed: int = 7):
    """Synthetic 400-day up-drifting folder; deterministic."""
    rng = random.Random(seed)
    d0 = date(2024, 1, 1)
    rows, expo = [], []
    bench = net = gross = 1.0
    for i in range(n):
        d = (d0 + timedelta(days=i)).isoformat()
        br = rng.gauss(0.0004, 0.01)
        nr = 1.2 * br + rng.gauss(0.0003, 0.002)
        gr = nr + 0.0002
        bench *= 1.0 + br
        net *= 1.0 + nr
        gross *= 1.0 + gr
        rows.append((d, round(net, 8), round(gross, 8), round(bench, 8)))
        expo.append(1.0 if (i // 15) % 2 == 0 else 0.0)
    return rows, expo


def _expect(cond: bool, msg: str, failures: list[str]) -> None:
    if not cond:
        failures.append(msg)


def run_selftest() -> tuple[dict, int]:
    failures: list[str] = []
    n = 0
    tool_path = Path(__file__).resolve()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # -- constants ----------------------------------------------------
        n += 1
        _expect(RKIT_VERSION == "0.1.2" and SPEC_VERSION == "1.0",
                "version constants deviate", failures)
        n += 1
        _expect(haircut.DSR_THRESHOLD == 0.95
                and diagnostics.DD_LEVELS == (5.0, 20.0, 30.0)
                and ANN_FACTOR == {"crypto": 365, "tradfi": 252},
                "declared constants deviate", failures)

        # -- haircut: math controls ---------------------------------------
        alt = [0.001, -0.001] * 250
        nn, sr, g3, g4 = haircut.sharpe_ratio(alt)
        n += 1
        _expect(nn == 500 and sr == 0.0 and g3 == 0.0
                and 0.99 < g4 < 1.01,
                "symmetric two-point series: sr=0, g3=0, g4~1", failures)
        n += 1
        _expect(abs(g4 - 1.0) < 1e-12,
                "m-9 moment control: two-point symmetric series must "
                "give the exact population moment g4 == 1.0", failures)
        n += 1
        _expect(abs(haircut.deflated_sharpe(alt, 1)["dsr"] - 0.5) < 1e-12,
                "K=1 with SR=0 must give DSR=Phi(0)=0.5 exactly", failures)
        # deterministic moderate-SR series: sr ~ 0.3, g3 = 0, g4 ~ 0.98
        det_rets = [0.0006 + (0.002 if i % 2 == 0 else -0.002)
                    for i in range(100)]
        d1 = haircut.deflated_sharpe(det_rets, 1)
        d5 = haircut.deflated_sharpe(det_rets, 5)
        d13 = haircut.deflated_sharpe(det_rets, 13)
        n += 1
        _expect(d1["sr0"] == 0.0 and d1["verdict"] == "pass"
                and d1["dsr"] > 0.99,
                "K=1 must degenerate to PSR and pass on sr~0.3", failures)
        n += 1
        _expect(d1["dsr"] > d5["dsr"] > d13["dsr"],
                "DSR must be strictly decreasing in K (selection burden)",
                failures)
        n += 1
        _expect(d13["verdict"] == "haircut_fails",
                "narrative control: sr~0.3 with K=13 must FAIL the 95% "
                f"haircut (dsr={d13['dsr']!r})", failures)
        n += 1
        _expect(d13["sr_variance_source"] == "sr_estimator_proxy",
                "proxy variance source must be reported", failures)
        d13v = haircut.deflated_sharpe(det_rets, 13,
                                       variant_srs=[0.5, 1.5])
        n += 1
        _expect(d13v["sr_variance_source"] == "variant_srs"
                and abs(d13v["sr0"] - haircut.sr0_for(
                    13, haircut.variance([0.5, 1.5]))) < 1e-15,
                "variant_srs wiring must hit sr0_for with sample variance",
                failures)
        # M-1: invalid variant_srs must raise (never silent proxy fallback)
        for bad_vs in ([0.5], ["x", 0.5], [0.5, True], [0.5, float("nan")],
                       {"a": 1}, "0.5,0.6"):
            n += 1
            try:
                haircut.deflated_sharpe(det_rets, 13, variant_srs=bad_vs)
                _expect(False,
                        f"variant_srs {bad_vs!r} must raise (no silent "
                        f"proxy fallback)", failures)
            except KitInputError:
                pass
        strong = [0.01 + (0.001 if i % 2 == 0 else -0.001)
                  for i in range(100)]
        n += 1
        _expect(haircut.deflated_sharpe(strong, 13)["dsr"] > 0.9999,
                "huge SR must survive a K=13 haircut (dsr ~ 1)", failures)
        # direct formula recomputation (wiring control, uses real g3/g4)
        _nn, _sr, _g3, _g4 = haircut.sharpe_ratio(det_rets)
        recompute = haircut.ND.cdf(
            (d1["sr"] - d1["sr0"]) * math.sqrt(d1["n"] - 1)
            / math.sqrt(1.0 - _g3 * d1["sr"]
                        + ((_g4 - 1.0) / 4.0) * d1["sr"] ** 2))
        n += 1
        _expect(abs(d1["dsr"] - recompute) < 1e-12,
                "DSR must equal direct formula recomputation", failures)
        for bad in (0, -3, 1.5, "x", True):
            n += 1
            try:
                haircut.deflated_sharpe(det_rets, bad)
                _expect(False, f"tried_variants {bad!r} must raise",
                        failures)
            except KitInputError:
                pass

        # -- timing shuffle: conservation ---------------------------------
        vals = [0.0, 1.0, 2.0, 0.0, 0.0, 3.0, 4.0, 0.0]
        n += 1
        _expect(timing_shuffle.extract_runs(vals) == [(1, 2), (5, 2)],
                "extract_runs must find maximal >0 segments", failures)
        shuf_fixture = [0.0, 1.0, 2.0, 0.0, 0.0, 3.0, 4.0, 5.0, 6.0, 0.0]
        s1 = timing_shuffle.shuffle_exposure(shuf_fixture, 1)
        s1b = timing_shuffle.shuffle_exposure(shuf_fixture, 1)
        s4 = timing_shuffle.shuffle_exposure(shuf_fixture, 4)
        n += 1
        _expect(s1 == s1b, "same seed must reproduce exactly", failures)
        n += 1
        _expect(len(s1) == len(shuf_fixture)
                and sorted(s1) == sorted(shuf_fixture),
                "shuffle must preserve length + exact value multiset",
                failures)
        n += 1
        _expect(timing_shuffle.extract_runs(s1) is not None
                and len(timing_shuffle.extract_runs(s1)) == 2,
                "shuffle must preserve run count", failures)
        n += 1
        _expect(sorted(ln for _, ln in timing_shuffle.extract_runs(s1))
                == sorted(ln for _, ln in
                          timing_shuffle.extract_runs(shuf_fixture)),
                "m-6: shuffle must preserve the run-LENGTH multiset",
                failures)
        n += 1
        _expect(s4 != s1, "seeds 1 vs 4 must differ (deterministic "
                          "fixture, probed)", failures)
        rets = [0.01, -0.02, 0.005, 0.03, -0.01, 0.02, -0.005, 0.01, 0.015]
        lt = timing_shuffle.luck_test(rets, [1.0, 1.0, 0.0, 0.0, 1.0, 0.0,
                                             1.0, 1.0, 1.0], 365,
                                      seed=5, perms=50)
        n += 1
        _expect(lt["tier"] == "verified" and 0.0 <= lt["p_value"] <= 1.0
                and len(lt["shuffled_cagr_dist"]) == 50,
                "luck_test must return a bounded p-value with perms draws",
                failures)
        pc = timing_shuffle.pseudo_cagr([1.0, 1.0], [0.1, 0.1], 365)
        n += 1
        _expect(abs(pc - (1.21 ** (365.25 / 365) - 1.0)) < 1e-12,
                f"m-5: pseudo_cagr hand control 1.21^(365.25/365)-1 "
                f"at 1e-12, got {pc}", failures)
        n += 1
        _expect(timing_shuffle.luck_test(rets, [0.0] * 9, 365)["tier"]
                == "cannot_run",
                "all-zero exposure must be reported cannot_run", failures)
        n += 1
        try:
            timing_shuffle.pseudo_cagr([1.0], [0.1, 0.1], 365)
            _expect(False, "length mismatch must raise", failures)
        except KitInputError:
            pass

        # -- start_by_year -------------------------------------------------
        rows3 = ([("2024-01-01", 1.0, 1.0, 1.0)]
                 + [(f"2024-{m:02d}-15", 1.0 + 0.01 * k, 1.0, 1.0)
                    for k, m in enumerate(range(2, 13))]
                 + [(f"2025-{m:02d}-15", 1.1 - 0.02 * k, 1.0, 1.0)
                    for k, m in enumerate(range(1, 13))]
                 + [("2026-01-15", 0.8, 1.0, 1.0)])
        rows3 = [(d, a, b, c) for d, a, b, c in rows3]
        _mk_equity(root / "sby", rows3)
        sby = start_by_year.start_from_each_year(
            _load_rows(root / "sby"), 365)
        n += 1
        _expect([s["start_year"] for s in sby["starts"]] == [2024, 2025,
                                                             2026]
                and sby["fragile"] is True,
                "declining later years must flag fragile", failures)
        n += 1
        _expect(sby["starts"][0]["n_rows"] == len(rows3)
                and sby["starts"][-1]["n_rows"] == 1
                and sby["starts"][-1]["cagr"] is None,
                "first-year start covers the whole sample; single-row "
                "last year is honestly reported", failures)
        n += 1
        _expect(abs(sby["starts"][0]["max_drawdown"] - (0.8 / 1.1 - 1.0))
                < 1e-9,
                "maxdd hand control on the declining fixture", failures)
        n += 1
        try:
            start_by_year.start_from_each_year(
                [{"date": date(2024, 1, 1), "strategy_net": 1.0},
                 {"date": date(2024, 6, 1), "strategy_net": 0.0}], 365)
            _expect(False, "non-positive level must raise", failures)
        except KitInputError:
            pass

        # -- search_perm (v0.1.1: shuffles RETURNS, recompounds prices) ---
        base = [float(i % 7) + 1.0 for i in range(100)]
        bs = search_perm.block_shuffle(base, 20, 3)
        n += 1
        _expect(len(bs) == len(base) and bs[0] == base[0],
                "fake prices must keep series length and the first level",
                failures)
        n += 1
        _expect(all(x > 0 for x in bs),
                "fake prices must stay positive (1+r > 0 recompounding)",
                failures)
        rets_in = sorted(b / a - 1.0 for a, b in zip(base, base[1:]))
        rets_out = sorted(b / a - 1.0 for a, b in zip(bs, bs[1:]))
        n += 1
        _expect(len(rets_in) == len(rets_out)
                and all(abs(a - b) < 1e-9
                        for a, b in zip(rets_in, rets_out)),
                "m-1: block shuffle must conserve the RETURN multiset "
                "(1e-9 fp recompounding tolerance)", failures)
        n += 1
        _expect(search_perm.block_shuffle(base, 20, 3) == bs,
                "block shuffle same seed reproducible", failures)
        n += 1
        _expect(bs != base,
                "shuffled fake prices must differ from the input levels "
                "(deterministic fixture, probed)", failures)
        noop = lambda data: {"cagr": 0.42}  # noqa: E731
        bon = search_perm.best_of_n(noop, base, 10, 20, 5)
        n += 1
        _expect(bon["failed_trials"] == 0 and bon["noise_best"] == 0.42
                and bon["noise_median"] == 0.42,
                "no-op adapter must give a degenerate constant dist",
                failures)
        n += 1
        _expect(search_perm.real_vs_noise(0.1, bon)["p_value"] == 1.0
                and search_perm.real_vs_noise(0.9, bon)["p_value"] == 0.0,
                "real_vs_noise p-value edges", failures)

        def boom(data):
            raise RuntimeError("nope")
        n += 1
        try:
            search_perm.best_of_n(boom, base, 5, 20, 1)
            _expect(False, "all-fail adapter must raise", failures)
        except KitInputError:
            pass
        n += 1
        try:
            search_perm.block_shuffle(base, 0, 1)
            _expect(False, "block<1 must raise", failures)
        except KitInputError:
            pass
        n += 1
        try:
            search_perm.block_shuffle([1.0], 20, 1)
            _expect(False, "single level (no returns) must raise",
                    failures)
        except KitInputError:
            pass
        n += 1
        try:
            search_perm.block_shuffle([1.0, 0.0, 2.0], 20, 1)
            _expect(False, "non-positive price level must raise",
                    failures)
        except KitInputError:
            pass

        # -- diagnostics: hand controls -------------------------------------
        dl = [1.00, 1.10, 0.99, 1.05, 0.90, 1.06]
        drows = [{"date": date(2024, 1, 1 + i), "strategy_net": v}
                 for i, v in enumerate(dl)]
        uw = diagnostics.underwater(drows)
        n += 1
        _expect(abs(uw["max_drawdown"] - (0.9 / 1.1 - 1.0)) < 1e-9
                and uw["underwater"]["5%"]["days_below"] == 2
                and uw["underwater"]["5%"]["longest_stretch"] == 1
                and uw["underwater"]["20%"]["days_below"] == 0
                and uw["underwater"]["30%"]["days_below"] == 0,
                f"underwater hand control, got {uw}", failures)
        n += 1
        _expect(diagnostics.time_in_market([0.0, 0.5, 1.0])
                ["time_in_market"] == 0.5,
                "time_in_market mean control", failures)
        n += 1
        try:
            diagnostics.alpha_beta([0.0, 0.0], [0.1, 0.1], 365)
            _expect(False, "zero-variance benchmark must raise", failures)
        except KitInputError:
            pass
        # alpha/beta exact linear control
        mkt = [0.01, -0.02, 0.03, 0.00, -0.01, 0.02, 0.04, -0.03]
        strat = [2.0 * m + 0.01 for m in mkt]
        ab = diagnostics.alpha_beta(strat, mkt, 365)
        n += 1
        _expect(abs(ab["beta"] - 2.0) < 1e-12
                and abs(ab["alpha_daily"] - 0.01) < 1e-12,
                f"beta=2/alpha=0.01 exact control, got {ab}", failures)

        # m-6: cost_drag / worst_period / positive_years hand controls
        k = 365.25 / 365
        cdrag_rows = [
            {"date": date(2024, 1, 1), "strategy_net": 1.0,
             "strategy_gross": 1.0},
            {"date": date(2024, 12, 31), "strategy_net": 1.1,
             "strategy_gross": 1.2},
        ]
        cd = diagnostics.cost_drag(cdrag_rows, 365)
        exp_g = 1.2 ** k - 1.0
        exp_n = 1.1 ** k - 1.0
        n += 1
        _expect(abs(cd["cagr_gross"] - exp_g) < 1e-12
                and abs(cd["cagr_net"] - exp_n) < 1e-12
                and abs(cd["cost_drag"] - (exp_g - exp_n)) < 1e-12,
                f"m-6: cost_drag hand control, got {cd}", failures)
        # 1.0 -> 1.1 -> 0.99 with the drop booked into 12-31:
        # Nov +0.1, Dec -0.1, year 2024 = 1.1*0.9 - 1 = -0.01
        wp_rows = [
            {"date": date(2024, 1, 31), "strategy_net": 1.0},
            {"date": date(2024, 11, 30), "strategy_net": 1.1},
            {"date": date(2024, 12, 31), "strategy_net": 0.99},
        ]
        wp = diagnostics.worst_period(wp_rows)
        n += 1
        _expect(wp["worst_month"]["period"] == "2024-12"
                and abs(wp["worst_month"]["return"] - (-0.1)) < 1e-9
                and wp["worst_year"]["period"] == "2024"
                and abs(wp["worst_year"]["return"] - (-0.01)) < 1e-9
                and wp["n_months"] == 2 and wp["n_years"] == 1,
                f"m-6: worst_period hand control (Nov +0.1 / Dec -0.1 / "
                f"2024 -0.01), got {wp}", failures)
        py = diagnostics.positive_years(wp_rows)
        n += 1
        _expect(abs(py["years"][2024] - (-0.01)) < 1e-9
                and py["positive_count"] == 0
                and py["positive_fraction"] == 0.0,
                f"m-6: single losing year must give positive_fraction=0 "
                f"(1.0->1.1->0.99 = -0.01), got {py}", failures)

        n += 1
        _expect(search_perm.real_vs_noise(
            0.5, {"n": 10, "dist": [0.0] * 8, "failed_trials": 2,
                  "tier": "cannot_determine"})["p_value"] == 0.2,
            "m-10: failed trials must count as '>= real' (conservative p)",
            failures)

        # -- loader + CLI (subprocess, full chain) ---------------------------
        demo = root / "demo"
        rows, expo = _demo_rows()
        dates = [r[0] for r in rows]
        _mk_run(demo, _base_run())
        _mk_equity(demo, rows)
        _mk_exposure(demo, expo, dates)
        p, code = check(demo, seed=42, perms=30)
        n += 1
        _expect(code == 0 and p["status"] == "checked"
                and set(p["results"]) == {
                    "multiple_tries_haircut", "timing_shuffle",
                    "start_from_each_year", "search_permutation",
                    "diagnostics"},
                f"check on demo folder must run the full registry, "
                f"got {p.get('cannot_run_tests')}", failures)
        n += 1
        _expect(p["results"]["multiple_tries_haircut"]["tier"] == "verified"
                and p["results"]["timing_shuffle"]["tier"] == "verified"
                and p["results"]["start_from_each_year"]["tier"] == "verified"
                and p["results"]["search_permutation"]["tier"] == "cannot_run"
                and p["results"]["diagnostics"]["tier"] == "verified",
                f"demo tier map, got "
                f"{ {k: v.get('tier') for k, v in p['results'].items()} }",
                failures)
        n += 1
        _expect(p["cannot_run_tests"] == ["search_permutation"],
                "only search_permutation may be cannot_run on the demo",
                failures)
        n += 1
        _expect(p["results"]["diagnostics"]["metrics"]["time_in_market"]
                ["tier"] == "verified",
                "demo has exposure -> time_in_market verified", failures)
        # m-2: real net calendar CAGR sits next to the pseudo CAGR
        days_demo = (date.fromisoformat(rows[-1][0])
                     - date.fromisoformat(rows[0][0])).days
        exp_net = (rows[-1][1] / rows[0][1]) ** (
            timing_shuffle.DAYS_PER_YEAR / days_demo) - 1.0
        n += 1
        _expect(abs(p["results"]["timing_shuffle"]["strategy_net_cagr"]
                    - exp_net) < 1e-12
                and "original_pseudo_cagr"
                in p["results"]["timing_shuffle"],
                f"m-2: timing payload must carry strategy_net_cagr "
                f"({exp_net:.6f}) beside original_pseudo_cagr", failures)

        # M-1: run.json variant_srs must reach the DSR through check()
        f_vs = root / "variant-srs"
        _mk_run(f_vs, _base_run(variant_srs=[0.05, 0.8, -0.2, 0.4]))
        _mk_equity(f_vs, rows[:120])
        p_vs, code_vs = check(f_vs, perms=5)
        n += 1
        _expect(code_vs == 0
                and p_vs["results"]["multiple_tries_haircut"]
                ["sr_variance_source"] == "variant_srs",
                "M-1: check() must consume run.json variant_srs "
                "(sr_variance_source == variant_srs)", failures)
        n += 1
        exp_sr0 = haircut.sr0_for(
            13, statistics.variance([0.05, 0.8, -0.2, 0.4]))
        _expect(abs(p_vs["results"]["multiple_tries_haircut"]["sr0"]
                    - exp_sr0) < 1e-12,
                "M-1: sr0 must equal sr0_for(K, statistics.variance("
                "variant_srs)) at 1e-12", failures)
        # M-1: variant_srs present but invalid -> exit 2, no fallback
        for tag, bad in (("single", [0.4]), ("string", "0.4,0.5"),
                         ("bool", [0.4, True]),
                         ("nan", [0.4, float("nan")]),
                         ("notlist", {"a": 1})):
            f_bv = root / f"bad-variant-{tag}"
            _mk_run(f_bv, _base_run(variant_srs=bad))
            _mk_equity(f_bv, rows[:50])
            n += 1
            try:
                check(f_bv)
                _expect(False, f"invalid variant_srs ({tag}) must raise",
                        failures)
            except KitInputError:
                pass
        # round-24 residual: key present but null is ambiguous -> exit 2
        f_null = root / "null-variant"
        _mk_run(f_null, _base_run(variant_srs=None))
        _mk_equity(f_null, rows[:50])
        n += 1
        try:
            check(f_null)
            _expect(False, "variant_srs null (key present) must raise "
                           "(round-24 residual)", failures)
        except KitInputError:
            pass

        # -- search_permutation adapter wiring (m-11, v0.1.2) ---------------
        adapter_file = root / "fixture_adapter.py"
        adapter_file.write_text(
            "def run_search(data):\n"
            "    return {'cagr': data[-1] / data[0] - 1.0,\n"
            "            'params': {'kind': 'fixture_bh'}}\n",
            encoding="utf-8")
        f_sa = root / "with-adapter"
        _mk_run(f_sa, _base_run(search_adapter=str(adapter_file)))
        _mk_equity(f_sa, rows[:120])
        p_sa, code_sa = check(f_sa, perms=8, blocks=5)
        n += 1
        _expect(code_sa == 0
                and p_sa["results"]["search_permutation"]["tier"]
                in ("verified", "cannot_determine")
                and 0.0 <= p_sa["results"]["search_permutation"]
                ["p_value"] <= 1.0
                and p_sa["results"]["search_permutation"]["noise_n"] == 8
                and p_sa["results"]["search_permutation"]["blocks"] == 5,
                "m-11: declared adapter must run the permutation test "
                "through check() with --blocks consumed", failures)
        n += 1
        _expect(p_sa["results"]["search_permutation"]["real_cagr"]
                > -1.0 and "real_params"
                in p_sa["results"]["search_permutation"],
                "adapter real side must return cagr + params through "
                "check()", failures)
        f_bada = root / "bad-adapter"
        _mk_run(f_bada, _base_run(search_adapter=str(root / "nope.py")))
        _mk_equity(f_bada, rows[:50])
        n += 1
        try:
            check(f_bada)
            _expect(False, "missing adapter module must raise", failures)
        except KitInputError:
            pass
        bad2 = root / "bad_adapter.py"
        bad2.write_text("GRID = [1]\n", encoding="utf-8")
        f_bada2 = root / "bad-adapter-2"
        _mk_run(f_bada2, _base_run(search_adapter=str(bad2)))
        _mk_equity(f_bada2, rows[:50])
        n += 1
        try:
            check(f_bada2)
            _expect(False, "adapter without callable run_search must "
                           "raise", failures)
        except KitInputError:
            pass

        # missing required field -> exit 2
        for field in ("benchmark", "period", "data_source", "costs",
                      "tried_variants"):
            f_bad = root / f"missing-{field}"
            run_bad = _base_run()
            del run_bad[field]
            _mk_run(f_bad, run_bad)
            _mk_equity(f_bad, rows[:50])
            n += 1
            try:
                check(f_bad)
                _expect(False, f"missing {field} must raise", failures)
            except KitInputError:
                pass
        n += 1
        try:
            check(demo.parent / "demo-x")  # no run.json at all
            _expect(False, "missing run.json must raise", failures)
        except KitInputError:
            pass

        # trades.csv without exposure -> timing cannot_run, others run
        f_tr = root / "trades-only"
        _mk_run(f_tr, _base_run())
        _mk_equity(f_tr, rows[:60])
        (f_tr / "trades.csv").write_text(
            "instrument,side,entry_time,exit_time,net_return\n"
            "ASSET,long,2024-01-01,2024-02-01,0.05\n", encoding="utf-8")
        p2, code2 = check(f_tr, perms=10)
        n += 1
        _expect(code2 == 0
                and p2["results"]["timing_shuffle"]["tier"] == "cannot_run"
                and p2["exposure_source"].startswith("trades.csv")
                and p2["results"]["multiple_tries_haircut"]["tier"]
                == "verified",
                "trades.csv folder: timing cannot_run, rest still run",
                failures)

        # neither exposure nor trades -> same shape, different reason
        f_ne = root / "no-exposure"
        _mk_run(f_ne, _base_run())
        _mk_equity(f_ne, rows[:60])
        p3, _ = check(f_ne, perms=10)
        n += 1
        _expect(p3["results"]["timing_shuffle"]["tier"] == "cannot_run"
                and p3["exposure_source"] == "none",
                "no exposure source at all -> cannot_run", failures)
        # m-3: invalid opts must exit 2 even when timing would cannot_run
        n += 1
        try:
            check(f_ne, perms=-3)
            _expect(False, "perms=-3 must raise at the check() entry "
                           "even with no exposure (m-3)", failures)
        except KitInputError:
            pass
        n += 1
        try:
            check(f_ne, blocks=0)
            _expect(False, "blocks=0 must raise at the check() entry "
                           "(m-3)", failures)
        except KitInputError:
            pass

        # guard interplay: blocked folder -> exit 2 via precheck
        f_blk = root / "guard-blocked"
        _mk_run(f_blk, _base_run(holdout={"start": "2024-06-01"}))
        _mk_equity(f_blk, rows)
        _mk_exposure(f_blk, expo, dates)
        n += 1
        try:
            check(f_blk)
            _expect(False, "guard-blocked folder must be refused", failures)
        except KitInputError:
            pass
        f_struct = root / "guard-struct"
        _mk_run(f_struct, _base_run(holdout={"start": "2099-01-01",
                                              "coins": ["AAA"]}))
        _mk_equity(f_struct, rows)
        n += 1
        try:
            check(f_struct)
            _expect(False, "guard structural error must surface as "
                           "KitInputError", failures)
        except KitInputError:
            pass

        # broken equity shapes -> exit 2
        for tag, content in (
            ("nonfinite", "date,strategy_net,strategy_gross,benchmark\n"
                          "2024-01-01,1.0,1.0,1.0\n"
                          "2024-01-02,nan,1.0,1.0\n"),
            ("dupcol", "date,strategy_net,strategy_net,benchmark\n"
                       "2024-01-01,1.0,1.0,1.0\n"
                       "2024-01-02,1.1,1.1,1.1\n"),
            ("ragged", "date,strategy_net,strategy_gross,benchmark\n"
                       "2024-01-01,1.0,1.0\n"
                       "2024-01-02,1.1,1.1,1.1\n"),
            ("zerolevel", "date,strategy_net,strategy_gross,benchmark\n"
                          "2024-01-01,1.0,1.0,1.0\n"
                          "2024-01-02,0.0,1.1,1.1\n"),
        ):
            f_b = root / f"broken-{tag}"
            _mk_run(f_b, _base_run())
            (f_b / "equity.csv").write_text(content, encoding="utf-8")
            n += 1
            try:
                check(f_b)
                _expect(False, f"broken equity ({tag}) must raise",
                        failures)
            except KitInputError:
                pass

        # exposure date mismatch + out-of-range
        f_mm = root / "expo-mismatch"
        _mk_run(f_mm, _base_run())
        _mk_equity(f_mm, rows[:60])
        _mk_exposure(f_mm, expo[:59], dates[:59])
        n += 1
        try:
            check(f_mm)
            _expect(False, "exposure date mismatch must raise", failures)
        except KitInputError:
            pass
        f_oor = root / "expo-oor"
        _mk_run(f_oor, _base_run())
        _mk_equity(f_oor, rows[:60])
        bad_expo = expo[:60]
        bad_expo[3] = 1.5
        _mk_exposure(f_oor, bad_expo, dates[:60])
        n += 1
        try:
            check(f_oor)
            _expect(False, "exposure outside [0,1] must raise", failures)
        except KitInputError:
            pass

        # CLI subprocess: exit codes + no-traceback + --help (m-3 style)
        proc = subprocess.run(
            [sys.executable, str(tool_path), "check", str(demo),
             "--perms", "20"], capture_output=True, text=True)
        n += 1
        _expect(proc.returncode == 0 and '"status": "checked"'
                in proc.stdout and "Traceback" not in proc.stderr,
                f"CLI check on demo must exit 0, rc={proc.returncode}",
                failures)
        proc = subprocess.run(
            [sys.executable, str(tool_path), "check", str(f_blk)],
            capture_output=True, text=True)
        n += 1
        _expect(proc.returncode == 2 and '"error"' in proc.stdout
                and "Traceback" not in proc.stderr,
                "CLI check on guard-blocked folder must exit 2 with error "
                "JSON, no traceback", failures)
        proc = subprocess.run(
            [sys.executable, str(tool_path), "--help"],
            capture_output=True, text=True)
        n += 1
        _expect(proc.returncode == 0 and "usage:" in proc.stdout
                and '"error"' not in proc.stdout,
                "--help must exit 0 with usage, no error envelope",
                failures)
        proc = subprocess.run(
            [sys.executable, str(tool_path), "check", str(demo),
             "--perms", "foo"], capture_output=True, text=True)
        n += 1
        _expect(proc.returncode == 2 and '"error"' in proc.stdout
                and "Traceback" not in proc.stderr,
                "argparse usage error must carry the exit-2 envelope",
                failures)
        # m-3 / Gate A reverify item 4: no exposure + --perms -3 -> exit 2
        proc = subprocess.run(
            [sys.executable, str(tool_path), "check", str(f_ne),
             "--perms", "-3"], capture_output=True, text=True)
        n += 1
        _expect(proc.returncode == 2 and '"error"' in proc.stdout
                and "perms" in proc.stdout
                and "Traceback" not in proc.stderr,
                "m-3: CLI check with no exposure and --perms -3 must "
                "exit 2 with a perms error JSON", failures)

    payload = {"tool": "research_kit", "version": RKIT_VERSION,
               "command": "selftest", "assertions": n, "failures": failures,
               "ok": not failures}
    return payload, (0 if not failures else 1)


def _load_rows(folder: Path) -> list[dict]:
    from equity_io import read_numeric_table
    return read_numeric_table(folder / "equity.csv", "equity.csv",
                              ("strategy_net", "strategy_gross",
                               "benchmark"))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="backtest-lint research_kit")
    ap.add_argument("command", choices=["check", "selftest"])
    ap.add_argument("folder", nargs="?", help="run folder (check)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--perms", type=int, default=200)
    ap.add_argument("--blocks", type=int, default=20)
    try:
        args = ap.parse_args()
    except SystemExit as e:
        if e.code not in (0, None):
            print(json.dumps({"tool": "research_kit",
                              "version": RKIT_VERSION,
                              "error": "invalid arguments "
                                       "(usage on stderr)"}))
        raise
    if args.command == "selftest":
        try:
            payload, code = run_selftest()
        except Exception as e:  # no-crash contract holds for the probe
            print(json.dumps({"tool": "research_kit", "command": "selftest",
                              "error": f"selftest crashed: {e}"}))
            sys.exit(2)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.exit(code)
    if not args.folder:
        print(json.dumps({"tool": "research_kit", "version": RKIT_VERSION,
                          "error": "command requires <run_folder>"}))
        sys.exit(2)
    folder = Path(args.folder)
    try:
        payload, code = check(folder, seed=args.seed, perms=args.perms,
                              blocks=args.blocks)
    except KitInputError as e:
        print(json.dumps({"tool": "research_kit", "version": RKIT_VERSION,
                          "command": "check", "run_folder": str(folder),
                          "error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(2)
    except Exception as e:  # no-crash contract: catch-all -> error JSON
        print(json.dumps({"tool": "research_kit", "version": RKIT_VERSION,
                          "command": "check", "run_folder": str(folder),
                          "error": f"unexpected: {type(e).__name__}: {e}"},
                         ensure_ascii=False, indent=2))
        sys.exit(2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
