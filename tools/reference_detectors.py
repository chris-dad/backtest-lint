#!/usr/bin/env python3
"""Reference detectors for the backtest-lint corpus.
(No version in this title - corpus version lives in build_corpus.CORPUS_VERSION.)

Purpose (HY-2 generalization of the build-time assertions): every planted
sample must be RE-OBSERVED in its artifact by an independent detector at
build time; every clean sample must stay silent. "The disease is
observable" becomes a construction guarantee, not a hope.

These detectors are ALSO the seed prototypes for Phase 2 profiler.py
(data-level) and the Phase 4 gap-fill linter (AST-level). They are
deliberately simple and stdlib-only; their job here is to prove the
planted modes are measurable, not to be the final production detectors.

Verdict tiers (agreed with Hermes, point A - honest capability bounds):
  verified         deterministic fact from the artifact itself (+contract
                   fields or a reference series). No intent inference.
  suspicious       strong statistical fingerprint, but the data alone
                   cannot prove what produced it. Correct output when no
                   reference exists.
  cannot_determine no pure-data fingerprint exists. Returning this is the
                   CORRECT behaviour, not a detection failure. A detector
                   that claims "verified" here is fabricating certainty.

Zero third-party deps.
"""
from __future__ import annotations

import ast
import csv
import json
import math
from datetime import datetime

TIER_VERIFIED = "verified"
TIER_SUSPICIOUS = "suspicious"
TIER_CANNOT = "cannot_determine"


def _verdict(fired: bool, tier: str, rule: str, evidence: str) -> dict:
    return {"fired": fired, "tier": tier, "rule": rule, "evidence": evidence}


def load_rows(path) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))[1:]


def load_meta(path) -> dict:
    return json.loads(open(path, encoding="utf-8").read())


# ==========================================================================
# Data-level detectors (profile rules)
# ==========================================================================

def det_201_reference(rows_suspect: list, rows_reference: list,
                      dividend_events: list) -> dict:
    """profile.201, VERIFIED tier: with a raw reference series + the
    corporate-action table, the suspect must equal raw minus cumulative
    future dividends. This is the only honest way to call 201 'verified'."""
    if len(rows_suspect) != len(rows_reference):
        return _verdict(False, TIER_CANNOT, "profile.201", "length mismatch vs reference")
    diffs = [float(a[1]) - float(b[1]) for a, b in zip(rows_reference, rows_suspect)]
    total = sum(e["amount"] for e in dividend_events)
    # diff must start at total, end at 0, and be a non-increasing step fn
    if abs(diffs[0] - total) > 1e-6 or abs(diffs[-1]) > 1e-6:
        return _verdict(False, TIER_CANNOT, "profile.201",
                        "diff endpoints do not match event-implied adjustment")
    for i in range(len(diffs) - 1):
        if diffs[i + 1] - diffs[i] > 1e-9:
            return _verdict(False, TIER_CANNOT, "profile.201",
                            "diff is not a non-increasing step function")
    return _verdict(True, TIER_VERIFIED, "profile.201",
                    f"suspect = reference - cumulative future dividends "
                    f"({len(dividend_events)} events, total {total:.2f})")


def det_201_cliff(rows: list) -> dict:
    """profile.201, SUSPICIOUS tier without reference: a single-day cliff
    consistent with an exact 1:2 split (ratio 0.5) after subtracting that
    day's own market move. Real vendor data always contaminates the split
    cliff with the same-day return, so the test is on the RESIDUAL:
    log(2 * px[i+1]/px[i]) at the extreme move must be ~0 (within daily
    noise). An exact-equality fingerprint would be untestable on real data."""
    try:
        px = [float(r[1]) for r in rows]
    except ValueError:
        return _verdict(False, TIER_CANNOT, "profile.201",
                        "second column not numeric (not a price series)")
    if any(p <= 0 for p in px):
        return _verdict(False, TIER_CANNOT, "profile.201", "non-positive prices")
    lr = [math.log(px[i + 1] / px[i]) for i in range(len(px) - 1)]
    i_min = lr.index(min(lr))
    r = px[i_min + 1] / px[i_min]
    resid = math.log(2.0 * r)
    if abs(resid) < 0.05:  # residual daily move within +-5%
        return _verdict(True, TIER_SUSPICIOUS, "profile.201",
                        f"down-cliff consistent with hidden 1:2 split at row "
                        f"{i_min}: ratio {r:.4f}, residual after split "
                        f"{resid * 100:+.2f}% (within daily noise)")
    i_max = lr.index(max(lr))
    r = px[i_max + 1] / px[i_max]
    resid = math.log(r / 2.0)
    if abs(resid) < 0.05:
        return _verdict(True, TIER_SUSPICIOUS, "profile.201",
                        f"up-cliff consistent with misapplied 1:2 adjustment "
                        f"at row {i_max}: ratio {r:.4f}, residual "
                        f"{resid * 100:+.2f}% (within daily noise)")
    return _verdict(False, TIER_CANNOT, "profile.201",
                    "no pure-data fingerprint (needs reference/contract)")


