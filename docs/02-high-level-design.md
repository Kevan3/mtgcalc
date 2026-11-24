# MTG Super Calculator: High-Level Design

| | |
|---|---|
| Document ID | HLD-02 |
| Version | 0.9 |
| Implements | SRS-01 v0.3 |
| Grounded in | `00-math-foundations.md` (MATH) |
| Detailed in | `03-low-level-design.md` (LLD) |
| Decisions | `adr/0001` – `adr/0013` |

---

## 1. Design goals and quality attributes

| Goal | Quality attribute | Mechanism |
|---|---|---|
| One engine answers every question | Correctness, maintainability | Atomization plus one sequential state DP (§4) |
| Exact results | Correctness | Integer numerators and a shared integer denominator (MATH §5.2, ADR-0002) |
| Mathematically checkable | Testability | Every algorithmic step corresponds to a theorem in MATH and is checked against an independent oracle (TP) |
| GUI/web later without rewrites | Modifiability | Pure core, immutable values, JSON round-trip, facade API (NFR-07, NFR-08) |
| Swappable hot path | Performance, extensibility | `Engine` protocol with a conformance suite (NFR-09) |
| Fails predictably | Robustness | Validation before computation; live-state limit checked during the run; typed errors |

## 2. System context (C4 level 1)

```
          Phase 3                        Phase 2
  ┌──────────────┐ ┌────────────┐   ┌────────────────────────────┐
  │ GUI / Web UI │ │ HTTP API   │   │ mtgcalc_online (ADR-0012)  │
  └──────┬───────┘ └─────┬──────┘   │ deck links → Deck          │
         │               │          └─────────┬──────────────────┘
         │ JSON-compatible dicts              │ Deck
         ▼               ▼                    ▼
  ╔═══════════════════════════════════════════════════════╗
  ║            mtgcalc core library (Phase 1)             ║
  ╚═══════════════════════════════════════════════════════╝
         ▲                          ▲
  ┌──────┴──────┐  ┌──────────┴──────────┐
  │ Test suites │  │ mtgcalc_gui (Tk)    │  test GUI, Phase 1 (ADR-0008)
  └─────────────┘  └─────────────────────┘
```

## 3. Containers and layers (C4 level 2/3)

```
┌────────────────────────────────────────────────────────────────────────┐
│ L5 Facade       api.py: probability, distribution, threshold_table,    │
│                 turn_table, mulligan_report, optimal_keep, optimize    │
├────────────────────────────────────────────────────────────────────────┤
│ L4 Analyses     analysis/stats · analysis/mulligan · analysis/optimizer│
├────────────────────────────────────────────────────────────────────────┤
│ L3 Engines      engine/base (protocol) · engine/exact · engine/montecarlo│
│                 engine/mulligan · engine/native (Rust) · engine/select │
├────────────────────────────────────────────────────────────────────────┤
│ L2 Compilation  compile/atomizer · compile/schedule · compile/compiler │
│                 compile/logic (bytecode, Kleene eval, Hall check)      │
│                 compile/policy (bottom policy resolution & evaluation) │
├────────────────────────────────────────────────────────────────────────┤
│ L1 Model        model/deck · selectors · conditions · game · mulligan  │
│                 · scenario · results · serialization                   │
├────────────────────────────────────────────────────────────────────────┤
│ L0 Math         math/comb (binomials, compositions, transitions)       │
│                 math/intervals (Wilson)                                │
└────────────────────────────────────────────────────────────────────────┘
  Side: io/decklist (L1 only) · io/expr (L1 only)       errors.py (all layers)
```

**Dependency rule:** a module may import only from its own layer or a lower one. `io` may import only `model` and `errors`. The rule is enforced in CI with an `import-linter` *layers* contract (EP §3).

## 4. Core mechanism

### 4.1 Request pipeline

```
Scenario(deck, game, mulligan?) ─┐
Query(condition, given?, turn) ──┼─► Atomizer ──► AtomTable          (MATH §6)
                                 ├─► Schedule ──► BatchPlan          (MATH §2)
                                 └─► Compiler ──► CompiledQuery
                                       • leaves (atom mask, op, value, checkpoint, bit)
                                       • outputs: postfix Boolean programs over bits
                                       • observers: (checkpoint, mask) marginals
                                       • retirement plan
                                              │
                         InitialStates ──────►│ (default opening hand, or mulligan-built)
                                              ▼
                                  Engine.run ──► RunResult (integer numerators, denominator)
                                              │
                         Analyses ────────────┘ ──► Result value objects (Fraction + float)
```

### 4.2 Atomization (MATH §6)

