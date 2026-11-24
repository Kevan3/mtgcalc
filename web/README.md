# mtgcalc web app

The calculator in the browser (ADR-0013). Every number comes from the Rust core
(`native/core`) compiled to WebAssembly. The page sends questions to a Web Worker, so
answers arrive while the player types. Nothing leaves the browser.

Increment 1 answers "What are my chances?" without mulligans. The other questions follow
the port stages in ADR-0013 §2.

## Setup

```bash
# Once: the Rust target and the wasm-bindgen CLI (its version must equal the crate's)
rustup target add wasm32-unknown-unknown
cargo install wasm-bindgen-cli --version 0.2.130 --locked

npm ci
npm run build          # WebAssembly + type check + production build into dist/
npm run preview        # http://localhost:4173
npm run dev            # live-reloading development server (run `npm run wasm` first)
```

`npm run wasm` rebuilds only the WebAssembly (into `src/wasm-pkg/`, which is not
committed). It refuses to run with a `wasm-bindgen` CLI that does not match the crate.

## Layout

| Path                  | Role                                                                                                                                                                               |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/forms/`          | The plain-language layer, a port of `mtgcalc_gui.forms`. It turns the form into a request and the reply into a sentence. Pure functions, no React.                                 |
| `src/engine/`         | Live updates: `scheduler.ts` (debounce, latest wins, stale replies dropped, restarts long calculations), `transport.ts` (Web Worker plumbing), `worker.ts` (loads the WebAssembly) |
| `src/app/`            | Form state (`state.ts`, a reducer), `useLiveAnswer`, `useSettled`                                                                                                                  |
| `src/components/`     | The three steps and the answer card                                                                                                                                                |
| `src/text/copy.ts`    | Every explanation the page shows, in one place for review                                                                                                                          |
| `fixtures/forms.json` | Golden cases generated from Python by `tests/web/make_fixtures.py` (do not edit)                                                                                                   |
| `e2e/`                | Playwright tests of the production build                                                                                                                                           |

## Tests

```bash
npm run typecheck      # TypeScript, strict
npm run lint           # ESLint (type-aware, React hooks, jsx-a11y strict) + Prettier
npm run coverage       # Vitest: unit, parity with Python, WebAssembly conformance, components
npx playwright install chromium firefox   # once
npm run e2e            # Playwright: Chromium, Firefox and a phone, against `vite preview`
```

| Suite                          | What it shows                                                                                                      |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `src/forms/parity.test.ts`     | The same request JSON, sentence and percentages as `mtgcalc_gui.forms`, for every golden case                      |
| `src/forms/wasm.test.ts`       | The `.wasm` file answers every golden request exactly as Python does                                               |
| `src/forms/parse.test.ts`      | Every problem message, and a property test: any form the page accepts gets an answer from the engine               |
| `src/engine/scheduler.test.ts` | Debounce, latest-wins, cancel, restart, crash, with a property test over random interleavings                      |
| `src/App.test.tsx`             | The real app with the real WebAssembly: live updates, stale answers never shown, problems only after typing pauses |
| `e2e/newcomer.spec.ts`         | First-time-user journeys, with no jargon on screen at any step                                                     |
| `e2e/quality.spec.ts`          | axe (WCAG 2.2 AA, light and dark), keyboard-only use, no network requests, speed budgets                           |

After changing the Python reference, regenerate the golden cases from the repository root
with `python -m tests.web.make_fixtures`. `pytest tests/web` fails while they are stale.
