# MTG Super Calculator: Test Plan

| | |
|---|---|
| Document ID | TP-04 |
| Version | 0.7 (synchronized with the Unreleased changes after 0.5.0) |
| Covers | SRS-01 v0.3, LLD-03 v0.3 |
| Tooling | pytest, Hypothesis, pytest-cov, SciPy (dev-only oracle), mutmut (increment 2), import-linter, mypy, ruff; cargo test/clippy; Vitest, fast-check, Testing Library, Playwright, axe-core (web) |

---

## 1. Strategy

Probability code fails quietly: a wrong number looks exactly as plausible as a right one. The strategy therefore rests on **independent oracles**: every result the engine produces is checked against at least one computation that shares none of its code (ADR-0007).

| Oracle | Independence from the engine | Scope |
|---|---|---|
| **Reference values** (MATH §12) | Computed by hand formulas and separate scripts | Fixed scenarios A1–A9 |
| **Brute-force enumerator** (`tests/oracle/bruteforce.py`) | Card-by-card sequence enumeration with `Fraction` products. No binomials, no merging, no batches, no retirement. | Small decks: N ≤ 14, ≤ 3 atoms, ≤ 8 cards seen |
| **SciPy** `hypergeom` / `multivariate_hypergeom` | Third-party implementation, float | Single-checkpoint PMFs |
| **Monte Carlo simulator** | Shares only the compiled leaves and programs, not the DP | Realistic decks (60/99), mulligans |
| **Closed forms** (MATH §3, §4, §9.3) | Formulas | Means, variances, covariances, geometric mulligan formula |
| **Metamorphic relations** | The engine checked against itself under transformations that must preserve or predictably change the answer | Everything |

The test pyramid in the prototype is roughly 60% unit, 25% property/metamorphic, 10% oracle/differential, and 5% performance.

## 2. Test levels and layout

```
tests/
  conftest.py                  # Hypothesis profiles ("dev", "ci-deep")
  strategies.py                # generators: decks, conditions, games, plain/mulligan/multi-checkpoint cases
  oracle/bruteforce.py         # independent enumerator (infrastructure, not a test file)
  oracle/test_vs_bruteforce.py # primary correctness gate (§6)
  unit/test_math.py test_model.py test_compile.py test_engine.py test_analysis.py test_io.py test_api.py
  reference/test_reference_values.py           # A1-A9 (+ A7 disjunction regression)
  differential/test_vs_scipy.py test_vs_montecarlo.py
  property/test_invariants.py                  # P1-P15
  metamorphic/test_relations.py                # M1-M8
  performance/test_budgets.py                  # PF1-PF3 (marker `perf`)
  gui/test_forms.py                            # plain-language layer: setups, goals, every question, wording (FR-80..FR-86)
  gui/test_app_smoke.py                        # Tk window: every example x every question, errors, typed rules, settings (marker `gui`)
  docs/test_reference_examples.py              # executes every python block of docs/REFERENCE.md (FR-84)
  online/test_archidekt.py                     # JSON -> Deck on trimmed real + edge-case fixtures (FR-65)
  online/test_sources.py                       # link recognition; nothing fetched for other text; Moxfield help
  online/test_http.py                          # get_json against a local HTTP server: codes, size cap, non-JSON, offline
  docs/test_usage_numbers.py                   # recomputes every number quoted in docs/USAGE.md (FR-84)
  engine/test_native_conformance.py            # Rust == Python, bit for bit: run, mulligan, hand_values, errors (NFR-09; skipped if not built)
  engine/test_core_conformance.py              # Rust model/compiler/probability == Python via JSON; same errors; Unicode (FR-90, FR-91)
  web/make_fixtures.py, web/test_fixtures.py   # golden cases for the web app, generated from Python; must be fresh
native/core/src/**/*.rs  #[cfg(test)]          # Rust unit tests (cargo test): engine (22) + ported model, compiler, probability, json
web/src/**/*.test.ts(x)                        # Vitest: parity with Python, WebAssembly conformance, forms, scheduler, components (§16)
web/e2e/*.spec.ts                              # Playwright: new-user journeys, accessibility, keyboard, privacy, speed (§16)
```

