# MTG Super Calculator: Software Requirements Specification

| | |
|---|---|
| Document ID | SRS-01 |
| Version | 0.8 |
| Source | `plan.md` |
| Phase covered | Phase 1: core calculation engine; Phase 3 (started): the web app (§5.11) |
| Related | `00-math-foundations.md` (MATH), `02-high-level-design.md` (HLD), `03-low-level-design.md` (LLD), `04-test-plan.md` (TP), `05-engineering-process.md` (EP), `adr/` |

### Change history

| Version | Change |
|---|---|
| 0.1 | Initial draft from `plan.md` |
| 0.2 | Resolved Q1–Q3 (Python; "by turn T" = after the draw; mulligan bottoming follows user-given groups) |
| 0.8 | Added §5.11, the web app (FR-90 – FR-99, ADR-0013), and NFR-16 – NFR-18. Updated §2.2. |
| 0.7 | Added FR-65 (import from a deck link) and FR-66 (write decklists). |
| 0.6 | FR-84 split into beginner and reference docs; added FR-85 (beginner-first GUI) and FR-86 (examples and in-app help). |
| 0.5 | Native engine (ADR-0009) made optional; FR-71 and NFR-06 reworded for limit-based fallback. |
| 0.4 | Added §5.10: a desktop test GUI (FR-80 – FR-83) and a usage guide (FR-84). |
| 0.3 | Aligned with the math baseline. Added user stories, acceptance criteria, FR-48 (optimal keep strategy), FR-15 (scenario object), input-safety NFRs, and reference values A7–A9. Moved the verification strategy to TP. |

---

## 1. Purpose

The MTG Super Calculator answers probability questions about drawing cards from a Magic: The Gathering deck. Examples:

- "What is the chance I have at least one of my 4 copies of X in my opening hand?"
- "What is the chance I make my first three land drops on time?"
- "How does mulliganing to 5 change my chance of having a ramp spell by turn 2?"
- "How many lands do I need so that I hit 4 lands by turn 4 at least 90% of the time?"

This document states **what** the system must do. The mathematics it must agree with is in MATH. How the system does it is in the HLD and LLD.

Requirement keywords follow RFC 2119 / RFC 8174: **shall** = mandatory, **should** = recommended, **may** = optional. Priorities use MoSCoW (**M**ust / **S**hould / **C**ould). Requirement IDs are stable. A retired ID is never reused.

## 2. Scope

### 2.1 In scope (Phase 1)

- Hypergeometric, multivariate, and grouped (tag-based, overlapping) probability calculations
- Multi-turn draw modelling with configurable draw schedules, including path-dependent conditions
- Threshold statistics and full distributions
- Logical conditions, conditional probability, and exclusive assignment
- The London mulligan with free mulligans, user-prioritised bottoming, strategy-level reports, and the optimal keep strategy
- An optimizer for card counts
- Parsing of local text decklists with tags
- A Monte Carlo engine (verification oracle and fallback)
- A stable, JSON-serializable programmatic API
- A comprehensive automated test suite (TP)

### 2.2 Out of scope (deferred)

| Item from plan.md | Deferred to | Phase 1 obligation |
|---|---|---|
| GUI elements (production) | Phase 3 | The API must be GUI-ready (NFR-08). A Tk **test GUI** ships in Phase 1 (§5.10). |
| Web app refactor | Phase 3, started: §5.11, ADR-0013 | The core must be pure, with no I/O (NFR-07). |
| Network fetching from deck sites | Done for Archidekt (FR-65, ADR-0012); Moxfield blocks programs | Define the importer interface (FR-63). |
| Native acceleration (Rust/C/C++) | Phase 2 | Put the engine behind an interface (NFR-09). |
| GitHub setup and site publication | GitHub: done. Site: Phase 3 (FR-98) | The repo is CI-ready (EP). |
| Colour-fixing analysis, generic opening-hand analysis | Future | None |

## 3. Glossary

