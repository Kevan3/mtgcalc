# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Removed
- The live Archidekt check (`tests/online/test_live.py`, the `network` test marker and its Nightly step). Archidekt now refuses requests from GitHub's servers, so it failed every night. Importing from Archidekt is unchanged and still tested on saved responses.

### Changed
- **The good game works like the keep rules.** Instead of one "all"/"any" switch, list kinds of good game. Each kind has lines that must all hold (*+ And also*), and a game that fits any kind is good (*+ Or another kind of good game*), so "3 land and removal by turn 3, or 4 land by turn 4" can now be said without a typed rule. Both apps share the layout and words with the keep rules, and the web app restates the good game in words (FR-106, ADR-0015). Saved web forms are upgraded. `mtgcalc_gui.forms.Goal(groups, custom)` replaces `Goal(requirements, combine, custom)`; `Goal.all_of` and `Goal.any_of` build the old shapes.
- **Wide screens.** The web app now uses the width of a computer monitor: steps 1 and 2 side by side from 1500 px, step 3 across both, and a wider answer column (FR-107).
- The keep rules and the good game share one layout in each app (the web's `LineGroups`, the desktop's `LineGroups`), and section headings look the same throughout.
- **Several keep rules for mulligans.** Instead of one keep rule, list the kinds of hand you keep. Each kind has one or more lines that must all hold (*2 land* **and** *1 to 7 ramp*), and a hand that fits any kind is kept (*3 to 5 land*, **or** *2 land and 1 to 7 ramp*). No kinds means "keep every hand". Both the desktop and web apps (FR-105, ADR-0014). The rule is restated in words, and an amount like *2 to 2* now reads *2*. Saved web forms are upgraded. The Commander example now uses two kinds of hand. `MulliganSetup.keep` (a tuple of kinds of `KeepRule`) replaces `keep_type`, `keep_min` and `keep_max` in `mtgcalc_gui.forms`. The engine is unchanged, because the keep rule was already any condition.
- **"How many should I play?" no longer needs a target.** Choose one card type or several sharing some cards, then aim for *the best chance I can get* (no target) or *a target chance I choose* (the fewest cards that reach it). Sharing can now aim for a target within the cards allowed, and one card type can aim for the best chance. Both the desktop and web apps; saved web forms are upgraded. The "from" numbers are now checked against the room in the deck and the cards allowed before searching.

### Fixed
- Averages and percentages of exact answers in the desktop app were rounded from a float, so a tie such as 147/40 = 3.675 printed as "3.67" while the web app said "3.68". They are now rounded exactly (ties to even) in both.

### Added
- **The web app, increment 1** (ADR-0013, SRS §5.11):
  - "What are my chances?" in the browser: card types with "also counts as", format presets, going first, draws per turn, and goal lines combined with "all" or "any".
  - The answer updates as you type. A Web Worker runs the calculation; a scheduler waits for a pause in typing, keeps only the newest question, never shows an answer to an older version of the form, and restarts a calculation that blocks a newer one for more than a second.
  - Problems are explained next to the field and in the answer card, never while you are still typing in that field. The last good answer stays on screen, labelled "Out of date". On phones, the pinned answer card shrinks so it never covers the field being fixed.
  - The page opens with an example already answered. It remembers your setup in this browser, makes no network requests after loading, and passes axe (WCAG 2.2 AA) in light and dark themes.
- **The web app, increment 5:** "How many should I play?": how many of one card type reach a target (and what one fewer would give), the best way to share some cards between card types, or the fewest cards that reach a target, with the best options tried. It runs when you press "Find the best counts". Renaming a card type now renames it everywhere it was chosen.
- **Rust port stage 5:** the card-count optimizer, identical to Python's (with one worker) down to the number of evaluations.
- **The web app, increment 4:** mulligans in step 2 (which hands you keep, what to keep first when bottoming, most mulligans, free first mulligan), included in every answer, and "Should I mulligan?" (your plan vs. never mulliganing vs. the best possible plan, with the hands the best plan keeps).
- **Rust port stage 4:** the mulligan model, bottom policy, strategy-level probabilities and tables, the mulligan report and the optimal keep strategy.
- **The web app, increment 3:** "How many will I draw?" (average and a chance-of-at-least table per turn, every number on request) and "Turn by turn". Step 3 now starts with the question.
- **Rust port stage 3:** count distributions and turn tables (`stats`), with observers in the compiler.
- **The web app, increment 2:** paste a decklist with `#tags` (Moxfield or Archidekt text) and see what was read; write your own rule (for experienced players), starting from your lines, with a short guide. Problems say which line or character and what to write.
- **Rust port stage 2:** the rule language (parser and printer) and decklist parsing, identical to Python's including Unicode details, without a regex engine in the WebAssembly.
- **A shared Rust core, `mtgcalc-core`:** the model, compiler and `probability` were ported from Python. They give identical answers and identical errors (field and message), including Python's Unicode rules for tag and card names. The JSON boundary uses Python's `to_dict` format.
- `mtgcalc_native.probability_json` and `normalize_text`, for the conformance suite.
- Tests:
  - core conformance against the pure-Python reference (generated questions, reference values, state limits, 26 kinds of invalid input, every Unicode code point);
  - golden cases generated from Python (`tests/web/make_fixtures.py`) for the TypeScript form layer and the `.wasm` build;
  - Vitest unit, property and component tests;
  - Playwright end-to-end tests on Chromium, Firefox and a phone, including first-time-user journeys and a check that no jargon appears on screen.
- CI: a `web` job, a GitHub Pages workflow (`pages.yml`), and Dependabot for npm.
- Git repository, and GitHub Actions CI:
  - Rust checks: fmt, clippy for the core and the bindings, tests, docs.
  - Python lint: ruff, mypy, import contracts.
  - A test matrix: Python 3.12/3.13 × native/Python engine, with coverage.
  - A nightly workflow: deep property tests, performance budgets, the live import check.
- Dependabot for actions, cargo and pip.

### Fixed
- A decklist section header that `(?i)` matches with a non-ASCII letter (e.g. `maın` with a dotless i) raised `KeyError` instead of switching section (found by the new conformance suite).

### Changed
- `native/` is now a Cargo workspace with three crates: `core`, `python` (the extension, now 0.5.0) and `wasm`. Build the extension with `maturin develop -m native/python/Cargo.toml`. `pip install ./native` works as before.
- Desktop app wording, kept identical to the web app:
  - exact 0 and 1 read "never" and "every game";
  - "at least 1 card" for any card (not "1 cards");
  - near-certain chances read "all but about 1 game in N" (not "about 10 games in 10"), and chances below 15% read "about 1 game in N".
- Native engine 0.4.1: PyO3 0.22 → 0.30:
  - `allow_threads` → `detach`, `get_type_bound` → `get_type`.
  - Two PyO3-0.22 workarounds removed: the `gil-refs` cfg declaration and the `useless_conversion` allow.
  - Bit-identical results (deep conformance) and the same speed.
- num-bigint stays on 0.4: PyO3 0.30 only converts num-bigint 0.4.x. Dependabot now skips num-bigint 0.5+ until PyO3 supports it.

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
