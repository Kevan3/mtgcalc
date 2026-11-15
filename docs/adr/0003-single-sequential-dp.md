# ADR-0003: Atomization plus a single sequential DP for every query type

**Status:** Accepted

## Context

The simple, multivariate, grouped, multi-turn, path-dependent, and mulligan queries could each be implemented as a separate calculator.

## Decision

All of them reduce to:
- disjoint atoms (MATH §6)
- a Markov chain over seen-count vectors with predicate bits (MATH §5)
- different initial states (the mulligan case)

## Consequences

- There is one algorithm to verify and to port.
- The simple cases are special cases. They are checked against a fast path and SciPy.
- The state space must be guarded (estimate and limit).
