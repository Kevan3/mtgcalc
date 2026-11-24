# The Rust workspace

The Rust side of mtgcalc (ADR-0009, ADR-0011, ADR-0013): one pure core and two thin
bindings.

| Crate | Path | Role |
|---|---|---|
| `mtgcalc-core` | `core/` | Pure Rust. The exact engine, plus the ported model, compiler and `probability`. No Python, no JavaScript. Feature `json` adds the JSON boundary. |
| `mtgcalc-native` | `python/` | The PyO3 extension module `mtgcalc_native`, used by Python automatically when installed (`MTGCALC_ENGINE=python` opts out) |
| `mtgcalc-wasm` | `wasm/` | `wasm-bindgen` exports for the web app (`probability`, `version`) |

Every module of the core is a faithful port of a Python module. The Python test suite
checks them against each other: `tests/engine/test_native_conformance.py` covers the
engine, and `tests/engine/test_core_conformance.py` covers the model, the compiler and
the JSON boundary.

## The core's modules

| Module | Port of | Responsibility |
|---|---|---|
| `error` | `mtgcalc.errors` | `Error` (`Overflow` / `Limit` / `Invalid` / `Validation` / `Unsupported`) and `Result` |
| `model` | `mtgcalc.model` | Validated decks, selectors, conditions and game settings, with Python's field paths and messages |
| `model::text` | `normalize_tag` | Python's `split`/`casefold`, using tables generated from Python (`tools/gen_unicode.py`) |
| `compile` | `mtgcalc.compile` | Atomizer, draw schedule, condition compiler (leaves and postfix programs) |
| `weight`, `binom`, `logic`, `engine` | `mtgcalc.engine.exact` | The exact DP (MATH §5), `u128` first with a `BigUint` re-run on overflow |
| `policy`, `mulligan` | `mtgcalc.engine.mulligan` | London-mulligan enumeration (MATH §9) |
| `api` | `mtgcalc.engine.native` | Engine entry points with automatic big-integer fallback |
| `probability` | `mtgcalc.api.probability` | P(condition) and P(condition \| given), exact (no mulligans yet) |
| `json` | `mtgcalc.model.serialization` | Requests and answers in Python's `to_dict` format (feature `json`) |

## Design rules

- **Exact.** Every probability is an integer over a shared integer denominator. Overflow is detected and the computation is repeated with big integers; it never wraps silently.
- **Validate at the boundary, then trust.** Model constructors, `Query::validate`, `Leaf::new`, `Program::new`, `Policy::new` and `MulliganPlan::validate` reject bad input. Model errors use Python's field paths and messages.
- **Never panic on input.** The JSON boundary turns every problem into an error object. Too much nesting, oversized requests and numbers beyond 64 bits are all reported as `malformed`.
- **No unsafe code** (`unsafe_code = "forbid"`). Every public item is documented (`missing_docs`). `clippy::pedantic` is on, and each allowed lint carries a written reason.
- **The GIL is released** for every computation, so Python threads can run engines in parallel.

## Commands

```bash
export PATH="$HOME/.cargo/bin:$PATH"
cargo fmt --check
cargo clippy --release --all-targets --workspace --exclude mtgcalc-native -- -D warnings
cargo clippy --release --all-targets -p mtgcalc-core --all-features -- -D warnings
cargo clippy --release --target wasm32-unknown-unknown -p mtgcalc-wasm -- -D warnings
cargo clippy --release -p mtgcalc-native -- -D warnings         # needs a Python
cargo test --release --workspace --exclude mtgcalc-native --all-features
cargo doc --no-deps --workspace --all-features
../.venv/bin/maturin develop --release -m python/Cargo.toml     # build and install into the venv
../.venv/bin/pytest ../tests/engine                             # conformance against Python
../.venv/bin/python core/tools/gen_unicode.py                   # after a Python/Unicode upgrade
```