| Term | Definition |
|---|---|
| **Library / deck** | The N cards that are shuffled at game start. The commander is excluded. |
| **Tag** | A user label on a card (`land`, `ramp`, …). One card may carry several tags. |
| **Selector** | A rule that picks cards: by tag, by card name, or by a Boolean combination (any / all / none). |
| **Group** | A named selector whose count among seen cards is used in conditions. |
| **Atom** | The set of cards that share the same membership pattern across the referenced groups. Atoms are disjoint (MATH §6). |
| **Seen cards** | The cards in the kept hand plus all cards drawn since. Cards put on the bottom are not seen. |
| **Checkpoint / "by turn T"** | Turn 0 = the kept opening hand. Turn T ≥ 1 = **after the draw step of turn T** (decision Q2). |
| **On the play / on the draw** | Whether the player skips the turn-1 draw. |
| **London mulligan** | Draw 7, then put `max(0, m − F)` cards on the bottom after the m-th mulligan. F is the number of free mulligans (MATH §9.1). |
| **Keep rule** | A condition on the kept hand that decides whether to keep or mulligan. |
| **Priority groups** | The user-ordered list of groups that drives which cards go to the bottom (decision Q3). |
| **Scenario** | Deck + game configuration + optional mulligan configuration. The fixed context of a query. |

## 4. Stakeholders and user stories

| ID | As a… | I want to… | So that… | FRs |
|---|---|---|---|---|
| US-1 | deckbuilder | know the chance of seeing a specific card by a given turn | I can decide how many copies to play | FR-10, FR-20 |
| US-2 | deckbuilder | ask about several card groups at once, even when cards overlap | I get correct answers for MDFCs and multi-role cards | FR-11, FR-12, FR-34 |
| US-3 | player | see how each mulligan changes my odds | I understand the cost of shipping a hand | FR-40 – FR-47 |
| US-4 | player | know the best keep/mulligan rule for a goal | I can mulligan correctly | FR-48 |
| US-5 | deckbuilder | combine conditions with AND/OR/IF across turns | I can model real game plans (curve-outs, combos) | FR-25, FR-32 – FR-35 |
| US-6 | deckbuilder | be told how many copies or lands I need for a target | I can tune my deck quickly | FR-50 – FR-54 |
| US-7 | Commander player | import my tagged decklist | I don't have to type counts by hand | FR-60 – FR-64 |
| US-8 | front-end developer (later) | call a stable, serializable API | I can build the GUI and web app without touching the maths | NFR-07, NFR-08 |

## 5. Functional requirements

### 5.1 Deck, scenario, and card modelling

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-01 | The system shall accept a deck as (a) an abstract population (deck size plus named category counts, which may overlap), or (b) a concrete card list with quantities and zero or more tags per card. | M | all |
| FR-02 | A card may carry multiple tags. Conditions shall count a multi-tagged card toward every group it belongs to (shared semantics), unless exclusive assignment is requested (FR-34). | M | grouped |
| FR-03 | Every card name shall be usable as a selector. | M | simple |
| FR-04 | The system shall validate inputs and reject impossible configurations before computing. Errors shall name the offending field (NFR-12). | M | — |
| FR-05 | Deck size shall be any positive integer. Presets shall exist for Limited (40), Constructed (60), and Commander (99 in the library + 1 commander), each with default game and mulligan settings. | M | — |
| FR-15 | Deck, game configuration, and mulligan configuration shall be bundled into an immutable **Scenario** that every query takes. | M | GUI readiness |

### 5.2 Core probability calculations

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-10 | **Simple hypergeometric:** given N, K, n, compute P(X = k), P(X ≥ k), P(X ≤ k), P(X > k), P(X < k), the PMF, and the CDF. | M | simple |
| FR-11 | **Multivariate:** compute the probability of any joint count condition over several disjoint categories. | M | multivariate |
| FR-12 | **Grouped:** compute joint count conditions over overlapping groups exactly (MATH §6). No independence or other approximation is allowed. | M | grouped |
| FR-13 | Results shall be exact rationals by default and shall be exposed both as an exact fraction and as a float. | M | — |
| FR-14 | Report E[X] and Var[X] for any group at any checkpoint. | S | thresholds |

### 5.3 Turns and draw schedule

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-20 | Compute probabilities "by turn T" for any T ≥ 0, with the semantics in §3. | M | multi-turn |
| FR-21 | Select on the play or on the draw. | M | multi-turn |
| FR-22 | Customize draws per turn: a default count, per-turn replacements, and per-turn extra draws. | M | draws/turn |
| FR-23 | The opening hand size shall be configurable (default 7). | M | — |
| FR-24 | Produce a per-turn table of a condition's probability for turns 0…T, from a single engine evaluation. | M | multi-turn |
| FR-25 | **Path-dependent conditions:** leaves of a condition may be bound to different checkpoints. The joint probability shall be exact (MATH §5.4, reference A7). | M | advanced logic |

