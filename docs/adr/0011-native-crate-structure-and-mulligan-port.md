# ADR-0011: Native crate structure, and mulligan enumeration in the engine

**Status:** Accepted (2026-11-14)

## Context

- After ADR-0009, mulligan-heavy questions were still largely Python. Enumerating drawn hands, bottoming and evaluating the keep rule happened in Python, and "optimal keep" made one Python→Rust call per distinct kept hand (hundreds per question).
- The first crate was a single 800-line `lib.rs` with Python bindings mixed into the core.

## Decision

1. Add two operations to the `Engine` protocol: `mulligan(cq, plan)` (every depth) and `hand_values(cq, plan, output)` (every drawn hand). The pure-Python implementation lives in `mtgcalc.engine.mulligan` and is the specification. `analysis.mulligan` only combines the integers these return.
2. Implement both in Rust, each as a single call: enumeration, bottoming, keep rule and DP, sharing one binomial table.
3. Restructure the crate into modules: `error`, `weight`, `binom`, `logic`, `engine`, `policy`, `mulligan`, `api`, `python`.
   - Put the PyO3 bindings behind a `python` feature.
   - Validate all input at construction.
   - Use a typed error that maps to Python exceptions (`ValueError`, `StateLimitExceeded` → `StateSpaceTooLargeError`).
   - Lints: no unsafe code, `missing_docs`, `clippy::pedantic`.
   - Write Rust unit tests that mirror the Python reference cases.
   - Ship type stubs (`mtgcalc_native.pyi`).
4. Do **not** parallelize inside Rust yet. "Optimal keep" on a 99-card deck with 4 card types takes 93 ms, which is interactive. Rayon over distinct kept hands is the next step if needed.

## Consequences

- Mulligan reports are 3.6× faster than 0.3.0, and "optimal keep" is 2.5–14× faster (14× on the Commander case, against Python).
- Conformance now also covers `mulligan` and `hand_values`, checked integer for integer under every optimization switch.
- `cargo test` runs without Python. The CI lint stage gains clippy in both feature configurations, plus `cargo test` and `cargo doc`.
