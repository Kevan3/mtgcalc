# ADR-0001: Python 3.12+ reference implementation

**Status:** Accepted

## Context

The core needs exact big-integer combinatorics and fast iteration. It also needs a path to a web backend and to native acceleration later.

## Decision

Implement the core in Python 3.12+, using the standard library only at runtime. Native acceleration (Rust via PyO3) is deferred to Phase 2 and sits behind the `Engine` protocol.

## Consequences

- **Benefits:**
  - Arbitrary-precision integers and `Fraction` are built in.
  - The test tooling (pytest, Hypothesis) is excellent.
- **Costs:**
  - Python is slower than native code for large state spaces. This is mitigated by exact state reductions and, later, a native engine that must pass the same conformance suite.
