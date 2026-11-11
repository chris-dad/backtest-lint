# backtest-lint

**Guardrails for backtests that would otherwise lie to you.**

A backtest is a claim about the future, assembled from code you wrote yourself and data you chose yourself. That is a structurally unreliable narrator. `backtest-lint` is a set of four independent gates that interrogate that narrator at four different layers — source code, input data, execution runtime, and statistical significance — before any number reaches a report.

No third-party dependencies for the static checker. No cloud service. Everything runs locally and emits JSON.

---

## Why this exists

Most backtest tooling helps you **compute** a result. Very little of it helps you decide whether the result is **allowed to be believed**.

The failure modes are not exotic. They are boring, common, and they all inflate returns:

| Failure | What it looks like | Typical cost |
|---|---|---|
| Same-bar execution | `position[t]` built from `close[t]`, multiplied by `close[t]/close[t-1]` | Turns a mediocre strategy into a spectacular one |
| Look-ahead | Signal computed on bar `t` close, filled at bar `t` open | Free money that never existed |
| Centered window | `rolling(20, center=True)` — the window sees 10 bars into the future | Smooth equity curve, fake alpha |
| Future data leak | `shift(-5)`, `iloc[-1]` normalization, tail-window statistics | Every bar knows the ending price |
| Vacuous tests | No assertions, all assertions commented out, `assert True` | Nobody ever checked anything |
| Search-optimal luck | The best of 200 parameter combinations, reported as if it were the only one tried | The entire result may be noise |

Every one of these is a **code-level** or **data-level** defect, which means it can be caught mechanically — before the backtest runs, and before the number is written into a deck.

---

## What makes it different

**1. The exam precedes the candidate.**
The acceptance corpus (`tests/corpus/`, 38 samples: 20 data-quality + 18 code) was written and frozen *before* the detectors existed. Each sample carries an expected verdict in `expected_results.json`. Detectors are graded against a fixed answer key, not the other way round. If a detector fails, the detector gets fixed — the exam does not get edited.

**2. It refuses to fake certainty.**
Every finding carries a tier:

- `verified` — the pattern itself is a contract violation. Deterministic statement about the code.
- `suspicious` — the pattern is a strong signal but context-dependent.
- `cannot_determine` — not enough information. The tools say so instead of inventing a verdict.

`cannot_determine` is a first-class outcome, not an error. A tool that always has an opinion is a tool you cannot trust.

**3. Four layers, not one score.**
A single "quality score" hides where the problem is. These four gates are independent and composable:

| Layer | Tool | Question it answers |
|---|---|---|
| **Code** | `tools/lint.py` | Does the strategy code violate execution contracts? (AST, before running) |
| **Data** | `tools/profiler.py` | Is the input data structurally sound? (gaps, duplicates, NaNs, unit drift) |
| **Runtime** | `tools/holdout_guard.py` | Is the holdout actually held out? (one-shot consumption, four-way snapshot agreement, per-file fingerprint) |
| **Statistics** | `tools/research_kit/` | Is the result distinguishable from luck? (the "luck quartet") |

**4. It publishes its own weaknesses.**
`docs/LINT-SPEC.md` §4 lists ten known limitations — including cases where the linter will *miss* a violation (e.g. when the return series is assigned through a local alias, or when a helper applies `.shift()` inside its `return` expression rather than on it). These are disclosed, not hidden. A guardrail that pretends to be complete is worse than one that tells you where the gaps are.

---

## The four gates

### 1. `lint.py` — static analysis (no dependencies, stdlib only)

Parses strategy source with `ast` and tracks a column-level data-flow graph. No execution, no imports, no pandas required.

```bash
python3 tools/lint.py check strategy.py          # JSON findings
python3 tools/lint.py gate --corpus tests/corpus # 18/18, exit 0 iff all pass
python3 tools/lint.py selftest                   # 30/30
```

| Rule | Detects |
|---|---|
| `lint.101` | Same-bar execution — position built from bar-`t` information × bar-`t` close-to-close return |
| `lint.102` | Look-ahead — unlagged position × open-to-open return |
| `lint.103` | Centered rolling window (`center=True`), including `**kwargs` passthrough and `.apply` forms |
| `lint.104` | Future data leak — negative `shift`, terminal scalar (`[-1]`), tail-window statistics |
| `lint.105` | Vacuous gates — zero effective assertions |

**The lag rule follows execution timing, not syntax.** A position is treated as T+1 clean when every price read that feeds it is protected by `shift(k>=1)` — wherever that shift is written: on both sides inside a comparison, on a helper's `return` suffix, or inside a `np.where` argument. `shift(0)` is an explicit identity and does *not* protect.

### 2. `profiler.py` — input data health

```bash
python3 tools/profiler.py check prices.csv
python3 tools/profiler.py gate --corpus tests/corpus   # 20/20
```

Checks the things that silently corrupt a backtest: calendar gaps, duplicate timestamps, NaN runs, unit/scale drift, stale prices, and metadata mismatches. Emits per-check verdicts with the same three-tier vocabulary.

### 3. `holdout_guard.py` — runtime circuit breaker

