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
python3 tools/holdout_guard.py selftest        # 123/123 expected
python3 tools/holdout_guard.py --help          # runtime modes
```

### `research_kit`

```bash
python3 tools/research_kit/cli.py check <run_folder>
python3 tools/research_kit/cli.py selftest     # 96/96 expected
```

### Exit codes (uniform across all four tools)

| Code | Meaning |
|---|---|
| `0` | Ran successfully. Findings (if any) are the product, not an error. |
| `1` | Gate or selftest failed. |
| `2` | Input error: missing file, syntax error, invalid argument, malformed run folder. |

All output is JSON on **stdout**, including error envelopes. Do not parse stderr; do not expect tracebacks.

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
        run: python3 tools/lint.py check strategies/
```

Because `check` exits `0` even when it finds violations (findings are the product), enforce the verdict in a wrapper step:

```bash
python3 tools/lint.py check strategies/ > out.json
python3 - <<'PY'
import json, sys
r = json.load(open("out.json"))
bad = [f for f in r["findings"] if f["tier"] == "verified"]
sys.exit(1 if bad else 0)
PY
```

---

## 5. Agent integration

The tools were designed to be called by an agent as plain subprocesses. Requirements are already met:

| Requirement | Status |
|---|---|
| Machine-readable output | JSON envelope on stdout, every command |
| Stable exit codes | `0` / `1` / `2`, documented above |
| No interactive prompts | None |
| No hidden state | Reads only the paths you pass |
| Deterministic | `selftest` and `gate` reproduce byte-identical JSON |

Recommended agent contract:

1. Run `selftest` once per session to confirm the toolchain is intact.
2. Run `check` / `gate` before any backtest execution.
3. Treat any `tier == "verified"` finding as blocking; fix the strategy code, never the detector.
4. Treat exit `2` as an input problem (wrong path, syntax error), not as a verdict.
5. Never parse human-readable text; read the JSON.

Write strategy code in a form the linter can actually see. The known blind spots (see `docs/LINT-SPEC.md` §4) are mechanical, not conceptual:

```python
# ✅ visible to the linter
df["pnl"] = df["position"] * df["close"].pct_change()

# ❌ return series via local alias: ret_source is not resolved
close = df["close"]
df["pnl"] = df["position"] * close.pct_change()

# ❌ pnl assigned to a plain variable: product check does not fire
pnl = df["position"] * df["close"].pct_change()

# ❌ position wrapped in .where / .mask before multiplying: name not visible
df["pnl"] = df["position"].where(cond, 0) * df["close"].pct_change()
```

---

## 6. Frozen artifacts

In the upstream development workflow these are frozen and must not be modified by consumers:

| Artifact | Reason |
|---|---|
| `tests/corpus/expected_results.json` | The answer key. Changing it turns the exam into a rubber stamp. |
| `tests/corpus/**` | Corpus is versioned as a unit; detector changes never edit samples. |
| `tools/profiler.py`, `tools/holdout_guard.py` | Frozen between audit gates in the upstream repo. |

If a validator fires on your file and the pattern is not one of the nine documented limitations, **fix the file**. Re-tuning a detector to pass your code is the failure mode this project exists to prevent.

---

## 7. What is not in this repository

This is an allow-list export. It contains the toolchain, the acceptance corpus, and the specifications — nothing else.

Deliberately excluded: any strategy implementation, parameter set, performance figure, run folder, or market data sample. The tools are domain-agnostic; the research they were built for is not public.