### 5.4 Threshold statistics

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-30 | For any group and checkpoint, report P(none), P(exactly k), P(at least k), P(at most k), and the full distribution. | M | thresholds |
| FR-31 | Produce a threshold table (rows k, columns exactly / at least / at most), optionally for several turns. | M | thresholds |

### 5.5 Logical conditions

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-32 | Comparison predicates on group counts: `==`, `!=`, `<`, `<=`, `>`, `>=`, and an inclusive range. | M | advanced logic |
| FR-33 | Connectives: AND, OR, binary XOR, NOT, IMPLIES, at-least-n-of, and exactly-n-of. Nesting is arbitrary. | M | advanced logic |
| FR-34 | **Exclusive assignment:** whether a set of `group ≥ d` demands can be met by distinct cards (MATH §8). | S | grouped |
| FR-35 | **Conditional probability:** P(A \| B). If P(B) = 0, report it as undefined, not as an error. | M | conditionals |
| FR-36 | Selectors: tag, card name, any-of, all-of, none-of, everything. | M | grouped |
| FR-37 | A plain-text condition syntax that round-trips with the structured form. | S | GUI readiness |

### 5.6 Mulligans

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-40 | Given a keep rule and a maximum of M mulligans, compute P(keep) at each depth. The hand at depth M is always kept. | M | mulligans |
| FR-41 | London mulligan with F ∈ {0, 1} free mulligans: on mulligan m, draw 7 and put `max(0, m − F)` cards on the bottom. | M | adv. mulligans |
| FR-42 | Cards put on the bottom are not seen. Later draws come only from the cards that were not among the 7 drawn (MATH §9.2). The system shall reject configurations whose draws would reach the bottomed cards. | M | adv. mulligans |
| FR-43 | **Bottoming by user-given groups.** The user supplies an ordered list of groups (selector + optional keep quota), from highest to lowest priority. Cards in no listed group go to the bottom first, then cards from lower-priority groups. Cards up to each group's quota stay protected for as long as possible. An omitted quota defaults to the largest lower bound that the keep rule or success condition places on that group, otherwise "keep all". | M | adv. mulligans |
| FR-44 | An optimal bottom policy (choose the bottom set that maximizes success). | C | adv. mulligans |
| FR-45 | Per-depth report: P(reach m), P(keep \| reached m), P(success \| forced keep at m), P(success ∧ keep \| reached m), and the hand size. | M | mulligan effect |
| FR-46 | Strategy-level result: P(success), E[mulligans], E[kept hand size]. | M | mulligan effect |
| FR-47 | The success condition may use any checkpoints, including path-dependent ones. | M | mulligans, multi-turn |
| FR-48 | **Optimal keep strategy:** for a given bottom policy and success condition, compute the keep strategy that maximizes P(success), using backward induction (MATH §9.5). Report its value and, at each depth, which hand compositions it keeps. | S | adv. mulligans |

### 5.7 Optimizer

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-50 | Minimum count of one variable category that meets a target probability. | M | optimizer |
| FR-51 | Maximize P(condition) over several bounded variable categories, subject to a total budget. | M | optimizer |
| FR-52 | Minimize the total of the variable counts subject to P ≥ target. | S | optimizer |
| FR-53 | Report the counts, the achieved probability, **whether optimality is proven**, the number of evaluations, and the best evaluated points. Optimality may only be claimed under the conditions in MATH §10. | M | optimizer |
| FR-54 | The optimizer shall accept any scenario and query the evaluator supports. | S | optimizer |

### 5.8 Deck import (local, Phase 1)

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-60 | Parse `N Name` / `Nx Name` lines, ignoring blank and comment lines. | M | API/tags |
| FR-61 | Parse Moxfield-style `#tag` and Archidekt-style `[Cat1,Cat2]` tags. Set-code suffixes are ignored. | S | API/tags |
| FR-62 | Recognise commander, sideboard, and maybeboard sections. Only the main deck becomes the library. | S | API/tags |
| FR-63 | Define a `DeckImporter` interface for Phase-2 network importers. | M | API/tags |
| FR-64 | Add, remove, and rename tags on a parsed deck. | S | API/tags |
| FR-65 | **Import from a deck link.**
- An Archidekt deck link shall be imported (cards, quantities, zones, categories as tags) in one step from the GUI and from Python.
- A Moxfield link shall be recognized and answered with instructions for its text export.
- Any other text is rejected without a network request.
- The core library stays free of I/O (separate `mtgcalc_online` package, ADR-0012). | S | API/tags |
| FR-66 | Write a deck back out as decklist text that the parser reads back identically (tags with spaces are hyphenated). | S | API/tags |