def det_202(rows: list, meta: dict) -> dict:
    """profile.202, VERIFIED tier: any row dated after the contractual
    expiry is a zombie by definition - the instrument ceased to exist.
    Evidence additionally reports secondary pathological signatures so the
    harder variants (nonzero post-expiry volume, frozen mark/IV against a
    moving underlying) are individually observed, not collapsed into one
    date check."""
    expiry = meta.get("expiry")
    if not expiry:
        return _verdict(False, TIER_CANNOT, "profile.202", "no expiry in contract")
    cont = [r for r in rows if r[0] > expiry]
    if not cont:
        return _verdict(False, TIER_VERIFIED, "profile.202", "no post-expiry rows")
    cols = meta.get("columns", [])
    sig = [f"{len(cont)} rows dated after contractual expiry {expiry}"]
    if "volume" in cols:
        iv = cols.index("volume")
        nz = sum(1 for r in cont if float(r[iv]) > 0)
        if nz:
            sig.append(f"{nz} post-expiry rows with nonzero volume")
    if "mark" in cols and "underlying" in cols:
        im, iu = cols.index("mark"), cols.index("underlying")
        marks = {r[im] for r in cont}
        unds = {r[iu] for r in cont}
        if len(marks) == 1 and len(unds) > 1:
            sig.append(f"mark frozen at {next(iter(marks))} while underlying moves")
    if "iv" in cols:
        ii = cols.index("iv")
        ivs = {r[ii] for r in cont}
        if len(ivs) == 1:
            sig.append(f"iv frozen at {next(iter(ivs))}")
    if "settle" in cols and "underlying" in cols:
        ist, iu = cols.index("settle"), cols.index("underlying")
        settles = {r[ist] for r in cont}
        unds = {r[iu] for r in cont}
        if len(settles) == 1 and len(unds) > 1:
            sig.append(f"settle frozen at {next(iter(settles))} "
                       f"while underlying moves")
    return _verdict(True, TIER_VERIFIED, "profile.202", "; ".join(sig))


def det_203(rows: list) -> dict:
    """profile.203, VERIFIED tier: parsed-timestamp order violations are
    deterministic facts (backward jumps / duplicate stamps)."""
    try:
        ts = [datetime.fromisoformat(r[0].replace("Z", "+00:00")) for r in rows]
    except ValueError:
        return _verdict(False, TIER_CANNOT, "profile.203",
                        "first column is not ISO timestamps")
    back = sum(1 for a, b in zip(ts, ts[1:]) if b < a)
    dup = sum(1 for a, b in zip(ts, ts[1:]) if b == a)
    # Round-7 Fix: adjacent equality cannot see duplicates appended at the
    # END of a file (they are not adjacent to their originals). Count
    # duplicates BY VALUE too - a duplicated timestamp is a duplicated
    # timestamp wherever it sits.
    dup_by_value = len(ts) - len(set(ts))
    if back or dup or dup_by_value:
        return _verdict(True, TIER_VERIFIED, "profile.203",
                        f"{back} backward jumps, {dup} adjacent duplicate "
                        f"stamps, {dup_by_value} duplicate-by-value rows")
    return _verdict(False, TIER_VERIFIED, "profile.203", "monotonic, no duplicates")


