# MTG Super Calculator: Test Plan

| | |
|---|---|
| Document ID | TP-04 |
| Version | 0.6 (synchronized with 0.4.0) |
| Covers | SRS-01 v0.3, LLD-03 v0.3 |
| Tooling | pytest, Hypothesis, pytest-cov, SciPy (dev-only oracle), mutmut (increment 2), import-linter, mypy, ruff |

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
  online/test_live.py                          # marker `network` (opt-in): the real Archidekt API, to catch format changes
  docs/test_usage_numbers.py                   # recomputes every number quoted in docs/USAGE.md (FR-84)
  engine/test_native_conformance.py            # Rust == Python, bit for bit: run, mulligan, hand_values, errors (NFR-09; skipped if not built)
native/src/*.rs  #[cfg(test)]                 # 22 Rust unit tests (cargo test): A1, A3, A4, bottom order, Hall, Kleene, overflow, validation
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
