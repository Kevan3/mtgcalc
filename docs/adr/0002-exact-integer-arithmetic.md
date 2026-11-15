# ADR-0002: Exact integer weights with a shared denominator

**Status:** Accepted

## Context

Floating-point and log-gamma evaluation lose precision in the tails and cancel badly near 1. Doing every step in `Fraction` is exact but slow.

## Decision

The engine keeps an integer numerator per state and a single integer denominator per run, as the product of the C(L, b) terms (MATH §5.2). A probability is formed once, at the API boundary, as a `Fraction`.

## Consequences

- Results are exact, and floats are correctly rounded.
- Tests can assert exact equality.
- Native ports need big integers, or u128 with an overflow fallback.
