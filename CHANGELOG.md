# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Git repository, and GitHub Actions CI:
  - Rust checks: fmt, clippy for the core and the bindings, tests, docs.
  - Python lint: ruff, mypy, import contracts.
  - A test matrix: Python 3.12/3.13 × native/Python engine, with coverage.
  - A nightly workflow: deep property tests, performance budgets, the live import check.
- Dependabot for actions, cargo and pip.

## [0.5.0] - 2026-11-14

### Added
- **Import a deck from a link** (ADR-0012):
  - In the GUI, paste a link into *Deck link* and press *Import*. The deck appears as editable text, with a summary of what was imported.
  - In Python, use `mtgcalc_online.fetch_deck`.
  - Archidekt is supported. Moxfield links get instructions for Moxfield's text export, because Moxfield blocks other programs.
- `mtgcalc_online`, a standard-library-only package:
  - guarded HTTP (timeout, size cap, user agent, friendly errors with the cause chained, DEBUG logging);
  - a pure Archidekt converter;
  - a link registry that never fetches unrecognized text.
- `format_decklist` (FR-66): writes a deck as text that `parse_decklist` reads back, with tags as `#tags`.
- Tests:
  - offline fixtures (trimmed real Archidekt responses and edge cases);
  - a local HTTP server for the error paths;
  - GUI import tests;
  - an opt-in `-m network` live check.

### Changed
- GUI:
  - one `App.background` helper runs every worker-thread job (questions and imports);
  - the deck-size box is hidden when the deck comes from a decklist or link;
  - the deck option is now called "Decklist or link".

## [0.4.0] - 2026-11-14

### Added
- `Engine.mulligan` and `Engine.hand_values` (ADR-0011). The pure-Python reference is in `mtgcalc.engine.mulligan`. The native engine does the whole mulligan enumeration (drawn hands, bottoming, keep rule, DP) in one Rust call.
- Native crate:
  - modules (`error`, `weight`, `binom`, `logic`, `engine`, `policy`, `mulligan`, `api`, `python`), with the bindings behind a `python` feature;
  - validated input types and a typed error, mapped to `ValueError` / `StateSpaceTooLargeError`;
  - 22 Rust unit tests;
  - `clippy::pedantic`, `unsafe_code = "forbid"`, `missing_docs`;
  - type stubs (`mtgcalc_native.pyi`) and `native/README.md`.
- Conformance tests for `mulligan` and `hand_values`, and for the native error mapping.

### Changed
- Mulligan reports are 3.6× faster than 0.3.0 (1.2 ms). Optimal keep is 2.5× faster on 60 cards, and the 99-card Commander case takes 93 ms (Python: 1.3 s). The heavy Commander optimizer went from 0.67 s to 0.44 s.
- The DP in Rust is restructured as a `Run` with one method per phase. Results are unchanged.
- `KEEP_BIT` moved to `mtgcalc.compile.policy`.

## [0.3.0] - 2026-11-14

### Added
- Optional native exact engine in Rust (`native/`, module `mtgcalc_native`, ADR-0009). It is selected automatically when installed, and `MTGCALC_ENGINE=python` forces the reference engine. A conformance suite checks bit-identical results.
- Optimizer `workers` option for parallel candidate evaluation. It is adaptive: threads are only used when evaluations are slow enough to benefit.
- Native engine verified:
  - bit-identical on about 7,500 generated cases;
  - the full suite passes on both engines;
  - clippy and rustfmt are clean;
  - about 20× faster on engine-bound queries, and 8× on a heavy Commander optimization (5.4 s → 0.67 s).

### Changed
- Optimizer:
  - `max_probability` searches only the full-cap slice when the condition is monotone (MATH §10.4).
  - `min_total` binary-searches the total.
  - Points are enumerated with pruning and counted exactly to choose between exhaustive and heuristic search.
  - Measured speedups on the Python engine: 3 variables 710 → 67 ms; `min_total` 115 → 23 ms.
- `engine="auto"` now runs exact and falls back only if the engine actually exceeds the state limit. The loose up-front estimate (removed) used to send ordinary multi-turn queries to Monte Carlo.
- Both engines enforce the state limit on the initial states as well.
- The monotonicity test handles `IMPLIES` precisely.

### Changed (GUI and documentation, ADR-0010)
- The GUI was redesigned for new users:
  - steps for "your deck" and "how you play", and five plain questions;
  - drop-down goal lines, with typed rules as an advanced option;
  - sentence-first answers with legends, tooltips everywhere;
  - an Examples menu, Help windows, and a Settings dialog for technical options.
- "Should I mulligan?" compares your plan with never mulliganing and with the best possible plan.
- `docs/USAGE.md` is now a jargon-free beginner's guide, with every quoted number test-checked. The technical guide moved to `docs/REFERENCE.md`, with every code block test-run.

### Fixed
- Optimizer point enumeration ignored the cap when a slice total exceeded it (found by a new brute-force test).
- GUI: Tk objects could be freed by the garbage collector on the worker thread, which stalled calculations. Garbage is now collected on the UI thread before each calculation.

## [0.2.0] - 2026-11-14

### Added
- `mtgcalc_gui`: a Tkinter test GUI (`mtgcalc-gui` / `python -m mtgcalc_gui`) covering every analysis,
  with a headless, unit-tested form layer (ADR-0008).
- `docs/USAGE.md`: a concise usage guide for the GUI and the Python API. Its examples run in CI.
- `parse_selector` / `format_selector` in the public API.

## [0.1.0] - 2026-11-14

### Added
- Prototype of the exact calculation core (Phase 1, increment 1):
  - Hypergeometric, multivariate, and grouped (overlapping tags) probabilities via atomization
    and an exact sequential integer DP.
  - Multi-turn and path-dependent conditions; AND/OR/XOR/NOT/IMPLIES/at-least/exactly;
    exclusive assignment (Hall); conditional probability.
  - London mulligan with free mulligans, bottoming by user-given priority groups, per-depth and
    strategy-level reports, and an optimal keep strategy (backward induction).
  - Distributions, threshold tables, turn tables.
  - Card-count optimizer (bisection, exhaustive, local search; optimality flagged only when proven).
  - Text condition language (parser and canonical printer) and decklist parser
    (plain, Moxfield, Archidekt).
  - Seeded Monte Carlo simulator and `engine="auto"` fallback.
- Requirements, math foundations, HLD, LLD, test plan, engineering process, and ADRs 0001-0007.
- Test suite: unit, reference (A1-A9), brute-force oracle, SciPy and Monte Carlo differential,
  property-based, metamorphic, and performance-budget tests.
