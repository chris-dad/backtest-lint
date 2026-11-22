# Case studies

Three backtests that produced numbers I was ready to believe. All three were wrong. None of them failed loudly — there was no exception, no crash, no NaN at the top of the curve. Each one produced a *better* result than the truth, which is exactly why it survived long enough to reach a report.

Each case follows the same three questions: **what the error looks like**, **how it was caught**, **what the numbers did once it was fixed**.

Reproduction for case 3 is included and takes about two minutes. Cases 1 and 2 describe private research; the mechanism is fully described, the parameter values are not.

---

## Case 1 — The sign error that printed 1.17 BTC

### What the error looks like

Cash-settled short put, assigned at expiry. The mechanics are a transfer, not a trade: if the put finishes in the money, the seller pays the buyer the intrinsic value, in cash. Seller: `+premium − intrinsic`. Buyer: `−premium + intrinsic`. Sum: exactly zero. That is the whole accounting.

The engine had the seller's settlement term added instead of subtracted, so an assignment credited the seller with the intrinsic value *and* kept the premium. Buyer and seller together ended the round up by twice the intrinsic value. In code the defect is one character wide — a `+` where a `−` belongs, or an absolute value taken on a quantity that is signed by construction.

It does not look like a bug from the outside. It looks like a strategy that is unusually good at being assigned.

### How it was caught

Not by reading the code. By asserting a conservation law first and then running the smallest possible case against it.

Build one synthetic expiry: one short put, one long put, same strike, underlying settles 10% below the strike. Sum the two legs' settlement cash flows. The correct answer is zero, and it must be zero for *any* strike, *any* premium, *any* settlement price — it is not a property of the strategy, it is a property of double-entry accounting. The engine returned `+2 × intrinsic`.

That single assertion is more powerful than any amount of curve inspection, because it cannot be satisfied by a lucky parameter set. The second tell was in the results: 79 rounds, 13.9% exercise rate, and not one assignment that lost money. A short-volatility book that never loses on assignment is not a good book. It is a broken ledger.

The general lesson I now apply everywhere: **if a result looks like free money, look for the missing term before you look for the edge.** Positive-sum is not a market condition.

### What the numbers did

| | before | after |
|---|---|---|
| Total multiple | 3.06x | **1.94x** |
| Phantom coins in the ending balance | — | **1.17 BTC (62% of the old ending balance)** |

The headline loss was 36%. The more useful number is the second one: the majority of the *reported* ending balance had never existed. Anything downstream of that equity curve — Sharpe, drawdown, position sizing for the next round — was computed on coins that were minted by a typo.

What survived is stated with its uncertainty attached. The overlay's contribution held up: `+10.02%` annualised, `t = 3.46`, bootstrap 95% CI `[+5.31%, +14.53%]`, interval excluding zero. The totals did not hold up nearly as well: Sharpe `0.913` with CI `[0.13, 1.69]`, CAGR CI `[-4.1%, 139.5%]`, MaxDD CI `[-90.1%, -47.0%]`. A six-and-a-half-year sample of a path-dependent options strategy does not pin down a CAGR to anything better than "somewhere between losing 4% a year and turning 1x into 2.4x a year". Publishing that interval next to the point estimate is the difference between a measurement and a sales pitch.

---

## Case 2 — The improvement that passed four gates out of six

### What the error looks like

An in-sample improvement you can watch arrive. Add a small entry buffer — require price to clear the moving average by some margin before entering — and the equity curve improves. Then widen the buffer, and it improves again. Then widen it further, and it improves a little more, all the way to the edge of the grid.

This is the dangerous shape: **monotonic** in the parameter, best at the boundary, and confirmed by every walk-forward fold. It reads as a robust effect. It is more often a soft version of `p`-hacking, where each extra basis point of buffer removes a handful of marginal whipsaw trades from a sample small enough that removing twelve trades moves the annualised number by a percentage point.

### How it was caught

Before looking at the out-of-sample window, I wrote down six gates and the threshold for each, and committed to accepting only if at least four passed *and* no gate failed on a structural ground. Pre-registration is unglamorous and it is the only thing that stops the analyst from redefining success after seeing the answer.

| Gate | Result | Threshold | Verdict |
|---|---|---|---|
| P1 — walk-forward folds improved | **3/6** | ≥4 | **FAIL** |
| P2 — median rank of the buffer setting | 0.556 | ≤0.60 | PASS |
| P3 — paired bootstrap p | 0.081 | ≤0.25 | PASS |
| P4 — MaxDD | −58.6% | ≥−67.3% | PASS |
| P5 — neighbourhood stability (span) | 0.00pp, no collapse | ≤0.5pp | PASS |
| P6 — in-sample → out-of-sample degradation | **19.7%** | ≤11.7% | **FAIL** |