pytest markers:
- `slow`: more than 1 s
- `perf`: budget tests
- `mc`: Monte Carlo statistics

The default CI run excludes `perf`. A nightly run includes everything with the Hypothesis `ci-deep` profile.

## 3. Unit tests (per module)

| Module | Must cover |
|---|---|
| `math/comb` | `binom` edge cases (negative, k > n, 0); `transitions` exact enumeration for small inputs; Vandermonde sum; cache does not leak state |
| `math/intervals` | Wilson matches a hand-computed value; 0/n and n/n cases; symmetry |
| `model/selectors` | Each selector type; casefolding; nested any/all/none |
| `model/conditions` | Validation (lengths, negatives); DSL operators build the expected AST; flattening of chained `&`/`\|` |
| `model/deck` | `from_counts` totals and filler; duplicate detection; zones; `with_tags`, `rename_tag` |
| `model/game` | `draws_on_turn` for play/draw, overrides, extras; dict normalization |
| `model/mulligan` | `bottom_count` with F = 0/1; validation of bounds; keep rule with `At(t ≠ 0)` rejected |
| `model/serialization` | Round trip for every public type through `json.dumps` |
| `compile/atomizer` | Overlapping tags produce the correct atoms; pool; complement selectors become tracked atoms; unknown card name raises an error |
| `compile/schedule` | Batches for play/draw/extra draws; checkpoint 0 always present |
| `compile/logic` | `run2` on every opcode; full `run3` truth tables vs. the definitions; `run3` soundness (exhaustive over the unknown bits for random programs); Hall check vs. a brute-force assignment search |
| `compile/compiler` | Leaf dedupe; checkpoint-ordered bits; `At` binding (innermost wins); retirement sets; draw-region validation |
| `compile/policy` | Quota derivation (explicit, `>=`, `>`, `==`, between, demand, polarity under `Not`); bottom order (pool → unprotected → released); conservation (Σ bottomed = n); multi-role protection order |
| `engine/exact` | Default opening; batches; snapshots; `StateSpaceTooLargeError`; early resolution & retirement switches |
| `engine/montecarlo` | Seeding determinism; trivial queries (P = 0, P = 1) exact |
| `analysis/stats` | PMF sums to 1; mean/variance closed forms; threshold-table columns consistent |
| `analysis/mulligan` | M = 0 equals no mulligan; forced keep at M; geometric formula; free mulligan keeps hand size 7 |
| `analysis/optimizer` | Monotonicity classifier on positive and negative examples; each strategy on a tiny known problem; infeasible target |
| `io/decklist` | Plain, Moxfield, Archidekt samples; sections; merging; set codes; errors with line numbers; size limit |
| `io/expr` | Every production; precedence; errors with column; keyword collision; depth and size limits |
| `api` | Each facade function end to end; string queries; `engine="auto"` fallback warning |

## 4. Error-path tests

Every `ValidationError` raise site has a test that checks the `field` attribute. Parsers check that `line`/`column` point at the offending token. `StateSpaceTooLargeError` is triggered with a tiny `limit`.

## 5. Reference tests

A1–A9 from MATH §12 are asserted as **exact `Fraction` equality** against independently written closed forms (in the test file, using `math.comb` directly), and to 10 decimal places against the published decimals.

## 6. Brute-force oracle tests

`bruteforce.py` enumerates every card-by-card draw sequence for the first n cards (hand, then draws), with probability Π remaining_i / remaining_total. For each sequence it evaluates the condition by direct AST interpretation, **not** through compiled leaves: it uses its own tag counting and its own recursive Boolean evaluator, including its own exclusive-assignment search (brute-force assignment). For mulligans, it enumerates each depth's 7-card (configurable) sequence, applies `bottom` (the policy itself is unit-tested separately), and then the subsequent draws, and combines depths by the law of total probability.

Hypothesis generates:

- decks: 2–14 cards, 1–3 tags, overlapping memberships
- game: hand 1–4, on play/draw, draws per turn 0–2, random extra draws (total seen ≤ 8)
- conditions: random ASTs of depth ≤ 3 over every node type, including `At` with turns ≤ 3, `Assignable`, and `Const`
- queries with and without `given`
- mulligans: M ≤ 2, F ∈ {0, 1}, draw size ≤ 4, random priority groups and quotas, random keep rules

**Assertion:** exact engine result == oracle result (both `Fraction`). This is the primary correctness gate (NFR-01).

## 7. Property-based invariants

| ID | Property | Source |
|---|---|---|
| P1 | 0 ≤ P ≤ 1; PMF sums to 1 | NFR-02 |
| P2 | P(A) + P(¬A) = 1 | MATH §7.1 |
| P3 | P(A ∨ B) = P(A) + P(B) − P(A ∧ B) | MATH §7.1 |
| P4 | P(A ⊕ B) = P(A ∨ B) − P(A ∧ B) | MATH §7.1 |
| P5 | P(A \| B) · P(B) = P(A ∧ B) | MATH §7.4 |
| P6 | Early resolution on == off; retirement on == off (all four combinations) | MATH §5.3 |
| P7 | General engine == `hypergeom` fast path for single-group queries | LLD §5.2 |
| P8 | Mean and variance equal the closed forms; covariance of two atoms equals the closed form | MATH §3, §4 |
| P9 | Mulligan with M = 0 == no-mulligan `probability` (hand 7) | MATH §9 |
| P10 | `optimal_keep.value ≥ mulligan_report(keep rule).p_success` for random keep rules | MATH §9.5 |
| P11 | Optimizer: bisection result == linear-scan result when classified monotone | MATH §10 |
| P12 | Monotone-classified queries: P non-decreasing in the variable (checked on a grid) | MATH §10.2 |
| P13 | `parse(format(q)) == q` for generated queries | FR-37 |
| P14 | `from_dict(to_dict(x)) == x` for generated value objects | NFR-07 |
| P15 | Exclusive assignment ⇒ shared semantics (Assignable true ⇒ each demand true individually) | MATH §8 |
| P16 | Optimizer pruning (full-cap slice, binary search on totals) gives the same optimum as the unpruned search | MATH §10.4 |

## 8. Metamorphic relations

| ID | Transformation | Expected relation |
|---|---|---|
| M1 | On the draw at turn t vs. on the play at turn t + 1 (single checkpoint) | Equal |
| M2 | Rename tags / reorder cards in the deck / reorder `And` items | Equal |
| M3 | Split one card into two copies with identical tags | Equal |
| M4 | Add a never-referenced card type with count c, and compare against a deck where the filler is increased by c | Equal (pool aggregation) |
| M5 | Swap a group and its complement: P(G ≥ k) at n cards = P(complement ≤ n − k) | Equal (MATH §3 complement) |
| M6 | Symmetry: Hyp(N, K, n) PMF == Hyp(N, n, K) PMF | Equal |
| M7 | Monotone-implication collapse: one draw per turn, ≥1 @T0 ∧ ≥2 @T1 ∧ … == last marginal (on the draw) | Equal (MATH §5.4) |
| M8 | Add a free mulligan (F: 0 → 1) | P(success) does not decrease when the keep rule = success = "≥1 copy" |

## 9. Parser fuzzing and security (NFR-14)

- Hypothesis `text()` and grammar-based fuzzing of both parsers: only `ParseError` or a valid result is allowed, never another exception.
- Oversized and deeply nested inputs are rejected quickly (bounded time).
- A grep test checks that `eval`/`exec` do not appear in `src/`.

## 10. Performance tests (NFR-03 – NFR-05)

Marked `perf`. Each scenario runs 5 times and asserts that the **median** is under budget on the reference machine:

| ID | Scenario | Budget |
|---|---|---|
| PF1 | 60 cards, 4 overlapping groups, single checkpoint T3 | 100 ms |
| PF2 | 99 cards, 4 groups, 10 checkpoints (path-dependent AND) | 1 s |
| PF3 | 60 cards, 3 groups, M = 3, F = 1, success by T5 | 3 s |

Peak state counts are recorded to catch algorithmic regressions independently of the machine.

## 11. Coverage and mutation targets (NFR-10)

