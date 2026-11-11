#!/usr/bin/env python3
"""backtest-lint profiler (Phase 2): production data-level checks 201-204.

Version: only PROFILER_VERSION below is authoritative - never restate it.

Relation to tools/reference_detectors.py (Phase 1 prototypes): the reference
detectors proved the planted modes are MEASURABLE; this module is the
production detector that must reproduce the same corpus verdicts through a
header-aware, real-data-ready interface (named columns, flexible timestamp
parsing, honest tiering). It does NOT import the reference module.

Honest tiers (unchanged from Phase 1 agreement):
  verified          deterministic fact from the artifact itself + contract
                    fields (+ a reference series where one exists).
  suspicious        strong statistical fingerprint; the data alone cannot
                    prove intent. Correct output when no reference exists.
  cannot_determine  no pure-data fingerprint exists. Emitting this tier on a
                    no-fingerprint sample is CORRECT behaviour, not failure.

Robustness contract: NO input shape may crash the profiler. Malformed input
produces an explicit error JSON (check) or a cannot_determine verdict -
never a traceback, and never a verdict whose evidence states something the
code did not establish. NaN/inf anywhere is gated by _finite_all() AT THE
COMPARISON POINT: a single non-finite value poisons any numeric comparison
(abs(nan - x) > tol is always False), which would fabricate a "matched"
verdict (red-team X2/X3/X4 class).

CLI (stdlib only, no third-party deps):
  check   : python3 tools/profiler.py check <csv> [--meta m.json]
            [--reference ref.csv --events ref.csv.meta.json]
            -> per-rule verdicts as JSON on stdout (exit 0; exit 2 on
               structurally broken input, with an "error" field)
  gate    : python3 tools/profiler.py gate [--corpus tests/corpus]
            -> run the Phase 1 corpus acceptance (profile-scope samples;
               lint samples are Phase 4 scope), compare against
               tests/corpus/expected_results.json INCLUDING the
               evidence_must_include token locks, exit 0/1.

Gate wiring note (iron rule: the DETECTOR never reads the answer key):
  the gate harness reads expected_results.json to decide WHAT to run, which
  mirror reference to hand the profiler, and WHICH evidence tokens to pin -
  the same thing a human operator does. The profiler itself only sees csv +
  meta (+ an explicitly supplied reference), never the expected verdict.

Check 201 dual-report design (Cursor review round 6): Mode A (reference
curve) and Mode B (split-residual cliff scan) run INDEPENDENTLY. A curve
that matches its reference cannot launder a cliff hiding in the data, and
a curve mismatch never suppresses the cliff scan - each emits its own
profile.201 verdict with its own tier.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

PROFILER_VERSION = "0.7.1"

TIER_VERIFIED = "verified"
TIER_SUSPICIOUS = "suspicious"
TIER_CANNOT = "cannot_determine"

# Column-name priorities, shared by every check (single source of truth).
TIME_COLS = ("timestamp", "trade_date", "date", "t", "ts", "time")
PRICE_COLS = ("close", "adj_close", "price")
VOL_COLS = ("ret", "return", "returns")
# A fallback (unnamed-position) column is only accepted as a time axis if
# its NAME looks like one - raw price columns ("open") must not be treated
# as timelines (Cursor review round 6, finding 5).
TIME_NAME_RE = re.compile(r"^(t|ts|time|date|datetime|timestamp|idx|index|"
                          r"seq|no|num|stamp)$", re.IGNORECASE)

# Split ratios worth fingerprinting (1:2 is the corpus mode; 1:3..1:10 and
# reverse splits occur on real vendors).
SPLIT_KS = (2, 3, 4, 5, 10)
# Residual tolerance AFTER removing the hypothesized split. 0.12 covers a
# 1:2 split landing on a day with up to ~12% concurrent market move; a move
# whose residual is larger is not attributable to an integer split at the
# tested ratios. (Honest bound - a crash day beyond +-12% can mask a split;
# only a reference series resolves that.)
SPLIT_RESID_TOL = 0.12
IDENTITY_MIN_N = 30  # moment identities are meaningless below this n


def _verdict(rule: str, fired: bool, tier: str, evidence: str) -> dict:
    return {"rule": rule, "fired": fired, "tier": tier, "evidence": evidence}


def _finite_all(vals) -> bool:
    """Central NaN/inf gate: a single non-finite value poisons ANY numeric
    comparison (abs(nan - x) > tol is always False), turning mismatch
    detection into all-pass - i.e. a fabricated 'matched' verdict.
    Every comparison input passes through here."""
    try:
        return all(math.isfinite(float(v)) for v in vals)
    except (TypeError, ValueError, OverflowError):
        return False


# ==========================================================================
# Loading (header-aware; ragged input is a hard error, not a silent zip)
# ==========================================================================

def load_table(csv_path: Path) -> tuple[list[str], list[dict]]:
    """Return (column_names, rows-as-dicts). utf-8-sig: a UTF-8 BOM must not
    rename the first column (Cursor review round 7, finding 7). Raises
    ValueError on an empty file, a ragged row, or DUPLICATE column names -
    dict(zip()) would silently keep only the last duplicate and every later
    check would run on the surviving column (finding 10)."""
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"{csv_path.name}: empty file (no header)")
        cols = [h.strip() for h in header]
        dupes = {c for c in cols if cols.count(c) > 1}
        # Case-colliding headers ("Close" + "close") are not exact dupes,
        # but _col folds case - a cliff living only in "Close" would be
        # invisible behind the surviving lowercase column (Cursor review
        # round 8, finding 8). Reject both kinds.
        fold: set[str] = set()
        folded_dupes: set[str] = set()
        for c in cols:
            k = c.lower()
            if k in fold:
                folded_dupes.add(c)
            fold.add(k)
        if dupes or folded_dupes:
            raise ValueError(
                f"{csv_path.name}: duplicate column name(s) "
                f"{sorted(dupes | folded_dupes)} (exact or case-colliding) "
                f"- schema is ambiguous, refusing to silently collapse")
        rows = []
        for i, r in enumerate(reader, start=2):  # data starts at line 2
            if len(r) != len(cols):
                raise ValueError(
                    f"{csv_path.name}: line {i} has {len(r)} fields, "
                    f"header has {len(cols)} (ragged row)")
            rows.append(dict(zip(cols, r)))
    return cols, rows


def _col(columns: list[str], *names: str) -> str | None:
    """First matching column name, case-insensitive. Returns the CSV's
    ACTUAL spelling - callers must index rows with it (Cursor review
    round 6, finding 8: evidence loops that hardcoded lowercase broke on
    'Volume'-style headers)."""
    lower = {c.lower(): c for c in columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def _time_col(columns: list[str]) -> str | None:
    """Single source of truth for time-axis recognition, used by checks
    202/203/204 alike (Cursor review round 7, finding 5: per-check
    divergence made the same file land on different axes or none). A
    designated name from TIME_COLS wins; otherwise ANY column whose name
    matches TIME_NAME_RE is accepted - including position 0 or not."""
    tc = _col(columns, *TIME_COLS)
    if tc is not None:
        return tc
    for c in columns:
        if TIME_NAME_RE.match(c):
            return c
    return None


def _ts_parse(raw: str) -> datetime:
    """Parse ISO date/datetime into a naive-UTC datetime.

    Naive stamps stay as-given; aware stamps are converted to UTC and
    stripped - so naive/aware MIXES compare safely."""
    s = str(raw).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _stamp_utc(raw) -> datetime:
    """Parse a row stamp into a naive-UTC datetime. Accepts ISO date,
    ISO datetime (any offset - normalized to UTC), and numeric Unix epochs
    (10-13 digit seconds/milliseconds, integral or decimal - exchange
    dumps print '1700000000.0'; the decimal form used to be rejected by
    the integer-only regex and silently skipped as unparseable, Cursor
    review round 8, finding 3).
    INPUT PRECONDITION (Cursor review round 9, real-data traps): the
    10-to-13-digit rule is a contract with the data supplier. A COMPACT
    stamp like 2024061512 (YYYYMMDDHH) also matches it and parses as a
    nonsense epoch (2034-02-20) - vendor files using compact stamps must
    be converted to ISO before checking.
    Raises ValueError otherwise."""
    s = str(raw).strip()
    if re.fullmatch(r"-?\d{10,13}(\.\d+)?", s):
        v = float(s)
        if abs(v) >= 10**12:  # milliseconds
            dt = datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
        else:  # seconds
            dt = datetime.fromtimestamp(v, tz=timezone.utc)
        return dt.replace(tzinfo=None)
    return _ts_parse(s)


def _coerce_numeric(rows: list[dict], col: str) -> tuple[list[float], int]:
    """Cell-by-cell float coercion (Cursor review round 8, finding 7):
    a single non-numeric cell must not abort the whole column - it becomes
    a non-finite value that joins the pairwise skip, and its count is
    reported in the evidence instead of being raised to the caller."""
    vals: list[float] = []
    bad = 0
    for r in rows:
        try:
            vals.append(float(r[col]))
        except (ValueError, KeyError, TypeError):
            vals.append(float("nan"))
            bad += 1
    return vals, bad


# ==========================================================================
# profile.201 - adjusted-price back-inflation (三档分级, dual report)
# ==========================================================================

def _levels_partial_sums(amounts: list[float], targets: list[float]) -> bool:
    """True iff SOME SINGLE ordering (permutation) of `amounts` visits
    every value in `targets`, in the given order, as a cumulative prefix
    sum. The backcast diff level L equals total MINUS the running sum of
    already-applied events, so the caller transforms plateau levels into
    prefix-sum targets (total - L, ascending) before calling - passing
    the raw descending levels checked the wrong direction and rejected
    every legitimate multi-level backcast (red-team round 11, R9-F3:
    events {1,1,1} with the perfect curve 3/2/1/0 was called
    inconsistent). The weak 201 convention used to accept plateau heights
    that are no partial sum of the amounts at all (diff 3/2.5/0 against
    events {1,2}: 2.5 is unreachable in any ordering) - Cursor review
    round 8, finding 1. Exhaustive DFS over used-amount masks; callers
    bound the event count (16) so the state space stays finite."""
    n = len(amounts)
    frontier: set[tuple[int, float]] = {(0, 0.0)}  # (used-mask, cumsum)
    for t in targets:
        seen: set[tuple[int, float]] = set()
        nxt: set[tuple[int, float]] = set()
        stack = list(frontier)
        while stack:
            mask, cum = stack.pop()
            if abs(cum - t) <= 1e-6:
                nxt.add((mask, round(cum, 9)))
                continue
            for j in range(n):
                if not mask >> j & 1:
                    st = (mask | 1 << j, round(cum + amounts[j], 9))
                    if st not in seen:
                        seen.add(st)
                        stack.append(st)
        if not nxt:
            return False
        frontier = nxt
    return True


def _cliff_scan(px: list[float]) -> dict | None:
    """Mode B: scan EVERY adjacent POSITIVE-price pair (a non-positive
    or non-finite price kills only its own ratios, never the whole scan -
    Cursor review round 7, finding 4: one trailing 0 used to drop the
    entire scan and hide a visible 1:2 cliff; red-team round 8, F1: an
    underflowed ratio 5e-324/1e300 -> 0.0 used to crash math.log and the
    whole run) for a move consistent with an integer split
    1:k after removing same-day noise. A larger crash elsewhere cannot mask
    a split (all pairs scanned); a crash ON the split day beyond the +-12%
    residual bound cannot be separated from the split without a reference -
    the bound is stated, not hidden."""
    hits = []
    for i in range(len(px) - 1):
        a, b = px[i], px[i + 1]
        if not (math.isfinite(a) and math.isfinite(b) and a > 0 and b > 0):
            continue  # non-finite / non-positive kills this pair only (N2)
        r = b / a
        if r <= 0.0:
            continue  # underflow to 0.0 (e.g. 5e-324/1e300): ratio
            # unresolvable for THIS pair only - math.log(0) must not
            # crash the whole run (red-team round 8, F1)
        if r < 1.0 / 1.4:  # down move beyond ~-28.6%: candidate split cliff
            for k in SPLIT_KS:
                resid = math.log(r * k)
                if abs(resid) < SPLIT_RESID_TOL:
                    hits.append((i, "down", k, r, resid))
                    break
        elif r > 1.4:  # up move beyond ~+40%: candidate misapplied adjustment
            for k in SPLIT_KS:
                resid = math.log(r / k)
                if abs(resid) < SPLIT_RESID_TOL:
                    hits.append((i, "up", k, r, resid))
                    break
    if not hits:
        return None
    parts = [f"row {i}: {d}-cliff ratio {r:.4f} ~ 1:{k} split "
             f"(residual {res * 100:+.2f}%, within +-{SPLIT_RESID_TOL * 100:.0f}% "
             f"noise bound)" for i, d, k, r, res in hits[:5]]
    more = f"; +{len(hits) - 5} more" if len(hits) > 5 else ""
    return _verdict("profile.201", True, TIER_SUSPICIOUS,
                    f"{len(hits)} cliff(s) consistent with hidden integer "
                    f"splits: " + "; ".join(parts) + more)


def check_201(columns: list[str], rows: list[dict], meta: dict,
              reference: list[dict] | None = None,
              dividend_events: list | None = None) -> list[dict]:
    """profile.201 前复权倒推. Returns one or more profile.201 verdicts:

    Mode A (verified/cannot): a raw reference series + corporate-action
    table are supplied. The SUSPECT is the ADJUSTED series: the declared
    price column is resolved separator-insensitively with adj_close FIRST
    (round 10, finding 2: binding the raw close let a dividend backcast
    in 'Adj Close' beside it verify as "no adjustment claimed" against a
    raw reference); the reference keeps close-first priority (raw by
    contract). EVERY event contributes to ONE expected adjustment
    curve through whatever anchor it carries - ex_index (position) or
    ex_date (calendar wall-clock date); a mixed-anchor table combines both
    contributions and the suspect-vs-reference diff must match the combined
    curve POINTWISE. The endpoint-only weak convention fires ONLY when no
    event carries any anchor, and every intermediate step level must be a
    partial sum along one single ordering of the event amounts (round 8,
    finding 1: plateau heights like 2.5 between events {1,2} used to
    verify) - otherwise cannot_determine.

    Mode B (suspicious): split-residual cliff scan over ALL rows of EVERY
    price-like column (close/adj_close/price/open/high/low - round 8,
    finding 8: a cliff living in adj_close beside a flat close, or in an
    'open' column, used to be invisible behind the column priority).
    Runs INDEPENDENTLY of Mode A - a matching reference cannot launder a
    cliff hiding in the data, and a mismatching reference never suppresses
    the scan. Cells are coerced one by one: a non-numeric cell ('N/A',
    '') becomes a non-finite value that kills only its own adjacent pairs
    and is counted in the evidence, instead of aborting the whole check
    (round 8, finding 7).

    Neither mode applicable -> honest cannot_determine, not fired."""
    rule = "profile.201"
    if not rows:
        return [_verdict(rule, False, TIER_CANNOT, "no rows")]
    out: list[dict] = []

    # Mode A first (kept first for verdict-order stability), on the one
    # declared price column. NO fall-through to columns[-1]: without a
    # declared price name, Mode A could "verify" a volume or last-price
    # column against a reference built from anything (Cursor review
    # round 9, finding 1) - honest cannot instead.
    if reference is not None and dividend_events is not None:
        # The SUSPECT of a backcast check is the ADJUSTED series - priority
        # adj_close FIRST (round 10, finding 2: binding the raw close let a
        # dividend backcast living in 'Adj Close' beside it verify as
        # "no adjustment claimed" against a raw reference with an empty
        # event table, and with the TRUE table the matching Adj Close was
        # never curve-checked). Reference keeps close-first priority: it
        # is the RAW series by contract.
        pcol = _price_col(columns, ("adjclose", "close", "price"))
        if pcol is not None:
            # Ambiguity guard (red-team round 15, FIX-1): load_table only
            # rejects case-folded EXACT duplicates, so 'Adj Close' and
            # 'adj_close' can coexist - _price_col takes the first in
            # column order and a dividend haircut hiding in the other
            # spelling (0.99 ratios, below the split-cliff gate) is never
            # curve-checked while the clean copy verifies.
            pri = _norm_col(pcol)
            clash = [c for c in columns if _norm_col(c) == pri]
            if len(clash) > 1:
                pcol = None
                out.append(_verdict(rule, False, TIER_CANNOT,
                                    f"{len(clash)} columns normalize to "
                                    f"'{pri}' "
                                    f"({', '.join(repr(c) for c in clash)}) "
                                    f"- which one is the declared price "
                                    f"series is ambiguous; Mode A refused"))
        if pcol is None:
            if not out:
                out.append(_verdict(rule, False, TIER_CANNOT,
                                    f"no declared price column "
                                    f"(adj_close/close/price, separator-"
                                    f"insensitive) in the data - Mode A "
                                    f"refused rather than assume the last "
                                    f"column is a price"))
        else:
            px, _bad_cells = _coerce_numeric(rows, pcol)
            out.append(_mode_a_201(px, pcol, columns, rows, reference,
                                   dividend_events))

    # Mode B: every price-like column, cell-by-cell coercion. Column
    # names are NORMALIZED (all non-alphanumerics removed) so Yahoo's
    # 'Adj Close' and the separator-free 'AdjClose' both match adjclose
    # (rounds 9/10, finding 1/2).
    scan_set = {"close", "adjclose", "price", "open", "high", "low"}
    for scol in [c for c in columns
                 if _norm_col(c) in scan_set]:
        vals, bad_cells = _coerce_numeric(rows, scol)
        if len(vals) < 2:
            continue
        cv = _cliff_scan(vals)
        if cv is not None:
            note = f" [column '{scol}']"
            if bad_cells:
                note += (f"; {bad_cells} non-numeric cell(s) coerced "
                         f"and skipped")
            # Count only LITERAL non-finite values ("nan"/"inf" strings
            # parse successfully): the coerced NaNs are already counted
            # as bad_cells - counting both read like two defects per
            # cell (red-team round 13, NT-2).
            nf = (sum(1 for v in vals if not math.isfinite(v))
                  - bad_cells)
            if nf > 0:
                note += f"; {nf} non-finite value(s) skipped pair-wise"
            out.append(dict(cv, evidence=cv["evidence"] + note))

    if not out:
        out.append(_verdict(rule, False, TIER_CANNOT,
                            "no pure-data fingerprint "
                            "(needs reference/contract)"))
    return out


def _norm_col(name: str) -> str:
    """Normalize a column name for semantic matching: lowercase, ALL
    non-alphanumerics removed. 'Adj Close', 'adj.close', 'adj-close',
    'adj_close' AND 'AdjClose' all normalize to adjclose (Cursor review
    round 9, finding 1: the exact allowlist made Yahoo's 'Adj Close'
    header invisible; round 10, finding 2: underscore-collapsing still
    hid the separator-free 'AdjClose' spelling)."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _price_col(columns: list[str], priorities: tuple[str, ...]) -> str | None:
    """Actual spelling of the FIRST column whose normalized name matches a
    priority, in priority order. Mode A binds the adjusted series through
    this (round 10, finding 2): exact-name matching let Mode A run on the
    raw close while the dividend backcast lived in 'Adj Close' beside it -
    the raw-vs-raw diff verified as 'no adjustment claimed' and the
    matching adjusted column was never curve-checked."""
    norm = [_norm_col(str(c)) for c in columns]
    for pri in priorities:
        for c, nc in zip(columns, norm):
            if nc == pri:
                return c
    return None


