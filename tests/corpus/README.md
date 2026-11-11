# Acceptance corpus — version 1.2.7

**38 samples = 8 clean + 30 planted defects.** The corpus was frozen *before* the detectors were written, and it is the answer key against which every detector change is graded.

Do not edit samples to make a detector pass. Fix the detector, or disclose the limitation.

## Acceptance criteria (per module)

| Criterion | Requirement |
|---|---|
| Recall on `verified` + `suspicious` planted defects | 100% (28/28; the remaining 2 of 30 planted samples are `cannot_determine` discipline samples — 28/30 is the capturable share of the defect set) |
| False positives on clean samples | 0 |
| Discipline samples | Must be reported honestly as `cannot_determine`, never asserted as defects |

## Layout

```
tests/corpus/
├── expected_results.json     # the answer key: sample_id → expected tier / rules
├── clean/
│   ├── data/                 # clean market-data samples (profiler)
│   └── strategies/           # clean strategy code (lint) — zero findings required
├── planted/
│   ├── profile/              # planted data-quality defects (module=profile)
│   └── lint/                 # planted code defects (module=lint, rules 101–105)
└── fixtures/                 # shared auxiliary inputs
```

`expected_results.json` carries the corpus version, the generation date, and one entry per sample with `module`, `expected.tier`, `expected.rules` and a human-readable description.

## Module split

| Module | Samples | Graded by |
|---|---|---|
| `profile` | 20 | `tools/profiler.py gate --corpus tests/corpus` |
| `lint` | 18 (15 planted + 3 clean) | `tools/lint.py gate --corpus tests/corpus` |

## Regeneration

```bash
python3 tools/build_corpus.py
```

The generator is standard-library only, uses a fixed seed, and is byte-reproducible. A self-check failure aborts the build rather than emitting a partial corpus. Regenerating must not change any file in this directory under the same version; a corpus change is a version bump, not a rebuild.

`expected_results.json` is written by that same run — it is never hand-edited, and it is the file the gates grade against. So the check is mechanical: rebuild into a copy and `diff -r` the two `tests/corpus/` trees; anything but an empty diff is a bug. This README is the only file here that is not generated.

## Why the corpus comes first

A detector graded against samples written after it exists is a detector graded against its own assumptions. Freezing the exam first inverts the incentive: false negatives and false positives both have somewhere visible to land, and "the detector is right because it agrees with itself" is not available as an argument.
