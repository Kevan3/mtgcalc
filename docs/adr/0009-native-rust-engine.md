# ADR-0009: Optional native (Rust/PyO3) exact engine

**Status:** Accepted (2026-11-14)

## Context

Profiling (0.2.0) showed that about 90% of runtime in realistic workloads is the exact engine's DP loop: state merging, transition enumeration and three-valued resolution. The optimizer and the optimal-keep analysis run that loop hundreds of times. Python's per-object overhead dominates.

## Decision

- Port only `ExactEngine.run` to Rust, as `native/` (PyO3 + maturin, module `mtgcalc_native`), behind the existing `Engine` protocol. Everything else stays in Python.
- **Exactness:** weights are generic. Each run uses `u128` first and re-runs with `BigUint` on any overflow.
- **Optional:** the core remains pure Python (NFR-13). `engine/select.default_engine()` uses the native engine only when it is installed and not disabled with `MTGCALC_ENGINE=python`.
- **Concurrency:** the GIL is released during a run, so the optimizer can evaluate candidates on threads.

## Consequences

- The largest speedup for the least code. No algorithm changes; one function is ported.
- Two implementations of the DP must stay identical. This is enforced by the conformance suite and by running all oracle suites against both engines.
- Building from source requires a Rust toolchain. Users without one still get the Python engine.

## Results (verified 2026-11-14, rustc 1.100, 8-core machine)

- **Conformance:** bit-identical to the Python engine on about 7,500 generated cases (Hypothesis `ci-deep`), including mulligan starting states, observer snapshots and the BigUint overflow path. The full suite (314 tests) passes on both engines.
- **Code quality:** `cargo clippy -- -D warnings` and `cargo fmt --check` are clean.

| Workload | Python engine | Native engine | Speedup |
|---|---|---|---|
| Single checkpoint, 4 overlapping groups (60 cards) | 38.6 ms | 2.1 ms | 18× |
| 10 checkpoints, 99 cards | 54.5 ms | 2.9 ms | 19× |
| 99 cards, OR across turns 3–10 | 201 ms | 10.1 ms | 20× |
| Mulligan report, 3 mulligans | 16.5 ms | 4.3 ms | 3.8× |
| Optimal keep, 3 mulligans | 31.0 ms | 10.7 ms | 2.9× |
| Optimizer, 3 variables, monotone | 82.5 ms | 13.4 ms | 6.2× |
| Optimizer, Commander, 3 variables + mulligans (308 candidates, 8 cores) | 5.43 s | 0.67 s | 8.1× |

Pure engine work gains about 20×. Mulligan-heavy work gains less, because hand enumeration and bottoming stay in Python; they are now the largest remaining cost. Since 0.2.0, the 3-variable optimizer went from 710 ms to 13 ms (53×): pruning plus the native engine.