def _cal_date(raw) -> date:
    """Wall-clock calendar date of a stamp - NO timezone conversion. Dividend
    ex-dates are venue-local calendar dates; normalizing them to UTC shifts
    cross-midnight offsets onto the wrong day and rejects honest backcasts
    (internal red-team round 7, N3). Non-ISO row stamps (Unix epochs) fall
    back to the UTC-normalized instant's date so a date-anchored event
    table works on epoch-stamped rows too (Cursor review round 9,
    finding 6: checks 202/203/204 already parsed those stamps)."""
    s = str(raw).strip()
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return _stamp_utc(s).date()


def _mode_a_201(px: list[float], pcol: str, columns: list[str],
                rows: list[dict], reference: list[dict],
                dividend_events: list) -> dict:
    """Mode A. Anchor resolution: EACH event contributes to the expected
    adjustment curve through whatever anchor it carries - ex_index
    (position) or ex_date (calendar wall-clock date). A mixed-anchor table
    is legitimate and both contributions combine into ONE pointwise curve;
    falling back to the endpoint-only convention while any anchor exists
    would let a wrong-day, wrong-size step verify (internal red-team round
    7, N1). The weak convention (endpoints + non-increasing + step shape)
    is used ONLY when NO event carries any anchor - including the empty
    event table - and its evidence says exactly that."""
    rule = "profile.201"
    if len(rows) != len(reference):
        return _verdict(rule, False, TIER_CANNOT,
                        "length mismatch vs reference")
    rcol = _price_col([str(c) for c in reference[0]],
                      ("close", "price", "adjclose"))
    if rcol is None:
        return _verdict(rule, False, TIER_CANNOT,
                        f"reference has no declared price column "
                        f"(close/price/adj_close, separator-insensitive) "
                        f"- Mode A refused "
                        f"rather than assume the last reference column "
                        f"is a price (round 9, finding 1)")
    ref_clash = [c for c in reference[0]
                 if _norm_col(str(c)) == _norm_col(rcol)]
    if len(ref_clash) > 1:
        return _verdict(rule, False, TIER_CANNOT,
                        f"{len(ref_clash)} reference columns normalize to "
                        f"'{_norm_col(rcol)}' "
                        f"({', '.join(repr(c) for c in ref_clash)}) - "
                        f"which one is the raw series is ambiguous; "
                        f"Mode A refused")
    try:
        diffs = []
        for a, b in zip(rows, reference):
            # Blame the side that actually failed (red-team round 15,
            # FIX-3: the joint except always said "reference column",
            # accusing a clean reference of a suspect's garbage cell).
            try:
                sv = float(a[pcol])
            except (ValueError, TypeError, KeyError):
                return _verdict(rule, False, TIER_CANNOT,
                                f"non-numeric price in SUSPECT column "
                                f"'{pcol}'")
            try:
                rv = float(b[rcol])
            except (ValueError, TypeError, KeyError):
                return _verdict(rule, False, TIER_CANNOT,
                                f"non-numeric price in reference column "
                                f"'{rcol}'")
            diffs.append(rv - sv)
    except KeyError:
        return _verdict(rule, False, TIER_CANNOT,
                        "non-numeric price in reference column")
    if not _finite_all(diffs):
        return _verdict(rule, False, TIER_CANNOT,
                        "non-finite value(s) in suspect/reference price "
                        "columns - pointwise comparison not establishable")

    try:
        total = sum(float(e["amount"]) for e in dividend_events)
    except (TypeError, ValueError, KeyError):
        return _verdict(rule, False, TIER_CANNOT,
                        "malformed event table: non-numeric amount")
    if not math.isfinite(total):
        return _verdict(rule, False, TIER_CANNOT,
                        "malformed event table: non-finite amount(s) "
                        "poison the comparison")

    pos_events = [e for e in dividend_events if "ex_index" in e]
    date_events = [e for e in dividend_events
                   if "ex_index" not in e and "ex_date" in e]

    if pos_events or date_events:
        # At least one anchored event -> pointwise curve. Row dates are
        # required if ANY event carries a date anchor (including dual-
        # anchor events); an unusable date column must NOT fall to the
        # endpoint shortcut (N1).
        unanchored = len(dividend_events) - len(pos_events) - len(date_events)
        if unanchored:
            # Events with no anchor never enter the expected curve - the
            # pointwise check covers only the anchored subset, so a
            # verified verdict (and a total that includes them) would
            # assert more than the code established (red-team round 8, F2;
            # same principle as N1 for partially anchored tables).
            return _verdict(rule, False, TIER_CANNOT,
                            f"{unanchored} event(s) carry neither ex_index "
                            f"nor ex_date - only the anchored subset "
                            f"({len(dividend_events) - unanchored} of "
                            f"{len(dividend_events)}) was verifiable; "
                            f"verified refused")
        dual_events = [e for e in pos_events if "ex_date" in e]
        pos_only = [e for e in pos_events if "ex_date" not in e]
        row_dates = None
        if date_events or dual_events:
            tcol = _time_col(columns)
            if tcol is not None:
                try:
                    row_dates = [_cal_date(r[tcol]) for r in rows]
                except (ValueError, OSError, OverflowError):
                    row_dates = None
            if row_dates is None:
                return _verdict(rule, False, TIER_CANNOT,
                                f"event table has "
                                f"{len(date_events) + len(dual_events)} "
                                f"date-anchored event(s) but row dates are "
                                f"unusable - jump-day verification not "
                                f"establishable; endpoint-only shortcut "
                                f"refused")
        # Validate + parse every anchor up front, so both dual-anchor
        # curves are built from the same validated material.
        parsed_pos: list[tuple[int, float]] = []
        beyond = 0
        for e in pos_events:
            try:
                idx_f = float(e["ex_index"])
            except (TypeError, ValueError, KeyError, OverflowError):
                return _verdict(rule, False, TIER_CANNOT,
                                f"malformed event table: ex_index "
                                f"{e.get('ex_index')!r} is not an integer "
                                f"row index")
            if not math.isfinite(idx_f):
                return _verdict(rule, False, TIER_CANNOT,
                                f"malformed event table: ex_index "
                                f"{e.get('ex_index')!r} is non-finite")
            idx = int(idx_f)
            if idx != idx_f or idx < 0:
                return _verdict(rule, False, TIER_CANNOT,
                                f"malformed event table: ex_index "
                                f"{idx_f!r} is not a non-negative integer "
                                f"row index")
            if idx >= len(diffs):
                beyond += 1  # event dated after data end: legitimately
                # applies to every row - but the operator should see it
            parsed_pos.append((idx, float(e["amount"])))
        parsed_date: list[tuple[date, float]] = []
        for e in dividend_events:
            if "ex_date" not in e:
                continue
            try:
                ed = _cal_date(e["ex_date"])
            except (ValueError, OSError, OverflowError):
                return _verdict(rule, False, TIER_CANNOT,
                                f"malformed event table: ex_date "
                                f"{e.get('ex_date')!r} is not a calendar "
                                f"date")
            parsed_date.append((ed, float(e["amount"])))

        def _apply(pos_pairs: list[tuple[int, float]],
                   date_pairs: list[tuple[date, float]]):
            exp = [0.0] * len(diffs)
            for idx, amt in pos_pairs:
                for i in range(min(idx, len(exp))):
                    exp[i] += amt
            for ed, amt in date_pairs:
                for i, rd in enumerate(row_dates):
                    if ed > rd:
                        exp[i] += amt
            return exp

        def _mismatches(exp):
            return [i for i, (d, x) in enumerate(zip(diffs, exp))
                    if abs(d - x) > 1e-6]

        if not _finite_all([a for _, a in parsed_pos] +
                           [a for _, a in parsed_date]):
            return _verdict(rule, False, TIER_CANNOT,
                            "malformed event table: non-finite amount(s) "
                            "poison the expected curve")

        if dual_events:
            # Dual-anchor events must agree with themselves (red-team
            # round 11 follow-up; Cursor review round 9, finding 7: the
            # position anchor silently won and a disagreeing ex_date was
            # never checked). Verify BOTH readings of the table: dual
            # events as position-anchored, and as date-anchored.
            pos_ids = {id(e) for e in dual_events}
            pos_only_pairs = [(idx, amt) for (idx, amt), e in
                              zip(parsed_pos, pos_events)
                              if id(e) not in pos_ids]
            date_only_pairs = [(ed, amt) for (ed, amt), e in
                               zip(parsed_date,
                                   [e for e in dividend_events
                                    if "ex_date" in e])
                               if id(e) not in pos_ids]
            dual_pos_pairs = [(idx, amt) for (idx, amt), e in
                              zip(parsed_pos, pos_events)
                              if id(e) in pos_ids]
            dual_date_pairs = [(ed, amt) for (ed, amt), e in
                               zip(parsed_date,
                                   [e for e in dividend_events
                                    if "ex_date" in e])
                               if id(e) in pos_ids]
            curve_pos = _apply(pos_only_pairs + dual_pos_pairs,
                               date_only_pairs)
            curve_date = _apply(pos_only_pairs,
                                date_only_pairs + dual_date_pairs)
            bad_pos = _mismatches(curve_pos)
            bad_date = _mismatches(curve_date)
            if not bad_pos and not bad_date:
                note = (f"; {beyond} event(s) dated after data end - "
                        f"apply to all rows" if beyond else "")
                note += (f"; {len(dual_events)} event(s) carry both "
                         f"anchors - position and date readings agree")
                return _verdict(rule, True, TIER_VERIFIED,
                                f"suspect = reference - event-implied "
                                f"adjustment curve on declared price "
                                f"column '{pcol}': "
                                f"{len(pos_events)} position-anchored + "
                                f"{len(date_events)} date-anchored events "
                                f"matched pointwise over {len(diffs)} "
                                f"rows (total {total:.2f})" + note)
            if bad_pos and bad_date:
                return _verdict(rule, False, TIER_CANNOT,
                                f"diff does not match the event-implied "
                                f"adjustment curve (first mismatch at row "
                                f"{bad_pos[0]}: got "
                                f"{diffs[bad_pos[0]]:.4f}, expected "
                                f"{curve_pos[bad_pos[0]]:.4f})")
            winner, loser = (("position", "date") if not bad_pos
                             else ("date", "position"))
            return _verdict(rule, False, TIER_CANNOT,
                            f"dual-anchor conflict: {len(dual_events)} "
                            f"event(s) carry both ex_index and ex_date "
                            f"and the anchors disagree - the {winner} "
                            f"reading matches the diff but the {loser} "
                            f"reading does not (first mismatch at row "
                            f"{(bad_pos or bad_date)[0]}) - the event "
                            f"table is internally inconsistent; verified "
                            f"refused")
        expected = _apply(parsed_pos, parsed_date)
        if not _finite_all(expected):
            return _verdict(rule, False, TIER_CANNOT,
                            "malformed event table: non-finite amount(s) "
                            "poison the expected curve")
        bad = [i for i, (d, x) in enumerate(zip(diffs, expected))
               if abs(d - x) > 1e-6]
        if bad:
            return _verdict(rule, False, TIER_CANNOT,
                            f"diff does not match the event-implied "
                            f"adjustment curve (first mismatch at row "
                            f"{bad[0]}: got {diffs[bad[0]]:.4f}, "
                            f"expected {expected[bad[0]]:.4f})")
        note = (f"; {beyond} event(s) dated after data end - apply to all "
                f"rows" if beyond else "")
        return _verdict(rule, True, TIER_VERIFIED,
                        f"suspect = reference - event-implied adjustment "
                        f"curve on declared price column '{pcol}': "
                        f"{len(pos_events)} position-anchored + "
                        f"{len(date_events)} date-anchored events matched "
                        f"pointwise over {len(diffs)} rows "
                        f"(total {total:.2f})" + note)

    # Weak convention - NO event carries any anchor (or the table is
    # empty): endpoints + non-increasing + GENUINE STEP SHAPE, and every
    # INTERIOR level must be a partial sum of one ordering of the
    # amounts (round 8, finding 1). With MULTIPLE events but no interior
    # level, ANY partition of the total fits the two endpoints - the
    # composition is unverifiable and verified is refused (round 10,
    # finding 3). Jump days CANNOT be checked here, and the evidence
    # says so.
    if abs(diffs[0] - total) > 1e-6 or abs(diffs[-1]) > 1e-6:
        return _verdict(rule, False, TIER_CANNOT,
                        "diff endpoints do not match event-implied "
                        "adjustment (not a backcast of this event table)")
    for i in range(len(diffs) - 1):
        if diffs[i + 1] - diffs[i] > 1e-9:
            return _verdict(rule, False, TIER_CANNOT,
                            "diff is not a non-increasing step function "
                            "(adjustment direction inconsistent)")
    distinct = {round(d, 9) for d in diffs}
    max_steps = len(dividend_events) + 1
    if len(distinct) > max_steps:
        return _verdict(rule, False, TIER_CANNOT,
                        f"diff takes {len(distinct)} distinct values but "
                        f"{len(dividend_events)} event(s) imply at most "
                        f"{max_steps} level(s) - adjustment is not a step "
                        f"function (gradual drift, not discrete ex-date "
                        f"jumps)")
    if not dividend_events:
        return _verdict(rule, True, TIER_VERIFIED,
                        f"empty event table: suspect column '{pcol}' "
                        f"matches reference column '{rcol}' exactly "
                        f"(diff identically 0, {len(diffs)} rows) - "
                        f"no adjustment claimed; a split-cliff scan on "
                        f"every price-like column runs independently")
    if len(dividend_events) > 16:
        return _verdict(rule, False, TIER_CANNOT,
                        f"{len(dividend_events)} events exceed the "
                        f"exhaustive permutation-verification bound (16) - "
                        f"the weak convention cannot establish verified")
    amounts = [float(e["amount"]) for e in dividend_events]
    # Step-height consistency (Cursor review round 8, finding 1; red-team
    # round 11, R9-F3): every intermediate plateau level L must satisfy
    # total - L = (sum of already-applied events) - and those running sums,
    # taken ASCENDING, must be prefix sums of ONE single ordering of the
    # amounts. Level count alone let 2.5 verify between events {1,2}
    # (reachable levels are only 0/1/2/3); the raw descending levels
    # checked the wrong direction and rejected honest multi-level curves.
    levels = sorted((d for d in distinct
                     if abs(d - total) > 1e-6 and abs(d) > 1e-6),
                    reverse=True)
    if len(dividend_events) >= 2 and not levels:
        # Endpoint-only curve with MULTIPLE events (round 10, finding 3):
        # total at the start, 0 at the end, no interior plateau. ANY
        # partition of the total fits - events {1,2}, {3} and {0.5,2.5}
        # are indistinguishable from two numbers - so the amount
        # composition is NOT established and verified would overclaim.
        # A single event keeps verified: its composition is unique.
        return _verdict(rule, False, TIER_CANNOT,
                        f"only the two endpoints are observed (total "
                        f"{total:.2f} -> 0, no interior plateau) with "
                        f"{len(dividend_events)} events {amounts} - any "
                        f"partition of the total fits the curve, so the "
                        f"amount composition is unverifiable; verified "
                        f"refused")
    if levels:
        prefix_targets = sorted(total - d for d in levels)
        if not _levels_partial_sums(amounts, prefix_targets):
            return _verdict(rule, False, TIER_CANNOT,
                            f"step level(s) {levels} imply running applied "
                            f"sums {prefix_targets} that are not prefix "
                            f"sums of any single ordering of the event "
                            f"amounts {amounts} - step heights "
                            f"inconsistent with the event table")
    return _verdict(rule, True, TIER_VERIFIED,
                    f"suspect column '{pcol}' = reference column "
                    f"'{rcol}' - cumulative future dividends: "
                    f"{len(dividend_events)} events, total {total:.2f}, "
                    f"step function verified over {len(diffs)} rows "
                    f"({len(distinct)} levels) - no date anchor in the "
                    f"event table, jump days unverified")


