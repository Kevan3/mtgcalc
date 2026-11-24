# MTG Super Calculator: Engineering Process

| | |
|---|---|
| Document ID | EP-05 |
| Version | 0.1 |

This document describes how the project is built, checked, versioned, and changed.

## 1. Lifecycle

The project develops **iteratively and incrementally**, with docs-as-code:

1. **Requirements** (SRS) state what is needed. They are versioned, and IDs are stable.
2. **Math baseline** (MATH) records the theory each algorithm relies on. Every claim is either cited or verified.
3. **Design** (HLD → LLD) adds detail step by step. Significant decisions are recorded as ADRs.
4. **Tests** come from the SRS and MATH (TP). They are written alongside the code: test-first for math and engine modules.
5. **Implementation** follows the LLD. A divergence between code and LLD is fixed in whichever of the two is wrong, in the same change.

All five artifacts live in the repository and change through the same review process.

## 2. Coding standards

- Python 3.12+. Typing is complete and checked with `mypy --strict`.
- `ruff` handles linting and formatting (line length 100). Rule sets: E, F, W, I, N, UP, B, SIM, RUF, PL (selected).
- Value objects are immutable (`frozen=True, slots=True`), and functions are pure. Side effects appear only at the edges, and Phase 1 has no such edges.
- Each module has a single responsibility, and dependencies point downward. Layering is enforced by `import-linter`.
- Every public function, class, and module has a docstring that states its contract. Where a docstring refers to theory, it cites MATH sections.
- Errors are explicit typed exceptions. There are no bare `except` clauses, and no failure is silently swallowed.
- There is no premature optimization. Performance work needs a benchmark (TP §10) and must preserve the oracle tests.
- TypeScript (`web/`):
  - `strict` plus `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`;
  - ESLint `strictTypeChecked`, React hooks rules and `jsx-a11y` strict; Prettier;
  - logic in pure modules (`forms/`, `engine/scheduler.ts`), React only in components and hooks;
  - every visible word lives in `src/text/copy.ts` or `forms/words.ts` and follows the beginner rule (FR-85).
- There are no runtime dependencies. Dev dependencies are pinned in `pyproject.toml` (optional `dev` extra).
- Rust (`native/`):
  - `unsafe` is forbidden; every public item is documented; `clippy::pedantic` is on, and every allowed lint has a written reason.
  - Input is validated at construction and then trusted, and errors are typed.
  - The workspace has one pure core and two binding crates (ADR-0013 §1), so the core is tested with plain `cargo test`. Bindings hold no logic.
  - `Cargo.lock` is committed. New crates are added only when a measurement justifies them.

## 3. Quality gates (CI pipeline)

```
lint (ruff check, ruff format --check;
      cargo fmt --check, cargo clippy --all-targets -- -D warnings  [pedantic],
      cargo clippy for the core (with and without json), the PyO3 crate and the wasm32 crate, cargo doc)
  → rust tests (cargo test --release)
  → types (mypy --strict src tests)
  → architecture (lint-imports)
  → build native engine (maturin develop --release -m native/python/Cargo.toml)
  → tests (pytest -m "not perf", coverage fail-under 95/90), on the native engine and again with MTGCALC_ENGINE=python
  → nightly: perf, Hypothesis deep profile, mutation testing
```

A change merges only when every gate is green. The pipeline runs on GitHub Actions:

| Workflow | When | Jobs |
|---|---|---|
| `.github/workflows/ci.yml` | Every push to `main` and every pull request | `rust` (fmt, clippy for the core and the bindings, test, doc); `lint` (ruff, mypy, import contracts); `test` (Python 3.12 and 3.13 × native and Python engine, with coverage; GUI tests run under `xvfb`) |
| `.github/workflows/nightly.yml` | Daily, and on demand | Hypothesis `ci-deep` on both engines, performance budgets, the live deck-site check |
| `.github/workflows/ci.yml`, job `web` | Every push and pull request | WebAssembly build, `tsc`, ESLint + Prettier, Vitest with coverage (95/90), Playwright on Chromium, Firefox and a phone |
| `.github/workflows/pages.yml` | Every push to `main` | Builds the web app and publishes it to GitHub Pages |
| `.github/dependabot.yml` | Weekly | Update PRs for actions, cargo, pip and npm dependencies |

The same commands run locally (see the README). The nightly performance budgets are machine-dependent, so a failure there is investigated rather than treated as a regression on its own.

## 4. Branching and review

- Trunk-based: short-lived feature branches, merged with pull requests.
- **Definition of Ready:**
  - the requirement has an ID
  - the LLD section exists
  - the acceptance tests are identified in TP
- **Definition of Done:**
  - code, tests, and docs are updated
  - the gates are green
  - TP §12 traceability is updated
  - the CHANGELOG has an entry
- The review checklist checks four things:
  1. correctness against MATH
  2. an oracle covers the change
  3. the API is backwards compatible
  4. there are no new global state or I/O paths in the core

## 5. Versioning and releases

- **Semantic Versioning** for the package, with the public API = `mtgcalc.api` plus the `mtgcalc` re-exports.
  - While on 0.x, minor bumps may break the API, and the break is noted in the CHANGELOG.
- The CHANGELOG follows Keep a Changelog.
- The serialized format carries type names. Changing a field is a breaking change.

## 6. Architecture decision records

Significant decisions are recorded in `docs/adr/NNNN-title.md` using the MADR-lite template:
- Context
- Decision
- Consequences
- Status

An ADR is never edited after acceptance. A later ADR supersedes it instead.

## 7. Dependency and security hygiene

- No runtime dependencies. Dev dependencies are updated deliberately.
- Parsers take untrusted input safely: bounded sizes, no `eval` (NFR-14).
- No user data leaves the process. The core has no network access.