Four of six is a fail, and saying so out loud is the whole point of writing the gates down first. A 4/6 that gets rounded up to "promising" is how a research process stops being a process.

P1 and P6 are not two independent unlucky draws. They are the same fact seen twice: the effect lives in-sample and decays out-of-sample. And P5's perfect stability was the tell, not the comfort — a parameter whose neighbourhood is *flat* while the out-of-sample result *rots* means the flat spot belongs to the noise, not to the market.

Then the control experiment, which was the actual discovery. Replace the buffer with a rule that has **zero parameters**: wait for two consecutive closes beyond the level, no magnitude requirement at all. That alone captured **86.4%** of the improvement attributed to the buffer.

So the finding was never "spread is alpha". It was "waiting for confirmation beats acting on the first touch". Those two claims have completely different implications: one would have justified tuning a parameter and shipping it, the other is a structural rule with nothing to overfit. The rejected improvement was worth keeping as an explanation even after it was rejected as a change.

### What the numbers did

Nothing. The shipped baseline was not touched — not the parameter, not the signal definition, not a comment. The measured result of a successful audit here is a diff of zero lines. A pre-registration protocol that only produces changes is not a protocol; it is a formality with a paper trail.

---

## Case 3 — Same-bar execution, and why "it's only one bar" is wrong

### What the error looks like

```python
df["signal"]   = (df["close"] > df["ma"]).astype(int)
df["position"] = df["signal"]
df["ret"]      = df["close"].pct_change()
df["pnl"]      = df["position"] * df["ret"]
```

Read it as a trader. `signal` is computed from bar `t`'s close. `position` equals `signal`, so the position for bar `t` is decided by bar `t`'s close. `pnl` multiplies that position by bar `t`'s close-to-close return — the return of the very bar whose close produced the decision.

So the strategy buys *at* the close that told it to buy. In a backtest that is free. In reality that price is already gone by the time the bar closes and you can act. The bias is always in the profitable direction, because the traded bar is by construction the bar that triggered the trade.

This is the failure mode that AI-assisted research makes cheap. It is a legitimate-looking four-line pandas block. It runs. It produces a smooth curve. It is off by one bar, and one bar is enough to turn a mediocre trend rule into a spectacular one.

### How it was caught

Statically, before execution. `tools/lint.py` parses the file with `ast` and tracks which bar each price read belongs to, then checks whether the position fed into a return column is protected by a `shift(k)` with `k >= 1` — wherever that shift is written: on both sides of a comparison, on a helper's `return` suffix, inside a `np.where` argument. `shift(0)` is an identity and protects nothing.

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

Tier `verified`, not `suspicious`: this is a deterministic statement about the code, not a heuristic guess. The same sample is one of 38 in the frozen corpus, written and answer-keyed before the detector existed — which is the only reason the 18/18 result means anything.

### What the numbers did

The fix is one `shift(1)`:

```python
df["position"] = df["signal"].shift(1)   # decide on t, hold from t+1
```

and the same file becomes silent:

```bash
$ python3 tools/lint.py check fixed.py
{"file": "fixed.py", "strategy_like": true, "findings": [],
 "caught": false, "rules": [], "lint_version": "0.1.3"}
```

The cost is not one bar of return. The cost is every trade you were never allowed to take, and it is systematically the winners: the entries you "made" on the exact bar the breakout printed. That is why the magnitude of a same-bar bias cannot be estimated afterwards — it is selected, not random, and averaging over trades does not remove a bias that is conditional on the trade happening at all.

The honest way to state the effect is therefore not a percentage. It is a rule: **a backtest that trades on the close that generated its signal has no defined return series, and no amount of out-of-sample discipline repairs it** — because the leak is in the mapping from signal to execution, not in the parameter choice.

---

## What the three cases have in common

| Case | Class of error | Detected by |
|---|---|---|
| 1 | Conservation violated — value created from nothing | Zero-sum assertion on a minimal case |
| 2 | Improvement that does not survive its own pre-registered gates | Pre-registration + control experiment |
| 3 | Execution contract violated — the future is inside the position | Static AST analysis, before running |

None of the three required a better model, a bigger dataset, or more compute. They required a check that was willing to say the result is not allowed to be believed — and, in two of the three cases, the check was aimed at my own work.

That is the entire thesis of this repository. The scarce skill is not generating a backtest. It is building the thing that tells you, mechanically and without flattery, whether the one in front of you should be trusted.
