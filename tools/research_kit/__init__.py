"""backtest-lint research_kit (Phase 4): statistical audit / luck tests.

Version: only RKIT_VERSION below is authoritative - never restate it.
Spec: docs/RESEARCH-KIT-SPEC-draft-v0.1.md -> v1.0 (2026-10-06, boss
approved). Contract: RUN_FOLDER_CONTRACT.md v0.1.5.

Iron rules carried over from Phase 3:
  - stdlib only, no third-party deps;
  - no input shape may crash: structurally broken input -> error JSON on
    exit 2, never a traceback;
  - every declared number/behavior is asserted in selftest (declaration
    == assertion);
  - ACCOUNTING KEYS are raw identifiers only (filename, date literal,
    column name as written); derived/normalized names are for MATCHING
    and DISPLAY, never bookkeeping (round-20/21 blind-spot lesson).
"""
RKIT_VERSION = "0.1.2"
SPEC_VERSION = "1.0"

# Honest tiering (same agreement as holdout_guard + new cannot_run):
#   verified         deterministic fact from the run folder itself.
#   cannot_run       the folder does not hold what this test needs (e.g.
#                    no exposure.csv and no trades.csv for timing shuffle)
#                    - reported, never silently skipped (spec v1.0 s3).
#   cannot_determine inputs present but ambiguous; reserved.
TEST_TIERS = ("verified", "cannot_run", "cannot_determine")
