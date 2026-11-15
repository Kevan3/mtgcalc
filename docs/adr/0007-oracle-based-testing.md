# ADR-0007: The test strategy is built on independent oracles

**Status:** Accepted

## Context

Wrong probabilities look plausible, so example-based tests alone are insufficient.

## Decision

Every engine feature is checked against at least one independent oracle:
- a brute-force card-by-card enumerator that interprets the AST directly
- SciPy for single-checkpoint distributions
- Monte Carlo
- closed forms
- metamorphic relations

See TP §1.

## Consequences

The oracle code is test infrastructure and must stay independent of `mtgcalc` internals. It may import only the public model types and the bottom-policy function.