def det_204(rows: list, meta: dict) -> dict:
    """profile.204, tiered. First-principles derivation of the observable
    fingerprint of full-sample normalization (HY-3):

    A full-sample standardization x = (r - mu_all)/sigma_all is affine, and
    any affine image of plausible raw data looks plausible - so the SIGNAL
    is not the shape, it is the SELF-REFERENTIAL MOMENT IDENTITY: the
    normalization constants equal the output's own full-sample moments
    (mean exactly 0 / std exactly 1, or exact [0,1] endpoints for min-max).
    Computing those constants requires the ENTIRE series including the
    future, therefore exactness is impossible for any causal (expanding)
    normalization. Exact moments => non-causal transform, full stop.

    Tier is still 'suspicious', not 'verified': the data cannot tell a
    leak apart from a disclosed full-sample protocol (e.g. deliberate ML
    preprocessing). Verified tier is reserved for contract violations.
    """
    cols = meta.get("columns") or []
    if len(cols) < 2:
        return _verdict(False, TIER_CANNOT, "profile.204", "no numeric column")
    try:
        vals = [float(r[len(cols) - 1]) for r in rows]
    except (ValueError, IndexError):
        return _verdict(False, TIER_CANNOT, "profile.204", "column not numeric")
    n = len(vals)
    mu = sum(vals) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / n)
    lo, hi = min(vals), max(vals)

    # VERIFIED tier: contract self-violation (checkable fact, no inference).
    stats = meta.get("stats") or {}
    as_of = stats.get("as_of")
    if as_of:
        try:
            last = datetime.fromisoformat(rows[-1][0][:10]).date()
            if (datetime.fromisoformat(as_of).date() > last
                    and stats.get("window") == "full_sample"):
                return _verdict(True, TIER_VERIFIED, "profile.204",
                                f"meta stats as_of {as_of} beyond data end "
                                f"{last.isoformat()} with window=full_sample")
        except ValueError:
            pass

    # SUSPICIOUS tier: self-referential moment identity.
    if abs(mu) < 1e-7 and abs(sd - 1.0) < 1e-6:
        return _verdict(True, TIER_SUSPICIOUS, "profile.204",
                        f"population moments exactly (0,1): mean={mu:.2e}, "
                        f"std={sd:.9f} - impossible for causal normalization "
                        f"or raw data (measure zero)")
    if abs(sd - 1.0) < 1e-6 and meta.get("column_semantics") == "return":
        return _verdict(True, TIER_SUSPICIOUS, "profile.204",
                        f"return column population std exactly {sd:.9f} "
                        f"(=100% daily vol, implausible + exact)")
    if lo >= -1e-12 and hi <= 1.0 + 1e-12 and abs(lo) < 1e-9 and abs(hi - 1.0) < 1e-9:
        return _verdict(True, TIER_SUSPICIOUS, "profile.204",
                        "min-max fingerprint: exact [0,1] endpoints, all values inside")

    return _verdict(False, TIER_CANNOT, "profile.204",
                    "no fingerprint (raw-like column)")


def profile_sweep(rows: list, meta: dict) -> list[dict]:
    """Run all reference-free profile detectors on one CSV+meta pair.
    Returns every verdict (fired or not) so the harness can audit silence."""
    return [det_201_cliff(rows), det_202(rows, meta),
            det_203(rows), det_204(rows, meta)]


# ==========================================================================
# AST-level detector (lint rules) - seed of the Phase 4 gap-fill linter
# ==========================================================================

def _has_shift(e: ast.expr) -> bool:
    return any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
               and x.func.attr == "shift" for x in ast.walk(e))


def _return_origin(e: ast.expr, col_assign: dict) -> list[str]:
    """Columns whose values flow from a .pct_change() on a df column."""
    out = []
    for x in ast.walk(e):
        if (isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
                and x.func.attr == "pct_change"
                and isinstance(x.func.value, ast.Subscript)
                and isinstance(x.func.value.slice, ast.Constant)):
            out.append(x.func.value.slice.value)
    if not out and isinstance(e, ast.Subscript) and isinstance(e.slice, ast.Constant):
        assigns = col_assign.get(e.slice.value, [])
        if assigns:
            out = _return_origin(assigns[-1], col_assign)
    return out