### 5.9 Verification and fallback

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-70 | A seedable Monte Carlo engine that takes the same scenario and query objects and returns an estimate with a Wilson 95% interval. | M | tests |
| FR-71 | `engine="auto"` shall run the exact engine and fall back to Monte Carlo, with a warning, only if the exact engine exceeds the configured live-state limit. | S | performance |

### 5.10 Test GUI and documentation (Phase 1 developer tooling)

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-80 | A desktop **test GUI** shall expose every Phase-1 analysis: probability (including conditional probability and engine choice), distribution/threshold tables, turn tables, mulligan report, optimal keep, and optimizer. | M | GUI |
| FR-81 | The GUI shall build scenarios from category counts or pasted/loaded decklists, and shall support every game and mulligan setting. | M | GUI |
| FR-82 | The GUI shall report invalid input in place and never crash on user input. Long calculations shall not freeze the window. | M | GUI |
| FR-83 | The GUI shall be a separate package that the core never imports. It is a developer tool and does not replace the Phase-3 web app. | M | GUI |
| FR-84 | Documentation shall be split by audience:
- **`USAGE.md`**: a beginner's guide to the app, free of jargon.
- **`REFERENCE.md`**: rule language and Python API.

Every number quoted in `USAGE.md` and every code example in `REFERENCE.md` shall be checked by the test suite. | M | docs |
| FR-85 | **Beginner-first GUI.** The GUI shall be usable without knowing the rule language or any statistical terms:
- the deck is entered as a table of card types (with "also counts as");
- play settings are plain questions;
- goals are built from drop-down lines ("at least 3 land by turn 3");
- each analysis is phrased as a question;
- every answer leads with a plain sentence;
- every field has hover help;
- technical options sit in a Settings dialog. | M | GUI |
| FR-86 | The GUI shall provide complete example setups and in-app help: getting started, a glossary, and the rule language for advanced users. | S | GUI |

### 5.11 Web app (Phase 3, ADR-0013)