Each card gets a membership signature over the selectors the query references. Cards with the same signature form an atom, and atoms are disjoint, so their counts are multivariate hypergeometric. Each group count is the sum of its atoms' counts. Cards in no referenced selector form the untracked **pool**, unless a complement selector (`none`, `everything`) needs the pool tracked.

### 4.3 Exact engine: sequential integer DP (MATH §5)

A **state** is `(seen vector, bottomed vector, predicate bits)` with an integer weight. The engine:

1. Starts from initial states: the default opening hand, or states built by the mulligan analysis.
2. For each batch of draws, convolves each state with the multivariate hypergeometric numerators of drawing *b* cards from what remains, and multiplies the shared denominator by C(L, b).
3. At each checkpoint, evaluates that checkpoint's leaves into bits, records observer marginals, resolves early the states whose outputs are already decided (Kleene logic, MATH §7.3, scaled per §5.3), and retires atoms that no later checkpoint references.
4. At the end, evaluates the output programs and returns integer numerators and the denominator.

All three reductions (merging, retirement, early resolution) are exact. Each one has an on/off equivalence test.

### 4.3a Engine selection and the native engine (ADR-0009)

`engine/select.default_engine()` chooses the engine:
- `NativeEngine`, a Rust port of the same DP, when the optional `mtgcalc_native` extension is installed;
- otherwise the reference `ExactEngine`.

Both return bit-identical integers. The native engine:
- runs in `u128` and transparently re-runs in `BigUint` if a value would overflow;
- releases the GIL, which lets the optimizer evaluate candidates on several threads.

Queries beyond its limits (more than 64 predicate bits or more than 32 atoms) fall back to Python. `MTGCALC_ENGINE=python` forces the reference engine.

The `Engine` protocol also has `mulligan` (every depth) and `hand_values` (every drawn hand). They move the whole mulligan enumeration (drawn hands, bottoming, keep rule, DP) into the engine, so with the native engine a mulligan question is one Rust call (ADR-0011). The Python implementation in `engine/mulligan.py` is the specification.

### 4.4 Conditions

The condition AST (comparisons, ranges, AND/OR/XOR/NOT/IMPLIES/at-least/exactly, `Assignable`, `At(turn, …)`) compiles to **leaves** (bit-producing predicates) plus **postfix bytecode** per output. Postfix bytecode is trivial to evaluate in both two- and three-valued logic and to port to a native engine. Conditional probability is one run with two outputs (`joint`, `given`). Exclusive assignment uses the Hall/Gale subset check (MATH §8).

### 4.5 Mulligans (MATH §9)

For each depth m, the mulligan analysis:

1. Enumerates the atom compositions H of the 7-card draw.
2. Applies the bottom policy built from the **user's priority groups**: B(H).
3. Evaluates the keep rule on H − B(H).
4. Seeds the engine with `(seen = H − B, bottomed = B, bits = {keep})`.

A single run per depth produces both "success under forced keep" and "success ∧ keep". The depths are combined with the law of total probability. **Optimal keep** (FR-48) computes s_m(H) for each composition (memoized single-state runs), then applies backward induction.

### 4.6 Statistics, tables, optimizer

- **Distributions and threshold tables:** one run with observers at the requested turns.
- **Turn tables:** one run with one output per turn.
- **Optimizer:** evaluates abstract decks through a memoized, optionally parallel evaluator.
  - When the coupling-monotonicity test passes (MATH §10.2):
    - single-variable targets use binary search;
    - `max_probability` searches only the full-cap slice (MATH §10.4);
    - `min_total` binary-searches the total.
  - Otherwise: exhaustive search when the number of candidates is small, and greedy plus local search when it is large.
  - Proven optimality is flagged only for binary search and exhaustive search.

### 4.7 Monte Carlo engine

The Monte Carlo simulator consumes the same `CompiledQuery` (and mulligan plan) as the exact engine. It simulates shuffles, mulligans, policy, and draws card by card, and evaluates the same compiled leaves and programs. It returns counts over trials and a Wilson interval. Because it shares the compiled query but not the DP, it is an independent check on the engine's state logic.

### 4.8 GUI (`mtgcalc_gui`, ADR-0008, ADR-0010)