# ==========================================================================
# profile.202 - zombie contract (到期边界, verified by definition)
# ==========================================================================

def check_202(columns: list[str], rows: list[dict], meta: dict) -> list[dict]:
    """profile.202 僵尸合约: any row whose timestamp INSTANT falls after the
    contractual expiry is a zombie BY DEFINITION -> verified. Returns a
    LIST of verdicts: a symbol self-inconsistency no longer REPLACES the
    zombie scan (Cursor review round 9, finding 5 - an early return hid
    the post-expiry row count and the nonzero-volume signature behind the
    symbol verdict); both facts are emitted. The expiry
    itself is parsed like any stamp: a full timestamp (any offset) is
    normalized to UTC and the cutoff is that INSTANT. A DATE-ONLY expiry
    is a venue-local calendar date: a zombie is a row whose stamp's own
    WALL-CLOCK calendar date is strictly after the expiry date - the UTC
    instant is never consulted, because converting first made an 8pm
    US-Eastern stamp on expiry day cross the next UTC midnight and verify
    as a zombie, and certified the next venue-local morning clean
    (Cursor review round 10, finding 1; epoch-stamped rows fall back to
    the UTC date). INPUT PRECONDITION (red-team round 15, N-1): the
    wall-clock reading assumes stamps are written in the venue's LOCAL
    wall clock - a Zulu-written stamp (Z or +00:00 suffix) has no venue
    information and is read as a UTC wall date, so an expiry-day evening
    written in Z hides past the cutoff exactly as it would in UTC; convert
    such files to venue-local stamps before checking.
    Unparseable stamps mean ABSENCE of zombies is NOT established: any
    skipped stamp on a no-hit file downgrades to cannot_determine naming
    the skipped rows (round 8, finding 3); a positive zombie finding on
    the parseable subset is still a deterministic fact. Instrument
    symbols: a 6-digit run counts as an embedded expiry date only with a
    NON-DIGIT root before it (futures-style IF240615) - a pure numeric
    instrument id like 600519 has no separate contract date embedded
    (round 8, finding 5); the symbol check applies only to single-symbol
    files (a roll file legitimately carries several contracts)."""
    rule = "profile.202"
    if not rows:
        return [_verdict(rule, False, TIER_CANNOT, "no rows")]
    expiry = meta.get("expiry")
    if not expiry:
        return [_verdict(rule, False, TIER_CANNOT,
                         "no expiry in contract meta")]
    tcol = _time_col(columns)
    if tcol is None:
        return [_verdict(rule, False, TIER_CANNOT,
                         f"no date column found (time-axis names: "
                         f"{TIME_COLS} or {TIME_NAME_RE.pattern})")]
    s_exp = str(expiry).strip()
    date_only = False
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s_exp):
            exp_d = date.fromisoformat(s_exp)
            date_only = True  # zombie iff stamp's WALL-CLOCK date > exp_d
        else:
            cutoff = _stamp_utc(s_exp)  # full timestamp -> UTC instant
            # The SYMBOL-embedded date is a venue-local calendar date: it
            # must be compared against the expiry's WALL-CLOCK date, not
            # the UTC-shifted one (red-team round 11, R9-F2: expiry
            # 23:00-04:00 is local 06-15 but UTC 06-16 - an honest
            # IF240615 was called self-inconsistent). Best effort: an
            # epoch expiry falls back to the UTC date.
            try:
                exp_d = datetime.fromisoformat(s_exp).date()
            except ValueError:
                exp_d = cutoff.date()
    except (ValueError, OSError, OverflowError):
        return [_verdict(rule, False, TIER_CANNOT,
                         f"unparseable expiry in meta: {expiry!r}")]

    # Contract self-consistency: symbol-embedded YYMMDD runs vs expiry.
    # A run needs a non-digit root (round 8, finding 5). Known heuristic
    # bounds (red-team round 11, Notes 1-2): letter-prefixed stock codes
    # (SH600519) still read 600519 as a date (false positive surface),
    # and an 8-digit embedded date (c20240615) is missed because the
    # lookbehind blocks the overlapping second window - detection gaps,
    # never fabrications. The inconsistency is COLLECTED, not returned:
    # the zombie scan below runs regardless (round 9, finding 5).
    extra: list[dict] = []
    icol = _col(columns, "instrument", "symbol", "contract")
    if icol:
        symbols = {str(r[icol]) for r in rows}
        if len(symbols) == 1:
            sym = next(iter(symbols))
            valid: list[date] = []
            for m in re.findall(r"(?<=[^0-9])(?=(\d{6}))", sym):
                try:
                    valid.append(date(2000 + int(m[:2]), int(m[2:4]),
                                      int(m[4:6])))
                except ValueError:
                    continue  # digit run is not a date - try the next one
            if valid and exp_d not in valid:
                extra.append(_verdict(
                    rule, True, TIER_VERIFIED,
                    f"instrument symbol {sym} embeds expiry "
                    f"date(s) {[d.isoformat() for d in valid]} "
                    f"but none equals the contract field "
                    f"{expiry} - contract self-inconsistency"))

    cont, bad_rows = [], []
    for i, r in enumerate(rows):
        try:
            if date_only:
                # A DATE-ONLY expiry is a venue-local calendar date: the
                # stamp's own wall-clock calendar date decides, NOT its
                # UTC instant. Converting the stamp to UTC first made an
                # 8pm US-Eastern stamp on expiry day cross the next UTC
                # midnight and verify as a zombie - and certified the next
                # venue-local morning clean while its UTC instant was
                # still the previous UTC date (Cursor review round 10,
                # finding 1). The symbol check already compares
                # wall-clock dates; the zombie cutoff must too.
                sdate = _cal_date(r[tcol])
                zombie = sdate > exp_d
            else:
                zombie = _stamp_utc(r[tcol]) > cutoff
        except (ValueError, OSError, OverflowError):
            bad_rows.append((i, r[tcol]))
            continue
        if zombie:
            cont.append(r)
    if not cont:
        if bad_rows:
            sample = ", ".join(f"row {i}={v!r}" for i, v in bad_rows[:3])
            return extra + [_verdict(
                rule, False, TIER_CANNOT,
                f"{len(bad_rows)} unparseable timestamp(s) in "
                f"date column '{tcol}' ({sample}) - absence "
                f"of post-expiry rows is NOT established")]
        return extra + [_verdict(rule, False, TIER_VERIFIED,
                                 f"no rows after contractual expiry {expiry}")]

    skipped = (f" ({len(bad_rows)} unparseable timestamp(s) skipped)"
               if bad_rows else "")
    sig = [f"{len(cont)} rows dated after contractual expiry {expiry}"
           + skipped]
    vol_col = _col(columns, "volume")
    if vol_col:
        try:
            nz = sum(1 for r in cont if float(r[vol_col]) > 0)
        except ValueError:
            sig.append("volume column has unparseable values - "
                       "nonzero-volume signature skipped")
        else:
            if nz:
                sig.append(f"{nz} post-expiry rows with nonzero volume")
    mark_col, und_col = _col(columns, "mark"), _col(columns, "underlying")
    if mark_col and und_col:
        try:
            marks = {r[mark_col] for r in cont}
            unds = {float(r[und_col]) for r in cont}
            if len(marks) == 1 and len(unds) > 1:
                sig.append(f"mark frozen at {next(iter(marks))} "
                           f"while underlying moves")
        except ValueError:
            sig.append("mark/underlying columns have unparseable values - "
                       "frozen-mark signature skipped")
    iv_col = _col(columns, "iv")
    if iv_col and len(cont) >= 2:
        # One observation cannot establish a freeze (round 7, finding 11).
        ivs = {r[iv_col] for r in cont}
        if len(ivs) == 1:
            sig.append(f"iv frozen at {next(iter(ivs))}")
    st_col = _col(columns, "settle")
    if st_col and und_col:
        try:
            settles = {r[st_col] for r in cont}
            unds = {float(r[und_col]) for r in cont}
            if len(settles) == 1 and len(unds) > 1:
                sig.append(f"settle frozen at {next(iter(settles))} "
                           f"while underlying moves")
        except ValueError:
            sig.append("settle/underlying columns have unparseable values - "
                       "frozen-settle signature skipped")
    oi_col = _col(columns, "open_interest")
    if oi_col:
        try:
            oi = sum(1 for r in cont if float(r[oi_col]) > 0)
        except ValueError:
            sig.append("open_interest column has unparseable values - "
                       "positive-OI signature skipped")
        else:
            if oi:
                sig.append(f"{oi} post-expiry rows with positive open "
                           f"interest")
    return extra + [_verdict(rule, True, TIER_VERIFIED, "; ".join(sig))]


