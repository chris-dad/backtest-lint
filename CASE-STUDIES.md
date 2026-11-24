# Case studies

Three backtests that produced numbers I was ready to believe. All three were wrong. None of them failed loudly — there was no exception, no crash, no NaN at the top of the curve. Each one produced a *better* result than the truth, which is exactly why it survived long enough to make it into a report.

Each case answers the same three questions: **what the error looks like**, **how it was caught**, **what happened to the numbers once it was fixed**.

The reproduction for case 3 is included and takes about two minutes. Cases 1 and 2 describe private research; the mechanisms are described in full, but the parameter values are not.

---

## Case 1 — The sign error that minted 62% of the ending balance

### What the error looks like

A cash-settled short put, assigned at expiry. The mechanics involve a transfer, not a trade: if the put finishes in the money, the seller pays the buyer the intrinsic value in cash. Seller: `+premium − intrinsic`. Buyer: `−premium + intrinsic`. Sum: exactly zero. That's all the accounting there is.

The engine added the seller's settlement term instead of subtracting it, so an assignment credited the seller with the intrinsic value *and* let the seller keep the premium. Buyer and seller together ended the round up by twice the intrinsic value. In code, the defect is one character wide — a `+` where a `−` belongs, or an absolute value taken on a quantity that's signed by construction.

It doesn't look like a bug from the outside. It looks like a strategy that's unusually good at being assigned.

### How it was caught

Not by reading the code. By asserting a conservation law first and then testing the smallest possible case against it.

Build one synthetic expiry: one short put, one long put, the same strike, and an underlying that settles 10% below the strike. Sum the two legs' settlement cash flows. The correct answer is zero, and it must be zero for *any* strike, *any* premium, *any* settlement price — it's not a property of the strategy; it's a property of double-entry accounting. The engine returned `+2 × intrinsic`.

That single assertion is more powerful than any amount of curve inspection because it can't be satisfied by a lucky parameter set. The second tell was in the results: 79 rounds, a 13.9% exercise rate, and — on the put side — nothing but assignments that paid. Every put assignment the engine recorded credited the seller; the call side, where the debits belong, was the only place a loss ever appeared. A short-volatility book in which assignment only ever pays isn't a good book. It's a ledger with the payment side missing.

The general lesson I now apply everywhere: **if a result looks like free money, look for the missing term before you look for the edge.** Positive-sum isn't a market condition.

### What the numbers did

| | before | after |
|---|---|---|
| Total multiple | 3.06x | **1.94x** |
| Phantom coins in the ending balance | — | **≈62% of the old ending balance** |

The reported multiple had been 58% above the corrected one — fixing it cut the headline by a third, from `3.06x` to `1.94x`. The more useful figure is the phantom balance: the majority of the *reported* ending balance had never existed. Anything downstream of that equity curve — Sharpe, drawdown, position sizing for the next round — was computed on coins minted by a typo.

What survived comes with its uncertainty attached. The overlay's contribution held up: `+10.02%` annualized, `t = 3.46`, bootstrap 95% CI `[+5.31%, +14.53%]`, with the interval excluding zero. The totals didn't hold up nearly as well: Sharpe `0.913` with CI `[0.13, 1.69]`, CAGR CI `[-4.1%, 139.5%]`, MaxDD CI `[-90.1%, -47.0%]`. A six-and-a-half-year sample of a path-dependent options strategy doesn't pin down CAGR any more precisely than "somewhere between losing 4.1% a year and turning 1x into 2.4x a year". Publishing that interval next to the point estimate is the difference between a measurement and a sales pitch.

---

## Case 2 — The improvement that passed four gates out of six

### What the error looks like

An in-sample improvement you can watch take shape. Add a small entry buffer — require the price to clear the moving average by some margin before entering — and the equity curve improves. Then widen the buffer, and it improves again. Then widen it further, and it improves a little more, all the way to the edge of the grid.

This is the dangerous shape: **monotonic** in the parameter, best at the boundary, and surviving half the walk-forward folds — 3 of 6, which is exactly the number that later killed it. It looks like a robust effect. It's more often a soft version of `p`-hacking: the sample is small enough that increasing the buffer by one grid step removes a few marginal whipsaw trades and moves the annualized number.

### How it was caught

Before looking at the out-of-sample window, I wrote down six gates and the threshold for each, and committed to accepting the change only if at least four passed *and* no gate failed on structural grounds. Preregistration is unglamorous, and it's the only thing that stops the analyst from redefining success after seeing the answer.

| Gate | Result | Threshold | Verdict |
|---|---|---|---|
| P1 — walk-forward folds improved | **3/6** | ≥4 | **FAIL** |
| P2 — median rank of the buffer setting | 0.556 | ≤0.60 | PASS |
| P3 — paired bootstrap | 0.081 | ≤0.25 | PASS |
| P4 — MaxDD | −58.6% | ≥−67.3% | PASS |
| P5 — neighborhood stability (span) | 0.00pp, no collapse | ≤0.5pp | PASS |
| P6 — in-sample → out-of-sample degradation | **19.7%** | ≤11.7% | **FAIL** |

Four of six is a fail, and saying so out loud is the whole point of writing the gates down first. Rounding a 4/6 up to "promising" is how a research process stops being a process.

P1 and P6 aren't two independent unlucky draws. They're the same fact seen twice: the effect lives in-sample and decays out-of-sample. And P5's perfect stability was the tell, not a reassurance — a parameter whose neighborhood is *flat* while the out-of-sample result *rots* means the flat spot belongs to the noise, not to the market.

