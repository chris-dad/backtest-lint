"""research_kit haircut: Deflated Sharpe Ratio (spec v1.0 s4.2).

Formula: Bailey & Lopez de Prado 2014, "The Deflated Sharpe Ratio"
(one-sided, stdlib NormalDist). Boss-approved 2026-10-06 (spec s7.3).

  DSR = Phi( (SR - SR0) * sqrt(n-1) / sqrt(base) )
  base = 1 - g3*SR + ((g4-1)/4)*SR^2     (g3 skew; g4 RAW kurtosis,
                                          normal = 3 -> base = 1 + SR^2/2)
  SR0 = sqrt(V[{SR}]) * ((1-gamma)*Z(1-1/K) + gamma*Z(1-1/(K*e)))
  gamma = Euler-Mascheroni constant; K = tried_variants.

Moments (v0.1.1, Gate A m-9): SR / g3 / g4 use the POPULATION standard
deviation (pstdev), so the reported g3/g4 are the true raw population
moments E[(x-mu)^k]/sigma^k (two-point symmetric series -> g4 == 1.0
exactly, asserted). Previously the z used the sample stdev while the
1/n outer division assumed population moments.

Edge cases (all asserted in selftest):
  K = 1  -> no selection bias -> SR0 = 0 (degenerates to PSR(SR*=0));
  K < 1 / non-int / bool -> structural error;
  base <= 0 -> structural error (pathological moments, fail-closed);
  V[{SR}]: `variant_srs` (>= 2 finite trial SRs) if provided, else the
  paper's proxy V = base/(n-1) (variance of the SR estimator).
  variant_srs present but not a list of >= 2 finite numbers (bool /
  string / single element / NaN) -> structural error; NEVER a silent
  fallback to the proxy (Gate A M-1: a too-small proxy inflates DSR
  towards false pass).
"""
from __future__ import annotations

import math
from statistics import NormalDist, mean, pstdev, variance

from equity_io import KitInputError

ND = NormalDist()
EULER_GAMMA = 0.5772156649015329  # Euler-Mascheroni
DSR_THRESHOLD = 0.95              # one-sided 95% (asserted in selftest)


def sharpe_ratio(returns: list[float]) -> tuple[int, float, float, float]:
    """Returns (n, SR, g3, g4): SR and raw population moments about the
    mean, all on the population stdev (pstdev). n >= 2 and positive
    variance required (fail-closed)."""
    n = len(returns)
    if n < 2:
        raise KitInputError(f"sharpe needs >= 2 returns, got {n}")
    m = mean(returns)
    s = pstdev(returns)  # population (ddof=0): moments below are exact
    if s <= 0:
        raise KitInputError(
            "zero-variance return series: SR undefined (fail-closed)")
    sr = m / s
    g3 = sum(((x - m) / s) ** 3 for x in returns) / n
    g4 = sum(((x - m) / s) ** 4 for x in returns) / n
    return n, sr, g3, g4


def sr0_for(k: int, v_sr: float) -> float:
    """Expected max SR across K trials (paper eq. for SR0). K=1 -> 0."""
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise KitInputError(f"tried_variants must be int >= 1, got {k!r}")
    if k == 1:
        return 0.0
    z1 = ND.inv_cdf(1.0 - 1.0 / k)
    z2 = ND.inv_cdf(1.0 - 1.0 / (k * math.e))
    return math.sqrt(v_sr) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def deflated_sharpe(returns: list[float], tried_variants: int,
                    variant_srs: list[float] | None = None) -> dict:
    if isinstance(tried_variants, bool) or not isinstance(
            tried_variants, int) or tried_variants < 1:
        raise KitInputError(
            f"tried_variants must be int >= 1, got {tried_variants!r}")
    n, sr, g3, g4 = sharpe_ratio(returns)
    base = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr * sr
    if base <= 0:
        raise KitInputError(
            f"non-positive PSR denominator ({base!r}): pathological "
            f"moments (g3={g3!r}, g4={g4!r}, SR={sr!r}) - fail-closed")
    if variant_srs is not None:
        if not isinstance(variant_srs, list) or len(variant_srs) < 2:
            raise KitInputError(
                "variant_srs must be a list of >= 2 trial SRs to "
                "estimate V[{SR}]; omit it to use the SR-estimator proxy "
                f"(got {variant_srs!r})")
        for v in variant_srs:
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not math.isfinite(v):
                raise KitInputError(
                    "variant_srs must contain finite numbers only "
                    f"(got {v!r}); NEVER silently falling back to the "
                    "proxy - a too-small proxy inflates DSR (Gate A M-1)")
        v_source = "variant_srs"
        v_sr = variance(variant_srs)
    else:
        v_source = "sr_estimator_proxy"
        v_sr = base / (n - 1)
    sr0 = sr0_for(tried_variants, v_sr)
    dsr = ND.cdf((sr - sr0) * math.sqrt(n - 1) / math.sqrt(base))
    return {"tried_variants": tried_variants, "n": n, "sr": sr,
            "sr0": sr0, "dsr": dsr, "threshold": DSR_THRESHOLD,
            "verdict": "pass" if dsr >= DSR_THRESHOLD else "haircut_fails",
            "tier": "verified", "sr_variance_source": v_source}