A separate top-level package, so the core stays pure. It has three modules:
- **`forms`** (no Tk) is the plain-language layer. Player concepts (`DeckSetup` of `CardType`s, `PlaySetup`, `MulliganSetup`, `Goal` of `Requirement` lines, `HowMany`) become model objects. Results become a `ResultView` with a headline sentence, details, a table, and a legend. It is fully unit-tested headless.
- **`help`** holds every user-facing explanation: tooltips, page intros, getting started, a glossary, the rule language, and the example setups.
- **`app`** (Tk view):
  - the left side holds step 1 (deck) and step 2 (play and mulligans);
  - the right side holds five question pages built from a shared `GoalBuilder`;
  - a Settings dialog, Help windows and an Examples menu.
  - Work runs on a worker thread. Garbage is collected on the UI thread before each job, so Tk objects are never freed off-thread.

An import-linter contract forbids `mtgcalc → mtgcalc_gui`.

### 4.9 Deck import from links (`mtgcalc_online`, ADR-0012)

A standard-library-only package outside the core:
- `sources` recognizes a link against a registry of `Source`s;
- `http.get_json` performs one guarded GET;
- each site module converts its JSON to a `Deck` as a pure function.

Only recognized deck links are ever fetched. In the GUI, *Import* fetches once on a worker thread and fills the decklist box using `format_decklist`, so the player can review the result. Questions never use the network. Import-linter forbids `mtgcalc → mtgcalc_online` and `mtgcalc_online → mtgcalc_gui`.

### 4.10 Web app (`native/core`, `native/wasm`, `web/`, ADR-0013)

The web app runs the calculator entirely in the browser:

```
 React page (web/src)                       Web Worker                  Rust core (WebAssembly)
 ┌───────────────────────────┐  request   ┌──────────────┐  JSON text  ┌─────────────────────────┐
 │ form ─► forms/parse ─► forms/request ──►│ LiveScheduler│────────────►│ json ─► model ─► compile│
 │  ▲                         │  (latest   │ (debounce,   │             │      ─► engine (DP)      │
 │  └── forms/words ◄── answer│◄── wins) ──│  restart)    │◄────────────│ Probability / Error     │
 └───────────────────────────┘            └──────────────┘             └─────────────────────────┘
```

- **The Rust core** (`mtgcalc-core`) is the single implementation the browser runs. The model, the compiler and `probability` are ports of the Python modules. The engine is shared with the Python extension (`mtgcalc-native`), and `mtgcalc-wasm` only forwards.
- **The JSON boundary** is Python's `to_dict` format. The conformance suite sends the same JSON to Python and to Rust and compares the answers.
- **`web/src/forms`** ports `mtgcalc_gui.forms`: player concepts become a request, and answers become sentences. Percentages are rounded from the exact fraction.
- **Live updates:** a debounced, latest-wins scheduler in front of a Web Worker. Stale replies are dropped, and a calculation that blocks a newer question for 1 s is ended by restarting the worker.
- **Problems** are shown next to the field once the player pauses or leaves it. The last good answer stays on screen, marked out of date.
- **Static hosting:** GitHub Pages, built by `.github/workflows/pages.yml`. No server, no data leaves the browser.

## 5. Public API (summary)

All entry points are pure functions in `mtgcalc.api`. They take a `Scenario` and a `Query` (or a condition / expression string) and return immutable result objects.

| Function | SRS |
|---|---|
| `hypergeom(N, K, n) -> Distribution` | FR-10 |
| `probability(scenario, query, *, engine, limit, seed) -> Probability \| ConditionalResult` | FR-11/12/25/35 |
| `distribution(scenario, selector, turn) -> Distribution` | FR-14, FR-30 |
| `threshold_table(scenario, selector, turns, ks) -> ThresholdTable` | FR-31 |
| `turn_table(scenario, condition, turns) -> TurnTable` | FR-24 |
| `mulligan_report(scenario, success) -> MulliganReport` | FR-40 – FR-47 |
| `optimal_keep(scenario, success) -> OptimalKeepReport` | FR-48 |
| `optimize(problem) -> OptimizeResult` | FR-50 – FR-54 |
| `parse_condition`, `format_condition`, `parse_decklist` | FR-37, FR-60 – FR-62 |

## 6. Cross-cutting concerns

| Concern | Approach |
|---|---|
| Validation | Value objects validate in `__post_init__`. Cross-object checks (deck vs. schedule vs. mulligan) run in the compiler before any computation. |
| Errors | `MtgCalcError` → `ValidationError(field)`, `ParseError(line, col)`, `StateSpaceTooLargeError(estimate, limit)`, `InfeasibleError`. P(B) = 0 is a result value, not an error. |
| Caching | Only pure functions are cached (`binom`, transition tables, policy evaluation), and caches are bounded. There is no other global state. |
| Serialization | Every public type has `to_dict()` / `from_dict()` with a `"type"` discriminator, for JSON compatibility. |
| Logging | None in the core (pure library). Callers log. |
| Concurrency | The core is re-entrant. The optimizer may later parallelize evaluations through an injectable map function. |
| Security | Parsers are hand-written recursive descent, never `eval`. Input size and depth are bounded (NFR-14). |