Then came the control experiment, which was the actual discovery. Replace the buffer with a rule that has **zero parameters**: wait for two consecutive closes beyond the level, with no magnitude requirement at all. That alone captured **86.4%** of the improvement attributed to the buffer.

So the finding was never "spread is alpha". It was "waiting for confirmation beats acting on the first touch". Those two claims have completely different implications: one would have justified tuning a parameter and shipping it; the other is a structural rule with nothing to overfit. The rejected improvement was worth keeping as an explanation even after it was rejected as a change.

### What the numbers did

Nothing. The shipped baseline wasn't touched — not the parameter, not the signal definition, not a comment. The measured result of a successful audit here is a diff of zero lines. A preregistration protocol that only produces changes isn't a protocol; it's a formality with a paper trail.

---

## Case 3 — Same-bar execution, and why "it's only one bar" is wrong

### What the error looks like

```python
df["ma"]       = df["close"].rolling(20).mean()
df["signal"]   = (df["close"] > df["ma"]).astype(int)
df["position"] = df["signal"]
df["ret"]      = df["close"].pct_change()
df["pnl"]      = df["position"] * df["ret"]
```

Read it as a trader. `signal` is computed from bar `t`'s close. `position` equals `signal`, so the position for bar `t` is determined by bar `t`'s close. `pnl` multiplies that position by bar `t`'s close-to-close return — the return of the very bar whose close produced the decision.

So the strategy buys *at* the close that told it to buy. In a backtest, that's free. In reality, that price is already gone by the time the bar closes and you can act. The bias is always in the profitable direction because the traded bar is, by construction, the bar that triggered the trade.

This is the failure mode that AI-assisted research makes cheap. It's a legitimate-looking four-line pandas block. It runs. It produces a smooth curve. It's off by one bar, and one bar is enough to turn a mediocre trend rule into a spectacular one.

### How it was caught

Statically, before execution. `tools/lint.py` parses the file with `ast` and tracks which bar each price read belongs to, then checks whether the position fed into a return column is protected by a `shift(k)` with `k >= 1` — wherever that shift appears: on both sides of a comparison, at the end of a helper's `return` expression, or inside an `np.where` argument. `shift(0)` is an identity and protects nothing.

```bash
$ python3 tools/lint.py check tests/corpus/planted/lint/code_case_01.py
{
  "file": "tests/corpus/planted/lint/code_case_01.py",
  "strategy_like": true,
  "findings": [
    {
      "rule": "lint.101",
      "tier": "verified",
      "evidence": "pnl col 'pnl': 'position' is unshifted and reads bar-t close info, multiplied by same-bar close-to-close return"
    }
  ],
  "caught": true,
  "rules": ["lint.101"],
  "lint_version": "0.1.3"
}
```

Tier `verified`, not `suspicious`: this is a deterministic statement about the code, not a heuristic guess. The same sample is one of 38 in the frozen corpus, which was written and given an answer key before the detector existed — which is the only reason the 18/18 result means anything.

### What the numbers did

The fix is one `shift(1)`:

```python
df["position"] = df["signal"].shift(1)   # decide on t, hold from t+1
```

And `lint.101` goes quiet. The file doesn't. Here's the second run, which is the part I'd keep if I had to cut the case study in half:

```bash
$ python3 tools/lint.py check fixed.py
{
  "file": "fixed.py",
  "strategy_like": true,
  "findings": [
    {
      "rule": "lint.105",
      "tier": "verified",
      "evidence": "0 assert statement(s) in file, 0 vacuous, 0 meaningful gates (NaN/conservation/position-domain/warmup)"
    }
  ],
  "caught": true,
  "rules": ["lint.105"],
  "lint_version": "0.1.3"
}
```

`lint.105` was suppressed on the first run. The checker stays silent on the vacuous-gate rule whenever an execution-level finding (101 to 104) fires, and `docs/LINT-SPEC.md` §3 records the rationale: the corpus is single-defect by construction, and in real code, an execution-level defect is the stronger finding. That's a product decision, and it has a visible cost — fix the leak, and the deferred finding surfaces.

That behavior is right, and it's the opposite of what most checkers do. An audit that converges to zero findings is usually converging to a threshold, not to safety. Both findings are also true of this file: it has no `assert`, no conservation check, and no position-domain check — the same disease the sample was planted to demonstrate, and the reason a `shift(1)` can't give it a clean bill of health.

The cost isn't one bar's return. The cost is every trade you were never allowed to take, and those trades are systematically the winners: the entries you "made" on the exact bar when the breakout printed. That's why the magnitude of same-bar bias can't be estimated after the fact — it's selected, not random, and averaging over trades doesn't remove a bias that's conditional on the trade happening at all.

The honest way to state the effect is therefore not a percentage. It's a rule: **a backtest that trades on the close that generated its signal has no defined return series, and no amount of out-of-sample discipline repairs it** — because the leak is in the mapping from signal to execution, not in the parameter choice.

---

## What the three cases have in common

| Case | Class of error | Detected by |
|---|---|---|
| 1 | Conservation violated — value created from nothing | Zero-sum assertion on a minimal case |
| 2 | Improvement that does not survive its own pre-registered gates | Preregistration + control experiment |
| 3 | Execution contract violated — the future is inside the position | Static AST analysis, before running |

None of the three required a better model, a bigger dataset, or more compute. They required a check willing to say the result can't be trusted — and, in two of the three cases, the check was aimed at my own work.

That's the entire thesis of this repository. The scarce skill isn't generating a backtest. It's building the thing that tells you, mechanically and without flattery, whether the one in front of you should be trusted.