The web app runs entirely in the browser. Its calculations come from the Rust core compiled to WebAssembly. Increment 1 covers "What are my chances?" without mulligans; the other questions follow the port stages in ADR-0013 §2.

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-90 | The Rust core shall implement `probability` (including conditional probability) for scenarios without mulligans, with results identical to the Python reference for every input both accept, and the same error kind for every input either rejects. | M | conformance |
| FR-91 | The core shall accept and produce the JSON format of `mtgcalc.model.serialization` (ADR-0013 §3), and report errors as `{kind, field, message}` without ever panicking on input. | M | API |
| FR-92 | The web app shall let a player describe a deck as a table of card types (name, how many, "also counts as"), choose a format preset, say whether they go first and how many cards they draw each turn, and build a goal from lines ("at least 3 land by turn 3") which combine as kinds of good game (FR-106). | M | web |
| FR-93 | **Live answers.** The answer shall update by itself after any change, with no button press (except "How many should I play?", FR-104), without blocking typing, and shall never show an answer that belongs to an older version of the form. | M | web |
| FR-94 | While the form is incomplete or invalid, the page shall keep the last good answer marked as out of date and say, next to the field, what to change in plain words. | M | web |
| FR-95 | The answer shall lead with a plain sentence (as FR-85) and offer the exact fraction on request. Percentages shall be rounded from the exact value. | M | web |
| FR-96 | Every field shall have a visible label and a short plain-language explanation; the page shall be usable with a keyboard alone and with a screen reader (announced answers). | M | web |
| FR-97 | The page shall open with a complete example already answered, so a first-time visitor sees what the tool does before typing anything. | S | web |
| FR-98 | The site shall be built and published by CI as static files (GitHub Pages). | S | ops |
| FR-99 | Questions beyond the exact engine's limits shall get a plain "too big to work out exactly" message that says how to simplify. | M | web |
| FR-100 | (Port stage 2) The web app shall accept a pasted decklist with `#tags` (Moxfield and Archidekt text), show what it read (cards, commander, tags), offer its tags as card types, and say which line is wrong in plain words. The Rust parser shall match `parse_decklist` exactly. | M | web |
| FR-102 | (Port stage 3) The web app shall answer "How many will I draw?" (the average and the chance of at least 1, 2, … of a card type by each turn, with every exact/at least/at most number on request) and "Turn by turn" (the chance of a good game at each turn), matching `analysis.stats` and the desktop app's tables. Tables shall be keyboard-scrollable and labelled. | M | web |
| FR-103 | (Port stage 4) The web app shall model the London mulligan (keep rule, cards to keep first with "up to" counts, most mulligans, free first mulligan), include it in every answer (saying so), and answer "Should I mulligan?" (your plan, never mulliganing, the best possible plan, and the hands the best plan keeps), matching `analysis.mulligan` and the desktop app's advice. | M | web |
| FR-104 | (Port stage 5) The web app shall answer "How many should I play?" for one card type or for several sharing a number of cards allowed, each aiming either for the best chance (no target needed) or for the fewest cards that reach a target the player chooses, with the chance one card fewer would give, whether the answer is guaranteed best, the best options tried, and plain advice when a target cannot be reached. It runs when the player asks (a search may take seconds). The Rust optimizer shall match `analysis.optimizer` exactly (counts, probability, evaluations, frontier, errors). | M | web |
| FR-105 | **Kinds of hand to keep.** Both apps shall let a player list several kinds of hand they keep, each made of one or more lines ("2 to 5 land", "1 to 7 ramp"). A hand is kept when it fits **any** kind, and it fits a kind when **every** line of that kind holds; no kinds means "keep every hand". The same rule applies at every hand size. The rule shall be restated in words ("keep a hand with 3 to 5 land, or with 2 land and 1 to 7 ramp"), and the web app shall match the desktop app's condition and words exactly. Web forms saved with one keep rule shall be upgraded. | S | GUI, web |
| FR-106 | **Kinds of good game.** Both apps shall build the good game the way they build the kinds of hand to keep (FR-105), with the same layout and words: kinds of good game, each with one or more lines. A game is good when it fits **any** kind, and it fits a kind when **every** line of that kind holds. This replaces the single "all"/"any" switch, which it covers: one kind is "all", and one line per kind is "any". The good game shall be restated in words, and web forms saved with the switch shall be upgraded. | S | GUI, web |
| FR-107 | **Wide screens.** On a computer monitor the web app shall use the width of the screen: steps 1 and 2 side by side (from 1500 px), step 3 across both, and a wider answer column. Phones and narrow windows keep one column. | S | web |
| FR-101 | (Port stage 2) Experienced players may write the goal as a rule (the rule language, FR-37), starting from their lines written as a rule, with a short guide; problems name the character and say what is expected. The Rust parser and printer shall match `parse_query` and `format_query` exactly. | S | web |

## 6. Non-functional requirements