Runs before the engine loads data, and refuses the load when the holdout has been touched. It enforces that the holdout window is consumed exactly once, that state and log agree four ways (snapshot = every read event = `run.json` = current equity first/last dates), and that the per-file `by_asset` fingerprint taken at consumption time still matches — any file added, removed, renamed or re-dated afterwards cancels the credit.

Mirror-P&L and settlement-boundary assertions are **not** part of this tool. They belong to the engine's own test suite; a guard that claimed them would be claiming coverage it does not execute.

```bash
python3 tools/holdout_guard.py selftest   # 124/124
```

### 4. `research_kit/` — the luck quartet

Given a standardized run folder (see `RUN_FOLDER_CONTRACT.md`), four independent statistical tests:

| Test | Question |
|---|---|
| **DSR haircut** | After accounting for how many variants were tried, is the Sharpe ratio still positive? (Bailey & López de Prado) |
| **Timing shuffle** | Does the strategy beat randomly reshuffled entry/exit timing on the same asset? |
| **Start-from-each-year** | Does starting in any single year produce a catastrophic result? |
| **Search permutation** | Does the best configuration beat the distribution of *search* outcomes under a null with the same rules? |

```bash
python3 tools/research_kit/cli.py check <run_folder>
python3 tools/research_kit/cli.py selftest   # 96/96
```

The search-permutation test is the one that matters most, and the one most often skipped: it simulates the *entire search process* under the null, so "I found a good parameter set" is compared against "how good does the best parameter set look when there is nothing there?"

---

## Quick start

```bash
git clone https://github.com/chris-dad/backtest-lint.git
cd backtest-lint

# Static check any strategy file — no install, no dependencies
python3 tools/lint.py check /path/to/your_strategy.py

# Verify the toolchain itself
python3 tools/lint.py selftest                    # 30/30
python3 tools/lint.py gate --corpus tests/corpus  # 18/18
python3 tools/profiler.py gate --corpus tests/corpus  # 20/20
python3 tools/holdout_guard.py selftest           # 124/124
python3 tools/research_kit/cli.py selftest        # 96/96
```

A `check` run on a clean strategy prints:

```json
{"file": "strategy.py", "strategy_like": true, "findings": [],
 "caught": false, "rules": [], "lint_version": "0.1.1"}
```

Exit codes are stable and scriptable: `0` = ran, and the findings are the product; `1` = gate/selftest failed **or a holdout check blocked the load**; `2` = bad input (missing file, syntax error, bad argument). Meaning of `1` is per-tool — see the table in `DEPLOY.md` §3. Error envelopes are JSON on stdout, with two exceptions: `--help` prints plain text, and argparse usage errors go to stderr only.

---

## Design principles

- **Mechanical over judgmental.** If a check cannot be made deterministic, it is `suspicious`, not `verified`.
- **Frozen exams.** Detector changes never touch `tests/corpus/`. The answer key is immutable within a corpus version.
- **No silent passes.** Every tool reports what it looked at, what it skipped, and why.
- **JSON everywhere.** Every CLI emits a machine-readable envelope. Designed to be called by CI, by an agent, or by another tool.
- **Disclose the gaps.** Nine known limitations are documented in `docs/LINT-SPEC.md` §4, including asymmetric ones that make the tool look weaker.

---

## Non-goals

- **Not a backtest engine.** It does not price trades, model margin, or generate signals.
- **Not a performance report generator.** It audits claims; it does not manufacture them.
- **Not a strategy library.** No signals, no parameters, no alpha — deliberately.
- **Not exhaustive.** It catches the failures that can be proven statically or structurally. Semantic bugs inside a correct-looking pattern remain your problem.

---

## Requirements

| Component | Requirement |
|---|---|
| `lint.py`, `profiler.py`, `holdout_guard.py`, `build_corpus.py` | Python ≥ 3.9, standard library only |
| `research_kit/` | Python ≥ 3.9 + `pandas` (see `requirements.txt`) |

No network access, no API keys, no telemetry.

---

## Repository layout

```
tools/
  lint.py                 # AST static checker (5 rules)
  profiler.py             # input data health profiler
  holdout_guard.py        # runtime holdout circuit breaker (one-shot consumption)
  research_kit/           # DSR haircut, timing shuffle, start-year, search permutation
  build_corpus.py         # deterministic corpus generator (fixed seed)
  reference_detectors.py  # independent reference implementations
tests/corpus/             # frozen acceptance corpus (38 samples) + answer key
docs/
  LINT-SPEC.md            # rule semantics, tiers, and ten known limitations
RUN_FOLDER_CONTRACT.md    # standard handoff format for engines -> research_kit
DEPLOY.md                 # install, CI, and agent integration
```

---

## Status

| Tool | Version | Acceptance |
|---|---|---|
| lint | 0.1.1 | 18/18 corpus · 30/30 selftest · externally audited |
| profiler | 0.7.1 | 20/20 corpus · 38-sample corpus · externally audited |
| holdout_guard | 0.1.5 | 124/124 selftest |
| research_kit | 0.1.2 | 96/96 selftest |

Each component passed an independent external audit gate before being published. Audit findings, including the ones that failed on first review, are reflected in the limitations section rather than erased.

---

## License

MIT — see [LICENSE](LICENSE).
