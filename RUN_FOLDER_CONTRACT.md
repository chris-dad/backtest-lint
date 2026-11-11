# Run Folder Contract — v0.1.5 (2026-10-06)

> Standard handoff format between a backtest engine and the toolchain (`holdout_guard`, `research_kit`). The engine writes a folder; metrics, luck tests and holdout governance are consumed from it by the tools.
>
> `holdout_guard.selftest` asserts that the first line of this file carries `v0.1.5`, matching `CONTRACT_VERSION` in `tools/holdout_guard.py`. If you change a number in this document, change the constant and the assertions with it.

## 1. File inventory

| File | Required | Content |
|---|---|---|
| `equity.csv` | ✅ | Daily rows: `date`, `strategy_net`, `strategy_gross`, `benchmark`. Equity marked to market every day (not only on close), starting at 1.0. |
| `run.json` | ✅ | Calendar, cost assumptions, data source, period, benchmark name, holdout config, `tried_variants` count (see §2). **A missing `calendar` field is a structural error — the toolchain refuses to guess a calendar.** |
| `trades.csv` | trade-type lanes | One row per trade: instrument, side, entry_time, exit_time, net_return. |
| `exposure.csv` | required for `timing_shuffle` | Daily gross exposure (0 = flat, 1 = fully invested). **`timing_shuffle` needs this file.** A derivation from `trades.csv` is declared upstream but **not implemented here**: a trades-only run folder returns `cannot_run` for that test — it does not pass, and it does not fail. |
| `by_asset/<name>.csv` | multi-asset lanes | Same columns as `equity.csv`, one file per instrument. |
| `guard_state.json` | written by guard | Last-read state (tool-generated; engines must not write it). |
| `guard_log.json` | written by guard | Append-only read-event log (tool-generated; engines must not write it). |

## 2. `run.json` field contract

```json
{
  "calendar": "tradfi",            // required: "crypto" (365) | "tradfi" (252).
                                   // missing / invalid / wrong key case ("Calendar") = exit 2
  "benchmark": "ASSET-BUY-HOLD",   // required: benchmark name (B-lane rules are declared
                                   // by the lane spec)
  "period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},   // required
  "data_source": "vendor_tape_v1", // required: data source identifier
  "costs": {"taker_bps": 10, "slippage_bps": 5},            // required: cost assumptions
  "holdout": null,                 // tri-state: null | {"start": "YYYY-MM-DD"} | {"coins": ["X","Y"]}
                                   //   start and coins together = exit 2 (structural)
                                   //   coins must be a non-empty array of strings, else exit 2
  "tried_variants": 1              // required: integer >= 1 — total variants tried on this
                                   // signal to date, including earlier research. 0 is
                                   // rejected at consumption time (exit 2): a search that
                                   // tried nothing has nothing to haircut.
}
```

- `strategy_gross` includes perpetual funding; `strategy_net` = gross − fees − spread − slippage − borrow.
- `tried_variants` is maintained by the engine/lane; `holdout_guard` and `research_kit` only read it. The multiple-tries haircut is triggered by this number.
- **Field ownership**: `holdout_guard` hard-enforces only `calendar` (missing → exit 2) and the presence of the `holdout` key (tri-state; missing key → exit 2). `benchmark`, `period`, `data_source`, `costs` and `tried_variants` produce warnings when absent; hard validation of those belongs to `research_kit` at consumption time.

## 3. Data rules (engine obligations)

1. **Never guess a calendar.** A missing `calendar` is a refusal (exit 2), not a warning. Wrong key casing (`"Calendar"`) counts as missing.
2. **Do not lose the first day's return.** If the first equity row already contains day-1 return, prepend a `1.0` row for the prior day; do not rebase onto the first row (that swallows day 1). The prepend must happen **before** `mark-read`: the read snapshot binds the first/last equity dates, so adding or removing data afterwards invalidates the consumption credit (see §4).
3. **`min_days` parking.** Instruments in `by_asset/` with less than `min_days` of history (default 180, counted in **distinct calendar days**, not rows — a `date` and a `datetime` on the same day count once) are listed in the output JSON under `parked_assets` with the reason. **Silent dropping is forbidden.** A lane that lowers `min_days` must declare it in the report.
4. **Same-close fills** may appear only as a labelled diagnostic (same-close CAGR can be nearly double next-open in converging markets).
5. **Adjusted prices** may be used to compute returns; they must **not** be used for price levels or thresholds (they embed future splits and dividends).
6. **Date semantics**: comparisons use the calendar literal before `T` or a space; timezone offsets are **not** converted (`2026-05-31T23:00:00-05:00` means 2026-05-31).
7. **Time-column rule**: every column whose casefolded name belongs to the known time-column set participates in the scan, and the global min/max date is taken over all of them. Duplicate time columns after casefolding are a structural error (exit 2).
8. **`by_asset` directory rules**: subdirectories fail closed unconditionally (exit 1) in every holdout mode. `.CSV` and other case variants are scanned as CSV. A non-CSV file present → `cannot_determine` naming the file; a `verified absent` claim is forbidden (same for `start` mode: a "not reached" `verified` claim is forbidden while a non-CSV file is present — tier `cannot_determine` naming the file, exit stays 0). Instrument-name matching normalises with NFKC compatibility equivalence + strip + casefold + whitespace removal. Prefix-similar stems after normalisation → `cannot_determine` naming the file; `verified absent` is forbidden.

## 4. Holdout governance (enforced by `holdout_guard`)