| Metric | Target | Gate |
|---|---|---|
| Line coverage (`mtgcalc`) | ≥ 95% | CI fail-under |
| Branch coverage | ≥ 90% | CI fail-under |
| Mutation score (`math`, `compile`, `engine`) | ≥ 80% | Increment 2, nightly |

## 12. Traceability (requirement → tests)

| Requirement | Tests |
|---|---|
| FR-01, FR-05, FR-15 | unit/test_deck, unit/test_scenario |
| FR-02, FR-12, FR-36 | unit/test_atomizer, oracle, M2/M3 |
| FR-10 | reference A1/A2, differential/scipy, P7, M6 |
| FR-11 | reference A6, differential/scipy multivariate, oracle |
| FR-13 | reference (exact equality) |
| FR-14 | P8, reference A9 |
| FR-20 – FR-23 | unit/test_game, reference A4, M1 |
| FR-24 | unit/test_stats turn table |
| FR-25 | reference A5/A7, oracle, M7 |
| FR-30, FR-31 | unit/test_stats, P1 |
| FR-32, FR-33 | unit/test_logic, oracle, P2–P4 |
| FR-34 | unit/test_logic Hall vs. brute force, oracle, P15 |
| FR-35 | reference A8, P5 |
| FR-37 | unit/test_expr, P13, §9 |
| FR-40 – FR-47 | reference A3, unit/test_mulligan, oracle (mulligan), P9, M8, differential/montecarlo |
| FR-48 | unit/test_mulligan optimal keep, P10 |
| FR-50 – FR-54 | unit/test_optimizer, P11, P12 |
| FR-60 – FR-64 | unit/test_decklist |
| FR-70, FR-71 | differential/test_vs_montecarlo, unit/test_api |
| NFR-01, NFR-02 | §5, §6, P1 |
| NFR-03 – NFR-06 | §10, §4 |
| NFR-07 | P14, import-linter |
| NFR-11 | unit/test_montecarlo seeding |
| NFR-14 | §9 |
| FR-80 – FR-83, FR-85, FR-86 | gui/test_forms, gui/test_app_smoke, import contract "Core never depends on the test GUI" |
| FR-84 | docs/test_reference_examples, docs/test_usage_numbers |
| FR-65 | online/*, gui/test_forms (import_deck), gui/test_app_smoke (import flow and errors) |
| FR-66 | unit/test_io (round-trip property, layout) |
| FR-90, FR-91 | engine/test_core_conformance, Rust unit tests (core), web/src/forms/wasm.test.ts |
| FR-92, FR-95, FR-97 | web/src/forms/parity.test.ts, web/src/App.test.tsx, e2e/newcomer |
| FR-93 | web/src/engine/scheduler.test.ts (incl. property), transport.test.ts, App.test.tsx (slow worker), e2e/quality (typing) |
| FR-94, FR-96 | web/src/forms/parse.test.ts, App.test.tsx, e2e/newcomer (mistakes, jargon), e2e/quality (axe, keyboard) |
| FR-98 | CI `pages.yml` (build) |
| FR-106 | gui/test_forms (conditions, words, all_of/any_of, a second kind adds games, exact rounding), gui/test_app_smoke (kinds of good game), web parity (random all/any/mixed goals vs Python), state.test.ts, storage.test.ts (upgrade), parse.test.ts (property with mixed kinds), App.test.tsx, e2e/quality (axe) |
| FR-107 | e2e (every project, including a phone), manual check at 1100, 1366 and 1920 px |
| FR-108 | e2e/quality (axe WCAG 2.2 AA with three kinds of hand and two kinds of good game, light and dark), LineGroups.test.ts (cycling), App.test.tsx (kind and button colours), gui/test_app_smoke (desktop colours follow position) |
| FR-105 | gui/test_forms (`keep_condition`, words, errors, more kinds keep more hands), gui/test_app_smoke (kinds of hand), web/src/forms/parity.test.ts (scenario JSON and words vs Python, every shape), web/src/app/state.test.ts, storage.test.ts (upgrade), App.test.tsx, e2e/quality (axe) |
| FR-99 | web/src/forms/answer.test.ts, App.test.tsx (too big) |
| NFR-16 | e2e/quality (first answer, typing pause + budget), WebAssembly size check in `npm run wasm` |
| NFR-17 | e2e/quality (axe WCAG 2.2 AA light/dark, with problems; keyboard; descriptions) |
| NFR-18 | e2e/quality (no requests after load) |

## 13. Statistical test hygiene

- Monte Carlo assertions use **fixed seeds**, so they are deterministic and never flaky.
- They use 99.9% Wilson intervals with 20k–50k trials. A failure therefore means a real discrepancy, or a change in code or seed, which is reviewed.
- The expected number of false alarms across the suite is < 0.01 per seed change.

## 14. Entry and exit criteria

- **Entry:** the module's LLD section is approved, and the module has stubs with types.
- **Exit (increment):**
  - all non-`perf` tests pass
  - coverage gates pass
  - `mypy --strict` and `ruff` are clean
  - import contracts hold
  - TP §12 has no untested M requirement

## 14a. Engine matrix

The oracle, property, metamorphic and reference suites run against the **default** engine:
- the native engine when it is built;
- otherwise the Python engine.

CI also runs them with `MTGCALC_ENGINE=python`, so both engines face the same independent oracles. In addition, `tests/engine/test_native_conformance.py` compares the two engines directly, integer for integer, including observer snapshots and the BigUint overflow path.

## 14b. 0.3.0 results (native engine verified 2026-11-14)

| Gate | Result |
|---|---|
| Full suite, native engine default | 314 passed |
| Full suite, `MTGCALC_ENGINE=python` | 314 passed |
| Native conformance, `ci-deep` profile | 5 suites, about 7,500 generated cases, all identical |
| `cargo clippy -- -D warnings`, `cargo fmt --check` | clean |

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

## 14c. 0.4.0 results (mulligan enumeration in Rust)

| Gate | Result |
|---|---|
| Full suite on the native engine and on `MTGCALC_ENGINE=python` | 317 passed each |
| Native conformance, `ci-deep` profile | 8 tests (run, mulligan, hand_values, errors), all identical |
| `cargo test` / `cargo clippy` (pedantic, both feature sets) / `cargo fmt` / `cargo doc` | 22 passed / clean / clean / no warnings |

| Workload | Python | 0.3.0 native | 0.4.0 native |
|---|---|---|---|
| Mulligan report, 3 mulligans | 16.5 ms | 4.3 ms | 1.2 ms |
| Optimal keep, 3 mulligans (60 cards) | 31.0 ms | 10.7 ms | 4.3 ms |
| Optimal keep, Commander, 4 card types (666 hands per depth) | 1327 ms | — | 93 ms |
| Optimizer, 99 cards, 2 variables + mulligans | 197 ms | 51 ms | 28 ms |
| Heavy Commander optimizer (308 candidates) | 5.43 s | 0.67 s | 0.44 s |

## 15. Prototype 0.1.0 results (2026-11-14)

| Gate | Result |
|---|---|
| Test suite (non-perf) | 252 passed |
| Coverage | 98.97% line+branch (gate 95%) |
| Performance PF1–PF3 | all within budget (total < 1 s on the dev machine) |
| `mypy --strict src tests`, `ruff`, import contracts | clean |
| Reference values A1–A9 | exact equality |
| Manual mutation sweep (18 planted defects in math/compile/engine/analysis/model) | 18/18 killed after adding one test |

**Findings from verifying the tests themselves:**
1. A planted defect in early resolution (dropping the future-denominator scale) survived
   the first random oracle suite, because random conditions rarely decide a state *true*
   at an early checkpoint. Fix: the `multi_checkpoint_cases` generator and the A7-disjunction
   regression test. Now caught by three independent tests.
2. An off-by-one in optimizer bisection survived the fast suites (only property test P11
   caught it). Fix: `test_bisection_equals_linear_scan` across eight targets.

Lesson for this test plan: every oracle-based suite also needs a planted-defect check that
shows it can fail. Increment 2 automates this with `mutmut` (§11).

## 16. Web app (Phase 3, increment 1, ADR-0013)

### 16.1 What is tested, and against what

| Level | Oracle | Where |
|---|---|---|
| Rust core unit tests | Hand-derived values (A1, a hypergeometric tail), Python's messages, closed form vs. turn-by-turn sum | `native/core` |
| Core conformance | The pure-Python reference (`MTGCALC_ENGINE=python`) on the same JSON: generated plain, multi-checkpoint and web-shaped cases; A1, A4–A8; identical state-limit behaviour; 26 kinds of invalid input with identical field and message; every Unicode code point | `tests/engine/test_core_conformance.py` |
| WebAssembly conformance | Python's answers in `web/fixtures/forms.json` | `web/src/forms/wasm.test.ts` |
| Form-layer parity | Python's `build_scenario`, `goal_condition`, `chances`, `pct`, `in_words` (64 cases, 325 percentages) | `web/src/forms/parity.test.ts` |
| Form validation | Hand-written expectations per message; property test: every accepted form gets an answer in [0, 1] from the real `.wasm` | `web/src/forms/parse.test.ts` |
| Live scheduler | A fake clock; property test over random interleavings of typing, time, replies and crashes | `web/src/engine/scheduler.test.ts` |
| Components | The real app with the real WebAssembly in-process (no worker) | `web/src/App.test.tsx` |
| End to end | The production build on Chromium, Firefox and a phone | `web/e2e/` |
| New users | Scripted first-time journeys (no jargon at any step), and an exploratory session by a reviewer who had never seen the app (§16.3) | `web/e2e/newcomer.spec.ts` |

### 16.1a Port stage 2 (rule language, decklists)

| Level | Oracle | Where |
|---|---|---|
| Rust unit tests | Python's outputs for every line shape, error, Unicode case (`ı`, `ſ`, Kelvin sign, Arabic-Indic digits) | `native/core/src/io`, `model/text.rs` |
| Text conformance | Python's `parse_query`/`format_query`/`parse_decklist` on hand-picked texts, fragment-generated texts (600 + 800 examples), arbitrary Unicode text, printed generated conditions, and whole text questions | `tests/engine/test_text_conformance.py` |
| Web pipeline parity | 35 golden form cases (pasted decklists, typed rules): raw form → read → request → `.wasm` → sentence, equal to Python's `chances` | `web/src/forms/parity.test.ts` |
| Messages | Every decklist and rule message, hand-checked | `web/src/forms/text.test.ts` |
| Journeys | Pasting a real Moxfield export; a wrong line; writing a rule from the lines; axe with both | `web/e2e/` |

Results: 76 Rust unit tests; 90 text-conformance tests; 8 of 8 planted parser defects caught (newline escape, arrow token, "found" message, `#!` backtracking, set-code length, CRLF, `repr` quotes, `x` quantity). The conformance suite found a bug in the Python reference: a section header matched by `(?i)` with a dotless `ı` raised `KeyError`; fixed, with a regression test in both languages.

### 16.1b Port stage 3 (distributions, turn tables)

- Rust: observer compilation (atomization order, checkpoints, retirement), the A2 PMF, turn rows equal to separate probabilities.
- Conformance: 300 generated distributions and 300 turn tables equal Python's (`to_dict`), a realistic 99-card case, the state limit, malformed questions, `GIVEN` refused. 2 of 2 planted defects caught (observers ignored by retirement, unsorted turns).
- Web: 12 golden question cases equal the desktop app's table rows string for string (averages, exactly/at least/at most, cards seen, chance, words); component and E2E journeys for both questions; axe with the tables (which found that sideways-scrolling tables must be keyboard-focusable: fixed).

### 16.1c Port stage 4 (mulligans)

- Rust: A3 (one mulligan), the best plan never worse than the configured one, validation messages, lower bounds.
- Conformance: 250 strategy-level probabilities, 200 mulligan reports, 200 optimal-keep reports, 100 mulligan-aware tables (or the same error), a realistic Commander plan, A3 through the boundary, 8 invalid configurations with Python's field and message, and 4 derived-quota cases with 7-card draws and 3 mulligans. Those last cases were added because 2 of 6 planted defects (strict bound without +1, quota from min) survived the generated cases; with them, 6 of 6 are caught.
- Web: 10 golden mulligan cases (chances with a plan, and "Should I mulligan?" rows, hand by hand) equal the desktop app; component tests for settings, problems, focus and the free first mulligan; E2E journey and axe.

### 16.1d Port stage 5 (the card-count optimizer)

- Conformance (`tests/engine/test_optimizer_conformance.py`): 250 generated problems (1–3 variables, every objective, fixed categories, mulligans, budgets, exhaustive limits 0/3/5000, monotonicity forced or detected, 16 rule shapes) give Python's `to_dict(OptimizeResult)` exactly, including `evaluations` and the frontier, or the same infeasible/validation error. Also: 8 invalid problems with Python's field and message, three realistic cases (exhaustive, bisection, local search), and `one_fewer` checked against the desktop app's `_one_fewer` on 60 generated problems.
- Planted defects: 7 of 7 caught (ties prefer more cards, local search accepting equal moves, bisection midpoint, `>` treated as not monotone, exhaustive limit off by one, pruning that stops instead of skipping, frontier length). "`>` not monotone" first survived, because every generated rule used `>=`. Rules with `>`, `NOT`, `->` and `atleast` were added; the defect is now caught.
- Web: 6 golden how-many cases (each mode, answered and out of reach) equal the desktop app's headline, details and rows. Reducer tests cover the pre-filled rows. Component tests cover each mode, the run-on-request button, focus, and problems (bounds against the deck size, a pasted decklist). E2E journeys and axe, before and after running.
- Results (2026-11-24): Rust 91 tests; Python 536 passed, 97% coverage; Vitest 750 passed (97.5% statements, 91.8% branches); Playwright 76 passed, 11 skipped. The WebAssembly is 352 kB gzipped (budget 500 kB).

### 16.2 Results (2026-11-23)

- **Rust:** 65 unit tests. `fmt`, `clippy::pedantic` (every crate, including the wasm32 target) and `doc` are clean.
- **Python:** 402 tests pass, with 97% coverage. The 44 core-conformance tests are included.
- **Web:** 589 Vitest tests pass, with 99% line, 93.5% branch and 97% function coverage. Playwright: 40 passed and 5 skipped (the axe scans on Firefox, where axe crashes Playwright's Firefox build; keyboard tests on the phone; phone tests on desktops).
- **Size and speed:** the WebAssembly file is 201 kB gzipped. Typical questions take 0.4–43 ms in WebAssembly (60-card, 2 types: 0.4 ms; 99-card, 4 types to turn 10: 43 ms; 8 lines to turn 20: 31 ms).
- **Planted defects** (each must make a test fail):
  - Rust port: 9 of 9 were caught: on-play draw, bit order, region check, case folding, retirement, `At` turns, quantity zero, `none_of`, at-least off by one.
  - Scheduler: 6 of 6 were caught after one test was added. Before that, "busy ignores computing" survived, which exposed a missing busy update when the debounce fires; it is fixed.
  - The jargon check fails when a technical word is planted in the page text.
  - The first run of the invalid-input suite sampled mutation kinds unevenly, so some kinds were never exercised. Each kind is now its own test case.
- **Bugs found by the tests and fixed:**
  - The form accepted decks smaller than an opening hand (found by the property test).
  - The out-of-date answer was dimmed with opacity, below WCAG AA contrast (found by axe).
  - The answer stayed grey after it arrived (found by review of screenshots).
  - On phones, the answer scrolled out of view (found by review of screenshots).
  - The wording said "about 1 games in 10" and "at least 1 cards", and exact 0 read as "almost never". Fixed in both apps.

### 16.3 New-user review (exploratory, 2026-11-23)

A reviewer who had never seen the app played a brand-new player. They used only the running page (Playwright and screenshots, no source code) and worked through tasks in character: a first impression, four questions of their own, the usual mistakes, keyboard only, and a phone.

**Correctness:** every answer they checked matched their own calculation. Examples: 23 lands, at least 2 in the opening hand, 83.5%; at least 4 lands by turn 4 on the draw, 68.3%; a Commander "3 lands or 1 ramp by turn 2", 90.7%; a 40-card "3 lands by turn 3 but at most 6 by turn 7", 54.9%.

**Round 1 findings, and what changed:**

| Finding | Severity | Change (with a test) |
|---|---|---|
| The card said only "Fix the highlighted field", and a section's problem waited a second | Blocker | The card states the problem ("To update the answer: …"). A section's problem shows as soon as the player leaves the section. A field's problem was already shown under the field; the reviewer's screenshot had cropped it out. |
| On phones, the pinned card grew over the field being fixed | Blocker | While the form has a problem, the card collapses to "Out of date" plus the problem; fields reached by scrolling stop below the card. Test: `e2e/newcomer` "never covers", shown to fail without the fix |
| The old answer looked current | Confusing | A red "Out of date: …" label |
| "about 10 games in 10" | Confusing | "all but about 1 game in N" above 85%, "about 1 game in N" below 15% (both apps) |
| Cards that count as two types were easy to double-count; "land ramp" without a comma silently made a new type | Confusing | An explicit hint, and a non-blocking note for "also counts as" names that are not card types |
| Names were lowercased ("lightning bolt") | Confusing | Names are shown as typed |
| Jargon in examples ("mdfc", "bomb"); format buttons kept old counts | Confusing | Plain names; a hint that the types stay as they are |
| Exact numbers meant nothing to a beginner | Polish | Four decimals, plus a sentence explaining the fraction |
| Half-typed answers flashed; the card changed height | Polish | A 250 ms pause (was 150 ms) and a fixed-height status line |
| Focus fell to the page after removing a row, and stayed on the button after adding one | Polish | Focus moves into a new row, and to the add button after a removal |
| A reload lost the setup | Polish | The setup is remembered in this browser |

**Round 2** (same reviewer, fixed build): 8 of the 10 changes were confirmed fixed and 2 partly fixed; nothing got worse. Follow-ups made:
- "Finish typing to update the answer" appeared after button presses, when nothing was being typed. Problems now show at once when no field has focus (regression test, shown to fail without the fix).
- "before the last change" is now "an earlier version of your setup".
- Table columns no longer resize when a message appears.
- The example names "key card" and "land and removal" read naturally.
- The examples say that they replace your setup.

**"How many should I play?" review (2026-11-24, two rounds, same method):**

| Finding | Severity | Change (with a test) |
|---|---|---|
| Pressing the button straight away said "cannot be reached": with removal fixed, the example could not reach the 90% default | Blocker | Choosing the question or a mode fills in the card types the good game uses, with ranges around their counts; the default target is 60%. Reducer tests, plus an E2E press on the starting values |
| An unreachable target showed "Details for a bug report" | Blocker | It is an answer, not a fault: no details |
| Share mode listed only land, sharing 20 cards | Blocker | Pre-filled with every card type of the good game, sharing their current total; a hint asks for a second card type when only one is listed |
| "to" of 70 and 200 cards to share were accepted in a 60-card deck | Minor | "This can't be more than the 60 cards in your deck." |
| "between 0 and 100" rejected 0 | Minor | "above 0 and up to 100 percent" |
| The button was only in the answer card; focus was lost while it ran | Minor | A second button at the end of step 3; both keep focus while working |
| Old answers and tables stayed on screen (also from another mode, or beside a problem) | Minor | A how-many result shows only while it matches the form |
| A pasted decklist left the player stuck | Minor | A "Describe my deck as card types" button |
| "best first" listed 40 land above the recommended count | Minor | "Options tried, highest chance first", and the answer's row says "(your answer)" |
| Renaming a card type broke the how-many and mulligan rows (found while writing the tests) | Minor | A rename now follows everywhere the type was chosen |

Accepted: the pinned answer card's height on phones (unchanged design, see above); a target shown as "99.990%" (the desktop app's format); names without automatic plurals.

**Accepted as is:**
- "at least 3 land": players say "3 land", and automatic plurals of names players choose would often be wrong.
- A brief flash when typing slower than the pause.
- "almost every game" above 99.5%.
