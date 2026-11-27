# mtgcalc: MTG Super Calculator (core)

Exact probabilities for drawing cards in Magic: The Gathering: opening hands, multi-turn
curves, overlapping card groups, logical conditions, London mulligans, and deck-count
optimization. It comes with a beginner-friendly desktop app and a web app that runs entirely
in the browser (the Rust core compiled to WebAssembly; see [`web/README.md`](web/README.md)).

## Optional: native engine (Rust, faster)

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
export PATH="$HOME/.cargo/bin:$PATH"
.venv/bin/pip install maturin
.venv/bin/maturin develop --release -m native/python/Cargo.toml   # builds and installs mtgcalc_native
```

The native engine gives about 15–20× faster exact calculations and up to 14× faster mulligan questions, with identical results. See [`native/README.md`](native/README.md) for the Rust workspace (the shared core, the Python bindings and the WebAssembly bindings) and its checks.

The native engine is used automatically when installed. Set `MTGCALC_ENGINE=python` to force the pure-Python engine.

## The app

```bash
.venv/bin/mtgcalc-gui        # or: python -m mtgcalc_gui
```

**New here?** Read [`docs/USAGE.md`](docs/USAGE.md), a plain-language guide to the app. Rule-writers and Python users should read [`docs/REFERENCE.md`](docs/REFERENCE.md).

## The web app

```bash
cd web && npm ci && npm run build && npm run preview    # then open http://localhost:4173
```

Building needs Node 20.19+ (or 22.12+), the `wasm32-unknown-unknown` Rust target and the
`wasm-bindgen` CLI at the crate's exact version; [`web/README.md`](web/README.md) has the
setup, the layout and the test commands. The answer updates as you type, and every number
comes from the same Rust code that the conformance suite checks against Python.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

```python
from fractions import Fraction
from mtgcalc import *

deck = Deck.from_counts(60, {"land": 24, "removal": 6})
s = Scenario(deck, GameConfig(on_play=True))

probability(s, "land >= 3 @T3 AND removal >= 1 @T3").value         # exact, as float
probability(s, "removal >= 1 GIVEN land >= 2").result.exact          # P(A | B), exact Fraction
distribution(s, tag("land"), turn=4).at_least(4)

mull = MulliganConfig(
    priority=(PriorityGroup(tag("land"), quota=3), PriorityGroup(tag("removal"), quota=1)),
    keep_rule=count("land").between(2, 5),
    max_mulligans=2,
)
mulligan_report(s.with_mulligan(mull), "land >= 3 @T3").p_success
optimal_keep(s.with_mulligan(mull), "land >= 3 @T3").value

optimize(OptimizeProblem(
    deck_size=60, variables=(Variable("land", 18, 40),),
    query=Query(parse_condition("land >= 4"), turn=4),
    objective="min_count", target=Fraction(9, 10),
))
```

Condition syntax: `land >= 3`, `land in 2..4`, `card:"Sol Ring" >= 1`, `any(ramp, draw) >= 2`,
`assign(land >= 3, ramp >= 1)` (distinct cards), `... @T3` (by turn 3, after its draw),
`AND`, `OR`, `XOR`, `NOT`, `->`, `atleast(n, ...)`, `exactly(n, ...)`, `... GIVEN ...`.

## Quality gates

GitHub Actions runs these on every push and pull request (`.github/workflows/ci.yml`), plus nightly deep checks (`nightly.yml`). Locally:

```bash
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
.venv/bin/mypy src tests                 # strict
.venv/bin/lint-imports                   # layered architecture contract
.venv/bin/pytest --cov                   # coverage gate: 95% (fail-under)
.venv/bin/pytest -m perf tests/performance
(cd native && cargo fmt --check \
  && cargo clippy --release --all-targets --workspace --exclude mtgcalc-native -- -D warnings \
  && cargo clippy --release -p mtgcalc-native -- -D warnings \
  && cargo test --release --workspace --exclude mtgcalc-native --all-features)   # Rust workspace
(cd web && npm run typecheck && npm run lint && npm run coverage && npm run e2e)  # web app
MTGCALC_ENGINE=python .venv/bin/pytest -q    # also test the pure-Python engine
HYPOTHESIS_PROFILE=ci-deep .venv/bin/pytest tests/oracle tests/property
```

## Documentation

| Document | Content |
|---|---|
| `docs/USAGE.md` | **How to use the app** (beginner's guide, no jargon) |
| `docs/REFERENCE.md` | Rule language and Python API (technical reference) |
| `docs/00-math-foundations.md` | The probability theory, proofs, and verified reference values |
| `docs/01-requirements.md` | Requirements (FR/NFR), user stories, acceptance criteria |
| `docs/02-high-level-design.md` | Architecture, layers, core mechanism |
| `docs/03-low-level-design.md` | Module contracts and algorithms |
| `docs/04-test-plan.md` | Test strategy, oracles, traceability |
| `docs/05-engineering-process.md` | Lifecycle, standards, quality gates |
| `docs/adr/` | Architecture decision records (0001-0015) |
| `web/README.md` | The web app: setup, layout, tests |
| `native/README.md` | The Rust workspace: core, Python and WebAssembly bindings |
