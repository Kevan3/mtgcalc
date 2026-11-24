# ADR-0013: Web app with the Rust core compiled to WebAssembly

**Status:** Accepted (2026-11-23)

## Context

- Phase 3 (SRS §2.2) asks for a web app that people can use without installing anything.
- The answers must stay exact and must match the Python reference: the project's main promise is answers people can trust.
- Since ADR-0009 and ADR-0011, the Rust engine computes the dynamic program and the mulligan enumeration. Everything in front of it is still Python, about 3,500 lines: the model, the parsers, the compiler, the analyses and the optimizer.
- Three ways to put the calculator on the web were considered:

| Option | For | Against |
|---|---|---|
| **A. Port the Python front half to Rust, and compile everything to WebAssembly** | A static site: free hosting, works offline, no server to run or secure. Answers arrive in milliseconds, so the page can update as the user types. | The most work. A second implementation of the front half must be kept identical to Python. |
| B. Run the Python code in the browser (Pyodide) with the Rust engine built for Emscripten | Almost no rewriting | About 10 MB or more to download before the first answer. The build is pinned to one exact Emscripten version. |
| C. A server running the native engine, plus a thin page | No porting | Paid hosting. The page stops working when the server is down. User data leaves the browser. |

- The user chose A, with a React + TypeScript front end and a page that updates as fields change.

## Decision

### 1. One Rust core, three crates

`native/` becomes a Cargo workspace:

| Crate | Path | Role |
|---|---|---|
| `mtgcalc-core` | `native/core` | Pure Rust: the engine (moved unchanged from `native/src`), plus the ported model, compiler and analyses. No Python, no JavaScript. |
| `mtgcalc-native` | `native/python` | The PyO3 extension module `mtgcalc_native`, unchanged for Python callers. It gains `probability_json` for the conformance suite (§3). |
| `mtgcalc-wasm` | `native/wasm` | `wasm-bindgen` bindings for the browser. It contains no logic of its own. |

`pip install ./native` keeps working: `native/pyproject.toml` points maturin at `python/Cargo.toml`.

### 2. The port proceeds stage by stage; Python stays the specification

Each stage is a faithful port of named Python modules. It ships only once the conformance suite (§3) shows identical results.

| Stage | Python modules | Unlocks in the web app |
|---|---|---|
| **1 (this ADR)** | `model` (deck, selectors, conditions, game, scenario; not mulligan), `compile` (atomizer, schedule, compiler; not policy), `api.probability` including conditional probability | "What are my chances?" without mulligans |
| 2 | `io.expr`, `io.decklist` | Typed rules, pasted decklists |
| 3 | `analysis.stats` | "How many will I draw?", turn-by-turn tables |
| 4 | `model.mulligan`, `compile.policy`, `analysis.mulligan` | Mulligans |
| 5 | `analysis.optimizer` | "How many should I play?" |

Monte Carlo is not ported. In the browser, a question beyond the exact engine's limits gets a clear "too big to work out exactly" message.

### 3. The JSON boundary is the existing serialization format

- Requests use the format of `mtgcalc.model.serialization.to_dict` for `Scenario` and `Query`. Responses use the same format for `Probability` and `ConditionalResult`.
- Python can therefore hand any scenario to Rust unchanged, and the conformance suite compares the two JSON answers directly.
- Errors are `{"type": "Error", "kind", "field", "message"}`, tagged like every other object in the format. `kind` is one of:
  - `validation`: Python's `ValidationError`;
  - `too_large`: Python's `StateSpaceTooLargeError`;
  - `unsupported`: beyond the native limits (more than 64 rule parts or 32 card groups);
  - `malformed`: the JSON itself is wrong;
  - `internal`: a bug (an engine invariant failed). It is reported, never a panic.
- Parsing (`serde`, behind the core's `json` feature) produces data-transfer types. These are converted into validated domain types, so validation happens once, at the boundary (the same rule as ADR-0011).

### 4. The front end: React + TypeScript, built with Vite

- **`web/src/forms/`** is a TypeScript port of `mtgcalc_gui.forms`, the plain-language layer:
  - it turns card types, play settings and goal lines into the JSON of §3;
  - it turns answers into sentences;
  - it is pure functions, with no React, and is unit-tested.
- **Wording** is taken from `mtgcalc_gui.help` so the two apps explain things the same way.
- **Percentages** are formatted from the exact fraction with `BigInt`, never from a floating-point approximation. Rounding is to the nearest value, ties to even.
- **TypeScript** is strict. ESLint runs the type-aware rule sets. TypeScript stays on 6.0 until `typescript-eslint` supports 7.

### 5. Live updates

- The core runs in a **Web Worker**, so typing never waits on a calculation.
- A **latest-wins scheduler** sits between the form and the worker:
  - it waits 250 ms after the last change (150 ms, first chosen, showed half-typed numbers to a tester who typed at an ordinary pace);
  - it keeps at most one request waiting, always the newest;
  - it numbers requests and ignores any answer that is no longer the newest;
  - it ends a superseded calculation that has run for more than 1 s by restarting the worker (WebAssembly calls cannot be interrupted).
- **While the form is invalid or a newer answer is on its way,** the last good answer stays on screen, marked as out of date. Half-typed input is never shown as an error while the user is still typing in that field.

### 6. Build and deployment

- Build steps:
  1. `cargo build --target wasm32-unknown-unknown --release -p mtgcalc-wasm`;
  2. `wasm-bindgen --target web`, with the CLI version pinned to the `wasm-bindgen` crate version (they must match exactly);
  3. Vite.
- `wasm-pack` is not used: the `rustwasm` organization was archived in 2025, and the plain CLI is the supported path.
- A GitHub Pages workflow publishes `web/dist` on every push to `main`. Pages must be enabled once in the repository settings.

### 7. Testing

| Level | What it shows |
|---|---|
| Rust unit tests (`mtgcalc-core`) | Each ported module matches its Python unit tests |
| Conformance (pytest + Hypothesis, through `mtgcalc_native.probability_json`) | Rust returns the same JSON as Python for generated scenarios and queries, and the same error kind for invalid ones |
| WebAssembly conformance (Node) | The `.wasm` build returns the same JSON as Python on golden cases that Python generated |
| Form-layer tests (Vitest) | The TypeScript form layer builds the same JSON and the same sentences as `mtgcalc_gui.forms` (golden cases from Python), plus edge cases |
| Scheduler tests (Vitest, fake timers) | Debounce, latest-wins, dropping stale answers, restarting the worker |
| Component tests (Vitest + Testing Library) | Fields, validation messages, accessibility labels |
| End-to-end (Playwright, Chromium and Firefox) | The real page with the real worker and WebAssembly: live updates, stale answers never shown, keyboard use, an axe accessibility scan, no jargon on screen |
| New-user walkthroughs | Scripted first-time-user journeys (Playwright), plus an exploratory session by a reviewer who has never seen the app, with its findings recorded and fixed |

## Consequences

- The calculator works fully offline in any modern browser, with no server and no data leaving the device.
- The front half now exists in two languages until the port is complete. The conformance suite is the guard: a Rust change that disagrees with Python fails CI.
- `native/src` moves to `native/core/src`. Build commands now name the crate (`-p`) or the manifest path.
- Contributors need Node 20.19+ (or 22.12+) and the `wasm32-unknown-unknown` Rust target in order to work on the web app.
- Questions beyond the exact engine's limits have no Monte Carlo fallback in the browser, for now.