# ==========================================================================
# profile.203 - timestamp order violations (verified facts)
# ==========================================================================

def check_203(columns: list[str], rows: list[dict], meta: dict) -> dict:
    """profile.203 时间戳乱序: parsed-timestamp order violations are
    deterministic facts -> verified. Counts backward jumps, ADJACENT
    duplicates, and BY-VALUE duplicates (end-appended copies are not
    adjacent to their originals - corpus round-7 lesson). Every stamp is
    parsed with _stamp_utc: MIXED epoch units (seconds vs milliseconds)
    are therefore compared as UTC instants - an order violation, not a
    clean numeric timeline (Cursor review round 8, finding 2). A file
    mixing parseable and unparseable stamps is itself a verified defect,
    AND the order facts of the parseable subset are reported in the SAME
    verdict (round 8, finding 10: the mixed-format note used to replace
    a real backward jump). A pure NUMERIC timeline (integer/float row
    index - values too small to be epochs) is a legitimate time axis
    ONLY for a designated/named time column - raw price columns are never
    timelines (Cursor review round 6, finding 5)."""
    rule = "profile.203"
    if not rows:
        return _verdict(rule, False, TIER_CANNOT, "no rows")
    tcol = _time_col(columns)
    if tcol is None:
        return _verdict(rule, False, TIER_CANNOT,
                        "no time column identified - order check skipped")
    raws = [r[tcol] for r in rows]
    stamps: list[datetime] = []
    bad_idx: list[int] = []
    for i, s in enumerate(raws):
        try:
            stamps.append(_stamp_utc(s))
        except (ValueError, OSError, OverflowError):
            # same tuple as check_202/204: an extreme-offset stamp
            # (OverflowError in astimezone) is a skipped-and-counted row,
            # never a whole-run crash (red-team round 8, F3)
            bad_idx.append(i)

    def _order_facts(seq) -> tuple[int, int, int]:
        back = sum(1 for a, b in zip(seq, seq[1:]) if b < a)
        dup_adj = sum(1 for a, b in zip(seq, seq[1:]) if b == a)
        dup_by_value = len(seq) - len(set(seq))
        return back, dup_adj, dup_by_value

    if bad_idx and stamps:
        # Mixed parseable/unparseable: the format inconsistency is one
        # defect, but it must not REPLACE the order facts of the
        # parseable subset (round 8, finding 10).
        back, dup_adj, dup_by_value = _order_facts(stamps)
        return _verdict(rule, True, TIER_VERIFIED,
                        f"{len(bad_idx)} unparseable timestamp(s) mixed "
                        f"with parseable ones (first at row "
                        f"{bad_idx[0]}) - inconsistent stamp formats; "
                        f"{back} backward jumps, {dup_adj} adjacent "
                        f"duplicate stamps, {dup_by_value} "
                        f"duplicate-by-value rows on the parseable subset")

    if not bad_idx:
        # Every stamp parses (ISO and/or epoch in any unit mix): compare
        # UTC INSTANTS - mixed epoch units land years apart and are an
        # order violation (round 8, finding 2).
        back, dup_adj, dup_by_value = _order_facts(stamps)
        if back or dup_adj or dup_by_value:
            return _verdict(rule, True, TIER_VERIFIED,
                            f"{back} backward jumps, {dup_adj} adjacent "
                            f"duplicate stamps, {dup_by_value} "
                            f"duplicate-by-value rows")
        return _verdict(rule, False, TIER_VERIFIED, "monotonic, no duplicates")

    # Nothing parses as a stamp -> numeric index timeline? Cell-by-cell
    # coercion (Cursor review round 9, finding 3): one non-numeric cell
    # must not drop a real backward jump - order facts are computed on
    # the finite numeric subset and reported in the SAME verdict as the
    # skipped-cell count (the ISO mixed path already keeps both facts).
    nums: list[float] = []
    badn = 0
    for s in raws:
        try:
            nums.append(float(s))
        except (ValueError, TypeError):
            nums.append(float("nan"))
            badn += 1
    if badn == len(raws):
        return _verdict(rule, False, TIER_CANNOT,
                        "time column is neither ISO stamps nor numeric "
                        "- no order facts extractable")
    finite = [x for x in nums if math.isfinite(x)]
    # nf counts LITERAL non-finite values only - the coerced NaNs are
    # already counted as badn (double counting read like two defects per
    # cell; red-team round 13, NT-2).
    nf = (len(nums) - len(finite)) - badn
    back, dup_adj, dup_by_value = _order_facts(finite)
    skipped = []
    if badn:
        skipped.append(f"{badn} non-numeric cell(s)")
    if nf:
        skipped.append(f"{nf} non-finite value(s) (nan/inf)")
    if skipped:
        # Broken cells are themselves a deterministic file defect; the
        # subset order facts ride along instead of being replaced.
        return _verdict(rule, True, TIER_VERIFIED,
                        f"{'; '.join(skipped)} in the numeric timeline "
                        f"(order undefined there); {back} backward jumps, "
                        f"{dup_adj} adjacent duplicate stamps, "
                        f"{dup_by_value} duplicate-by-value rows on the "
                        f"{len(finite)}-value numeric subset")
    if back or dup_adj or dup_by_value:
        return _verdict(rule, True, TIER_VERIFIED,
                        f"numeric timeline: {back} backward jumps, "
                        f"{dup_adj} adjacent duplicate stamps, "
                        f"{dup_by_value} duplicate-by-value rows")
    return _verdict(rule, False, TIER_VERIFIED,
                    "numeric timeline monotonic, no duplicates")