- Explore → freeze → **read exactly once**.
- Default holdout: crypto = the last 12 months or a coin set never seen during exploration; tradfi = the last 25% of history. A lane declares one of the two up front.
- **Date trigger**: `start` mode scans the maximum date across `equity.csv` **and** all `by_asset/*.csv`; touching the holdout start refuses the load (exit 1). `coins` mode triggers when a held-out coin appears in `by_asset` after normalised matching.
- Consumption credit requires **all** of the following; any failure is fail-closed and counts as unread:
  1. `guard_state.json` has `holdout_read` as a **JSON boolean `true`** (the string `"true"` or the number `1` does not count);
  2. `guard_log.json` contains the corresponding `holdout_read` event — **state without a log is unread** (state alone is not evidence, even when it looks like a matching snapshot);
  3. **four-way agreement**: `state.snapshot` = the `snapshot` of **every** `holdout_read` event in the log = the current `run.json` holdout object = the current first/last equity dates. Any mismatch invalidates the credit;
  4. **`by_asset` fingerprint agreement**: the mark-read snapshot records one entry per scanned CSV path — `assets: [{file, stem, first, last}, …]` sorted by original filename; derived names must never be used as record keys. Files whose normalised stems collide, and same-stem files differing only in extension case, are separate records with independent date spans. Scans, fingerprints and parking statistics all work per CSV path (derived names are for matching only). The fingerprint is a per-file set: adding, deleting or renaming any `by_asset` file after consumption — or changing any file's date span — invalidates the credit. The same record also stores the **sorted list of non-CSV file names** and `{"present": false}` when the directory is absent, so a directory that appears, or a stray non-CSV file that lands, after consumption invalidates the credit exactly like a CSV change.
  
  Snapshot-less legacy credits are equally invalid. When credit is invalidated, `holdout_read=false` is reported with an invalidation warning regardless of whether exposure was triggered this round.
- Mark-read write order: **log first, state second**. A crash between the two leaves "log without state", which is fail-closed on the check side, never the reverse.
- Mark-read shares the same structural holdout validation as `check` (double-key holdout, etc. → exit 2). A top-level array log, or any unrecognisable log shape, is rejected **without rewriting the file** — silent reset to `{"events": []}` is forbidden.
- Recovery after invalidation: clear `guard_state.json` and `guard_log.json`, re-evaluate, and mark-read again. This is a re-declaration, consistent with "once seen, no longer a holdout", not a bypass.
- The holdout may only be consumed via `holdout_guard.py mark-read`. Once a `holdout_read` event exists, **any further mark-read is exit 2** regardless of state. Mark-read on `holdout: null` is exit 2.
- Read is read: after consumption the report must state that it is no longer a holdout; continuing requires declaring a new holdout, which inherits no credit from the old one.
- A forward paper run counts as a second holdout.

## 5. Deliberate deviations from the source specification

| Deviation | Reason |
|---|---|
| `run.yaml` → `run.json` | Standard-library-only rule in this repository; YAML is not stdlib. Field semantics are 1:1. |
| `settings.yaml` holding `holdout_read` → `guard_state.json` + `guard_log.json` | Separation of state and evidence: state can be edited, the log is append-only. State without a log is fail-closed. |
| `holdout_guard` does not check walk-forward folds / logging | Declared "planned" upstream as well; out of scope here. |
| Equity date **monotonicity and range coverage** are not enforced | `holdout_guard` takes the min/max date and `research_kit` sorts before use; neither rejects an out-of-order series, nor a series that stops before the holdout start. This is a **declared non-guarantee**, not a validation: consume a monotone, covering series, and treat the absence of a rejection as silence, not approval. The pre-exploration `start` mode keeps its existing semantics — not having reached the holdout is a legitimate state. |

## 6. CLI and exit codes (`tools/holdout_guard.py`)

| Command | Semantics | Exit |
|---|---|---|
| `check <run_folder>` | Pre-load gate: holdout exposure check + parking check + contract validation | 0 = pass / 1 = holdout exposure blocked / 2 = structural error |
| `mark-read <run_folder> [--note "..."]` | One-time holdout consumption | 0 = recorded / 2 = refused (repeat consumption, no holdout, bad input) |
| `selftest` | Built-in positive and negative probes (temporary fixtures) | 0 = all pass / 1 = fail |

All normal output is JSON on stdout; exit 2 carries an `"error"` field, including argparse usage errors and a negative `--min-days`. `--help` is the exception: exit 0, help text on stdout, no error envelope. No input shape may produce a traceback.

## 7. Glossary (every term below is *proposed* — a lane that uses one must define it in its own report)

- **Calmar (whole-period)**: full-period CAGR ÷ deepest drawdown.
- **Days beyond X% drawdown**: total days below a prior high by more than X%, plus the longest consecutive run.
- **Luck test**: a test of whether a result could plausibly be luck.
- **Holdout read**: the single permitted read of frozen-period data.
- **Tried variants**: total rule variants attempted on the same signal, including earlier research.
- **Parked asset**: an instrument excluded from statistics for insufficient history, named explicitly in the output.
- **Run folder**: the standard file set an engine hands to the toolchain.

## 8. Version

- Contract version: **v0.1.5** (2026-10-06). Changes must be mirrored in `GUARD_VERSION` / `CONTRACT_VERSION` and in the selftest assertions, which check that this file's title version equals the constant.
- Every concrete number in this contract (exit-code semantics, `min_days=180`, mark-read refusal conditions, fail-closed variants) is backed by a `selftest` assertion.
- **2026-11-11 editorial pass** (no field, no exit code, no behavioural change, version unchanged): restored two elements that were lost in the original translation — the non-CSV name list and the `{"present": false}` directory-absent record in the §4 fingerprint, and the "define it in the report" obligation on §7 terms; corrected the §2 `tried_variants` example to a legal value; declared the un-enforced equity-order/coverage in §5. Each of these describes what the code already did (or already did not do), so nothing here needed a version bump.
