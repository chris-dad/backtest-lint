"""research_kit equity_io: run-folder loading for the Phase 4 audit kit.

Contract source: RUN_FOLDER_CONTRACT.md v0.1.5. Hard field validation
belongs HERE at consumption time (contract section 2: benchmark / period
/ data_source / costs / tried_variants are warn-only in the guard and
HARD here).

Robustness: no input shape crashes; every malformed shape raises
KitInputError -> exit 2 with an error JSON (no-crash contract).
Accounting keys are raw date literals / column names as written.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from datetime import date
from pathlib import Path

RUN_FILE = "run.json"
EQUITY_FILE = "equity.csv"
EXPOSURE_FILE = "exposure.csv"
TRADES_FILE = "trades.csv"
TIME_COLS = ("date", "timestamp", "trade_date", "t", "ts", "time")
CALENDARS = ("crypto", "tradfi")
ANN_FACTOR = {"crypto": 365, "tradfi": 252}


class KitInputError(ValueError):
    """Structurally broken input -> exit 2 with an error JSON."""


def _parse_date(s: object) -> date:
    token = str(s).strip().split("T")[0].split(" ")[0]
    try:
        return date.fromisoformat(token)
    except ValueError as e:
        raise KitInputError(f"unparseable date {s!r}") from e


def load_run_json(folder: Path) -> dict:
    path = folder / RUN_FILE
    if not path.is_file():
        raise KitInputError(f"{RUN_FILE} missing in {folder}")
    try:
        run = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise KitInputError(f"{RUN_FILE} unparseable: {e}") from e
    if not isinstance(run, dict):
        raise KitInputError(f"{RUN_FILE} must be a JSON object")
    if run.get("calendar") not in CALENDARS:
        raise KitInputError(
            f"{RUN_FILE}: calendar must be one of {list(CALENDARS)}, "
            f"got {run.get('calendar')!r}")
    # Contract section 2: hard validation happens HERE (research_kit).
    for field in ("benchmark", "period", "data_source", "costs",
                  "tried_variants"):
        if field not in run:
            raise KitInputError(
                f"{RUN_FILE}: required field '{field}' missing "
                f"(research_kit hard validation, contract s2)")
    if not isinstance(run["benchmark"], str) or not run["benchmark"].strip():
        raise KitInputError("run.json: benchmark must be a non-empty string")
    if not isinstance(run["period"], dict):
        raise KitInputError("run.json: period must be an object")
    for k in ("start", "end"):
        if k not in run["period"]:
            raise KitInputError(f"run.json: period.{k} missing")
        _parse_date(run["period"][k])
    if not isinstance(run["data_source"], str) or not run["data_source"].strip():
        raise KitInputError("run.json: data_source must be a non-empty string")
    if not isinstance(run["costs"], dict) or not run["costs"]:
        raise KitInputError("run.json: costs must be a non-empty object")
    tv = run["tried_variants"]
    if isinstance(tv, bool) or not isinstance(tv, int) or tv < 1:
        raise KitInputError(
            f"run.json: tried_variants must be an integer >= 1, got {tv!r}")
    # round-24 residual close-out (Phase 5): the key present but null is
    # ambiguous - omit the key for the proxy, never write null.
    if "variant_srs" in run and run["variant_srs"] is None:
        raise KitInputError(
            "run.json: variant_srs is null; omit the key to use the "
            "SR-estimator proxy (key-present-null is ambiguous)")
    sa = run.get("search_adapter")
    if sa is not None:
        ok = isinstance(sa, str) and sa.strip() or (
            isinstance(sa, dict) and isinstance(sa.get("path"), str)
            and sa["path"].strip())
        if not ok:
            raise KitInputError(
                "run.json: search_adapter must be a module path string or "
                f"an object with a non-empty 'path' (got {sa!r})")
    return run


def read_numeric_table(path: Path, label: str,
                       required_cols: tuple[str, ...]) -> list[dict]:
    """Parse a csv with one recognized time column + required numeric
    columns. Returns rows sorted by date: [{"date": date, col: float}].
    Casefolded duplicate time-column names -> structural error (contract
    s3 rule 7, round-18 M-8). Non-finite values are poison -> error."""
    if not path.is_file():
        raise KitInputError(f"{label}: file missing")
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise KitInputError(f"{label}: empty file (no header)")
        cols = [h.strip() for h in header]
        if len(set(cols)) != len(cols):
            raise KitInputError(f"{label}: duplicate column names")
        time_idx = [i for i, c in enumerate(cols) if c.lower() in TIME_COLS]
        if not time_idx:
            raise KitInputError(
                f"{label}: no time column (looked for {TIME_COLS})")
        time_names = [cols[i].lower() for i in time_idx]
        if len(set(time_names)) != len(time_names):
            raise KitInputError(
                f"{label}: duplicate time-column names after case-folding "
                f"{time_names} (round-18 M-8)")
        if len(time_idx) > 1:
            raise KitInputError(
                f"{label}: research_kit reads exactly one time column, "
                f"found {len(time_idx)} ({time_names})")
        t_i = time_idx[0]
        col_idx: dict[str, int] = {}
        for c in required_cols:
            if c not in cols:
                raise KitInputError(
                    f"{label}: required column '{c}' missing "
                    f"(header {cols})")
            col_idx[c] = cols.index(c)
        rows: list[dict] = []
        for lineno, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(cols):
                raise KitInputError(
                    f"{label} line {lineno}: ragged row "
                    f"({len(row)} cells vs {len(cols)} columns)")
            d = _parse_date(row[t_i])
            vals: dict[str, float] = {}
            for c, i in col_idx.items():
                try:
                    v = float(row[i])
                except ValueError as e:
                    raise KitInputError(
                        f"{label} line {lineno}: column '{c}' not numeric: "
                        f"{row[i]!r}") from e
                if not math.isfinite(v):
                    raise KitInputError(
                        f"{label} line {lineno}: column '{c}' non-finite "
                        f"({row[i]!r}) - poison guard")
                vals[c] = v
            rows.append({"date": d, **vals})
        if not rows:
            raise KitInputError(f"{label}: header only, no data rows")
    rows.sort(key=lambda r: r["date"])
    dupes = sum(1 for a, b in zip(rows, rows[1:]) if a["date"] == b["date"])
    if dupes:
        raise KitInputError(f"{label}: {dupes} duplicate date rows")
    return rows


def guard_precheck(folder: Path) -> dict:
    """Consume precondition (spec v1.0 s3): guard check must not block.
    Reuses holdout_guard.evaluate (no re-implementation of holdout rules).
    Blocked/structural -> KitInputError (exit 2), never a silent pass."""
    tools_dir = str(Path(__file__).resolve().parent.parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import holdout_guard  # noqa: PLC0415 - deliberate late import
    try:
        payload, code = holdout_guard.evaluate(folder)
    except holdout_guard.GuardInputError as e:
        raise KitInputError(f"guard structural error: {e}") from e
    if code == holdout_guard.EXIT_BLOCKED:
        ev = "; ".join(v.get("evidence", "") for v in payload["verdicts"]
                       if v.get("fired"))
        raise KitInputError(
            f"guard blocks this folder (exit 1): {ev or payload['status']}"
            " - resolve the holdout gate before running research_kit")
    return payload


def load_run_folder(folder: Path) -> dict:
    """Load a run folder per contract v0.1.5. Returns ctx dict:
    {"folder", "run", "equity": rows, "exposure": rows|None,
     "exposure_source": "exposure.csv"|"trades.csv"|None}."""
    run = load_run_json(folder)
    equity = read_numeric_table(
        folder / EQUITY_FILE, EQUITY_FILE,
        ("strategy_net", "strategy_gross", "benchmark"))
    if len(equity) < 2:
        raise KitInputError(
            f"{EQUITY_FILE}: need >= 2 rows for daily returns, got "
            f"{len(equity)}")
    for r in equity:
        for c in ("strategy_net", "strategy_gross", "benchmark"):
            if r[c] <= 0:
                raise KitInputError(
                    f"{EQUITY_FILE} {r['date']}: column '{c}' <= 0 "
                    f"({r[c]!r}) - equity levels are mark-to-market "
                    f"values starting at 1.0 (contract s1)")

    eq_dates = [r["date"] for r in equity]
    exposure_rows = None
    source = "none"
    if (folder / EXPOSURE_FILE).is_file():
        exposure_rows = read_numeric_table(
            folder / EXPOSURE_FILE, EXPOSURE_FILE, ("exposure",))
        exp_dates = [r["date"] for r in exposure_rows]
        if exp_dates != eq_dates:
            first_diff = next((a.isoformat() for a, b
                               in zip(exp_dates, eq_dates) if a != b),
                              "length mismatch")
            raise KitInputError(
                f"{EXPOSURE_FILE}: dates must match {EQUITY_FILE} exactly "
                f"({len(exp_dates)} vs {len(eq_dates)} rows; first diff: "
                f"{first_diff})")
        for r in exposure_rows:
            if not 0.0 <= r["exposure"] <= 1.0:
                raise KitInputError(
                    f"{EXPOSURE_FILE} {r['date']}: exposure "
                    f"{r['exposure']!r} outside [0, 1]")
        source = "exposure.csv"
    elif (folder / TRADES_FILE).is_file():
        # v0.1.0: trades->exposure derivation is NOT implemented; the
        # timing-shuffle builder reports cannot_run while every other
        # test still runs (spec v1.0 s3: never skip silently, never
        # poison the whole check for one test's missing input).
        source = "trades.csv (derivation unsupported in v0.1.0)"
    return {"folder": folder, "run": run, "equity": equity,
            "exposure": exposure_rows, "exposure_source": source}