# ==========================================================================
# profile.204 - full-sample statistics leak (never fake certainty)
# ==========================================================================

def check_204(columns: list[str], rows: list[dict], meta: dict) -> list[dict]:
    """profile.204 全样本统计泄漏. Signal = SELF-REFERENTIAL MOMENT
    IDENTITY: full-sample standardization makes the output's own moments
    EXACTLY (0, 1) (population or ddof=1 variants), or exact [0,1] min-max
    endpoints - computing those constants requires the whole series
    including the future, so no causal normalization can leave them.
    Exact centering alone (mean precisely ~0 relative to the column's own
    std) is the same measure-zero fingerprint. EVERY fully-numeric finite
    column is tested - a leaked ret column beside a raw close column must
    not hide behind column priority (Cursor review round 6, finding 10).
    All identity branches require n >= 30. LOW-CARDINALITY GUARDS: every
    identity branch requires >= max(10, n/2) distinct values (round 9,
    finding 4: the old 5-distinct floors let a designed 5-level value set
    hit exact (0,1) or exact [0,1] moments from CONSTRUCTION) - a balanced
    +-1 position column, a symmetric +-0.01 return column, or a designed
    -2..2 signal gets its exact moments from its VALUE SET, not from
    full-sample math (round 8, finding 9). The centering tolerance scales
    with the column's own std.
    Returns a LIST of verdicts: an as_of contract hit no longer suppresses
    the moment scan (round 8, finding 6 - returning early dropped a real
    (0,1) column on the same file), and if ANY time-column stamp is
    unparseable the as_of verdict is SKIPPED entirely - a skipped last
    stamp shrinks max(date) and fabricates an early data end, turning a
    same-day as_of into a fake full-sample leak. Tier stays suspicious
    for moment identities; verified is reserved for contract violations:
    meta as_of beyond the data end, where data end = MAX parsed stamp
    date (not the last row - newest-first files must not fake an early
    end; findings 4/11)."""
    rule = "profile.204"
    if len(rows) < 2:
        return [_verdict(rule, False, TIER_CANNOT, "too few rows")]
    out: list[dict] = []

    # Verified tier: contract self-violation (checkable fact). Data end =
    # MAX parsed stamp date, and as_of is UTC-normalized exactly like the
    # row stamps - a +09:00 as_of whose UTC instant lands inside the sample
    # must not fabricate a violation, and a mirror-shaped one must not be
    # missed (Cursor review round 7, finding 3).
    stats = meta.get("stats") or {}
    as_of = stats.get("as_of")
    if as_of:
        tcol = _time_col(columns)
        if tcol is not None:
            dates: list[date] = []
            bad_stamps = 0
            for r in rows:
                try:
                    dates.append(_stamp_utc(r[tcol]).date())
                except (ValueError, OSError, OverflowError):
                    bad_stamps += 1  # a skipped stamp shrinks max(date)
                    # and fakes an early data end - the whole as_of
                    # verdict is refused below (round 8, finding 6)
            if dates and not bad_stamps:
                last = max(dates)
                try:
                    if _stamp_utc(as_of).date() > last:
                        window = stats.get("window")
                        if window == "full_sample":
                            out.append(_verdict(
                                rule, True, TIER_VERIFIED,
                                f"meta stats as_of {as_of} beyond data "
                                f"end {last.isoformat()} with "
                                f"window=full_sample"))
                        else:
                            out.append(_verdict(
                                rule, True, TIER_SUSPICIOUS,
                                f"meta stats as_of {as_of} beyond data "
                                f"end {last.isoformat()} (window="
                                f"{window if window else 'unspecified'})"
                                f" - stats dated after the data they "
                                f"describe"))
                except (ValueError, OSError, OverflowError):
                    # same tuple as row stamps below and checks 202/203: an
                    # extreme-offset as_of is unparseable - the contract check
                    # is skipped (not fabricated), the moment-identity scan
                    # still runs (red-team round 9, F4)
                    pass

    # Suspicious tier: self-referential moment identities, per column.
    # Runs even after an as_of hit above (round 8, finding 6), and does
    # NOT stop at the first hit: every fingerprinted column is reported
    # (round 9, finding 4 - a 0/1 weight column before a real z-score
    # used to shadow it). Columns that cannot be scanned (bad cells,
    # overflow) are TRACKED: the final cannot verdict must never claim
    # "raw-like data" over columns it silently skipped (round 9,
    # finding 2 - absence of a fingerprint is not established there).
    skipped: list[str] = []
    nonnumeric = 0  # columns where EVERY cell failed coercion
    scanned = 0     # columns that actually reached the moment identities
    for cname in columns:
        vals, bad_cells = _coerce_numeric(rows, cname)
        if bad_cells == len(rows):
            # EVERY cell failed coercion: a non-numeric column (dates,
            # symbols, strings). It can never carry a moment identity, and
            # listing it as "skipped" claimed absence was not established
            # over a column that was never a fingerprint candidate - which
            # made a clean date+price file uncertifiable (Cursor review
            # round 10, finding 4). Silent skip: nothing numeric to scan.
            nonnumeric += 1
            continue
        n = len(vals)
        if n < IDENTITY_MIN_N:
            continue
        if bad_cells or not _finite_all(vals):
            skipped.append(f"'{cname}' (non-finite/non-numeric cell(s)"
                           f"{f': {bad_cells}' if bad_cells else ''})")
            continue
        scanned += 1
        try:
            mu = sum(vals) / n
            sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / n)
        except OverflowError:
            skipped.append(f"'{cname}' (OverflowError in moments)")
            continue  # finite but huge spread (1e300-class): the squared
            # deviations overflow - honest skip of THIS column, other
            # columns and checks still run (round-6 Fix-1)
        if sd == 0.0:
            continue  # constant column (all-zero volume of a halted instrument,
            # dead-contract OI): the mean is known from row 1, no full-sample
            # information exists, the measure-zero argument does not apply
            # (round-6 Fix-2) - genuinely nothing to scan, not a skipped
            # absence claim
        if not (math.isfinite(mu) and math.isfinite(sd)):
            # Overflowed accumulation: sum(vals) or the squared deviations
            # can silently overflow to inf even with finite inputs, and
            # inf <= 1e-6*inf is True - an inf-poisoned comparison pointing
            # AT a hit fabricates "exact centering" (red-team round 11,
            # R9-F1). Honest skip of THIS column, other columns still run.
            skipped.append(f"'{cname}' (moments overflowed to inf)")
            continue
        n_distinct = len(set(vals))
        lo, hi = min(vals), max(vals)
        ddof1_sd = math.sqrt((n - 1) / n)
        # All identity branches share one cardinality floor (round 9,
        # finding 4): a designed 5-level value set hits exact (0,1) or
        # exact [0,1] moments from CONSTRUCTION, not from full-sample
        # math - the old 5-distinct floor let it through. Continuous
        # full-sample output has ~n distinct values.
        distinct_floor = max(10, n // 2)
        if (n_distinct >= distinct_floor and abs(mu) < 1e-6
                and abs(sd - 1.0) < 1e-6):
            out.append(_verdict(rule, True, TIER_SUSPICIOUS,
                                f"column '{cname}': population moments (0,1) "
                                f"to within 1e-6: mean={mu:.2e}, "
                                f"std={sd:.9f} ({n_distinct} distinct "
                                f"values) - impossible for causal "
                                f"normalization or raw data (measure zero)"))
            continue
        if (n_distinct >= distinct_floor and abs(mu) < 1e-6
                and abs(sd - ddof1_sd) < 1e-6):
            # A z-score is CENTERED by definition: without the mean gate an
            # uncentered column that happens to carry sample-std 1 would be
            # called a z-score (Cursor review round 7, finding 9).
            out.append(_verdict(rule, True, TIER_SUSPICIOUS,
                                f"column '{cname}': centered (mean {mu:.2e}) "
                                f"with population std exactly {sd:.9f} = "
                                f"sqrt((n-1)/n) for n={n} ({n_distinct} "
                                f"distinct values), i.e. sample std "
                                f"(ddof=1) exactly 1 - fingerprint of a "
                                f"full-sample z-score with pandas .std() "
                                f"default ddof"))
            continue
        if (n_distinct >= distinct_floor and abs(sd - 1.0) < 1e-6
                and cname.lower() in {v.lower() for v in VOL_COLS}
                and meta.get("column_semantics") == "return"):
            # The semantics claim applies to return-NAMED columns only -
            # labelling whichever numeric column happened to have std ~1
            # as a "return column" was arbitrary (round 7, finding 9).
            # Same cardinality floor as the other branches: a designed
            # 5-level value set scaled to std 1 fires from CONSTRUCTION,
            # not from full-sample math (red-team round 13, NT-3).
            out.append(_verdict(rule, True, TIER_SUSPICIOUS,
                                f"column '{cname}': return column population "
                                f"std exactly {sd:.9f} (=100% daily vol, "
                                f"implausible + exact)"))
            continue
        if n_distinct >= distinct_floor and abs(mu) <= 1e-6 * sd:
            # Exact centering, with the tolerance scaled by the column's
            # own std (round 8, finding 9) and a cardinality floor: a
            # designed low-cardinality value set (cycling -2..2) carries
            # mean 0 from SYMMETRY, not from full-sample math; a real
            # z-score of continuous data has ~n distinct values.
            out.append(_verdict(rule, True, TIER_SUSPICIOUS,
                                f"column '{cname}': population mean "
                                f"{mu:.2e} <= 1e-6 of its own std "
                                f"{sd:.4g} over {n_distinct} distinct "
                                f"values - exact centering requires the "
                                f"full sample; measure-zero for raw data"))
            continue
        if (lo >= -1e-12 and hi <= 1.0 + 1e-12 and abs(lo) < 1e-9
                and abs(hi - 1.0) < 1e-9 and n_distinct >= distinct_floor):
            out.append(_verdict(rule, True, TIER_SUSPICIOUS,
                                f"column '{cname}': min-max fingerprint - "
                                f"exact [0,1] endpoints, all values inside "
                                f"({n_distinct} distinct values)"))
            continue
    if not out:
        if len(rows) < IDENTITY_MIN_N:
            # Zero columns were scanned: the n<30 gate short-circuits
            # before any coercion. Claiming "raw-like data" here would be
            # evidence stating something the code did NOT establish -
            # the same column at n=30 can fingerprint (red-team round 13,
            # FX-1).
            out.append(_verdict(rule, False, TIER_CANNOT,
                                f"n={len(rows)} below "
                                f"IDENTITY_MIN_N={IDENTITY_MIN_N} - moment "
                                f"identities not scanned; absence NOT "
                                f"established"))
        elif skipped:
            out.append(_verdict(rule, False, TIER_CANNOT,
                                f"no fingerprint in the scanned numeric "
                                f"columns; {len(skipped)} column(s) "
                                f"skipped: {', '.join(skipped)} - absence "
                                f"NOT established for skipped columns"))
        elif scanned == 0:
            # No column ever reached the moment identities: everything was
            # either entirely non-numeric (dates/symbols - C10-4 silent
            # skip) or a partial-numeric skip. Calling that "raw-like
            # data" would repeat the round-9 finding-2 overclaim through
            # the C10-4 back door (red-team round 15, FIX-2: a price
            # column of pure "N/A" or a date+symbol-only file certified
            # as clean).
            out.append(_verdict(rule, False, TIER_CANNOT,
                                f"no numeric column was fingerprint-"
                                f"scannable ({nonnumeric} column(s) "
                                f"entirely non-numeric"
                                + (f"; {len(skipped)} partial-numeric "
                                   f"skipped" if skipped else "")
                                + ") - raw-like NOT established"))
        else:
            out.append(_verdict(rule, False, TIER_CANNOT,
                                "no fingerprint in any numeric column "
                                "(raw-like data)"))
    elif skipped:
        # Hits and skipped columns coexist: the hits are positive facts,
        # but the skipped columns get an explicit disclosure instead of
        # vanishing silently (red-team round 13, NT-1).
        out.append(_verdict(rule, False, TIER_CANNOT,
                            f"{len(skipped)} column(s) skipped (not "
                            f"fingerprint-scanned): "
                            f"{', '.join(skipped)}"))
    return out


# ==========================================================================
# Sweep
# ==========================================================================

def profile(columns: list[str], rows: list[dict], meta: dict,
            reference: list[dict] | None = None,
            dividend_events: list | None = None) -> list[dict]:
    """Run all profile checks on one table+meta. Returns every verdict
    (fired or not) so callers can audit silence, not just hits.
    First verdict: schema contract - meta.columns (when present) must match
    the CSV header, else that mismatch is itself a verified defect."""
    out: list[dict] = []
    mcols = meta.get("columns")
    if mcols is not None and [str(c).strip() for c in mcols] != list(columns):
        out.append(_verdict(
            "profile.schema", True, TIER_VERIFIED,
            f"meta.columns {mcols} does not match CSV header {columns}"))
    out += check_201(columns, rows, meta, reference, dividend_events)
    out.extend(check_202(columns, rows, meta))
    out.append(check_203(columns, rows, meta))
    out.extend(check_204(columns, rows, meta))
    return out


# ==========================================================================
# Corpus gate (Phase 1 acceptance run by the Phase 2 student)
# ==========================================================================

# Gate wiring (operator config, NOT read by the detectors): mirror pairs
# documented in tests/corpus/README.md. The reference series + event table
# are handed to the profiler exactly like a human operator would.
MIRROR_REFERENCES = {
    "PRF-201-01": ("clean/data/data_case_01.csv",
                   "clean/data/data_case_01.csv.meta.json"),
}


def run_gate(corpus_dir: Path) -> tuple[bool, dict]:
    expected = json.loads(
        (corpus_dir / "expected_results.json").read_text(encoding="utf-8"))
    report: dict = {"profiler_version": PROFILER_VERSION,
                    "corpus_version": expected["corpus_version"],
                    "samples": [], "pass": True}
    n_pass = n_fail = 0
    for s in expected["samples"]:
        if s["module"] != "profile":
            continue  # lint samples are Phase 4 scope
        path = corpus_dir / s["path"]
        cols, rows = load_table(path)
        meta = json.loads(
            (path.with_suffix(path.suffix + ".meta.json"))
            .read_text(encoding="utf-8"))
        ref_rows = ref_events = None
        if s["id"] in MIRROR_REFERENCES:
            rp, rm = (Path(corpus_dir / MIRROR_REFERENCES[s["id"]][0]),
                      Path(corpus_dir / MIRROR_REFERENCES[s["id"]][1]))
            _, ref_rows = load_table(rp)
            ref_events = json.loads(rm.read_text(encoding="utf-8")) \
                .get("dividend_events", [])
        verdicts = profile(cols, rows, meta, ref_rows, ref_events)
        exp = s["expected"]
        fired = [v for v in verdicts if v["fired"]]

        if exp["caught"]:
            rules_ok = all(r in {v["rule"] for v in fired}
                           for r in exp["rules"])
            tier_ok = any(v["tier"] == exp.get("tier", TIER_VERIFIED)
                          for v in fired if v["rule"] in exp["rules"])
            # Answer-key token locks: evidence_must_include must appear in
            # the fired evidence of an intent-rule verdict (same discipline
            # as the corpus build harness - a listed token that nothing
            # reads is decoration).
            tokens_ok = all(
                any(tok in v["evidence"] for v in fired
                    if v["rule"] in exp["rules"])
                for tok in exp.get("evidence_must_include", []))
            ok = rules_ok and tier_ok and tokens_ok
            why = None if ok else (
                f"expected rules {exp['rules']} tier {exp.get('tier')} "
                f"tokens {exp.get('evidence_must_include', [])}; "
                f"fired={[(v['rule'], v['tier'], v['evidence'][:60]) for v in fired]}")
        else:
            ok = not fired
            why = None if ok else f"clean/discipline sample fired: {fired}"

        report["samples"].append({"id": s["id"], "path": s["path"],
                                  "pass": ok, "why": why,
                                  "verdicts": verdicts})
        n_pass += ok
        n_fail += not ok
        report["pass"] &= ok
    report["summary"] = {"pass": n_pass, "fail": n_fail,
                         "total": n_pass + n_fail}
    return report["pass"], report


def main() -> None:
    ap = argparse.ArgumentParser(description="backtest-lint profiler")
    ap.add_argument("command", choices=["check", "gate"])
    ap.add_argument("csv", nargs="?", help="csv to check (command=check)")
    ap.add_argument("--meta", help="meta json for check")
    ap.add_argument("--reference", help="raw reference csv (201 mode A)")
    ap.add_argument("--events", help="corporate-action events json")
    ap.add_argument("--corpus", default="tests/corpus",
                    help="corpus dir for gate")
    args = ap.parse_args()

    if args.command == "check":
        if not args.csv:
            ap.error("check requires a csv path")
        payload: dict = {"profiler_version": PROFILER_VERSION,
                         "file": args.csv}
        try:
            cols, rows = load_table(Path(args.csv))
            meta = (json.loads(Path(args.meta).read_text(encoding="utf-8"))
                    if args.meta else {})
            ref = ev = None
            if args.reference:
                _, ref = load_table(Path(args.reference))
                ev = (json.loads(Path(args.events).read_text(encoding="utf-8"))
                      if args.events else {}).get("dividend_events", [])
            payload["verdicts"] = profile(cols, rows, meta, ref, ev)
        except Exception as e:  # robustness contract: NO input shape crashes
            # Broken input is an explicit error JSON, never a traceback.
            payload["error"] = f"{type(e).__name__}: {e}"
            payload["verdicts"] = []
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            sys.exit(2)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    try:
        ok, report = run_gate(Path(args.corpus))
    except Exception as e:  # gate mode honors the no-crash contract too;
        # exit 3 distinguishes a profiler bug from a gate failure (exit 1).
        print(json.dumps({"profiler_version": PROFILER_VERSION,
                          "gate_error": f"{type(e).__name__}: {e}"},
                         ensure_ascii=False))
        sys.exit(3)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