| ID | Category | Requirement | Verification |
|---|---|---|---|
| NFR-01 | Correctness | Exact results equal MATH §12 reference values as rationals, and equal the brute-force oracle on generated small scenarios. | TP §5, §6 |
| NFR-02 | Correctness | Every probability is in [0, 1]. Every PMF sums to exactly 1. | TP §7 |
| NFR-03 | Performance | Single-checkpoint query, 60 cards, ≤ 4 groups: < 100 ms (reference Python). | TP §10 |
| NFR-04 | Performance | 10-turn sequential query, 100 cards, ≤ 4 groups: < 1 s. | TP §10 |
| NFR-05 | Performance | Mulligan report, M ≤ 3, success by turn ≤ 5, ≤ 3 groups: < 3 s. | TP §10 |
| NFR-06 | Robustness | The exact engines stop as soon as the number of live states exceeds a configurable limit, raising `StateSpaceTooLargeError` or falling back per FR-71. | TP §4 |
| NFR-07 | Architecture | The core is pure: no network, file, or console I/O, and no mutable global state other than bounded pure-function caches. All public inputs and outputs round-trip through JSON-compatible dicts. | TP §7, import contracts |
| NFR-08 | Extensibility | The public API is stable under SemVer and front-end agnostic. | EP §5 |
| NFR-09 | Extensibility | The exact engine sits behind an `Engine` protocol (`run`, `mulligan`, `hand_values`). The optional native (Rust) engine (ADR-0009, ADR-0011) must return bit-identical integers to the Python engine for all three operations (conformance suite). | TP §6, tests/engine |
| NFR-10 | Quality | Line coverage ≥ 95% and branch coverage ≥ 90% for `mtgcalc`. Mutation score ≥ 80% on `math`, `compile`, and `engine`. Every FR has at least one linked test. | TP §11 |
| NFR-11 | Determinism | Exact results are deterministic. Monte Carlo is reproducible from a seed. | TP §8 |
| NFR-12 | Usability | Errors identify the field (or line/column for parsers) and the reason. | TP §4 |
| NFR-13 | Portability | Pure Python 3.12+. No required runtime dependencies. Optional extras for acceleration. | CI matrix |
| NFR-14 | Security | Parsers never `eval` input. Input sizes are bounded (decklist ≤ 1 MB, expression ≤ 10 kB, nesting ≤ 64) to protect future web deployment. | TP §9 |
| NFR-16 | Performance (web) | On a mid-range laptop, an increment-1 question on a 60- or 99-card deck with up to 4 card types and turn 10 answers within 100 ms of the last change, plus the 250 ms typing pause. The first answer appears within 2 s of opening the page. The WebAssembly file is under 500 kB (gzip). | TP §16 |
| NFR-17 | Accessibility (web) | WCAG 2.2 AA: an automated axe scan finds no violations; every control is reachable and operable by keyboard; answers are announced through a polite live region. | TP §16 |
| NFR-18 | Privacy (web) | The web app makes no network requests after loading and stores nothing about the user beyond, optionally, their own form in the browser. | TP §16 |
| NFR-15 | Maintainability | `mypy --strict` and `ruff` are clean. Layer dependencies are enforced automatically (HLD §3). Public items have docstrings. | CI |

## 7. Assumptions and constraints

1. The library is uniformly shuffled. No scry, tutor, or shuffle effects are modelled (MATH §2).
2. Only "draw a card" effects are modelled, through the draw schedule.
3. Cards put on the bottom are never drawn within the horizon (validated, FR-42).
4. Mulligans are independent shuffles. The keep rule is evaluated on the hand **after** bottoming.
5. Shared counting is the default for overlapping groups (FR-02).

## 8. Decisions and open questions

| # | Question | Status | Decision / ADR |
|---|---|---|---|
| Q1 | Core language | Resolved | Python 3.12+ (ADR-0001) |
| Q2 | Meaning of "by turn T" | Resolved | After the draw step of turn T (ADR-0004) |
| Q3 | Bottoming priority | Resolved | User-given groups in order (ADR-0005) |
| Q4 | Historical mulligan rules (Vancouver/Paris)? | Open | Not planned. Can be added later as a new `MulliganRule`. |
| Q5 | Should optimal bottoming (FR-44) be prioritized above C? | Open | C for now |

## 9. Acceptance criteria (Phase 1 exit)

1. Every **M** requirement is implemented and linked to at least one passing test (TP §12 traceability).
2. References A1–A9 (MATH §12) pass exactly.
3. The brute-force oracle suite passes with the default generated examples (TP §6).
4. The NFR performance budgets pass on the reference machine (TP §10).
5. The quality gates in EP §3 are green.

## Appendix: traceability from plan.md

| plan.md item | Requirements |
|---|---|
| simple hypergeometric calculator | FR-10, FR-13 |
| multivariate hypergeometric calculator | FR-11 |
| grouped multivariate hypergeometric calculator | FR-02, FR-12, FR-34, FR-36 |
| logic for mulligans | FR-40, FR-46 |
| count probabilities over multiple turns | FR-20, FR-21, FR-24, FR-25 |
| customize number of cards drawn per turn | FR-22 |
| stats for different thresholds | FR-14, FR-30, FR-31 |
| show how mulligans affect percentages | FR-45 |
| advanced logic for mulligans | FR-41 – FR-44, FR-47, FR-48 |
| advanced logic (conditionals, AND/OR/XOR…) | FR-25, FR-32 – FR-35, FR-37 |
| API functionality with tags | FR-60 – FR-64 |
| optimizer function | FR-50 – FR-54 |
| establish unit tests | FR-70, NFR-01, NFR-10, TP |
| optimize performance | NFR-03 – NFR-06, NFR-09, FR-71 |
| implement gui elements | FR-80 – FR-83 (test GUI); production GUI deferred (§2.2) |
| web app / GitHub / publish | FR-90 – FR-99, NFR-16 – NFR-18 (ADR-0013) |
