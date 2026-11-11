# LINT-SPEC v0.1 — semantics of `tools/lint.py`

- **Version**: 0.1.2 (review history in §7)
- **Exam**: 18 frozen lint samples in `tests/corpus/` (15 planted defects + 3 clean strategies), answer key `tests/corpus/expected_results.json` (module = `lint`)
- **Implementation**: standard library only (`ast`, `json`, `argparse`) — zero third-party dependencies

---

## 1. Rule semantics

| Rule | Defect | Detection mechanism |
|---|---|---|
| `lint.101` | **Same-bar execution**: a position decided on bar-`t` information multiplied by the bar-`t` close-to-close return | Product pattern on `df["pnl"]`: the position side (a `POS`/`SIGNAL`-named column) has **at least one unprotected bar-`t` price read** (`bar_t_cols` non-empty; reads propagate through df columns, variables and helper arguments), and the return side has `ret_source == 'close'`. **Lag judgment follows execution timing, not syntax**: the position is T+1 clean when every price read feeding it is protected by `shift(k>=1)` — wherever the shift is written (both operands inside a comparison, a helper's `return` suffix, inside a `np.where` argument). `shift(0)` is an explicit identity and does not protect. Helper wrappers and loop forms are covered (loop body reads `.iloc[loopvar]` → appended list → position column → × close return) |
| `lint.102` | **Look-ahead**: an unlagged position multiplied by an open-to-open return (bar-`t` close information used for a fill at bar-`t` open) | Same product pattern, `ret_source == 'open'`. **The price read used for conviction** is the actual column(s) in the position's `bar_t_cols` — an unprotected read of close, open, high or low all qualify. Evidence names only the columns actually read; `close` is mentioned only when an unprotected close read genuinely exists |
| `lint.103` | **Centered window**: `rolling(center=True)`, including the `.apply` form, `**kwargs` passthrough into a helper's `rolling(**kw)`, and the positional third argument | The `center` feature propagates through the column/variable inheritance graph into the position/pnl chain (transitive reachability) |
| `lint.104` | **Future data leak**: `shift(negative)`; terminal scalar (`[-1]`-style index); `iloc[-N:]` tail-window statistics | Negative shift is convicted syntactically (including through helper bodies merged at the call site). Terminal scalars and tail-window statistics are convicted only when they flow into a signal/position/pnl chain — reporting uses such as `final = eq.iloc[-1]` are not flagged |
| `lint.105` | **Vacuous gates**: no assertions, all assertions commented out, or only tautologies (`assert True`, `is (not) None`, constant-vs-constant comparison) | File-level effective-assertion count equals zero **and** no 101–104 hit. Single-defect corpus convention: execution-level defects take precedence, so 105 is suppressed when a stronger rule fires |

---

## 2. Verdict tiers

| Tier | Meaning |
|---|---|
| `verified` | The pattern itself is a contract violation — a deterministic statement about the code. 101–104 hit at this tier. |
| `suspicious` | Pattern is a strong signal but context-dependent. |
| `cannot_determine` | Not enough information. A file with no `df["col"]` strategy pattern produces **no findings** rather than an invented verdict. 105 uses exact counting, not estimation. |

The corpus expects `verified` for all planted defects (they are constructed to be deterministic), matching the profiler's convention.

---

## 3. Suppression rule (105)

`lint.105` stays silent whenever any of 101–104 fires. Rationale: the corpus is single-defect by construction (every expected `rules` array has exactly one element), and in real code an execution-level defect is the stronger finding. This is a product decision, not an optimisation; see §7.

---

## 4. Known limitations (disclosed, not hidden)

1. **Name-level data flow.** Column/variable tracking is by name. pandas chain renaming (`df.rename`, rebinding an intermediate DataFrame) is not fully modelled.
2. **`shift(unresolvable variable)` is treated as lagged.** Deliberate direction: anti-false-positive, at the cost of possible misses.
3. **Return source is limited to close → 101 and open → 102.** high/low return sources are not judged (not covered by the corpus).
4. **Loop coverage is narrow.** Only the append-to-list → `[0]+` concatenation → same-bar product form is detected. Other loop shapes (e.g. per-bar cash accounting) are not judged.
5. **Tautology catalogue is finite.** Constant truthiness, `is (not) None`, and constant-vs-constant comparisons. Semantically vacuous but syntactically complex assertions (e.g. `assert len(df) > 0`) count as effective.
6. **Helper `center` via positional argument is not captured.** `rolling(20, 5, True)` inside a helper body escapes passthrough detection, which only covers `**kwargs` and call-site keywords.
7. **Return series via a local alias is not convicted.** After `close = df["close"]`, `close.pct_change()` does not resolve `ret_source` (only the direct `df["close"].pct_change()` subscript form is recognised), so 101/102 are missed. Likewise, assigning `pnl` to a plain variable (a `Name` target) never reaches the product check, which fires only on `df["pnl"]` column assignment. Both behaviours predate v0.1.1 and are not regressions; the corpus and the review probes all use direct `df[...]` subscripts. **Status: disclosed, not fixed in this version.** Position-side aliases *do* work — `close = df["close"]` followed by `(close.shift(1) > ma.shift(1))` is correctly treated as lagged.
8. **Helper lag is recognised only via a `return`-suffix shift.** Transparent suffixes (`fillna`, `astype`) are peeled, but a `shift` *inside* the returned expression — `return (close.shift(1) > close.rolling(20).mean().shift(1)).astype(int)` — or assigning to a local and returning it bare (`lagged = sig.shift(1); return lagged`) means the call site may still treat the input as bar-`t` and report 101 falsely. Same family as limitation 6: helper bodies are not inlined.
9. **`name_of` transparent-suffix whitelist excludes `.where` / `.mask`.** `df["pnl"] = df["position"].where(...) * df["close"].pct_change()` hides the position name, so a genuine same-bar defect is missed. `fillna` is covered (fixed in v0.1.1).
10. **Top-level statements are not analysed.** Analysis starts inside function bodies. A module-level expression — e.g. `df["pnl"] = df["position"] * df["close"].pct_change()` written at import time — yields `strategy_like: false` and no findings at all. Write strategies as functions that take a DataFrame. Extending the product check to module level would require modelling globals and import order, which a tool that never executes the file cannot do honestly. **This one is a scope boundary, not a bug: it is disclosed because "no findings" would otherwise read as "no defects".**

---

## 5. CLI and verification

```bash
python3 tools/lint.py check <file.py|dir>        # JSON findings, exit 0 = normal
python3 tools/lint.py gate --corpus tests/corpus # 18/18, exit 0 iff all pass
python3 tools/lint.py selftest                   # 31/31 (27 inline positive/negative
                                                 # probes incl. T+1 lag forms and
                                                 # evidence-content assertions,
                                                 # + 3 CLI probes + gate control)
```

Exit convention: `0` = normal (findings are the product); `1` = gate/selftest failed; `2` = input error (missing file, syntax error, non-`.py`), with an error JSON envelope on stdout and no traceback.

---

## 6. Writing code the linter can see

These are mechanical visibility constraints, not style preferences:

```python
# ✅ direct subscript + column assignment
df["pnl"] = df["position"] * df["close"].pct_change()

# ✅ lag anywhere is fine — comparison operands, helper return, np.where
df["position"] = (df["close"].shift(1) > ma.shift(1)).astype(int)
def lagged(s): return sig(s).shift(1)          # return-suffix shift
df["position"] = np.where(sig.shift(1) > 0, 1, 0)
```

See `DEPLOY.md` §5 for the three forms that are silently missed (limitations 7 and 9).

---

## 7. Version history

| Version | Change |
|---|---|
| 0.1.0 | Initial delivery: five rules, 18/18 corpus, 20/20 selftest. |
| 0.1.1 | Review fixes. **M-1**: lag judgment moved from "shift on the definition suffix" to "every price read protected by `shift(k>=1)`" (`bar_t_cols`), fixing four false-positive T+1 forms and one missed conviction (`position.fillna(0)`). **m-1**: 102 evidence now names only the price columns actually read. `shift(0)` explicitly does not protect; helper lag via `return` suffix is recognised (with transitive local-variable expansion). 30/30 selftest. Limitations 7–9 disclosed after that review. |
| 0.1.2 | `gate` no longer escapes as a bare traceback on a corpus it cannot read: a corrupt or structurally invalid `expected_results.json` now prints a JSON error envelope on stdout and exits `2` (input error), instead of raising with an empty stdout. Detection rules unchanged; 18/18 corpus, 31/31 selftest. |

This version was reviewed against a written adversarial brief, by a second agent on the same machine under the same owner — a review, not a third-party audit. Where that review found a limit rather than a defect, the limit is recorded in §4 instead of being removed.