def _is_vacuous_assert(test: ast.expr) -> bool:
    if isinstance(test, ast.Constant) and test.value is True:
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op, cmp = test.ops[0], test.comparators[0]
        if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(cmp, ast.Constant) \
                and cmp.value is None:
            return True
        if isinstance(op, (ast.Eq, ast.Is)) and isinstance(test.left, ast.Name) \
                and isinstance(cmp, ast.Name) and test.left.id == cmp.id:
            return True
    return False


def det_lint(src: str) -> dict:
    """AST sweep over run_backtest. Returns fired rules + evidence.

    Note on lint.101/102 detection semantics: the position-side column
    assignment must contain a .shift() call at the TOP LEVEL of that
    assignment expression for the fill to be lagged. Helper functions
    containing shift (indicator lookbacks) do NOT satisfy this - which is
    exactly the point: an indicator lookback shift is not an execution lag.
    """
    tree = ast.parse(src)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_backtest":
            fn = node
            break
    if fn is None:
        return {"fired": [], "evidence": {"error": "no run_backtest"}}

    col_assign: dict[str, list[ast.expr]] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                        and isinstance(t.slice, ast.Constant)
                        and isinstance(t.slice.value, str)):
                    col_assign.setdefault(t.slice.value, []).append(node.value)

    fired: list[str] = []
    evidence: dict[str, str] = {}

    # lint.101/102: pnl-like column = position-like * return-like, where the
    # position column's (last) assignment carries no top-level .shift().
    for col in ("pnl", "strat_ret"):
        assigns = col_assign.get(col, [])
        if not assigns:
            continue
        e = assigns[-1]
        if not (isinstance(e, ast.BinOp) and isinstance(e.op, ast.Mult)):
            continue
        ret_cols: list[str] = []
        pos_col = None
        for opnd in (e.left, e.right):
            org = _return_origin(opnd, col_assign)
            if org:
                ret_cols = org
            elif isinstance(opnd, ast.Subscript) and isinstance(opnd.slice, ast.Constant):
                pos_col = opnd.slice.value
        if not ret_cols or pos_col is None:
            continue
        pos_assigns = col_assign.get(pos_col, [])
        if pos_assigns and not _has_shift(pos_assigns[-1]):
            rule = "lint.101" if ret_cols[0] == "close" else "lint.102"
            if rule not in fired:
                fired.append(rule)
                evidence[rule] = (f"'{pos_col}' assignment has no shift; "
                                  f"pnl aligned to same-bar {ret_cols[0]} returns")

    # lint.103: center=True anywhere (direct or through **kwargs call site).
    for x in ast.walk(fn):
        if isinstance(x, ast.Call):
            for kw in x.keywords:
                if kw.arg == "center" and isinstance(kw.value, ast.Constant) \
                        and kw.value.value is True:
                    if "lint.103" not in fired:
                        fired.append("lint.103")
                        evidence["lint.103"] = "center=True keyword found"

    # lint.104: negative shift args / negative indexing / negative slices.
    neg = []
    for x in ast.walk(fn):
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) \
                and x.func.attr == "shift":
            for a in x.args:
                if isinstance(a, ast.UnaryOp) and isinstance(a.op, ast.USub) \
                        and isinstance(a.operand, ast.Constant):
                    neg.append(f"shift(-{a.operand.value})")
        if isinstance(x, ast.Subscript):
            sl = x.slice
            cand = None
            if isinstance(sl, ast.UnaryOp) and isinstance(sl.op, ast.USub) \
                    and isinstance(sl.operand, ast.Constant):
                cand = sl.operand.value
            elif isinstance(sl, ast.Slice):
                for b in (sl.lower, sl.upper):
                    if isinstance(b, ast.UnaryOp) and isinstance(b.op, ast.USub) \
                            and isinstance(b.operand, ast.Constant):
                        cand = b.operand.value
            if cand is not None:
                neg.append(f"index/slice [-{cand}]")
    if neg:
        fired.append("lint.104")
        evidence["lint.104"] = "future-anchored access: " + ", ".join(sorted(set(neg)))

    # lint.105: zero non-vacuous asserts in run_backtest.
    real = [x for x in ast.walk(fn) if isinstance(x, ast.Assert)
            and not _is_vacuous_assert(x.test)]
    if not real:
        fired.append("lint.105")
        evidence["lint.105"] = "no non-vacuous assert statement in run_backtest"

    return {"fired": fired, "evidence": evidence}
