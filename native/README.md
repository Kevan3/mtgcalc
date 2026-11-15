# mtgcalc-native

The optional Rust engine for `mtgcalc`. It is a bit-for-bit port of the Python reference
engine (`mtgcalc.engine.exact` and `mtgcalc.engine.mulligan`), about 15–20× faster.
Python selects it automatically when it is installed (`MTGCALC_ENGINE=python` opts out).

## Layout

| Module | Responsibility |
|---|---|
| `error` | `Error` (`Overflow` / `Limit` / `Invalid`) and `Result` |
| `weight` | `Weight` trait: exact integers with checked arithmetic (`u128`, `BigUint`) |
| `binom` | Binomial table, with overflow reported rather than wrapped |
| `logic` | `Leaf` and `Program`, validated at construction; two- and three-valued (Kleene) evaluation; Hall's theorem |
| `engine` | `Query` (validated), and the DP as a `Run` with one method per phase (MATH §5) |
| `policy` | London-mulligan bottoming and the keep rule |
| `mulligan` | All depths and per-hand values in one call (MATH §9) |
| `api` | Public entry points: `u128` first, automatic `BigUint` re-run on overflow |
| `python` | PyO3 bindings, only with `--features python` (enabled by maturin) |

`mtgcalc_native.pyi` holds the type stubs for the Python module.

## Design rules

- **Exact.** Every probability is an integer over a shared integer denominator. Overflow is detected and the computation is repeated with big integers; it never wraps silently.
- **Validate at the boundary, then trust.** `Query::validate`, `Leaf::new`, `Program::new`, `Policy::new` and `MulliganPlan::validate` reject malformed input with `Error::Invalid`, which becomes a Python `ValueError`. Evaluation code relies on these invariants.
- **No unsafe code** (`unsafe_code = "forbid"`). Every public item is documented (`missing_docs`). `clippy::pedantic` is on, and each allowed lint carries a written reason.
- **Pure-Rust core.** PyO3 is an optional dependency, so `cargo test` needs no Python.
- **The GIL is released** for every computation, so Python threads can run engines in parallel.

## Commands

```bash
export PATH="$HOME/.cargo/bin:$PATH"
cargo fmt --check
cargo clippy --release --all-targets -- -D warnings          # pure-Rust core
cargo clippy --release --features python -- -D warnings      # with the bindings
cargo test --release                                         # Rust unit tests
cargo doc --no-deps                                          # API docs
../.venv/bin/maturin develop --release                       # build and install into the venv
../.venv/bin/pytest ../tests/engine                          # conformance against Python
```
