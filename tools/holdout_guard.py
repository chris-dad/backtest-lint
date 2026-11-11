#!/usr/bin/env python3
"""backtest-lint holdout_guard (Phase 3, guard-lite): one-time holdout gate.

Version: only GUARD_VERSION below is authoritative - never restate it.
Contract: RUN_FOLDER_CONTRACT.md (repo root) - CONTRACT_VERSION below must
equal the version in that file's title (asserted in selftest, round-18 m-1).

Review history (Cursor: a separate agent from the implementer, not a third-party audit):
  round-17 (internal adversarial-verifier): PASS w/ 3 Major -> fixed in 0.1.1
  round-18 (Cursor review): FAIL - 1 Blocker (B-1), 8 Major (M-1..M-8),
  6 Minor (m-1..m-6) -> ALL fixed in 0.1.2.
  round-19 (Cursor review re-verify): FAIL - 1 Blocker + 2 Major + 3 Minor
  (all in the credit-granting path, none locked by the 90 assertions)
  -> ALL fixed in 0.1.3:
     B-1  credit now requires LOG evidence: state.snapshot, EVERY log
          event's snapshot, the current holdout and the current equity
          span must agree four-ways; mark-read writes the LOG FIRST then
          the state (a two-step crash can only leave log-without-state,
          which check reads as NOT read).
     M-1  the snapshot binds a by_asset FINGERPRINT (normalized stem +
          first/last per scanned csv, plus the non-csv names); a file
          added after consumption invalidates the credit like A11.
     M-2  start mode: unscanned non-csv entries forbid a verified
          "not reached" -> cannot_determine naming them (aligns coins
          mode M-5).
     m-1  a snapshot-mismatched credit reads holdout_read=false even
          when this round triggers no exposure, with the same
          invalidation warning.
     m-2  mark-read refuses (exit 2, no rewrite of the original file)
          when the log is a recognizable shape containing a holdout_read
          event - including the top-level-array form; unrecognizable
          shapes stay explicit GuardInputError, never a silent reset to
          {"events": []}. mark-read shares the check-side structural
          holdout validation (both-keys holdout -> exit 2).
     m-3  --help (SystemExit 0) no longer gets the error-JSON envelope.
     plus (未升格, adopted): coin-name normalization now includes NFKC
     compatibility equivalence - fullwidth lookalike stems can no longer
     dodge a held-out coin match (contract section 3 documents this).
  round-20 (Cursor review re-verify): FAIL - 1 Major (M-1 residual) +
  Minor substring locks -> ALL fixed in 0.1.4:
     M-1r the fingerprint was a normalized-stem-KEYED dict: two files
          normalizing to the same token (e.g. ' ACME.csv' vs 'ACME.csv')
          collapsed into one entry, last-write-wins - the surviving entry
          kept the credit alive while the collidee still fed scan_last.
          The fingerprint is now a PER-FILE record list (raw filename +
          normalized stem + first/last, sorted by filename): two files
          are two records, always.
     minor the round-19 handoff's evidence/warning substrings are now
          themselves locked by net-new assertions (R20-L*), and the three
          collision filenames are locked (R20-M1-C1..C3).
  round-21 (Cursor review re-verify): FAIL - 1 Major (M-1 residual:
  the blind spot moved from the fingerprint dict to by_asset_stats'
  Path.stem key) -> ALL fixed in 0.1.5:
     M-1r2 'ACME.csv' and 'ACME.CSV' share Path.stem 'ACME' but are TWO
          files on a case-sensitive volume; by_asset_stats collapsed
          them last-write-wins, so the loser's dates fed neither the
          date trigger (scan_last) nor the fingerprint. The stats map
          is now keyed by RAW FILENAME (unique inside by_asset/) and
          the fingerprint/parking lookups follow suit - no derived
          name (stem, normalized token) may ever be an accounting key;
          derived names are for MATCHING only.
     new   R21-M1 assertions: a dual same-stem pair (ACME.csv 30 days +
          ACME.CSV 600 days, fed via a synthetic dir-state on volumes
          that cannot host both names) must BLOCK pre-consumption
          (loser last >= start), and extending the loser's dates after
          consumption must invalidate the credit.

Core semantics (tightened by round-18):
  - equity dates reach the holdout start, or by_asset/ contains a held-out
    coin  ->  BLOCKED (exit 1) unless the holdout was formally consumed via
    `mark-read` (one-time).
  - Consumption credit is bound to a SNAPSHOT taken at mark-read time: the
    holdout object itself + equity first/last dates + a by_asset
    FINGERPRINT (round-19 M-1). If the current folder's holdout, equity
    span or by_asset contents no longer match the snapshot, the credit is
    INVALID -> fail-closed BLOCKED (round-18 B-1: an engine-side run.json /
    equity.csv edit must not be able to launder an unseen holdout as read;
    round-19 B-1/M-1: neither may a log-less state or a post-consumption
    by_asset file).
  - The credit requires BOTH guard_state.json (holdout_read exactly JSON
    true, round-18 M-2) AND an append-log event. State w/o log = NOT read.
    Log event w/o confirming state = NOT read + warning, and the log event
    alone refuses any further mark-read (round-18 M-1). round-19 B-1: the
    credit ALSO requires every log holdout_read event's snapshot to equal
    the state snapshot - state alone (even with a matching-looking
    snapshot) proves nothing.
  - calendar missing/illegal in run.json  ->  structural error (exit 2);
    the toolkit never guesses the calendar.
  - by_asset/ subdirectories  ->  fail-closed BLOCKED in EVERY holdout mode
    (round-18 M-6: previously only the coins branch checked).
  - holdout with BOTH start and coins  ->  structural error (round-18 M-7).
  - Time columns: every column whose casefolded name is a known time column
    is scanned; casefolded duplicate time-column names -> exit 2; the span
    is the min/max across ALL of them (round-18 M-8). Date literals are
    compared as the calendar face before 'T' - timezone offsets are NOT
    converted (round-18 m-4 decision, documented in the contract).
  - start mode ALSO scans by_asset dates: the date trigger is the max date
    across equity.csv and every scanned by_asset csv (round-18 m-6, chosen
    fail-closed option, documented in the contract).
  - by_asset files shorter than MIN_DAYS (DISTINCT calendar days) are
    PARKED, never silently dropped.

Honest tiering (same agreement as profiler.py):
  verified          deterministic fact from the run folder itself.
  cannot_determine  the folder does not hold what the check needs (missing
                    by_asset dir, no top-level csv, unscannable non-csv
                    entries, prefix-lookalike coin names). Emitting this
                    tier is CORRECT behaviour - and it MUST name the
                    unscanned/lookalike entries (round-18 M-3/M-4/M-5: a
                    verdict may never claim "absent" while such files sit
                    in the folder).

Robustness contract: NO input shape may crash the guard. Structurally broken
input produces an error JSON on exit 2 - never a traceback. exit 2 always
carries a stdout JSON envelope (round-18 m-3: argparse usage errors too).

CLI (stdlib only, no third-party deps):
  check      : python3 tools/holdout_guard.py check <run_folder>
               [--min-days N]  -> verdict JSON (exit 0 pass / 1 blocked /
               2 broken input)
  mark-read  : python3 tools/holdout_guard.py mark-read <run_folder> [--note S]
               -> record the ONE-TIME holdout consumption (exit 0; exit 2 on
               refusal: already consumed, nothing to consume, broken input)
  selftest   : python3 tools/holdout_guard.py selftest
               -> built-in positive+negative control probe on temp fixtures
               (exit 0 all pass / 1 failure)
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

GUARD_VERSION = "0.1.5"
CONTRACT_VERSION = "0.1.5"

EXIT_PASS = 0         # documented + asserted in selftest (contract section 6)
EXIT_BLOCKED = 1      # documented + asserted in selftest
EXIT_INPUT_ERROR = 2  # documented + asserted in selftest

MIN_DAYS = 180        # contract section 3 default; asserted in selftest

CALENDARS = ("crypto", "tradfi")
TIME_COLS = ("date", "timestamp", "trade_date", "t", "ts", "time")

STATE_FILE = "guard_state.json"
LOG_FILE = "guard_log.json"
RUN_FILE = "run.json"
EQUITY_FILE = "equity.csv"


class GuardInputError(ValueError):
    """Structurally broken input -> exit 2 with an error JSON."""


def _norm_token(s: object) -> str:
    """Normalization for coin-name identity matching (round-18 M-4):
    NFKC compatibility equivalence (round-19 adopted: fullwidth lookalike
    stems like 'ＡＡＡ.csv' can no longer dodge a held-out coin match),
    strip whitespace, casefold, drop ALL internal whitespace."""
    return "".join(unicodedata.normalize("NFKC", str(s)).strip()
                   .casefold().split())


# ==========================================================================
# Loading helpers (no-crash: every malformed shape raises GuardInputError)
# ==========================================================================

def load_run(run_folder: Path) -> dict:
    path = run_folder / RUN_FILE
    if not path.is_file():
        raise GuardInputError(f"{RUN_FILE} missing in {run_folder}")
    try:
        run = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise GuardInputError(f"{RUN_FILE} unparseable: {e}") from e
    if not isinstance(run, dict):
        raise GuardInputError(f"{RUN_FILE} must be a JSON object")
    if "calendar" not in run:
        # Contract: the toolkit never guesses the calendar.
        raise GuardInputError(f"{RUN_FILE}: 'calendar' missing (never guessed)")
    if run["calendar"] not in CALENDARS:
        raise GuardInputError(
            f"{RUN_FILE}: calendar must be one of {list(CALENDARS)}, "
            f"got {run['calendar']!r}")
    if "holdout" not in run:
        # holdout is three-state (null | {start} | {coins}); the KEY itself
        # must exist so an omitted holdout cannot masquerade as "no holdout".
        raise GuardInputError(f"{RUN_FILE}: 'holdout' key missing "
                              f"(use null for no holdout)")
    return run


def _parse_date_str(s: str) -> date:
    # Calendar-face semantics (round-18 m-4 decision, contract section 3):
    # compare the literal before 'T'/' space'; offsets are NOT converted.
    token = str(s).strip().split("T")[0].split(" ")[0]
    try:
        return date.fromisoformat(token)
    except ValueError as e:
        raise GuardInputError(f"unparseable date {s!r}") from e


def read_time_table(path: Path, label: str) -> dict:
    """Parse a csv with one or more recognized time columns.

    Returns {"first": date, "last": date, "rows": int, "days": int} where
    `days` counts DISTINCT calendar days across all time columns (parking
    semantics, round-17 Major-2) and the span is the min/max across ALL
    recognized time columns (round-18 M-8: first-match lost the contract's
    date column to a differently-cased duplicate).
    """
    if not path.is_file():
        raise GuardInputError(f"{label}: file missing")
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise GuardInputError(f"{label}: empty file (no header)")
        cols = [h.strip() for h in header]
        if len(set(cols)) != len(cols):
            raise GuardInputError(f"{label}: duplicate column names")
        time_idx = [i for i, c in enumerate(cols) if c.lower() in TIME_COLS]
        if not time_idx:
            raise GuardInputError(
                f"{label}: no time column (looked for {TIME_COLS})")
        time_names = [cols[i].lower() for i in time_idx]
        if len(set(time_names)) != len(time_names):
            raise GuardInputError(
                f"{label}: duplicate time-column names after case-folding "
                f"{time_names} (round-18 M-8)")
        first = last = None
        days: set[date] = set()
        n = 0
        for lineno, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue  # fully blank line is not data
            if len(row) != len(cols):
                raise GuardInputError(
                    f"{label} line {lineno}: ragged row "
                    f"({len(row)} cells vs {len(cols)} columns)")
            for i in time_idx:
                d = _parse_date_str(row[i])
                if first is None or d < first:
                    first = d
                if last is None or d > last:
                    last = d
                days.add(d)
            n += 1
        if n == 0:
            raise GuardInputError(f"{label}: header only, no data rows")
    return {"first": first, "last": last, "rows": n, "days": len(days)}


def by_asset_dir_state(run_folder: Path) -> dict:
    """Classify by_asset/ contents (round-18 M-3/M-5):
    {"present", "subdirs", "csvs": [(stem, Path)], "non_csv"} - csv
    detection is CASE-INSENSITIVE on the extension (AAA.CSV counts)."""
    d = run_folder / "by_asset"
    if not d.is_dir():
        return {"present": False, "subdirs": [], "csvs": [], "non_csv": []}
    subdirs: list[str] = []
    csvs: list[tuple[str, Path]] = []
    non_csv: list[str] = []
    for p in sorted(d.iterdir()):
        if p.is_dir():
            subdirs.append(p.name)
        elif p.suffix.lower() == ".csv":
            csvs.append((p.stem, p))
        else:
            non_csv.append(p.name)
    return {"present": True, "subdirs": subdirs, "csvs": csvs,
            "non_csv": non_csv}


def by_asset_stats(csvs: list[tuple[str, Path]]) -> dict:
    """Per-asset {"days", "first", "last"} for parking + start-mode scan.
    Keyed by the RAW FILENAME (round-21): never Path.stem - 'ACME.csv' and
    'ACME.CSV' share the stem 'ACME' but are two files on a case-sensitive
    volume, and a stem-keyed dict collapsed them last-write-wins so the
    loser's dates fed neither the date trigger nor the fingerprint.
    Derived names (stem, normalized token) are for MATCHING only, never
    for accounting keys; filenames are unique inside by_asset/."""
    out: dict[str, dict] = {}
    for stem, path in csvs:
        out[path.name] = read_time_table(path, f"by_asset/{path.name}")
    return out


def load_guard_state(run_folder: Path) -> tuple[dict | None, list[str]]:
    """Return (state_or_None, warnings). Any ambiguity -> (None, warning):
    fail-closed means an unreadable state counts as NOT read."""
    warnings: list[str] = []
    path = run_folder / STATE_FILE
    if not path.is_file():
        return None, warnings
    try:
        state = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        warnings.append(f"{STATE_FILE} unparseable -> treated as NOT read "
                        f"(fail-closed)")
        return None, warnings
    if not isinstance(state, dict) or "holdout_read" not in state:
        warnings.append(f"{STATE_FILE} malformed -> treated as NOT read "
                        f"(fail-closed)")
        return None, warnings
    return state, warnings


def read_credit(run_folder: Path) -> dict:
    """Consumption-credit evaluation. Returns
    {"claimed": bool, "logged": bool, "events": [dict], "state": dict|None,
     "warnings": [...]} where `events` are the exact-action holdout_read
    event objects (round-19 B-1: their snapshots are the credit's
    evidence and must agree with the state snapshot).

    Rules:
      M-2 (round-18)  claimed requires state.holdout_read to be EXACTLY
                      JSON true; any other type -> NOT read + warning.
      M-1 (round-18)  logged requires an exact-action holdout_read event;
                      logged-but-not-claimed -> warning (folder state is
                      inconsistent).
      round-17        claimed-but-not-logged -> fail-closed NOT read.
      m-5 (round-18)  an events list containing non-object entries is a
                      STRUCTURAL error (exit 2), not an ambiguity.
    """
    warnings: list[str] = []
    state, w = load_guard_state(run_folder)
    warnings.extend(w)

    claimed = False
    if state is not None:
        val = state.get("holdout_read")
        if val is True:
            claimed = True
        else:
            warnings.append(
                f"{STATE_FILE} holdout_read is not JSON true "
                f"(got {type(val).__name__}: {val!r}) -> treated as NOT "
                f"read (round-18 M-2)")

    logged = False
    read_events: list[dict] = []
    log_path = run_folder / LOG_FILE
    if log_path.is_file():
        try:
            log = json.loads(log_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            warnings.append(f"{LOG_FILE} unparseable -> read event NOT "
                            f"credited (fail-closed)")
            log = None
        if isinstance(log, dict) and isinstance(log.get("events"), list):
            for e in log["events"]:
                if not isinstance(e, dict):
                    raise GuardInputError(
                        f"{LOG_FILE} events contain a non-object entry "
                        f"(structural, round-18 m-5)")
            read_events = [e for e in log["events"]
                           if e.get("action") == "holdout_read"]
            logged = bool(read_events)
        elif log is not None:
            warnings.append(f"{LOG_FILE} malformed (expected object with "
                            f"'events' list) -> read event NOT credited "
                            f"(fail-closed)")

    if claimed and not logged:
        warnings.append(f"{STATE_FILE} claims holdout_read but {LOG_FILE} "
                        f"has no event -> fail-closed: treated as NOT read")
    if logged and not claimed:
        warnings.append(f"{LOG_FILE} already records a holdout_read event "
                        f"but {STATE_FILE} does not confirm it -> treated "
                        f"as NOT read (round-18 M-1)")

    return {"claimed": claimed, "logged": logged, "events": read_events,
            "state": state, "warnings": warnings}


def log_read_at(run_folder: Path) -> str:
    """Consumption timestamp cited from the APPEND LOG (round-17 Minor-7 +
    round-18 m-2 lock: never the editable state.read_at)."""
    path = run_folder / LOG_FILE
    try:
        log = json.loads(path.read_text(encoding="utf-8-sig"))
        for e in log.get("events", []):
            if isinstance(e, dict) and e.get("action") == "holdout_read":
                return str(e.get("at", "unknown"))
    except Exception:
        pass
    return "unknown"


# ==========================================================================
# Core evaluation
# ==========================================================================

def _by_asset_fingerprint(bas: dict, bas_stats: dict) -> dict:
    """round-19 M-1 + round-20 M-1 residual: stable fingerprint of the
    by_asset/ contents at mark-read time, kept as a PER-FILE record list -
    {"present": false} when the directory is absent; otherwise one record
    {file, stem, first, last} per SCANNED CSV PATH (raw filename +
    normalized stem + first/last date), sorted by raw filename, plus the
    sorted non-csv names. A normalized-stem-KEYED dict is FORBIDDEN here
    (round-20): two files normalizing to the same token (' ACME.csv' /
    'ACME .csv' / 'A CME.csv' / 'ＡＣＭＥ.csv' vs 'ACME.csv') are TWO records -
    a dict would collapse them last-write-wins and let a collidee that
    still feeds the date trigger escape the fingerprint. Any file
    added/removed/renamed/dated-differently after consumption changes this
    fingerprint and invalidates the credit (same treatment as an A11
    equity extension)."""
    if not bas.get("present"):
        return {"present": False}
    records: list[dict] = []
    for stem, path in bas.get("csvs", []):
        # round-21: stats are keyed by RAW FILENAME, never stem - the
        # same-stem dual-path pair (ACME.csv / ACME.CSV) is two entries.
        st = bas_stats.get(path.name)
        if st is not None:
            records.append({
                "file": path.name,
                "stem": _norm_token(stem),
                "first": st["first"].isoformat(),
                "last": st["last"].isoformat(),
            })
    records.sort(key=lambda r: (r["file"], r["stem"]))
    return {"present": True, "assets": records,
            "non_csv": sorted(bas.get("non_csv", []))}


def _validate_holdout(run: dict) -> None:
    """Structural holdout validation shared by check AND mark-read
    (round-19 m-2: mark-read must not accept what check would reject).
    Exactly one of null | {start} | {coins}; coins a non-empty list of
    strings; start a parseable date. Raises GuardInputError -> exit 2."""
    holdout = run["holdout"]
    if holdout is None:
        return
    if not isinstance(holdout, dict) or (
            "start" not in holdout and "coins" not in holdout):
        raise GuardInputError(
            "run.json holdout must be null or an object with 'start' or "
            f"'coins', got {holdout!r}")
    if "start" in holdout and "coins" in holdout:
        # round-18 M-7: the contract defines exactly one of
        # null | {start} | {coins} - compound holdout = structural.
        raise GuardInputError(
            "run.json holdout has BOTH 'start' and 'coins': the "
            "contract defines exactly one of null | {start} | {coins}")
    if "start" in holdout:
        try:
            _parse_date_str(holdout["start"])
        except GuardInputError as e:
            raise GuardInputError(f"run.json holdout.start: {e}") from e
    else:
        coins = holdout["coins"]
        if not isinstance(coins, list) or not coins:
            raise GuardInputError(
                "run.json holdout.coins must be a non-empty list")
        if not all(isinstance(c, str) for c in coins):
            # round-18 m-5: non-string coins were a bare TypeError.
            raise GuardInputError(
                "run.json holdout.coins must contain only strings")


def _verdict(check: str, fired: bool, tier: str, evidence: str) -> dict:
    return {"check": check, "fired": fired, "tier": tier, "evidence": evidence}


def _credit_valid(credit: dict, holdout: object, eq_first: date,
                  eq_last: date,
                  fingerprint: dict) -> tuple[bool, str]:
    """round-18 B-1 + round-19 B-1/M-1: a consumption credit is only valid
    when ALL of the following hold (fail-closed otherwise: NOT read):
      1. the state claims holdout_read (EXACTLY JSON true, round-18 M-2);
      2. the append log BACKS it with >= 1 holdout_read event (round-19
         B-1: state alone proves nothing);
      3. the state snapshot is a dict that still matches the CURRENT
         folder: holdout object, equity first/last, by_asset fingerprint
         (round-19 M-1);
      4. EVERY log holdout_read event's snapshot equals the state
         snapshot (round-19 B-1: the log is the tamper-resistant copy -
         a state-only edit cannot launder a different window).
    """
    if not credit.get("claimed"):
        return False, ("state does not claim holdout_read as JSON true -> "
                       "treated as NOT read")
    state = credit.get("state") or {}
    snap = state.get("snapshot")
    if not isinstance(snap, dict):
        return False, ("consumption credit has no snapshot -> fail-closed: "
                       "treated as NOT read; re-evaluate the holdout and "
                       "consume fresh")
    if not credit.get("logged"):
        return False, (f"{STATE_FILE} claims holdout_read but {LOG_FILE} "
                       f"has no holdout_read event -> fail-closed: treated "
                       f"as NOT read; a new holdout must be chosen and "
                       f"consumed fresh")
    reasons = []
    if snap.get("holdout") != holdout:
        reasons.append("holdout config changed since consumption")
    if snap.get("equity_first") != eq_first.isoformat():
        reasons.append("equity first date changed since consumption")
    if snap.get("equity_last") != eq_last.isoformat():
        reasons.append("equity last date changed since consumption")
    if snap.get("by_asset") != fingerprint:
        reasons.append("by_asset fingerprint changed since consumption "
                       "(round-19 M-1)")
    for i, ev in enumerate(credit.get("events", []), start=1):
        if ev.get("snapshot") != snap:
            reasons.append(
                f"log holdout_read event #{i} snapshot differs from the "
                f"state snapshot (round-19 B-1)")
    if reasons:
        return False, ("consumption credit INVALID: " + "; ".join(reasons)
                       + " -> fail-closed: treated as NOT read; a new "
                         "holdout must be chosen and consumed fresh "
                         f"(clear {STATE_FILE}/{LOG_FILE} and re-evaluate)")
    return True, ""


def _match_coins(coins: list, stems: list[str]) -> tuple[list[str],
                                                         list[str]]:
    """round-18 M-4. Returns (exposed, lookalikes).
    exposed: coins whose normalized token exactly matches a stem token.
    lookalikes: no exact match, but a prefix relation between the
    normalized coin and some normalized stem (coin 'AAA' vs stem 'AAA.csv'
    from 'AAA.csv.csv'; coin 'AAA.csv' vs stem 'AAA')."""
    stem_norms = {_norm_token(s) for s in stems}
    exposed = sorted({c for c in coins if _norm_token(c) in stem_norms})
    if exposed:
        return exposed, []
    lookalikes = sorted({
        stem for stem in stems for c in coins
        if (na := _norm_token(c)) and (ns := _norm_token(stem))
        and (ns.startswith(na) or na.startswith(ns))
    })
    return [], lookalikes


def evaluate(run_folder: Path, min_days: int = MIN_DAYS) -> tuple[dict, int]:
    """Full `check` evaluation. Returns (payload, exit_code)."""
    run = load_run(run_folder)  # raises GuardInputError -> exit 2
    # equity.csv is a REQUIRED contract file in every branch: validate its
    # shape unconditionally (round-17 selftest 6N caught the null-holdout
    # branch skipping this check).
    eq = read_time_table(run_folder / EQUITY_FILE, EQUITY_FILE)
    warnings: list[str] = []
    verdicts: list[dict] = []
    blocked = False

    # Contract field sanity beyond calendar/holdout: warned, not fatal (the
    # guard's job is holdout exposure; research_kit owns the rest).
    for field in ("benchmark", "period", "data_source", "costs",
                  "tried_variants"):
        if field not in run:
            warnings.append(f"run.json: recommended field '{field}' missing")

    # round-18 M-6: by_asset subdirectories are fail-closed in EVERY
    # holdout mode (null / start / coins) - held-out data hides there.
    bas = by_asset_dir_state(run_folder)
    if bas["subdirs"]:
        verdicts.append(_verdict(
            "holdout.exposure", True, "verified",
            f"by_asset/ contains unscanned subdirectories {bas['subdirs']}: "
            f"held-out coins or post-holdout dates could hide there, "
            f"fail-closed BLOCKED (flatten by_asset/ to top-level "
            f"*.csv files)"))
        blocked = True

    credit = read_credit(run_folder)
    warnings.extend(credit["warnings"])

    bas_stats: dict = {}
    if bas["present"] and not bas["subdirs"]:
        bas_stats = by_asset_stats(bas["csvs"])

    # round-19 M-1: fingerprint of the scanned by_asset contents, bound
    # into the credit snapshot at mark-read time and compared here.
    fingerprint = _by_asset_fingerprint(bas, bas_stats)

    # round-19 B-1/m-1: credit validity is computed ONCE against the
    # current folder and used BOTH for the exposure branches and for the
    # payload's holdout_read flag (which must be false even when this
    # round triggers no exposure).
    credit_valid = False
    credit_why = "no holdout configured"
    if not blocked and isinstance(run["holdout"], dict):
        credit_valid, credit_why = _credit_valid(
            credit, run["holdout"], eq["first"], eq["last"], fingerprint)

    if not blocked:
        holdout = run["holdout"]
        # round-19 m-2: shared structural validation (check + mark-read).
        _validate_holdout(run)
        if holdout is None:
            verdicts.append(_verdict(
                "holdout.config", False, "verified",
                "holdout is null: no holdout configured, nothing to guard"))
            if credit["claimed"]:
                warnings.append("stale consumption credit present while "
                                "holdout is null; ignored")
        elif isinstance(holdout, dict) and "start" in holdout:
            h_start = _parse_date_str(holdout["start"])
            # round-18 m-6 (chosen fail-closed option): the date trigger is
            # the max date across equity.csv AND every scanned by_asset csv
            # - post-holdout per-asset data in the folder is exposure too.
            scan_last = eq["last"]
            for st in bas_stats.values():
                if st["last"] > scan_last:
                    scan_last = st["last"]
            reached = scan_last >= h_start
            if not reached:
                if bas["non_csv"]:
                    # round-19 M-2: align with coins-mode M-5 - an
                    # unscanned non-csv entry makes the not-reached claim
                    # unverifiable; never a verified verdict naming
                    # nothing. (evidence must not contain "not reached".)
                    verdicts.append(_verdict(
                        "holdout.exposure", False, "cannot_determine",
                        f"max scanned date {scan_last.isoformat()} "
                        f"(equity + by_asset) < holdout start "
                        f"{h_start.isoformat()}, but by_asset/ holds "
                        f"UNSCANNED non-csv entries {bas['non_csv']}: the "
                        f"date-trigger absence cannot be verified"))
                    warnings.append(f"unscanned non-csv entries in "
                                    f"by_asset/: {bas['non_csv']}")
                else:
                    verdicts.append(_verdict(
                        "holdout.exposure", False, "verified",
                        f"max scanned date {scan_last.isoformat()} (equity + "
                        f"by_asset) < holdout start {h_start.isoformat()}: "
                        f"not reached"))
                # round-19 m-1: a stale/mismatched credit must not leave
                # holdout_read=true just because no exposure fired here.
                if credit["claimed"] and not credit_valid:
                    warnings.append(credit_why)
            else:
                if credit_valid:
                    verdicts.append(_verdict(
                        "holdout.exposure", False, "verified",
                        f"max scanned date {scan_last.isoformat()} >= "
                        f"holdout start {h_start.isoformat()} but holdout "
                        f"was consumed at {log_read_at(run_folder)}: "
                        f"folder is readable, holdout status must be "
                        f"declared in any report"))
                else:
                    if credit["claimed"]:
                        warnings.append(credit_why)
                    verdicts.append(_verdict(
                        "holdout.exposure", True, "verified",
                        f"max scanned date {scan_last.isoformat()} >= "
                        f"holdout start {h_start.isoformat()} and no valid "
                        f"consumption credit: loading this folder would "
                        f"expose the holdout"))
                    blocked = True
        elif isinstance(holdout, dict) and "coins" in holdout:
            coins = holdout["coins"]
            if not bas["present"]:
                verdicts.append(_verdict(
                    "holdout.exposure", False, "cannot_determine",
                    "holdout lists coins but by_asset/ directory is "
                    "absent: coin-level exposure cannot be verified from "
                    "this folder (aggregate equity may still contain "
                    "held-out coins)"))
                warnings.append("cannot verify coin holdout without "
                                "by_asset/; treat this folder as "
                                "unverifiable for coin-level claims")
            elif not bas["csvs"]:
                # round-18 4H: directory exists but holds no top-level
                # *.csv - never a verified absent on an empty scan. Name
                # any unscannable entries present (round-18 M-5/B6).
                extra = (f"; unscanned non-csv entries {bas['non_csv']}"
                         if bas["non_csv"] else "")
                verdicts.append(_verdict(
                    "holdout.exposure", False, "cannot_determine",
                    f"by_asset/ directory exists but holds no top-level "
                    f"*.csv files{extra}: coin-level exposure cannot be "
                    f"verified (aggregate equity may still contain "
                    f"held-out coins)"))
                warnings.append("by_asset/ has no top-level *.csv; treat "
                                "this folder as unverifiable for "
                                "coin-level claims")
                if bas["non_csv"]:
                    warnings.append(f"unscanned non-csv entries in "
                                    f"by_asset/: {bas['non_csv']}")
            else:
                stems = [stem for stem, _p in bas["csvs"]]
                exposed, lookalikes = _match_coins(coins, stems)
                if exposed:
                    if credit_valid:
                        verdicts.append(_verdict(
                            "holdout.exposure", False, "verified",
                            f"held-out coins {exposed} present in by_asset/ "
                            f"but holdout was consumed at "
                            f"{log_read_at(run_folder)}: folder is "
                            f"readable, holdout status must be declared "
                            f"in any report"))
                    else:
                        if credit["claimed"]:
                            warnings.append(credit_why)
                        verdicts.append(_verdict(
                            "holdout.exposure", True, "verified",
                            f"held-out coins {exposed} present in "
                            f"by_asset/ and no valid consumption credit: "
                            f"loading would expose the holdout"))
                        blocked = True
                elif bas["non_csv"]:
                    # round-18 M-5: unscannable entries -> NEVER claim
                    # verified absent. Name them.
                    verdicts.append(_verdict(
                        "holdout.exposure", False, "cannot_determine",
                        f"coins {sorted(coins)} not matched among scanned "
                        f"csv stems {stems}, but by_asset/ holds UNSCANNED "
                        f"non-csv entries {bas['non_csv']}: coin-level "
                        f"exposure cannot be verified"))
                    warnings.append(f"unscanned non-csv entries in by_asset/"
                                    f": {bas['non_csv']}")
                elif lookalikes:
                    # round-18 M-4: lookalike stems must not read as
                    # verified absent.
                    verdicts.append(_verdict(
                        "holdout.exposure", False, "cannot_determine",
                        f"coins {sorted(coins)} not exactly matched, but "
                        f"lookalike stems {lookalikes} exist in by_asset/: "
                        f"identity cannot be verified"))
                    warnings.append(f"lookalike stems for held-out coins: "
                                    f"{lookalikes}")
                else:
                    verdicts.append(_verdict(
                        "holdout.exposure", False, "verified",
                        f"held-out coins {sorted(coins)} absent from "
                        f"by_asset/ ({stems})"))
        else:
            raise GuardInputError(
                "run.json holdout must be null or an object with 'start' or "
                f"'coins', got {holdout!r}")

    # Parking report (contract section 3): informational, never fatal.
    # round-21: stats are keyed by raw filename; the reported asset label
    # stays the STEM (contract's parked asset naming), the LOOKUP is by
    # filename so a same-stem dual pair parks as two entries, never one.
    parked = []
    for stem, path in bas["csvs"]:
        st = bas_stats.get(path.name)
        if st is not None and st["days"] < min_days:
            parked.append({"asset": stem, "days": st["days"],
                           "reason": f"history {st['days']} distinct days "
                                     f"< min_days {min_days}"})

    payload = {
        "tool": "holdout_guard",
        "guard_version": GUARD_VERSION,
        "contract_version": CONTRACT_VERSION,
        "command": "check",
        "run_folder": str(run_folder),
        "calendar": run["calendar"],
        "holdout": run["holdout"],
        # round-19 m-1: holdout_read reflects a VALID credit (four-way
        # agreement, B-1) - not merely a claim - and is false whenever
        # this check blocked, even if the exposure branch did not fire.
        "holdout_read": bool(credit_valid and not blocked),
        "verdicts": verdicts,
        "parked_assets": parked,
        "warnings": warnings,
        "status": "blocked" if blocked else "pass",
    }
    return payload, (EXIT_BLOCKED if blocked else EXIT_PASS)


def mark_read(run_folder: Path, note: str = "") -> tuple[dict, int]:
    """One-time holdout consumption. Refusals are exit 2, never silent."""
    run = load_run(run_folder)  # structural errors first
    # round-19 m-2: mark-read shares the check-side structural rejection -
    # a both-keys holdout (or any malformed holdout) is refused here too.
    _validate_holdout(run)
    if run["holdout"] is None:
        raise GuardInputError(
            "refusing mark-read: run.json holdout is null - there is no "
            "holdout to consume; recording one would forge history")
    credit = read_credit(run_folder)
    if credit["logged"]:
        # round-18 M-1: the append log is the memory. Even if the state
        # file is deleted or contradicts it, a recorded event means the
        # holdout has already been consumed ONCE.
        raise GuardInputError(
            f"refusing mark-read: {LOG_FILE} already records a "
            f"holdout_read event (at {log_read_at(run_folder)}) - a "
            f"holdout is read ONCE")
    if credit["claimed"]:
        raise GuardInputError(
            "refusing mark-read: state claims holdout_read but the log "
            "does not back it - clear the guard files and re-evaluate "
            "instead of double-consuming")

    # round-19 m-2: structural log-shape refusals BEFORE any write - a
    # recognizable holdout_read event in ANY log shape (including the
    # top-level-array form) refuses with the original file untouched;
    # unrecognizable shapes stay an explicit GuardInputError and are
    # NEVER silently reset to {"events": []}.
    log_path = run_folder / LOG_FILE
    raw_log: dict | None = None
    if log_path.is_file():
        try:
            raw = json.loads(log_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise GuardInputError(
                f"refusing mark-read: {LOG_FILE} unparseable ({e}) - fix "
                f"or clear it explicitly instead of silently replacing "
                f"history (round-19 m-2)") from e
        if isinstance(raw, dict) and isinstance(raw.get("events"), list):
            raw_log = raw
        elif isinstance(raw, list):
            if any(isinstance(e, dict) and e.get("action") == "holdout_read"
                   for e in raw):
                raise GuardInputError(
                    f"refusing mark-read: {LOG_FILE} already records a "
                    f"holdout_read event (top-level array form) - a "
                    f"holdout is read ONCE (round-19 m-2)")
            raise GuardInputError(
                f"refusing mark-read: {LOG_FILE} is a top-level JSON array "
                f"without a recognizable holdout_read event (structural, "
                f"round-19 m-2)")
        else:
            raise GuardInputError(
                f"refusing mark-read: {LOG_FILE} malformed (expected "
                f"object with 'events' list) - not silently replaced "
                f"(round-19 m-2)")

    eq = read_time_table(run_folder / EQUITY_FILE, EQUITY_FILE)
    # round-18 B-1 + round-19 M-1: bind the credit to a snapshot of WHAT
    # was consumed - the holdout object, the equity span, and the by_asset
    # fingerprint (files added later invalidate the credit like an A11
    # equity extension).
    bas = by_asset_dir_state(run_folder)
    bas_stats: dict = {}
    if bas["present"] and not bas["subdirs"]:
        bas_stats = by_asset_stats(bas["csvs"])
    snapshot = {
        "holdout": run["holdout"],
        "equity_first": eq["first"].isoformat(),
        "equity_last": eq["last"].isoformat(),
        "by_asset": _by_asset_fingerprint(bas, bas_stats),
    }

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log_event = {"action": "holdout_read", "at": now,
                 "guard_version": GUARD_VERSION, "note": note,
                 "snapshot": snapshot}
    # round-19 B-1: write the LOG FIRST, then the state. A crash between
    # the two steps can only leave log-without-state, which check reads
    # as NOT read (fail-closed) - never the reverse (state-without-log,
    # which the round-19 B-1 repro-1 dead end showed).
    if raw_log is None:
        log = {"events": [log_event]}
    else:
        raw_log["events"].append(log_event)
        log = raw_log
    log_path.write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state = {"holdout_read": True, "read_at": now,
             "guard_version": GUARD_VERSION, "note": note,
             "snapshot": snapshot}
    (run_folder / STATE_FILE).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    payload = {
        "tool": "holdout_guard",
        "guard_version": GUARD_VERSION,
        "command": "mark-read",
        "run_folder": str(run_folder),
        "read_at": now,
        "snapshot": snapshot,
        "status": "consumed",
        "note": note,
    }
    return payload, EXIT_PASS


# ==========================================================================
# Selftest: built-in positive + negative controls (temp fixtures).
# Every number/behavior documented in RUN_FOLDER_CONTRACT.md is asserted
# here (artifact-builder iron rule 2: declaration == assertion).
# ==========================================================================

def _mk_run(folder: Path, run: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / RUN_FILE).write_text(
        json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")


def _mk_equity(folder: Path, dates: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["date,strategy_net,strategy_gross,benchmark"]
    lines += [f"{d},1.0{i},1.0{i},1.0{i}" for i, d in enumerate(dates)]
    (folder / EQUITY_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mk_by_asset(folder: Path, name: str, n: int, filename: str = None,
                 sub: str = None) -> None:
    """n DISTINCT calendar days starting 2025-01-01. Optional alternate
    filename (round-18 M-3/M-4) or subdirectory (round-18 M-6)."""
    d = folder / "by_asset" if sub is None else folder / "by_asset" / sub
    d.mkdir(parents=True, exist_ok=True)
    lines = ["date,strategy_net,strategy_gross,benchmark"]
    base = date(2025, 1, 1)
    lines += [f"{(base + timedelta(days=i)).isoformat()},1,1,1"
              for i in range(n)]
    (d / (filename or f"{name}.csv")).write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def _mk_by_asset_dup(folder: Path, name: str, n_rows: int,
                     n_days: int) -> None:
    """n_rows rows cycling over only n_days DISTINCT dates: row count is
    high but history is short - must still park (round-17 Major-2)."""
    d = folder / "by_asset"
    d.mkdir(parents=True, exist_ok=True)
    lines = ["date,strategy_net,strategy_gross,benchmark"]
    base = date(2025, 1, 1)
    for i in range(n_rows):
        day = (base + timedelta(days=i % n_days)).isoformat()
        lines.append(f"{day},1,1,1")
    (d / f"{name}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _base_run(**over) -> dict:
    run = {
        "calendar": "crypto",
        "benchmark": "ACME-HOLD",
        "period": {"start": "2025-01-01", "end": "2026-09-30"},
        "data_source": "fixture",
        "costs": {"taker_bps": 10, "slippage_bps": 5},
        "holdout": None,
        "tried_variants": 0,
    }
    run.update(over)
    return run


def _expect(cond: bool, msg: str, failures: list[str]) -> None:
    if not cond:
        failures.append(msg)


def run_selftest() -> tuple[dict, int]:
    failures: list[str] = []
    n_asserts = 0
    tool_path = Path(__file__).resolve()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # -- constants + version stamps (contract section 6, m-1) ---------
        n_asserts += 1
        _expect(EXIT_PASS == 0 and EXIT_BLOCKED == 1
                and EXIT_INPUT_ERROR == 2,
                "exit code map deviates from contract", failures)
        n_asserts += 1
        _expect(MIN_DAYS == 180, "MIN_DAYS default deviates from contract",
                failures)
        doc = tool_path.parent.parent / "RUN_FOLDER_CONTRACT.md"
        first_line = doc.read_text(encoding="utf-8").splitlines()[0]
        n_asserts += 1
        _expect(f"v{CONTRACT_VERSION}" in first_line,
                f"contract doc version does not match "
                f"CONTRACT_VERSION={CONTRACT_VERSION} (m-1)", failures)

        # 1P. clean folder, holdout null -> pass
        f1 = root / "clean"
        _mk_run(f1, _base_run())
        _mk_equity(f1, ["2026-01-01", "2026-06-30", "2026-09-30"])
        p, code = evaluate(f1)
        n_asserts += 1
        _expect(code == EXIT_PASS and p["status"] == "pass"
                and not p["verdicts"][0]["fired"],
                f"1P clean/null-holdout should pass, got exit={code}",
                failures)
        n_asserts += 1
        _expect(p["contract_version"] == CONTRACT_VERSION,
                "payload contract_version must equal constant (m-1)",
                failures)

        # 1P2. minimal run.json -> pass with exactly 5 recommended warnings
        f1b = root / "minimal"
        _mk_run(f1b, {"calendar": "crypto", "holdout": None})
        _mk_equity(f1b, ["2026-01-01"])
        p, code = evaluate(f1b)
        n_asserts += 1
        _expect(code == EXIT_PASS and sum(
            1 for w in p["warnings"] if "recommended field" in w) == 5,
            "1P2 minimal run.json should emit 5 recommended-field warnings",
            failures)

        # 2P/2N. holdout {start}: not reached vs reached
        f2 = root / "notreached"
        _mk_run(f2, _base_run(holdout={"start": "2030-01-01"}))
        _mk_equity(f2, ["2026-01-01", "2026-09-30"])
        p, code = evaluate(f2)
        n_asserts += 1
        _expect(code == EXIT_PASS and "not reached" in p["verdicts"][0][
            "evidence"], f"2P not-reached should pass, got exit={code}",
            failures)
        f3 = root / "reached"
        _mk_run(f3, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(f3, ["2026-01-01", "2026-09-30"])
        p, code = evaluate(f3)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["verdicts"][0]["fired"],
                f"2N reached-unconsumed must BLOCK, got exit={code}",
                failures)

        # 2N2. equality edge + previous day (m-2 locks)
        f2b = root / "equality"
        _mk_run(f2b, _base_run(holdout={"start": "2026-06-01"}))
        _mk_equity(f2b, ["2026-06-01"])
        p, code = evaluate(f2b)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED,
                f"2N2 equity last == start must BLOCK, got exit={code}",
                failures)
        f2c = root / "prevday"
        _mk_run(f2c, _base_run(holdout={"start": "2026-07-01"}))
        _mk_equity(f2c, ["2026-06-30"])
        p, code = evaluate(f2c)
        n_asserts += 1
        _expect(code == EXIT_PASS, "2N2b previous day must pass", failures)
        f2d = root / "leap"
        _mk_run(f2d, _base_run(holdout={"start": "2024-03-01"}))
        _mk_equity(f2d, ["2024-02-29"])
        p, code = evaluate(f2d)
        n_asserts += 1
        _expect(code == EXIT_PASS,
                "2N2c leap-day previous day must pass", failures)

        # 2N3. same-day with time components -> BLOCKED (round-18 lock)
        f2e = root / "sameday-time"
        _mk_run(f2e, _base_run(holdout={"start": "2026-06-01T00:00:00Z"}))
        _mk_equity(f2e, ["2026-06-01T23:59:59"])
        p, code = evaluate(f2e)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED,
                "2N3 same-day datetime literals must BLOCK", failures)

        # 2N4. m-4 documented semantics: calendar face, offsets NOT converted
        f2f = root / "tz-face"
        _mk_run(f2f, _base_run(holdout={"start": "2026-06-01"}))
        _mk_equity(f2f, ["2026-05-31T23:00:00-05:00"])
        p, code = evaluate(f2f)
        n_asserts += 1
        _expect(code == EXIT_PASS,
                "2N4 tz-offset date must keep calendar-face semantics "
                "(documented m-4)", failures)

        # 3P. consumed folder (state + log + snapshot) with exposure -> pass
        f4 = root / "consumed"
        _mk_run(f4, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(f4, ["2026-01-01", "2026-09-30"])
        _mp, mcode = mark_read(f4, note="selftest 3P")
        n_asserts += 1
        _expect(mcode == EXIT_PASS, "3P mark-read should succeed", failures)
        p, code = evaluate(f4)
        n_asserts += 1
        _expect(code == EXIT_PASS and p["holdout_read"] is True,
                f"3P consumed folder should pass with holdout_read, "
                f"got exit={code}", failures)

        # 3P2. evidence cites the LOG 'at', not state.read_at (m-2 lock)
        f4b = root / "consumed-evid"
        _mk_run(f4b, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(f4b, ["2026-01-01", "2026-09-30"])
        mark_read(f4b, note="3P2")
        state = json.loads((f4b / STATE_FILE).read_text())
        state["read_at"] = "2000-01-01T00:00:00+00:00"  # poison the state
        (f4b / STATE_FILE).write_text(json.dumps(state))
        p, code = evaluate(f4b)
        n_asserts += 1
        _expect(code == EXIT_PASS and "2000-01-01"
                not in p["verdicts"][0]["evidence"],
                "3P2 evidence must cite log at, not state.read_at", failures)

        # 3N. state claims read but log absent -> fail-closed BLOCKED
        f5 = root / "stateonly"
        _mk_run(f5, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(f5, ["2026-01-01", "2026-09-30"])
        (f5 / STATE_FILE).write_text(json.dumps(
            {"holdout_read": True, "read_at": "2026-10-05T00:00:00+00:00"}),
            encoding="utf-8")
        p, code = evaluate(f5)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                f"3N state-without-log must fail-closed BLOCK, "
                f"got exit={code}", failures)

        # 3N2. state + EMPTY events log -> fail-closed BLOCKED
        f5b = root / "stateonly-emptylog"
        _mk_run(f5b, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(f5b, ["2026-01-01", "2026-09-30"])
        (f5b / STATE_FILE).write_text(json.dumps(
            {"holdout_read": True, "read_at": "2026-10-05T00:00:00+00:00"}),
            encoding="utf-8")
        (f5b / LOG_FILE).write_text(json.dumps({"events": []}),
                                    encoding="utf-8")
        p, code = evaluate(f5b)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                "3N2 state + empty events log must fail-closed BLOCK",
                failures)

        # 3N3. state + garbage log -> fail-closed BLOCKED
        f5c = root / "stateonly-garbagelog"
        _mk_run(f5c, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(f5c, ["2026-01-01", "2026-09-30"])
        (f5c / STATE_FILE).write_text(json.dumps(
            {"holdout_read": True, "read_at": "2026-10-05T00:00:00+00:00"}),
            encoding="utf-8")
        (f5c / LOG_FILE).write_text("not json at all", encoding="utf-8")
        p, code = evaluate(f5c)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                "3N3 state + garbage log must fail-closed BLOCK", failures)

        # 3N4. garbage state + valid log -> fail-closed BLOCKED
        f5d = root / "garbagestate-oklog"
        _mk_run(f5d, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(f5d, ["2026-01-01", "2026-09-30"])
        (f5d / STATE_FILE).write_text("{{{", encoding="utf-8")
        (f5d / LOG_FILE).write_text(json.dumps(
            {"events": [{"action": "holdout_read",
                         "at": "2026-10-05T00:00:00+00:00"}]}),
            encoding="utf-8")
        p, code = evaluate(f5d)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                "3N4 garbage state + valid log must fail-closed BLOCK",
                failures)

        # 3N5. log is a top-level JSON ARRAY -> fail-closed (round-18 lock)
        f5e = root / "log-array"
        _mk_run(f5e, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(f5e, ["2026-01-01", "2026-09-30"])
        (f5e / STATE_FILE).write_text(json.dumps(
            {"holdout_read": True, "read_at": "2026-10-05T00:00:00+00:00"}),
            encoding="utf-8")
        (f5e / LOG_FILE).write_text(json.dumps(
            [{"action": "holdout_read", "at": "2026-10-05T00:00:00+00:00"}]),
            encoding="utf-8")
        p, code = evaluate(f5e)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                "3N5 top-level array log must fail-closed BLOCK", failures)

        # 3N6. trailing-space action never credits (round-18 lock)
        f5f = root / "log-space-action"
        _mk_run(f5f, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(f5f, ["2026-01-01", "2026-09-30"])
        (f5f / STATE_FILE).write_text(json.dumps(
            {"holdout_read": True, "read_at": "2026-10-05T00:00:00+00:00"}),
            encoding="utf-8")
        (f5f / LOG_FILE).write_text(json.dumps(
            {"events": [{"action": "holdout_read ",
                         "at": "2026-10-05T00:00:00+00:00"}]}),
            encoding="utf-8")
        p, code = evaluate(f5f)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                "3N6 trailing-space action must NOT credit", failures)

        # 4P/4N. holdout {coins}
        f6 = root / "coins-clean"
        _mk_run(f6, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(f6, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(f6, "BBB", 200)
        p, code = evaluate(f6)
        n_asserts += 1
        _expect(code == EXIT_PASS and not p["parked_assets"],
                f"4P coins absent from by_asset should pass, got "
                f"exit={code}", failures)
        f7 = root / "coins-exposed"
        _mk_run(f7, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(f7, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(f7, "AAA", 200)
        p, code = evaluate(f7)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED,
                f"4N held-out coin in by_asset must BLOCK, got "
                f"exit={code}", failures)

        # 4E. short by_asset history -> parked, named, never silent
        f8 = root / "parked"
        _mk_run(f8, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(f8, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(f8, "BBB", 10)
        p, code = evaluate(f8)
        n_asserts += 1
        _expect(code == EXIT_PASS and len(p["parked_assets"]) == 1
                and p["parked_assets"][0]["asset"] == "BBB"
                and p["parked_assets"][0]["days"] == 10,
                f"4E short history must be parked with named reason, "
                f"got {p['parked_assets']}", failures)

        # 4E2. duplicate-date rows: 200 rows / 28 distinct days -> parked
        f8b = root / "parked-dup"
        _mk_run(f8b, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(f8b, ["2026-01-01", "2026-09-30"])
        _mk_by_asset_dup(f8b, "BBB", 200, 28)
        p, code = evaluate(f8b)
        n_asserts += 1
        _expect(code == EXIT_PASS and len(p["parked_assets"]) == 1
                and p["parked_assets"][0]["days"] == 28,
                f"4E2 200 rows over 28 distinct days must park with days=28, "
                f"got {p['parked_assets']}", failures)

        # 4E3. parking counts distinct calendar days across mixed date and
        # datetime literals of the same day (round-18 lock: 90 days)
        f8c = root / "parked-mixed"
        _mk_run(f8c, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(f8c, ["2026-01-01", "2026-09-30"])
        d_mixed = f8c / "by_asset"
        d_mixed.mkdir(parents=True, exist_ok=True)
        base_d = date(2025, 1, 1)
        rows = ["date,strategy_net,strategy_gross,benchmark"]
        for i in range(90):
            day = (base_d + timedelta(days=i)).isoformat()
            rows.append(f"{day},1,1,1")
            rows.append(f"{day}T10:00:00,1,1,1")
        (d_mixed / "BBB.csv").write_text("\n".join(rows) + "\n",
                                         encoding="utf-8")
        p, code = evaluate(f8c)
        n_asserts += 1
        _expect(code == EXIT_PASS and len(p["parked_assets"]) == 1
                and p["parked_assets"][0]["days"] == 90,
                f"4E3 mixed date/datetime rows must count distinct days=90, "
                f"got {p['parked_assets']}", failures)

        # 4E4. boundary: exactly min_days distinct -> NOT parked; -1 parks
        f8d = root / "boundary-180"
        _mk_run(f8d, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(f8d, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(f8d, "BBB", 180)
        p, code = evaluate(f8d)
        n_asserts += 1
        _expect(code == EXIT_PASS and not p["parked_assets"],
                "4E4 exactly 180 distinct days must NOT park", failures)
        f8e = root / "boundary-179"
        _mk_run(f8e, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(f8e, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(f8e, "BBB", 179)
        p, code = evaluate(f8e)
        n_asserts += 1
        _expect(code == EXIT_PASS and len(p["parked_assets"]) == 1,
                "4E4b 179 distinct days must park", failures)

        # 4F. {coins} with no by_asset/ -> cannot_determine, exit 0, warned
        f9 = root / "coins-nobyasset"
        _mk_run(f9, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(f9, ["2026-01-01", "2026-09-30"])
        p, code = evaluate(f9)
        n_asserts += 1
        _expect(code == EXIT_PASS
                and p["verdicts"][0]["tier"] == "cannot_determine"
                and p["warnings"],
                f"4F missing by_asset must be cannot_determine + warning, "
                f"got exit={code} tier={p['verdicts'][0]['tier']}", failures)

        # 4G. held-out coin hidden in a by_asset SUBDIRECTORY -> fail-closed
        f9b = root / "coins-subdir"
        _mk_run(f9b, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(f9b, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(f9b, "BBB", 200)
        _mk_by_asset(f9b, "AAA", 5, sub="sub")
        p, code = evaluate(f9b)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and "subdirectories"
                in p["verdicts"][0]["evidence"],
                f"4G held-out coin in by_asset subdirectory must fail-closed "
                f"BLOCK, got exit={code}", failures)

        # 4H. by_asset/ exists but no top-level *.csv -> cannot_determine
        f9c = root / "coins-emptydir"
        _mk_run(f9c, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(f9c, ["2026-01-01", "2026-09-30"])
        (f9c / "by_asset").mkdir(parents=True, exist_ok=True)
        p, code = evaluate(f9c)
        n_asserts += 1
        _expect(code == EXIT_PASS
                and p["verdicts"][0]["tier"] == "cannot_determine"
                and "no top-level" in p["verdicts"][0]["evidence"],
                f"4H empty by_asset dir must honestly cannot_determine, "
                f"got {p['verdicts'][0]}", failures)

        # ---- B-1: consumption credit must bind to the snapshot ----------
        # B1-a (A8b): consume an untouched window, then move start earlier
        fb1 = root / "b1-start-move"
        _mk_run(fb1, _base_run(holdout={"start": "2026-07-01"}))
        _mk_equity(fb1, ["2026-01-01", "2026-06-30"])
        _mp, mcode = mark_read(fb1, note="b1a")
        n_asserts += 1
        _expect(mcode == EXIT_PASS,
                "B1-a mark-read on untouched window succeeds", failures)
        p, code = evaluate(fb1)
        n_asserts += 1
        _expect(code == EXIT_PASS, "B1-a pre-edit check passes", failures)
        _mk_run(fb1, _base_run(holdout={"start": "2026-06-01"}))
        p, code = evaluate(fb1)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                f"B1-a moved start must INVALIDATE credit and BLOCK, "
                f"got exit={code}", failures)

        # B1-b (A9): consume coins NOTREAL, then swap in a real held-out coin
        fb2 = root / "b1-coins-swap"
        _mk_run(fb2, _base_run(holdout={"coins": ["NOTREAL"]}))
        _mk_equity(fb2, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(fb2, "AAA", 200)
        mark_read(fb2, note="b1b")
        _mk_run(fb2, _base_run(holdout={"coins": ["AAA"]}))
        p, code = evaluate(fb2)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                f"B1-b swapped coins must INVALIDATE credit and BLOCK, "
                f"got exit={code}", failures)

        # B1-c (A11): consume before equity touches, then extend equity
        fb3 = root / "b1-equity-grow"
        _mk_run(fb3, _base_run(holdout={"start": "2026-06-01"}))
        _mk_equity(fb3, ["2026-01-01", "2026-05-31"])
        mark_read(fb3, note="b1c")
        _mk_equity(fb3, ["2026-01-01", "2026-05-31", "2026-06-01",
                         "2026-09-30"])
        p, code = evaluate(fb3)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                f"B1-c grown equity must INVALIDATE credit and BLOCK, "
                f"got exit={code}", failures)

        # B1-d (A10): transplant guard files from another consumed folder
        fb4 = root / "b1-donor"
        _mk_run(fb4, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(fb4, ["2026-01-01", "2026-09-30"])
        mark_read(fb4, note="b1d-donor")
        fb5 = root / "b1-recipient"
        _mk_run(fb5, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(fb5, ["2026-01-01", "2026-08-15"])  # different equity
        (fb5 / STATE_FILE).write_text((fb4 / STATE_FILE).read_text())
        (fb5 / LOG_FILE).write_text((fb4 / LOG_FILE).read_text())
        p, code = evaluate(fb5)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                f"B1-d transplanted guard files must fail snapshot match "
                f"and BLOCK, got exit={code}", failures)

        # B1-e: legacy state+log WITHOUT snapshot -> fail-closed
        fb6 = root / "b1-legacy"
        _mk_run(fb6, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(fb6, ["2026-01-01", "2026-09-30"])
        (fb6 / STATE_FILE).write_text(json.dumps(
            {"holdout_read": True, "read_at": "2026-10-05T00:00:00+00:00"}),
            encoding="utf-8")
        (fb6 / LOG_FILE).write_text(json.dumps(
            {"events": [{"action": "holdout_read",
                         "at": "2026-10-05T00:00:00+00:00"}]}),
            encoding="utf-8")
        p, code = evaluate(fb6)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                "B1-e snapshot-less credit must fail-closed BLOCK", failures)

        # ---- M-1: log event refuses further consumption ------------------
        fm1 = root / "m1-statefalse"
        _mk_run(fm1, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(fm1, ["2026-01-01", "2026-09-30"])
        (fm1 / STATE_FILE).write_text(json.dumps({"holdout_read": False}),
                                      encoding="utf-8")
        (fm1 / LOG_FILE).write_text(json.dumps(
            {"events": [{"action": "holdout_read",
                         "at": "2026-10-05T00:00:00+00:00"}]}),
            encoding="utf-8")
        p, code = evaluate(fm1)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED
                and any("already records" in w for w in p["warnings"]),
                "M-1 check: log event + state false -> BLOCKED + warning",
                failures)
        try:
            mark_read(fm1, note="m1-again")
            n_asserts += 1
            _expect(False, "M-1 mark-read with existing log event must "
                           "refuse", failures)
        except GuardInputError:
            n_asserts += 1  # correct
        fm1b = root / "m1-rm-state"
        _mk_run(fm1b, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(fm1b, ["2026-01-01", "2026-09-30"])
        mark_read(fm1b, note="first")
        (fm1b / STATE_FILE).unlink()
        try:
            mark_read(fm1b, note="second-after-rm-state")
            n_asserts += 1
            _expect(False, "M-1 A6: mark-read after state deletion must "
                           "refuse (log remains)", failures)
        except GuardInputError:
            n_asserts += 1  # correct

        # ---- M-2: holdout_read must be EXACTLY JSON true ------------------
        # (fixture snapshot carries the round-19 M-1 by_asset fingerprint
        # field: no by_asset/ directory in these fixtures)
        _snap = {"holdout": {"start": "2026-01-01"},
                 "equity_first": "2026-01-01",
                 "equity_last": "2026-09-30",
                 "by_asset": {"present": False}}
        for tag, val, expect_read in (
                ("str-false", "false", False), ("str-true", "true", False),
                ("int-1", 1, False), ("int-0", 0, False),
                ("bool-true", True, True)):
            fm2 = root / f"m2-{tag}"
            _mk_run(fm2, _base_run(holdout={"start": "2026-01-01"}))
            _mk_equity(fm2, ["2026-01-01", "2026-09-30"])
            (fm2 / STATE_FILE).write_text(json.dumps(
                {"holdout_read": val, "read_at": "x",
                 "snapshot": _snap}), encoding="utf-8")
            (fm2 / LOG_FILE).write_text(json.dumps(
                {"events": [{"action": "holdout_read", "at": "y",
                             "snapshot": _snap}]}), encoding="utf-8")
            p, code = evaluate(fm2)
            n_asserts += 1
            if expect_read:
                _expect(code == EXIT_PASS and p["holdout_read"] is True,
                        f"M-2 {tag} must credit as read", failures)
            else:
                _expect(code == EXIT_BLOCKED and p["holdout_read"] is False
                        and any("not JSON true" in w for w in p["warnings"]),
                        f"M-2 {tag}={val!r} must NOT credit (BLOCKED + "
                        f"warning), got exit={code}", failures)

        # ---- M-3: .CSV case-insensitive extension -------------------------
        fm3 = root / "m3-upper-csv"
        _mk_run(fm3, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(fm3, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(fm3, "BBB", 200)
        _mk_by_asset(fm3, "AAA", 200, filename="AAA.CSV")
        p, code = evaluate(fm3)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED,
                f"M-3 AAA.CSV must count as csv and BLOCK, got "
                f"exit={code}", failures)
        fm3b = root / "m3-only-upper"
        _mk_run(fm3b, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(fm3b, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(fm3b, "AAA", 200, filename="AAA.CSV")
        p, code = evaluate(fm3b)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED,
                f"M-3b only AAA.CSV must BLOCK, got exit={code}", failures)

        # ---- M-4: coin identity normalization -----------------------------
        fm4 = root / "m4-case"
        _mk_run(fm4, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(fm4, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(fm4, "aaa", 200)
        p, code = evaluate(fm4)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED,
                f"M-4 aaa.csv vs coins AAA must BLOCK (case-only), got "
                f"exit={code}", failures)
        fm4b = root / "m4-lookalike"
        _mk_run(fm4b, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(fm4b, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(fm4b, "BBB", 200)
        _mk_by_asset(fm4b, "CCC", 200, filename="AAA.csv.csv")
        p, code = evaluate(fm4b)
        n_asserts += 1
        _expect(code == EXIT_PASS
                and p["verdicts"][0]["tier"] == "cannot_determine"
                and "AAA.csv" in p["verdicts"][0]["evidence"],
                f"M-4b lookalike stem must cannot_determine and name it, "
                f"got {p['verdicts'][0]}", failures)
        fm4c = root / "m4-space"
        _mk_run(fm4c, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(fm4c, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(fm4c, "BBB", 200)
        _mk_by_asset(fm4c, "AAA", 200, filename="AAA .csv")
        p, code = evaluate(fm4c)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED,
                "M-4c 'AAA .csv' vs coins AAA must BLOCK (whitespace "
                "normalized)", failures)

        # ---- M-5: non-csv entries forbid verified-absent ------------------
        fm5 = root / "m5-bak-with-csv"
        _mk_run(fm5, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(fm5, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(fm5, "BBB", 200)
        (fm5 / "by_asset" / "AAA.csv.bak").write_text(
            "date,net\n2026-01-01,1\n", encoding="utf-8")
        p, code = evaluate(fm5)
        n_asserts += 1
        _expect(code == EXIT_PASS
                and p["verdicts"][0]["tier"] == "cannot_determine"
                and "AAA.csv.bak" in p["verdicts"][0]["evidence"],
                f"M-5 non-csv entry must forbid verified absent and be "
                f"named, got {p['verdicts'][0]}", failures)
        fm5b = root / "m5-bak-only"
        _mk_run(fm5b, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(fm5b, ["2026-01-01", "2026-09-30"])
        (fm5b / "by_asset").mkdir(parents=True, exist_ok=True)
        (fm5b / "by_asset" / "AAA.csv.bak").write_text(
            "date,net\n2026-01-01,1\n", encoding="utf-8")
        p, code = evaluate(fm5b)
        n_asserts += 1
        _expect(code == EXIT_PASS
                and p["verdicts"][0]["tier"] == "cannot_determine"
                and "AAA.csv.bak" in p["verdicts"][0]["evidence"],
                "M-5b bak-only must cannot_determine naming the bak",
                failures)

        # ---- M-6: subdirs fail-closed in ALL modes ------------------------
        fm6 = root / "m6-null-subdir"
        _mk_run(fm6, _base_run())  # holdout null
        _mk_equity(fm6, ["2026-01-01"])
        _mk_by_asset(fm6, "NEW", 1, sub="hidden")
        p, code = evaluate(fm6)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED,
                f"M-6 null holdout + by_asset subdir must BLOCK, got "
                f"exit={code}", failures)
        fm6b = root / "m6-start-subdir"
        _mk_run(fm6b, _base_run(holdout={"start": "2030-01-01"}))
        _mk_equity(fm6b, ["2026-01-01", "2026-05-31"])
        hidden = fm6b / "by_asset" / "hidden"
        hidden.mkdir(parents=True, exist_ok=True)
        (hidden / "AAA.csv").write_text(
            "date,strategy_net,strategy_gross,benchmark\n"
            "2030-06-01,1,1,1\n", encoding="utf-8")
        p, code = evaluate(fm6b)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED,
                f"M-6b start not-reached + hidden subdir with post-holdout "
                f"dates must BLOCK, got exit={code}", failures)

        # ---- M-7: both start and coins -> structural error ----------------
        fm7 = root / "m7-both-keys"
        _mk_run(fm7, _base_run(
            holdout={"start": "2099-01-01", "coins": ["AAA"]}))
        _mk_equity(fm7, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(fm7, "AAA", 200)
        try:
            evaluate(fm7)
            n_asserts += 1
            _expect(False, "M-7 both keys must raise GuardInputError",
                    failures)
        except GuardInputError:
            n_asserts += 1  # correct

        # ---- M-8: time columns --------------------------------------------
        fm8 = root / "m8-case-dup"
        _mk_run(fm8, _base_run(holdout={"start": "2026-06-01"}))
        (fm8 / EQUITY_FILE).write_text(
            "Date,date,strategy_net,strategy_gross,benchmark\n"
            "2026-01-01,2026-09-01,1,1,1\n", encoding="utf-8")
        try:
            evaluate(fm8)
            n_asserts += 1
            _expect(False, "M-8 casefolded duplicate time columns must "
                           "raise", failures)
        except GuardInputError:
            n_asserts += 1  # correct
        fm8b = root / "m8-two-cols"
        _mk_run(fm8b, _base_run(holdout={"start": "2026-06-01"}))
        (fm8b / EQUITY_FILE).write_text(
            "date,timestamp,strategy_net,strategy_gross,benchmark\n"
            "2026-01-01,2026-09-01,1,1,1\n", encoding="utf-8")
        p, code = evaluate(fm8b)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED,
                f"M-8b max across BOTH time columns must BLOCK, got "
                f"exit={code}", failures)

        # ---- m-6: start mode scans by_asset dates too ----------------------
        fm6c = root / "m6-start-byasset"
        _mk_run(fm6c, _base_run(holdout={"start": "2026-06-01"}))
        _mk_equity(fm6c, ["2026-01-01", "2026-05-31"])
        _mk_by_asset(fm6c, "ACME", 600)  # 2025-01-01..2026-08-23
        p, code = evaluate(fm6c)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED,
                f"m-6 chosen option: by_asset dates beyond start must "
                f"BLOCK in start mode, got exit={code}", failures)

        # ==== round-19: B-1 / M-1 / M-2 / m-1 / m-2 / m-3 (all NET-NEW; no
        # round-17/18 assertion may be replaced or dropped) =================

        # R19-B1-1 (round-19 B-1 repro 1): state + MATCHING snapshot but
        # the log file deleted -> credit invalid, BLOCK, and the evidence
        # must NOT claim the holdout was consumed.
        fr1 = root / "r19-b1-logdel"
        _mk_run(fr1, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(fr1, ["2026-01-01", "2026-09-30"])
        mark_read(fr1, note="r19-b1-1")
        (fr1 / LOG_FILE).unlink()
        p, code = evaluate(fr1)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False
                and "was consumed" not in p["verdicts"][0]["evidence"]
                and "consumed at" not in p["verdicts"][0]["evidence"],
                f"R19-B1-1 matched snapshot without log must BLOCK with no "
                f"consumed-at claim, got exit={code} "
                f"ev={p['verdicts'][0]['evidence']}", failures)

        # R19-B1-1b: same, but the log EXISTS with an empty events list.
        (fr1 / LOG_FILE).write_text(json.dumps({"events": []}),
                                    encoding="utf-8")
        p, code = evaluate(fr1)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                "R19-B1-1b empty events log must fail the credit (BLOCK)",
                failures)

        # R19-B1-2 (round-19 B-1 repro 2): state.snapshot forged to match
        # the CURRENT config/span while the log keeps the original window
        # -> the four-way check fails -> BLOCK.
        fr2 = root / "r19-b1-forged-snap"
        _mk_run(fr2, _base_run(holdout={"start": "2026-09-01"}))
        _mk_equity(fr2, ["2026-01-01", "2026-08-15"])
        mark_read(fr2, note="r19-b1-2")
        _mk_run(fr2, _base_run(holdout={"start": "2026-06-01"}))
        _mk_equity(fr2, ["2026-01-01", "2026-08-15", "2026-09-30"])
        st = json.loads((fr2 / STATE_FILE).read_text())
        st["snapshot"]["holdout"] = {"start": "2026-06-01"}
        st["snapshot"]["equity_last"] = "2026-09-30"
        (fr2 / STATE_FILE).write_text(json.dumps(st), encoding="utf-8")
        p, code = evaluate(fr2)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False
                and "was consumed" not in p["verdicts"][0]["evidence"],
                "R19-B1-2 forged state.snapshot (log snapshot differs) "
                "must BLOCK", failures)

        # R19-B1-2b (transplant variant): recipient's state edited to the
        # recipient span but the log snapshot is still the donor's -> BLOCK.
        fr2b = root / "r19-b1-transplant-edit"
        _mk_run(fr2b, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(fr2b, ["2026-01-01", "2026-09-30"])
        mark_read(fr2b, note="r19-b1-2b-donor")
        fr2c = root / "r19-b1-recipient-edit"
        _mk_run(fr2c, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(fr2c, ["2026-01-01", "2026-08-15"])
        (fr2c / LOG_FILE).write_text((fr2b / LOG_FILE).read_text(),
                                     encoding="utf-8")
        st = json.loads((fr2b / STATE_FILE).read_text())
        st["snapshot"]["equity_last"] = "2026-08-15"
        (fr2c / STATE_FILE).write_text(json.dumps(st), encoding="utf-8")
        p, code = evaluate(fr2c)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                "R19-B1-2b state edited to recipient span but log snapshot "
                "is donor's -> BLOCK", failures)

        # R19-B1-3: mark-read writes the LOG FIRST - a failed log write
        # (path occupied) must leave NO state file behind (the only
        # possible crash window is log-without-state = NOT read).
        fr3 = root / "r19-b1-log-first"
        _mk_run(fr3, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(fr3, ["2026-01-01", "2026-09-30"])
        (fr3 / LOG_FILE).mkdir()  # occupy the log path -> write fails
        raised = False
        try:
            mark_read(fr3, note="r19-b1-3")
        except Exception:
            raised = True
        n_asserts += 1
        _expect(raised and not (fr3 / STATE_FILE).exists(),
                "R19-B1-3 log-first ordering: failed log write must leave "
                "no state file", failures)

        # R19-M1-1 (round-19 M-1 repro 1): by_asset csv added AFTER
        # consumption extends the scanned window -> credit invalid, BLOCK.
        fr4 = root / "r19-m1-byasset-add"
        _mk_run(fr4, _base_run(holdout={"start": "2026-06-01"}))
        _mk_equity(fr4, ["2026-01-01", "2026-05-31"])
        mark_read(fr4, note="r19-m1-1")
        _mk_by_asset(fr4, "ACME", 600)  # reaches into 2026-08
        p, code = evaluate(fr4)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False
                and "was consumed" not in p["verdicts"][0]["evidence"],
                "R19-M1-1 by_asset file added post-consumption must "
                "BLOCK", failures)

        # R19-M1-2 (round-19 M-1 repro 2): coin verified-absent at
        # consumption, its file added later -> BLOCK.
        fr5 = root / "r19-m1-coin-add"
        _mk_run(fr5, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(fr5, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(fr5, "BBB", 200)
        mark_read(fr5, note="r19-m1-2")
        _mk_by_asset(fr5, "AAA", 200)
        p, code = evaluate(fr5)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                "R19-M1-2 held-out coin file added post-consumption must "
                "BLOCK", failures)

        # R19-M1-3 (round-19 M-1 repro 3): a second coin file added after
        # consumption -> BLOCK (both coins were in the held-out list).
        fr6 = root / "r19-m1-second-coin"
        _mk_run(fr6, _base_run(holdout={"coins": ["AAA", "BBB"]}))
        _mk_equity(fr6, ["2026-01-01", "2026-09-30"])
        _mk_by_asset(fr6, "AAA", 200)
        mark_read(fr6, note="r19-m1-3")
        _mk_by_asset(fr6, "BBB", 200)
        p, code = evaluate(fr6)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False,
                "R19-M1-3 second coin file added post-consumption must "
                "BLOCK", failures)

        # R19-M2-1 (round-19 M-2): start mode + unscanned non-csv entry ->
        # cannot_determine naming the file, evidence WITHOUT "not reached",
        # exit stays 0 (aligns coins-mode M-5).
        fr7 = root / "r19-m2-start-bak"
        _mk_run(fr7, _base_run(holdout={"start": "2026-06-01"}))
        _mk_equity(fr7, ["2026-01-01", "2026-05-31"])
        (fr7 / "by_asset").mkdir(parents=True, exist_ok=True)
        (fr7 / "by_asset" / "ACME.csv.bak").write_text(
            "date,strategy_net,strategy_gross,benchmark\n"
            "2026-08-01,1,1,1\n", encoding="utf-8")
        p, code = evaluate(fr7)
        n_asserts += 1
        _expect(code == EXIT_PASS
                and p["verdicts"][0]["tier"] == "cannot_determine"
                and "ACME.csv.bak" in p["verdicts"][0]["evidence"]
                and "not reached" not in p["verdicts"][0]["evidence"],
                f"R19-M2-1 start-mode non-csv must cannot_determine naming "
                f"it without 'not reached', got {p['verdicts'][0]}",
                failures)

        # R19-M2-2: .parquet variant, same honest tier.
        (fr7 / "by_asset" / "ACME.csv.bak").unlink()
        (fr7 / "by_asset" / "ACME.parquet").write_bytes(b"\x00\x01")
        p, code = evaluate(fr7)
        n_asserts += 1
        _expect(code == EXIT_PASS
                and p["verdicts"][0]["tier"] == "cannot_determine"
                and "ACME.parquet" in p["verdicts"][0]["evidence"]
                and "not reached" not in p["verdicts"][0]["evidence"],
                "R19-M2-2 parquet entry likewise forbids a verified "
                "not-reached", failures)

        # R19-m-1 (round-19 m-1 Minor): snapshot mismatch WITHOUT exposure
        # (still not reached) -> exit 0, evidence "not reached", but
        # holdout_read=false + the same invalidation warning as B-1.
        fr8 = root / "r19-minor1-stale"
        _mk_run(fr8, _base_run(holdout={"start": "2030-01-01"}))
        _mk_equity(fr8, ["2026-01-01", "2026-05-31"])
        mark_read(fr8, note="r19-m1-minor")
        _mk_equity(fr8, ["2026-01-01", "2026-05-31", "2026-06-01"])
        p, code = evaluate(fr8)
        n_asserts += 1
        _expect(code == EXIT_PASS and p["holdout_read"] is False
                and "not reached" in p["verdicts"][0]["evidence"]
                and any("INVALID" in w or "changed since consumption" in w
                        for w in p["warnings"]),
                f"R19-m-1 stale credit without exposure must give "
                f"holdout_read=false + invalidation warning, got "
                f"exit={code} read={p['holdout_read']} "
                f"warn={p['warnings']}", failures)

        # R19-m2-1 (round-19 m-2): top-level array log WITH a holdout_read
        # event -> mark-read refuses (exit 2) and does NOT rewrite the file.
        fr9 = root / "r19-m2-array-read"
        _mk_run(fr9, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(fr9, ["2026-01-01", "2026-09-30"])
        orig = json.dumps([{"action": "holdout_read",
                            "at": "2026-10-06T00:00:00+00:00"}])
        (fr9 / LOG_FILE).write_text(orig, encoding="utf-8")
        try:
            mark_read(fr9, note="r19-m2-1")
            n_asserts += 1
            _expect(False, "R19-m2-1 mark-read must refuse a top-level "
                           "array log with a holdout_read event", failures)
        except GuardInputError:
            n_asserts += 1  # correct
        n_asserts += 1
        _expect((fr9 / LOG_FILE).read_text(encoding="utf-8") == orig,
                "R19-m2-1 refused mark-read must not rewrite the log",
                failures)

        # R19-m2-2: top-level array WITHOUT a holdout_read event ->
        # structural refusal, never a silent reset to {"events": []}.
        fr9b = root / "r19-m2-array-other"
        _mk_run(fr9b, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(fr9b, ["2026-01-01", "2026-09-30"])
        (fr9b / LOG_FILE).write_text(json.dumps(
            [{"action": "other", "at": "x"}]), encoding="utf-8")
        try:
            mark_read(fr9b, note="r19-m2-2")
            n_asserts += 1
            _expect(False, "R19-m2-2 array without holdout_read must be a "
                           "structural refusal (no silent reset)", failures)
        except GuardInputError:
            n_asserts += 1  # correct

        # R19-m2-3: malformed dict log (no events list) -> structural
        # refusal, never a silent reset.
        fr9c = root / "r19-m2-malformed"
        _mk_run(fr9c, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(fr9c, ["2026-01-01", "2026-09-30"])
        (fr9c / LOG_FILE).write_text(json.dumps({"note": "not a log"}),
                                     encoding="utf-8")
        try:
            mark_read(fr9c, note="r19-m2-3")
            n_asserts += 1
            _expect(False, "R19-m2-3 malformed dict log must refuse (no "
                           "silent events reset)", failures)
        except GuardInputError:
            n_asserts += 1  # correct

        # R19-m2-4: both-keys holdout -> mark-read shares check's
        # structural rejection (exit 2).
        fr9d = root / "r19-m2-bothkeys-mr"
        _mk_run(fr9d, _base_run(holdout={"start": "2099-01-01",
                                          "coins": ["AAA"]}))
        _mk_equity(fr9d, ["2026-01-01", "2026-09-30"])
        try:
            mark_read(fr9d, note="r19-m2-4")
            n_asserts += 1
            _expect(False, "R19-m2-4 mark-read on a both-keys holdout must "
                           "refuse (shared structural validation)",
                    failures)
        except GuardInputError:
            n_asserts += 1  # correct

        # R19-m3 (round-19 m-3): --help exits 0 with NO error-JSON envelope
        # appended to the help text (usage errors keep the envelope: 13d/e).
        proc = subprocess.run(
            [sys.executable, str(tool_path), "--help"],
            capture_output=True, text=True)
        n_asserts += 1
        _expect(proc.returncode == EXIT_PASS and "usage:" in proc.stdout
                and '"error"' not in proc.stdout,
                "R19-m3 --help must exit 0 with usage on stdout and no "
                "error JSON", failures)

        # R19-NFKC (round-19 adopted 未升格 item): a fullwidth lookalike
        # stem can no longer dodge a held-out coin match - normalization
        # now includes NFKC compatibility equivalence (contract section 3).
        frw = root / "r19-nfkc-fullwidth"
        _mk_run(frw, _base_run(holdout={"coins": ["AAA"]}))
        _mk_equity(frw, ["2026-01-01", "2026-09-30"])
        (frw / "by_asset").mkdir(parents=True, exist_ok=True)
        (frw / "by_asset" / "ＡＡＡ.csv").write_text(
            "date,strategy_net,strategy_gross,benchmark\n"
            "2025-01-01,1,1,1\n", encoding="utf-8")
        p, code = evaluate(frw)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED,
                f"R19-NFKC fullwidth lookalike stem must BLOCK (NFKC "
                f"normalization), got exit={code}", failures)

        # ==== round-20: M-1 residual (per-file fingerprint) + substring
        # locks. ALL NET-NEW; none of the 108 existing asserts replaced. ==

        # R20-M1-C1 (round-20 repro 1): collidee ' ACME.csv' (leading space,
        # sorts BEFORE ACME.csv) added post-consumption with post-holdout
        # dates -> per-file fingerprint sees TWO records -> BLOCK.
        fr10 = root / "r20-collision-space"
        _mk_run(fr10, _base_run(holdout={"start": "2026-06-01"}))
        _mk_equity(fr10, ["2026-01-01", "2026-05-31"])
        _mk_by_asset(fr10, "ACME", 30)  # ACME.csv: 2025-01-01..2025-01-30
        mark_read(fr10, note="r20-c1")
        _mk_by_asset(fr10, "ACME", 600, filename=" ACME.csv")
        p, code = evaluate(fr10)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False
                and p["verdicts"][0]["tier"] == "verified"
                and "no valid consumption credit"
                in p["verdicts"][0]["evidence"]
                and "was consumed" not in p["verdicts"][0]["evidence"]
                and "consumed at" not in p["verdicts"][0]["evidence"]
                and any("by_asset fingerprint changed since consumption"
                        in w for w in p["warnings"]),
                f"R20-M1-C1 ' ACME.csv' collidee must BLOCK via per-file "
                f"fingerprint, got exit={code} read={p['holdout_read']} "
                f"ev={p['verdicts'][0]['evidence']} warn={p['warnings']}",
                failures)

        # R20-M1-C2 (round-20 repro 2): 'ACME .csv' (space before extension).
        fr11 = root / "r20-collision-trailspace"
        _mk_run(fr11, _base_run(holdout={"start": "2026-06-01"}))
        _mk_equity(fr11, ["2026-01-01", "2026-05-31"])
        _mk_by_asset(fr11, "ACME", 30)
        mark_read(fr11, note="r20-c2")
        _mk_by_asset(fr11, "ACME", 600, filename="ACME .csv")
        p, code = evaluate(fr11)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False
                and p["verdicts"][0]["tier"] == "verified"
                and "no valid consumption credit"
                in p["verdicts"][0]["evidence"]
                and "was consumed" not in p["verdicts"][0]["evidence"]
                and "consumed at" not in p["verdicts"][0]["evidence"]
                and any("by_asset fingerprint changed since consumption"
                        in w for w in p["warnings"]),
                f"R20-M1-C2 'ACME .csv' collidee must BLOCK via per-file "
                f"fingerprint, got exit={code} read={p['holdout_read']} "
                f"ev={p['verdicts'][0]['evidence']} warn={p['warnings']}",
                failures)

        # R20-M1-C3 (round-20 repro 3): 'A CME.csv' (internal space).
        fr12 = root / "r20-collision-intspace"
        _mk_run(fr12, _base_run(holdout={"start": "2026-06-01"}))
        _mk_equity(fr12, ["2026-01-01", "2026-05-31"])
        _mk_by_asset(fr12, "ACME", 30)
        mark_read(fr12, note="r20-c3")
        collidee_name = "A CME.csv"
        _mk_by_asset(fr12, "ACME", 600, filename=collidee_name)
        # Precondition: the fixture must actually be a normalized-token
        # collidee. Without this, a rename silently turns C3 into a plain
        # "new file appeared" test and the collision branch stops being
        # exercised at all (still green, but no longer the test it claims).
        # It is bound to the same variable the fixture uses, so changing the
        # fixture name alone makes this assertion fail.
        n_asserts += 1
        _expect(_norm_token(collidee_name.rsplit(".", 1)[0]) == _norm_token("ACME")
                and _norm_token(collidee_name.rsplit(".", 1)[0]) != _norm_token("OTHER"),
                f"R20-M1-C3 fixture {collidee_name!r} must normalize to "
                f"{_norm_token('ACME')!r} (a collidee of 'ACME'), got "
                f"{_norm_token(collidee_name.rsplit('.', 1)[0])!r}", failures)
        p, code = evaluate(fr12)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False
                and p["verdicts"][0]["tier"] == "verified"
                and "no valid consumption credit"
                in p["verdicts"][0]["evidence"]
                and "was consumed" not in p["verdicts"][0]["evidence"]
                and "consumed at" not in p["verdicts"][0]["evidence"]
                and any("by_asset fingerprint changed since consumption"
                        in w for w in p["warnings"]),
                f"R20-M1-C3 'A CME.csv' collidee must BLOCK via per-file "
                f"fingerprint, got exit={code} read={p['holdout_read']} "
                f"ev={p['verdicts'][0]['evidence']} warn={p['warnings']}",
                failures)

        # R20-L1 (round-20 Minor): R19-B1-1's evidence substring is itself
        # locked (fr1 is the log-deleted fixture from R19-B1-1).
        p, code = evaluate(fr1)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and "no valid consumption credit"
                in p["verdicts"][0]["evidence"],
                "R20-L1 R19-B1-1 evidence must contain 'no valid "
                "consumption credit'", failures)

        # R20-L2: R19-B1-2's warning substring is locked (fr2 = forged
        # state.snapshot fixture from R19-B1-2).
        p, code = evaluate(fr2)
        n_asserts += 1
        _expect(code == EXIT_BLOCKED
                and any("log holdout_read event #1 snapshot differs from "
                        "the state snapshot (round-19 B-1)" in w
                        for w in p["warnings"]),
                "R20-L2 R19-B1-2 warning must contain the exact "
                "snapshot-differs substring", failures)

        # R20-L3a/b/c: R19-M1-1/2/3's warning substring is locked
        # (fr4/fr5/fr6 = post-consumption by_asset/coin additions).
        for tag, fol in (("a", fr4), ("b", fr5), ("c", fr6)):
            p, code = evaluate(fol)
            n_asserts += 1
            _expect(code == EXIT_BLOCKED
                    and any("by_asset fingerprint changed since "
                            "consumption (round-19 M-1)" in w
                            for w in p["warnings"]),
                    f"R20-L3{tag} R19-M1 warning must contain the exact "
                    f"fingerprint-changed substring", failures)

        # R20-L4a/b: R19-M2 evidence names the entry shape (fr7 is in its
        # ACME.parquet state after R19-M2-2; restore the .bak state first).
        (fr7 / "by_asset" / "ACME.parquet").unlink()
        (fr7 / "by_asset" / "ACME.csv.bak").write_text(
            "date,strategy_net,strategy_gross,benchmark\n"
            "2026-08-01,1,1,1\n", encoding="utf-8")
        p, code = evaluate(fr7)
        n_asserts += 1
        _expect(code == EXIT_PASS and "UNSCANNED non-csv entries"
                in p["verdicts"][0]["evidence"],
                "R20-L4a R19-M2-1 evidence must contain 'UNSCANNED non-csv "
                "entries'", failures)
        (fr7 / "by_asset" / "ACME.csv.bak").unlink()
        (fr7 / "by_asset" / "ACME.parquet").write_bytes(b"\x00\x01")
        p, code = evaluate(fr7)
        n_asserts += 1
        _expect(code == EXIT_PASS and "UNSCANNED non-csv entries"
                in p["verdicts"][0]["evidence"],
                "R20-L4b R19-M2-2 evidence must contain 'UNSCANNED non-csv "
                "entries'", failures)

        # R20-L5: R19-m-1's warning must contain BOTH exact substrings
        # (fr8 = stale-credit-not-reached fixture from R19-m-1).
        p, code = evaluate(fr8)
        n_asserts += 1
        _expect(code == EXIT_PASS
                and any("consumption credit INVALID" in w
                        and "equity last date changed since consumption" in w
                        for w in p["warnings"]),
                "R20-L5 R19-m-1 warning must contain both 'consumption "
                "credit INVALID' and 'equity last date changed since "
                "consumption'", failures)

        # ==== round-21: M-1 residual - same-stem dual-path pair ==========
        # 'ACME.csv' and 'ACME.CSV' share Path.stem 'ACME' but are TWO files
        # on a case-sensitive volume. The selftest volume may fold the two
        # names into one file, so the dual-path dir state is fed DIRECTLY
        # (round-21 review's sanctioned option): two REAL csv files live in
        # separate temp subdirs and by_asset_dir_state is monkeypatched to
        # expose them as one by_asset/ pair. Restored in finally - no other
        # fixture may observe the patch.
        fr13 = root / "r21-same-stem"
        _mk_run(fr13, _base_run(holdout={"start": "2026-06-01"}))
        _mk_equity(fr13, ["2026-01-01", "2026-05-31"])
        pair_a = root / "r21-pair-a"   # loser: ACME.csv, 30 days
        pair_b = root / "r21-pair-b"   # winner: ACME.CSV, 600 days
        _mk_by_asset(pair_a, "ACME", 30, filename="ACME.csv")
        _mk_by_asset(pair_b, "ACME", 600, filename="ACME.CSV")
        p_a = pair_a / "by_asset" / "ACME.csv"
        p_b = pair_b / "by_asset" / "ACME.CSV"
        fake_state = {"present": True, "subdirs": [],
                      "csvs": [("ACME", p_a), ("ACME", p_b)],
                      "non_csv": []}
        orig_dir_state = globals()["by_asset_dir_state"]

        # R21-M1-pre: BEFORE consumption the loser's last (2026-08-23) is
        # >= start -> BLOCKED. (Pre-fix, scan_last only saw the stem-
        # collapsed entry -> "not reached" exit 0.)
        globals()["by_asset_dir_state"] = lambda folder: dict(fake_state)
        try:
            p, code = evaluate(fr13)
        finally:
            globals()["by_asset_dir_state"] = orig_dir_state
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["verdicts"][0]["fired"]
                and "no valid consumption credit"
                in p["verdicts"][0]["evidence"]
                and "not reached" not in p["verdicts"][0]["evidence"],
                f"R21-M1-pre same-stem dual pair must BLOCK pre-consumption "
                f"(loser last >= start), got exit={code} "
                f"ev={p['verdicts'][0]['evidence']}", failures)

        # R21-M1-mark: mark-read records BOTH files' TRUE spans.
        globals()["by_asset_dir_state"] = lambda folder: dict(fake_state)
        try:
            _mp, mcode = mark_read(fr13, note="r21")
        finally:
            globals()["by_asset_dir_state"] = orig_dir_state
        n_asserts += 1
        _expect(mcode == EXIT_PASS,
                "R21-M1 mark-read on the dual-path pair should succeed",
                failures)
        snap = json.loads((fr13 / STATE_FILE).read_text())["snapshot"]
        files = sorted(a["file"] for a in snap["by_asset"]["assets"])
        lasts = sorted(a["last"] for a in snap["by_asset"]["assets"])
        n_asserts += 1
        _expect(files == ["ACME.CSV", "ACME.csv"]
                and lasts == ["2025-01-30", "2026-08-23"],
                f"R21-M1 snapshot must carry BOTH same-stem files' true "
                f"spans, got files={files} lasts={lasts}", failures)

        # R21-M1-post: extend the LOSER's dates after consumption -> the
        # fingerprint must change -> credit INVALID -> BLOCK.
        _mk_by_asset(pair_a, "ACME", 700, filename="ACME.csv")
        globals()["by_asset_dir_state"] = lambda folder: dict(fake_state)
        try:
            p, code = evaluate(fr13)
        finally:
            globals()["by_asset_dir_state"] = orig_dir_state
        n_asserts += 1
        _expect(code == EXIT_BLOCKED and p["holdout_read"] is False
                and "was consumed" not in p["verdicts"][0]["evidence"]
                and any("by_asset fingerprint changed since consumption"
                        in w for w in p["warnings"]),
                f"R21-M1-post loser date extension must invalidate the "
                f"credit and BLOCK, got exit={code} "
                f"read={p['holdout_read']} warn={p['warnings']}", failures)

        # 5N. calendar missing -> exit 2 (never guessed)
        f10 = root / "nocal"
        run_nc = _base_run()
        del run_nc["calendar"]
        _mk_run(f10, run_nc)
        _mk_equity(f10, ["2026-01-01"])
        try:
            evaluate(f10)
            n_asserts += 1
            _expect(False, "5N missing calendar must raise", failures)
        except GuardInputError:
            n_asserts += 1  # correct

        # 5N2. holdout KEY missing (distinct from null) -> exit 2
        f11 = root / "noholdoutkey"
        run_nh = _base_run()
        del run_nh["holdout"]
        _mk_run(f11, run_nh)
        _mk_equity(f11, ["2026-01-01"])
        try:
            evaluate(f11)
            n_asserts += 1
            _expect(False, "5N2 missing holdout key must raise", failures)
        except GuardInputError:
            n_asserts += 1  # correct

        # 5N3. illegal calendar values (round-18 regression lock) -> exit 2
        for tag, bad in (("null", ("calendar", None)),
                         ("empty", ("calendar", "")),
                         ("upper", ("calendar", "CRYPTO")),
                         ("pad", ("calendar", " crypto ")),
                         ("int", ("calendar", 365)),
                         ("list", ("calendar", ["crypto"])),
                         ("wrongcase", ("Calendar", "crypto"))):
            f12 = root / f"badcal-{tag}"
            run_bc = _base_run()
            del run_bc["calendar"]      # the real key must be GONE...
            run_bc[bad[0]] = bad[1]     # ...before the wrong name lands
            _mk_run(f12, run_bc)
            _mk_equity(f12, ["2026-01-01"])
            try:
                evaluate(f12)
                n_asserts += 1
                _expect(False, f"5N3 calendar {tag} must raise", failures)
            except GuardInputError:
                n_asserts += 1  # correct
        f12ok = root / "goodcal-tradfi"
        _mk_run(f12ok, _base_run(calendar="tradfi"))
        _mk_equity(f12ok, ["2026-01-01"])
        p, code = evaluate(f12ok)
        n_asserts += 1
        _expect(code == EXIT_PASS, "5N3b legal tradfi calendar passes",
                failures)

        # 6N. broken equity shapes -> exit 2
        for tag, maker in (
            ("ragged", lambda fol: (fol / EQUITY_FILE).write_text(
                "date,strategy_net,strategy_gross,benchmark\n"
                "2026-01-01,1,1\n", encoding="utf-8")),
            ("empty", lambda fol: (fol / EQUITY_FILE).write_text(
                "", encoding="utf-8")),
            ("header-only", lambda fol: (fol / EQUITY_FILE).write_text(
                "date,strategy_net,strategy_gross,benchmark\n",
                encoding="utf-8")),
            ("bad-date", lambda fol: (fol / EQUITY_FILE).write_text(
                "date,strategy_net,strategy_gross,benchmark\n"
                "not-a-date,1,1,1\n", encoding="utf-8")),
            ("invalid-cal-date", lambda fol: (fol / EQUITY_FILE).write_text(
                "date,strategy_net,strategy_gross,benchmark\n"
                "2025-02-29,1,1,1\n", encoding="utf-8")),
        ):
            fb = root / f"broken-{tag}"
            _mk_run(fb, _base_run())
            maker(fb)
            try:
                evaluate(fb)
                n_asserts += 1
                _expect(False, f"6N {tag} equity must raise", failures)
            except GuardInputError:
                n_asserts += 1  # correct

        # 7N. missing run.json -> exit 2
        f13 = root / "norun"
        f13.mkdir()
        _mk_equity(f13, ["2026-01-01"])
        try:
            evaluate(f13)
            n_asserts += 1
            _expect(False, "7N missing run.json must raise", failures)
        except GuardInputError:
            n_asserts += 1  # correct

        # 8N. mark-read on holdout null -> refuse
        f14 = root / "mr-null"
        _mk_run(f14, _base_run())
        _mk_equity(f14, ["2026-01-01"])
        try:
            mark_read(f14)
            n_asserts += 1
            _expect(False, "8N mark-read on null holdout must refuse",
                    failures)
        except GuardInputError:
            n_asserts += 1  # correct

        # 9P/9N. mark-read once; second attempt refused
        f15 = root / "mr-once"
        _mk_run(f15, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(f15, ["2026-01-01", "2026-09-30"])
        _mp, c1 = mark_read(f15, note="first")
        n_asserts += 1
        _expect(c1 == EXIT_PASS, "9P first mark-read should succeed",
                failures)
        try:
            mark_read(f15, note="second")
            n_asserts += 1
            _expect(False, "9N second mark-read must refuse", failures)
        except GuardInputError:
            n_asserts += 1  # correct
        log = json.loads((f15 / LOG_FILE).read_text())
        n_asserts += 1
        _expect(len(log["events"]) == 1
                and isinstance(log["events"][0].get("snapshot"), dict),
                "9P exactly one log event WITH snapshot expected (B-1)",
                failures)

        # 10N. holdout.coins malformed -> exit 2
        f16 = root / "badcoins"
        _mk_run(f16, _base_run(holdout={"coins": []}))
        _mk_equity(f16, ["2026-01-01"])
        try:
            evaluate(f16)
            n_asserts += 1
            _expect(False, "10N empty coins list must raise", failures)
        except GuardInputError:
            n_asserts += 1  # correct
        f16b = root / "dictcoins"
        _mk_run(f16b, _base_run(holdout={"coins": [{"a": 1}]}))
        _mk_equity(f16b, ["2026-01-01"])
        try:
            evaluate(f16b)
            n_asserts += 1
            _expect(False, "10N2 dict coins must raise GuardInputError "
                           "(m-5)", failures)
        except GuardInputError:
            n_asserts += 1  # correct

        # 11N. holdout.start unparseable -> exit 2
        f17 = root / "badstart"
        _mk_run(f17, _base_run(holdout={"start": "tomorrow"}))
        _mk_equity(f17, ["2026-01-01"])
        try:
            evaluate(f17)
            n_asserts += 1
            _expect(False, "11N bad start date must raise", failures)
        except GuardInputError:
            n_asserts += 1  # correct

        # 11N2. holdout {} -> exit 2 (round-18 lock)
        f17b = root / "empty-holdout"
        _mk_run(f17b, _base_run(holdout={}))
        _mk_equity(f17b, ["2026-01-01"])
        try:
            evaluate(f17b)
            n_asserts += 1
            _expect(False, "11N2 empty holdout object must raise", failures)
        except GuardInputError:
            n_asserts += 1  # correct

        # 13. CLI subprocess mapping (round-17 + round-18 m-2/m-3): the
        # documented exit codes must hold through main(), including the
        # stdout JSON envelope.
        f18 = root / "cli-broken"
        f18.mkdir()
        proc = subprocess.run(
            [sys.executable, str(tool_path), "check", str(f18)],
            capture_output=True, text=True)
        n_asserts += 1
        _expect(proc.returncode == EXIT_INPUT_ERROR and '"error"' in
                proc.stdout and "Traceback" not in proc.stderr,
                f"13 CLI broken input must exit {EXIT_INPUT_ERROR} with "
                f"error JSON, got rc={proc.returncode}", failures)

        f18b = root / "cli-clean"
        _mk_run(f18b, _base_run())
        _mk_equity(f18b, ["2026-01-01"])
        proc = subprocess.run(
            [sys.executable, str(tool_path), "check", str(f18b)],
            capture_output=True, text=True)
        n_asserts += 1
        _expect(proc.returncode == EXIT_PASS and "Traceback" not in
                proc.stderr, "13b CLI clean pass exits 0", failures)

        f18c = root / "cli-blocked"
        _mk_run(f18c, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(f18c, ["2026-01-01"])
        proc = subprocess.run(
            [sys.executable, str(tool_path), "check", str(f18c)],
            capture_output=True, text=True)
        n_asserts += 1
        _expect(proc.returncode == EXIT_BLOCKED and "Traceback" not in
                proc.stderr, "13c CLI blocked exits 1", failures)

        # 13d/13e. argparse + negative threshold carry the JSON envelope (m-3)
        proc = subprocess.run(
            [sys.executable, str(tool_path), "check", str(f18b),
             "--min-days", "foo"], capture_output=True, text=True)
        n_asserts += 1
        _expect(proc.returncode == EXIT_INPUT_ERROR and '"error"' in
                proc.stdout and "Traceback" not in proc.stderr,
                "13d --min-days foo must exit 2 with stdout error JSON",
                failures)
        proc = subprocess.run(
            [sys.executable, str(tool_path), "check", str(f18b),
             "--min-days", "-1"], capture_output=True, text=True)
        n_asserts += 1
        _expect(proc.returncode == EXIT_INPUT_ERROR and '"error"' in
                proc.stdout,
                "13e --min-days -1 must be refused with exit 2 JSON",
                failures)

        # 14. m-5: log events containing null -> explicit GuardInputError
        f19 = root / "null-events"
        _mk_run(f19, _base_run(holdout={"start": "2026-01-01"}))
        _mk_equity(f19, ["2026-01-01", "2026-09-30"])
        (f19 / STATE_FILE).write_text(json.dumps({"holdout_read": True}),
                                      encoding="utf-8")
        (f19 / LOG_FILE).write_text(json.dumps(
            {"events": [None, {"action": "holdout_read", "at": "x"}]}),
            encoding="utf-8")
        try:
            evaluate(f19)
            n_asserts += 1
            _expect(False, "14 null event entry must raise GuardInputError",
                    failures)
        except GuardInputError:
            n_asserts += 1  # correct

    payload = {
        "tool": "holdout_guard",
        "guard_version": GUARD_VERSION,
        "contract_version": CONTRACT_VERSION,
        "command": "selftest",
        "assertions": n_asserts,
        "failures": failures,
        "ok": not failures,
    }
    return payload, (EXIT_PASS if not failures else EXIT_BLOCKED)


# ==========================================================================
# CLI
# ==========================================================================

def main() -> None:
    ap = argparse.ArgumentParser(description="backtest-lint holdout_guard")
    ap.add_argument("command", choices=["check", "mark-read", "selftest"])
    ap.add_argument("folder", nargs="?", help="run folder (check/mark-read)")
    ap.add_argument("--min-days", type=int, default=MIN_DAYS,
                    help=f"parking threshold (default {MIN_DAYS})")
    ap.add_argument("--note", default="", help="mark-read note")
    try:
        args = ap.parse_args()
    except SystemExit as e:
        # round-18 m-3 + round-19 m-3: argparse usage errors must still
        # honor the exit-2 stdout JSON envelope (usage itself goes to
        # stderr, no traceback) - but a SUCCESSFUL --help (SystemExit 0)
        # must NOT get the error envelope appended after the help text.
        if e.code not in (0, None):
            print(json.dumps({"tool": "holdout_guard",
                              "guard_version": GUARD_VERSION,
                              "error": "invalid arguments (usage on stderr)"}))
        raise

    if args.min_days < 0:
        print(json.dumps({"tool": "holdout_guard",
                          "guard_version": GUARD_VERSION,
                          "error": f"--min-days must be >= 0, got "
                                   f"{args.min_days}"}))
        sys.exit(EXIT_INPUT_ERROR)

    if args.command == "selftest":
        try:
            payload, code = run_selftest()
        except Exception as e:  # no-crash contract holds even for the probe
            print(json.dumps({"tool": "holdout_guard", "command": "selftest",
                              "error": f"selftest crashed: {e}"}))
            sys.exit(EXIT_INPUT_ERROR)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.exit(code)

    if not args.folder:
        print(json.dumps({"tool": "holdout_guard",
                          "guard_version": GUARD_VERSION,
                          "error": "command requires <run_folder>"}))
        sys.exit(EXIT_INPUT_ERROR)
    folder = Path(args.folder)
    try:
        if args.command == "check":
            payload, code = evaluate(folder, min_days=args.min_days)
        else:
            payload, code = mark_read(folder, note=args.note)
    except GuardInputError as e:
        print(json.dumps({"tool": "holdout_guard",
                          "guard_version": GUARD_VERSION,
                          "command": args.command,
                          "run_folder": str(folder),
                          "error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(EXIT_INPUT_ERROR)
    except Exception as e:  # no-crash contract: catch-all -> error JSON
        print(json.dumps({"tool": "holdout_guard",
                          "guard_version": GUARD_VERSION,
                          "command": args.command,
                          "run_folder": str(folder),
                          "error": f"unexpected: {type(e).__name__}: {e}"},
                         ensure_ascii=False, indent=2))
        sys.exit(EXIT_INPUT_ERROR)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
