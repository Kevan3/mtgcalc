"""Confidence intervals for Monte Carlo estimates (LLD §2.2, MATH §11)."""

from __future__ import annotations

import math

from mtgcalc.errors import ValidationError

Z95 = 1.959963984540054


def wilson(successes: int, trials: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Preferred over the Wald interval because it stays inside [0, 1] and keeps its
    coverage near 0 and 1 (Brown, Cai & DasGupta 2001).
    """
    if trials <= 0:
        raise ValidationError("trials", "must be positive")
    if not 0 <= successes <= trials:
        raise ValidationError("successes", "must be between 0 and trials")
    p = successes / trials
    z2 = z * z
    denom = 1.0 + z2 / trials
    center = (p + z2 / (2 * trials)) / denom
    half = z * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials)) / denom
    return max(0.0, center - half), min(1.0, center + half)
