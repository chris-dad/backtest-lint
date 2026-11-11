# Deployment & Integration

Everything runs locally. No services, no credentials, no network calls.

---

## 1. Requirements

| Component | Python | Third-party |
|---|---|---|
| `tools/lint.py` | ≥ 3.9 | none |
| `tools/profiler.py` | ≥ 3.9 | none |
| `tools/holdout_guard.py` | ≥ 3.9 | none |
| `tools/build_corpus.py` | ≥ 3.9 | none |
| `tools/research_kit/` | ≥ 3.9 | `pandas >= 2.0` |

```bash
git clone https://github.com/chris-dad/backtest-lint.git
cd backtest-lint
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # only needed for research_kit
```

The static checker works with the system Python and no virtualenv at all.

---

## 2. Path resolution

There are **no hardcoded absolute paths**. Both of these forms are used, and both are relocatable:

- `Path(__file__).resolve().parent.parent / "tests" / "corpus"` — resolved relative to the script, so the repo can be cloned anywhere.
- `--corpus` / `check <path>` — explicit arguments, resolved relative to the caller's working directory.

Practical consequence: the whole directory can be moved, symlinked, vendored into another project, or mounted read-only in a container without editing a single line.

If you need a single anchor for scripts and agent prompts, export one:

```bash
export BL_ROOT="/absolute/path/to/backtest-lint"
python3 "$BL_ROOT/tools/lint.py" check strategy.py
```

Shell variables are documentation convenience only — no tool reads `BL_ROOT`.

---

## 3. CLI reference

### `lint.py`

```bash
python3 tools/lint.py check <file.py|dir>      # JSON findings
python3 tools/lint.py gate --corpus <dir>      # 18/18 expected, exit 0 iff pass
python3 tools/lint.py selftest                 # 30/30 expected
```

### `profiler.py`

```bash
python3 tools/profiler.py check <data.csv>     # JSON verdicts
python3 tools/profiler.py gate --corpus <dir>  # 20/20 expected
```

> `profiler.py` has **no `selftest` subcommand**. The only subcommands are `check` and `gate`; 20/20 refers to the gate run. `profiler.py selftest` exits 2 (`invalid choice`) by design.

### `holdout_guard.py`

```bash
python3 tools/holdout_guard.py selftest        # 124/124 expected
python3 tools/holdout_guard.py --help          # runtime modes
```

### `research_kit`

```bash
python3 tools/research_kit/cli.py check <run_folder>
python3 tools/research_kit/cli.py selftest     # 96/96 expected
```

### Exit codes (**not** uniform — `1` means different things per tool)

| Command | `0` | `1` | `2` | `3` |
|---|---|---|---|---|
| `lint.py check` | ran; findings are the product | — | input error | — |
| `lint.py gate` / `selftest` | all pass | at least one fail | input error | — |
| `profiler.py check` | ran; verdicts are the product | — | input error | — |
| `profiler.py gate` | all pass | at least one fail | input error | gate infrastructure failure |
| `holdout_guard.py check` | pass | **holdout exposure blocked the load** | structural error | — |
| `holdout_guard.py mark-read` | recorded | — | refused (repeat consumption, `holdout: null`, bad input) | — |
| `holdout_guard.py selftest` | all pass | at least one fail | — | — |
| `research_kit/cli.py check` | ran; verdicts are the product | — | malformed run folder / bad input | — |
| `research_kit/cli.py selftest` | all pass | at least one fail | — | — |

Never treat `1` as "gate failed" without checking which command produced it: for `holdout_guard check`, `1` is a **finding** (the holdout was touched), not a tool malfunction.

Output is JSON on stdout, with two exceptions — and the second one is **not uniform across the four tools**:

- `--help` prints plain text on stdout, exit `0`, no envelope. This is the same in all four.
- Argparse usage errors (unknown subcommand, bad flag) all exit `2`, but they split in two:
  - `lint.py` and `profiler.py` let argparse handle it: usage goes to **stderr**, stdout stays **empty**.
  - `holdout_guard.py` and `research_kit/cli.py` install their own error handler: usage goes to stderr **and** a JSON envelope goes to **stdout** — `{"tool": "holdout_guard", "guard_version": "0.1.5", "error": "invalid arguments (usage on stderr)"}` and `{"tool": "research_kit", "version": "0.1.2", "error": "invalid arguments (usage on stderr)"}` respectively. Note the version key differs too.

So an agent that parses stdout unconditionally sees valid JSON from two tools and an empty stream from the other two on the very same mistake. Branch on the exit code first. No input shape produces a traceback.

---

## 4. CI integration

Minimal GitHub Actions job that refuses to merge a strategy that violates execution contracts:

```yaml
name: backtest-lint
on: [pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - name: Toolchain self-check
        run: |
          python3 tools/lint.py selftest
          python3 tools/lint.py gate --corpus tests/corpus
          python3 tools/profiler.py gate --corpus tests/corpus
          python3 tools/holdout_guard.py selftest
      - name: Lint strategy code
        run: |
          test -d strategies || { echo "strategies/ not found - point this at your own directory"; exit 1; }
          python3 tools/lint.py check strategies/ > lint-out.json
          python3 - <<'PY'
          import json, sys
          report = json.load(open("lint-out.json"))
          # Directory mode returns {"files": [{file, findings, ...}]} - there is no
          # top-level "findings" key. Reading the wrong level silently passes everything.
          bad = [(f["file"], x) for f in report["files"] for x in f["findings"]
                 if x["tier"] == "verified"]
          for path, x in bad:
              print(f"{path}: {x['rule']} - {x['evidence']}")
          sys.exit(1 if bad else 0)
          PY
```

`check` exits `0` even when it finds violations (findings are the product), so the wrapper above is what enforces the verdict. Both commands below therefore exit `0` — feed their reports to that wrapper and check *its* exit code instead:

```bash
python3 tools/lint.py check tests/corpus/clean/strategies/ > /tmp/c.json   # check: exit 0
python3 tools/lint.py check tests/corpus/planted/lint/     > /tmp/p.json   # check: exit 0
# then run the wrapper on /tmp/c.json (must exit 0) and on /tmp/p.json (must exit 1)
```

---

## 5. Agent integration

The tools were designed to be called by an agent as plain subprocesses. Requirements are already met:

| Requirement | Status |
|---|---|
| Machine-readable output | JSON envelope on stdout — except `--help` (plain text, all four) and argparse usage errors, which are stderr-only in `lint`/`profiler` but emit JSON on stdout too in `guard`/`research_kit`. See §3. |
| Stable exit codes | Per-tool, **not** uniform: `0` / `1` / `2`, plus `3` for a `profiler.py gate` infrastructure failure. See §3. |
| No interactive prompts | None |
| No hidden state | Reads only the paths you pass |
| Deterministic | `selftest` and `gate` reproduce byte-identical JSON |

Recommended agent contract:

1. Run `selftest` once per session to confirm the toolchain is intact.
2. Run `check` / `gate` before any backtest execution.
3. Treat any `tier == "verified"` finding as blocking; fix the strategy code, never the detector.
4. Treat exit `2` as an input problem (wrong path, syntax error), not as a verdict.
5. Never parse human-readable text; read the JSON.

Write strategy code in a form the linter can actually see. Note that analysis starts **inside function bodies**: a bare module-level assignment is reported as `strategy_like: false` and produces no findings at all (limitation 10 in `docs/LINT-SPEC.md` §4), so the examples below are functions. The `assert` lines are there so `lint.105` (vacuous gates) does not fire and mask the rule under discussion.

```python
# ✅ visible to the linter -> lint.101
def run(df):
    assert len(df) > 0
    df["position"] = (df["close"] > df["close"].rolling(20).mean()).astype(int)
    df["pnl"] = df["position"] * df["close"].pct_change()
    return df

# ✅ T+1 lag, wherever it is written -> no findings
def run(df):
    assert len(df) > 0
    df["position"] = (df["close"].shift(1) > df["close"].rolling(20).mean().shift(1)).astype(int)
    df["pnl"] = df["position"] * df["close"].pct_change()
    return df

# ❌ return series via local alias: ret_source is not resolved -> missed
def run(df):
    assert len(df) > 0
    close = df["close"]
    df["pnl"] = df["position"] * close.pct_change()         # no finding

# ❌ pnl assigned to a plain variable: product check does not fire -> missed
def run(df):
    assert len(df) > 0
    pnl = df["position"] * df["close"].pct_change()         # no finding

# ❌ position wrapped in .where / .mask before multiplying: name not visible -> missed
def run(df, cond):
    assert len(df) > 0
    df["pnl"] = df["position"].where(cond, 0) * df["close"].pct_change()   # no finding
```

---

## 6. Frozen artifacts

In the upstream development workflow these are frozen and must not be modified by consumers:

| Artifact | Reason |
|---|---|
| `tests/corpus/expected_results.json` | The answer key. Changing it turns the exam into a rubber stamp. |
| `tests/corpus/**` | Corpus is versioned as a unit; detector changes never edit samples. |
| `tests/corpus/README.md` | **Declared exception**: this is an English rewrite of the upstream note. It is documentation only — no gate reads it — and it is the single non-generated file in that directory, so it is excluded from the "rebuild changes nothing" rule. |
| `tools/profiler.py`, `tools/holdout_guard.py` | Frozen between review gates in the upstream repo. |

If a validator fires on your file and the pattern is not one of the ten documented limitations, **fix the file**. Re-tuning a detector to pass your code is the failure mode this project exists to prevent.

---

## 7. What is not in this repository

This is an allow-list export. It contains the toolchain, the acceptance corpus, and the specifications — nothing else.

Deliberately excluded: any strategy implementation, parameter set, performance figure, run folder, or market data sample. The tools are domain-agnostic; the research they were built for is not public.