## 7. Architecture decision records

| ADR | Decision |
|---|---|
| 0001 | Python 3.12+ reference implementation, standard library only at runtime |
| 0002 | Exact integer arithmetic with a shared denominator |
| 0003 | Atomization plus a single sequential DP for every query type |
| 0004 | "By turn T" means after the draw step of turn T |
| 0005 | Bottoming is driven by user-given priority groups |
| 0006 | Postfix bytecode for compiled Boolean programs (portable, Kleene-evaluable) |
| 0007 | The test strategy is built on independent oracles (brute force, Monte Carlo, SciPy) |
| 0008 | Tkinter test GUI as a separate package with a headless form layer |
| 0009 | Optional native (Rust/PyO3) exact engine with u128 → BigUint fallback |
| 0010 | Beginner-first GUI: guided steps, goal builder, questions instead of analyses |
| 0011 | Native crate structure; mulligan enumeration moved into the engine (Rust) |
| 0012 | Importing decks from deck-site links (separate package; Moxfield via text export) |
| 0013 | Web app: the Python front half ported to Rust stage by stage, everything compiled to WebAssembly; React + TypeScript; live updates |

## 8. Repository layout

```
hyper2/
  plan.md  pyproject.toml  README.md  CHANGELOG.md
  docs/  00..05 *.md  adr/
  src/mtgcalc/
    __init__.py api.py errors.py py.typed
    math/ model/ compile/ engine/ analysis/ io/
  src/mtgcalc_gui/  src/mtgcalc_online/
  native/                  Rust workspace (ADR-0013 §1)
    core/                  mtgcalc-core: engine + ported model/compile/probability (+ json)
    python/                mtgcalc-native: PyO3 module mtgcalc_native
    wasm/                  mtgcalc-wasm: wasm-bindgen exports for the browser
  web/                     React + TypeScript web app (Vite, Vitest, Playwright)
    src/ e2e/ fixtures/ scripts/
  tests/
    conftest.py
    unit/ reference/ oracle/ property/ metamorphic/ differential/ performance/
```

## 9. Delivery plan

| Increment | Content | Exit tests |
|---|---|---|
| 1 (prototype) | Everything in Phase 1 at prototype quality: full exact engine, mulligans, optimal keep, Monte Carlo, optimizer, parsers, facade | TP §5 – §9 green |
| 2 | Hardening: mutation testing to target, performance tuning, API docs | NFR-03 – NFR-05, NFR-10 |
| Phase 2 | Native engine (Rust/PyO3), network importers | Engine conformance suite |
| Phase 3, increment 5 (done) | Port stage 5: the card-count optimizer in Rust; "How many should I play?" in the web app, run on request | Optimizer conformance (fuzzed against Python), planted defects, parity with the desktop app, E2E |
| Phase 3, increment 4 (done) | Port stage 4: the mulligan model, bottom policy, strategy-level answers, mulligan report and optimal keep in Rust; mulligan settings and "Should I mulligan?" in the web app | Mulligan conformance (incl. derived quotas), advice parity with the desktop app, E2E |
| Phase 3, increment 3 (done) | Port stage 3: distributions and turn tables in Rust (compiler observers); "How many will I draw?" and "Turn by turn" in the web app | Stats conformance, table parity with the desktop app, E2E |
| Phase 3, increment 2 (done) | Port stage 2: the rule language and decklists in Rust; pasted decklists and typed rules in the web app | Text conformance (fuzzed against Python), golden form cases, E2E journeys |
| Phase 3, increment 1 (done) | Web app: "What are my chances?" without mulligans (port stage 1), live updates, Pages | Conformance, parity, E2E, new-user tests (TP §16) |


## 10. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| State-space growth with many overlapping groups or bits | Slow or refused queries | Retirement, early resolution, live-state limit plus Monte Carlo fallback, native engine |
| Users misread shared vs. exclusive counting | "Wrong" answers | Explicit `Assignable`; documentation and examples |
| Priority groups differ from how the user would actually bottom | Mulligan figures feel off | Explicit ordering; optimal keep as an upper bound; FR-44 later |
| Monotonicity wrongly assumed in the optimizer | False "proven" claim | Syntactic coupling test (MATH §10.2); property test comparing bisection with scan |
| Python speed for optimizer and optimal keep | Long runs | Memoization; native engine in Phase 2 |
