# MTG Super Calculator: Low-Level Design

| | |
|---|---|
| Document ID | LLD-03 |
| Version | 0.10 (synchronized with the Unreleased changes after 0.5.0) |
| Implements | HLD-02 v0.3 |
| Language | Python 3.12+, standard library only at runtime (ADR-0001); Rust (`native/`) and TypeScript (`web/`) for the native engine and the web app (§11) |

This document specifies each module: its types, contracts (pre- and postconditions), and algorithms. Signatures are typed Python stubs. Algorithms are pseudocode. The source code in `src/mtgcalc` is the authoritative implementation, and any divergence from this document is a defect in one of the two. MATH §n refers to `00-math-foundations.md`.

---

## 0. Conventions

- All value types are `@dataclass(frozen=True, slots=True)`, so they are immutable and hashable. Collections inside them are `tuple` or `frozenset`. Constructors normalize `dict` / `list` inputs into these.
- Validation runs in `__post_init__` and raises `ValidationError(field, message)`.
- Exact probabilities are `fractions.Fraction`. Floats appear only as derived `.value` properties.
- Every public type supports `to_dict()` / `from_dict()` through `model/serialization.py`.
- Internal "vectors" are `tuple[int, ...]` indexed by atom index.
- Functions are pure. The only caches are `functools.lru_cache` on pure functions of hashable arguments.
- Naming: `N` = library size, `K` = atom counts, `pool` = untracked count, `D` = denominator.

---

## 1. Package map and dependency layers

| Layer | Module | Responsibility |
|---|---|---|
| L0 | `math/comb.py` | `binom`, `transitions` |
| L0 | `math/intervals.py` | Wilson score interval |
| L1 | `model/selectors.py` | Selector AST and `matches` |
| L1 | `model/conditions.py` | Condition AST, `Query`, builder DSL |
| L1 | `model/deck.py` | `Card`, `Deck`, `Category` |
| L1 | `model/game.py` | `GameConfig` |
| L1 | `model/mulligan.py` | `PriorityGroup`, `MulliganConfig` |
| L1 | `model/scenario.py` | `Scenario`, presets |
| L1 | `model/results.py` | Result value types |
| L1 | `model/serialization.py` | Generic `to_dict` / `from_dict` |
| L2 | `compile/atomizer.py` | `AtomTable`, `atomize` |
| L2 | `compile/schedule.py` | `BatchPlan`, `plan` |
| L2 | `compile/logic.py` | `Leaf`, opcodes, `run2`, `run3`, `hall_feasible`, `eval_leaf`, `leaf_bits` |
| L2 | `compile/compiler.py` | `LeafSpec`, `CompiledQuery`, `compile_query`, `compile_predicate` |
| L2 | `compile/policy.py` | `ResolvedPolicy`, `lower_bounds`, `resolve_policy`, `bottom`, `MulliganPlan`, `build_plan` |
| L3 | `engine/base.py` | `InitialStates`, `RunResult`, `Engine` protocol |
| L3 | `engine/exact.py` | `ExactEngine` |
| L3 | `engine/select.py` | `native_module`, `native_available`, `default_engine` |
| L3 | `engine/native.py` | `NativeEngine` (adapter for the Rust extension), `supported`, `plan_supported`, `_flatten`, `_flatten_plan` |
| L3 | `engine/mulligan.py` | Reference mulligan enumeration: `hands`, `mulligan_depths`, `hand_values` |
| L3 | `engine/montecarlo.py` | `simulate` |
| L4 | `analysis/prepare.py` | `Prepared`, `prepare` (scenario + outputs → compiled form, keep bit) |
| L4 | `analysis/evaluation.py` | `exact_values`, `montecarlo_counts`, `evaluate` (method dispatch, auto fallback) |
| L4 | `analysis/stats.py` | Distributions and tables |
| L4 | `analysis/mulligan.py` | `run_mulligan`, mulligan report, optimal keep |
| L4 | `analysis/optimizer.py` | Optimizer |
| side | `io/decklist.py`, `io/expr.py` | Parsers and printers |
| L5 | `api.py` | Facade |
| — | `errors.py` | Exception hierarchy |

---

## 2. L0: Math

### 2.1 `math/comb.py`

```python
def binom(n: int, k: int) -> int
    # 0 if k < 0 or k > n or n < 0; otherwise math.comb(n, k). Cached.

def transitions(rem: tuple[int, ...], pool_rem: int, b: int) -> tuple[tuple[tuple[int, ...], int], ...]
    # All (d, coef) with 0 <= d[i] <= rem[i], 0 <= b - sum(d) <= pool_rem,
    # coef = prod(binom(rem[i], d[i])) * binom(pool_rem, b - sum(d)) > 0.
    # Lexicographic order. lru_cache(maxsize=2**16).
    # Post: sum(coef) == binom(sum(rem) + pool_rem, b)   (Chu–Vandermonde, MATH §4)
```

The same function enumerates opening hands: `transitions(K, pool, hand_size)` yields every hand composition with its numerator.

### 2.2 `math/intervals.py`

```python
def wilson(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]
    # MATH §11. Pre: 0 <= successes <= trials, trials > 0.
```

---

## 3. L1: Model

### 3.1 Selectors (`model/selectors.py`)

```python
Tag(name: str)                      # name normalized: strip + casefold; non-empty
CardName(name: str)                 # exact (whitespace-normalized) card name
AnyOf(items: tuple[Selector, ...])  # len >= 1
AllOf(items: tuple[Selector, ...])  # len >= 1
NoneOf(items: tuple[Selector, ...]) # len >= 1; complement of union
Everything()

def matches(sel: Selector, card: Card) -> bool
def tag(name) / card(name) / any_of(*s) / all_of(*s) / none_of(*s) / everything()   # builders
```

Cards are matched by name with `casefold()`, so `card("sol ring")` matches "Sol Ring".

### 3.2 Conditions (`model/conditions.py`)

```python
Op = Literal["==", "!=", "<", "<=", ">", ">="]
Compare(sel: Selector, op: Op, value: int)          # value >= 0
Between(sel: Selector, lo: int, hi: int)            # 0 <= lo <= hi
And(items: tuple[Condition, ...])                   # len >= 2
Or(items: tuple[Condition, ...])                    # len >= 2
Xor(a: Condition, b: Condition)
Not(item: Condition)
Implies(a: Condition, b: Condition)
AtLeast(n: int, items: tuple[Condition, ...])       # 0 <= n, len >= 1
Exactly(n: int, items: tuple[Condition, ...])
Demand(sel: Selector, need: int)                    # need >= 1
Assignable(demands: tuple[Demand, ...])             # len >= 1; distinct-card feasibility
At(turn: int, item: Condition)                      # turn >= 0
Const(value: bool)

Query(condition: Condition, given: Condition | None = None, turn: int = 0)
```

**Builder DSL:** `count(sel)` returns a `Count` with `>=, >, <=, <` operators and `.eq(v)`, `.ne(v)`, `.between(lo, hi)`. Conditions overload `&` (And), `|` (Or), `^` (Xor), `~` (Not), `.implies(other)`, and `.at(turn)`. Chained `&` and `|` flatten into n-ary nodes.

**Binding semantics:** the innermost `At` determines a leaf's checkpoint. Unbound leaves use `Query.turn`.

### 3.3 Deck (`model/deck.py`)

```python
Zone = Literal["library", "commander", "sideboard", "maybeboard"]
Card(name: str, quantity: int = 1, tags: frozenset[str] = frozenset(), zone: Zone = "library")
Deck(cards: tuple[Card, ...], name: str | None = None)
    size: int                      # sum of library quantities (> 0)
    library: tuple[Card, ...]
    tag_counts() -> dict[str, int]
    with_tags(card: str, add=(), remove=()) -> Deck
    rename_tag(old: str, new: str) -> Deck
    @staticmethod from_counts(deck_size: int, categories: Mapping[str, int | Category]) -> Deck
Category(count: int, tags: frozenset[str] = frozenset())
```

`from_counts` creates one card per category. Its name is the category name, and its tags are `{category name} ∪ tags`. A filler card `"(other)"` with the tag `"(other)"` takes the remainder.

Validation:
- duplicate (casefolded) names within the same zone
- quantity < 1
- library size 0
- `Σ categories > deck_size`

### 3.4 Game (`model/game.py`)

```python
GameConfig(hand_size: int = 7, on_play: bool = True, draws_per_turn: int = 1,
           draw_overrides: tuple[tuple[int, int], ...] = (),   # turn -> draws (replaces)
           extra_draws: tuple[tuple[int, int], ...] = ())      # turn -> additional draws
    draws_on_turn(t) -> int     # t == 0 -> 0; override if present; else draws_per_turn,
                                # except 0 for t == 1 and on_play; then + extra
    draws_through(t) -> int     # sum over 1..t
```

The constructor accepts dicts (typed `TurnMapInput = TurnMap | Mapping[int, int]`) and normalizes them to sorted tuples. Turn keys must be ≥ 1 and values ≥ 0.

### 3.5 Mulligan (`model/mulligan.py`)

```python
PriorityGroup(selector: Selector, quota: int | None = None, name: str | None = None)
MulliganConfig(priority: tuple[PriorityGroup, ...],    # user order = priority (ADR-0005); len >= 1
               keep_rule: Condition = KEEP_ANY,        # Const(True); evaluated on the kept hand, turn 0 only
               max_mulligans: int = 2,                 # M >= 0
               free_mulligans: int = 0,                # F in {0, 1}
               draw_size: int = 7)
    bottom_count(m) -> int = max(0, m - free_mulligans)   # validated: bottom_count(M) <= draw_size
    hand_size(m) -> int = draw_size - bottom_count(m)
```

Priority-group selectors must be distinct. A keep rule containing `At(t, ·)` with t ≠ 0 is rejected.

### 3.6 Scenario (`model/scenario.py`)

```python
Scenario(deck: Deck, game: GameConfig = GameConfig(), mulligan: MulliganConfig | None = None)
PRESETS: dict[str, Preset]    # "limited" (40), "constructed" (60), "commander" (99 + commander, F = 1)
```

### 3.7 Results (`model/results.py`)

```python
Probability(exact: Fraction | None, estimate: float | None = None, ci95: tuple[float, float] | None = None,
            method: Literal["exact", "montecarlo"] = "exact", warnings: tuple[str, ...] = ())
    value -> float                 # float(exact) if exact else estimate
ConditionalResult(joint: Probability, given: Probability, result: Probability | None)
    defined -> bool
Distribution(turn: int, pmf: tuple[Fraction, ...])
    exactly(k), at_least(k), at_most(k), none(), cdf(), sf(), mean, variance
ThresholdRow(turn, k, exactly, at_least, at_most)      # Fractions
ThresholdTable(rows)
TurnRow(turn, cards_seen, probability: Fraction)
TurnTable(rows)
MulliganRow(depth, hand_size, p_reach, p_keep_given_reach, p_success_forced, p_success_and_keep_given_reach)
MulliganReport(rows, p_success, expected_mulligans, expected_hand_size)
KeptHand(atom_counts: tuple[int, ...], probability: Fraction, success: Fraction, keep: bool)
OptimalKeepRow(depth, hand_size, continuation_value: Fraction, p_keep_given_reach: Fraction, hands: tuple[KeptHand, ...])
OptimalKeepReport(value: Fraction, rows, atoms: tuple[tuple[str, ...], ...])   # atom -> card names
OptimizeResult(counts: tuple[tuple[str, int], ...], probability: Fraction, proven_optimal: bool,
               evaluations: int, frontier: tuple[tuple[tuple[tuple[str, int], ...], Fraction], ...])
```

### 3.8 Serialization (`model/serialization.py`)

- `to_dict(obj)` handles each value type as follows:
  - Dataclasses become `{"type": ClassName, field: …}`.
  - `Fraction` becomes `{"type": "Fraction", "value": "n/d"}`.
  - `frozenset` becomes `{"type": "frozenset", "items": sorted list}`.
  - Tuples become lists.
  - Primitives are unchanged.
- `from_dict` is the inverse, using a registry of public types. Lists decode to tuples.
- Postcondition: `from_dict(json.loads(json.dumps(to_dict(x)))) == x`.

---

## 4. L2: Compilation

### 4.1 Atomizer (`compile/atomizer.py`)

```python
AtomTable(deck_size: int, selectors: tuple[Selector, ...], signatures: tuple[tuple[bool, ...], ...],
          counts: tuple[int, ...], names: tuple[tuple[str, ...], ...], pool: int)
    mask(sel) -> tuple[int, ...]       # atom indices i with signatures[i][selectors.index(sel)]
    size -> int                         # number of tracked atoms

def atomize(deck: Deck, selectors: Iterable[Selector]) -> AtomTable
```

Algorithm (MATH §6):

```text
sels ← unique(selectors) in first-seen order
groups ← {}                                  # signature → (count, names)
for card in deck.library:
    σ ← tuple(matches(s, card) for s in sels)
    groups[σ] += card.quantity
pool ← groups.pop(all-False, 0)              # cards that no referenced selector matches
atoms ← sorted(groups) by signature, descending (deterministic order)
```

Complement selectors (`NoneOf`, `Everything`) need no special case. They are evaluated per card, so the cards they match get a `True` bit and become tracked atoms. Unknown `CardName` (no matching card) raises `ValidationError`.

### 4.2 Schedule (`compile/schedule.py`)

```python
BatchPlan(checkpoints: tuple[int, ...], batches: tuple[int, ...], hand_size: int)
    # checkpoints sorted unique and include 0; batches[0] == 0;
    # batches[j] = draws_through(cp[j]) - draws_through(cp[j-1])
def plan(game: GameConfig, turns: Iterable[int], hand_size: int) -> BatchPlan
    cards_seen(j) = hand_size + draws_through(checkpoints[j])
```

### 4.3 Logic (`compile/logic.py`)

Opcodes (ints): `BIT i`, `CONST b`, `NOT`, `AND n`, `OR n`, `XOR`, `IMPLIES`, `ATLEAST k n`, `EXACTLY k n`. A program is a flat `tuple[int, ...]`: each opcode followed by its operands, in postfix order.

```python
def run2(prog, bits: int) -> bool
def run3(prog, bits: int, known: int) -> bool | None   # Kleene strong logic (MATH §7.3)
def hall_feasible(demands: tuple[tuple[tuple[int, ...], int], ...], seen: tuple[int, ...]) -> bool
def eval_leaf(leaf, seen) -> bool
```

`run3` truth tables (U = unknown):
- AND: F if any operand is F; T if all are T; else U. OR is the dual.
- NOT U = U.
- XOR: U if either operand is U.
- IMPLIES a b: T if a = F or b = T; F if a = T and b = F; else U.
- ATLEAST k: T if #T ≥ k; F if #T + #U < k; else U.
- EXACTLY k: F if #T > k or #T + #U < k; T if #U = 0 and #T = k; else U.

`hall_feasible` checks every non-empty subset S of demands (MATH §8): Σ need over S ≤ Σ seen over the union of the masks. Memoized on (demands, seen).

### 4.4 Compiler (`compile/compiler.py`)

`Leaf` lives in `compile/logic.py` (the engines evaluate it). The compiler builds `LeafSpec`
values first: a leaf without a bit, used as the deduplication key.

```python
LeafSpec(turn, kind, mask=(), op="", value=0, lo=0, hi=0, demands=())  ->  .to_leaf(bit, checkpoint)
Leaf(bit: int, checkpoint: int, kind: Literal["cmp", "between", "assign"],
     mask: tuple[int, ...] = (), op: str = "", value: int = 0, lo: int = 0, hi: int = 0,
     demands: tuple[tuple[tuple[int, ...], int], ...] = ())
CompiledQuery(atoms: AtomTable, plan: BatchPlan, leaves: tuple[Leaf, ...],
              outputs: tuple[tuple[str, tuple[int, ...]], ...],
              observers: tuple[tuple[int, tuple[int, ...]], ...],      # (checkpoint idx, mask)
              retire_after: tuple[tuple[int, ...], ...],               # per checkpoint idx
              reserved_bits: int)

def compile_query(deck, game, outputs: Mapping[str, Condition], *, turn: int = 0,
                  observe: Sequence[tuple[int, Selector]] = (), extra_selectors: Sequence[Selector] = (),
                  hand_size: int, reserved_bits: int = 0, max_draw_region: int | None = None) -> CompiledQuery
def compile_predicate(cond: Condition, atoms: AtomTable) -> tuple[tuple[Leaf, ...], tuple[int, ...]]
```

`compile_query` algorithm:

1. **Collect** every selector from the outputs, observers, and `extra_selectors` (keep rule and priority groups). Run `atomize`.
2. **Collect checkpoints** with a binding-aware walk (`At` overrides). Include `turn` and the observer turns. Run `plan`.
3. **Pass 1 (leaf discovery):** walk each output and key each leaf by `(turn, kind, mask, op, value, lo, hi, demands)`. Identical keys share one leaf.
4. **Bit assignment:** sort the unique leaves by (checkpoint index, discovery order). Bits start at `reserved_bits`, so all bits of checkpoint j are numbered before those of checkpoint j + 1.
5. **Pass 2 (emit):** generate the postfix program for each output.
6. **Retirement:** `retire_after[j]` = atoms that appear in no leaf mask, demand mask, or observer mask at any checkpoint index > j.
7. **Validation:** `hand_size + draws_through(last) ≤ (max_draw_region or N)`. The mulligan analysis passes `max_draw_region = N` and checks `draw_size + draws ≤ N` itself (FR-42).

`compile_predicate` compiles a keep rule on an existing atom table. All its leaves sit at checkpoint 0, and its bits start at 0 in a private namespace. It is used by the mulligan analysis and the Monte Carlo simulator to evaluate the keep rule directly on a kept-hand vector.

### 4.5 Bottom policy (`compile/policy.py`, FR-43, ADR-0005)

```python
ResolvedPolicy(rules: tuple[tuple[tuple[int, ...], int], ...])   # (mask, quota), high → low priority
def lower_bounds(conditions: Sequence[Condition]) -> dict[Selector, int]
def resolve_policy(cfg: MulliganConfig, success: Sequence[Condition], atoms: AtomTable) -> ResolvedPolicy
def bottom(policy: ResolvedPolicy, hand: tuple[int, ...], pool_in_hand: int, n: int) -> tuple[int, ...]
MulliganPlan(policy, keep_leaves, keep_prog, bottoms: tuple[int, ...], draw: int)
    max_mulligans -> int;  keeps(kept: tuple[int, ...]) -> bool
def build_plan(cfg: MulliganConfig, success: Sequence[Condition], atoms: AtomTable) -> MulliganPlan
```

`MulliganPlan` lives in L2 (not L4) because both the exact analysis (L4) and the Monte
Carlo simulator (L3) consume it, and the layering contract forbids L3 → L4 imports.

**Quota resolution:** an explicit `quota` is used as given. Otherwise, take the maximum positive-polarity lower bound on a structurally equal selector, found in the keep rule and then the success conditions:
- `>= v` → v
- `> v` → v + 1
- `== v` → v
- `Between lo..hi` → lo
- `Demand need` → need

If no bound is found, use `draw_size` ("keep all").

**Evaluation** (deterministic, memoized):

```text
protected ← 0-vector; log ← []
for r, (mask, quota) in enumerate(rules):                          # high → low
    need ← quota − Σ protected[mask]                                # already-protected cards count
    for i in mask ordered by (−#rules containing i, i):            # multi-role cards first
        take ← min(need, hand[i] − protected[i]); protect; log (r, i, take)
bott ← 0-vector; left ← n
left −= min(left, pool_in_hand)                                     # 1. cards in no group
for i ordered by (lowest priority first: −min rule index containing i, then i):
    take ← min(left, hand[i] − protected[i] − bott[i])             # 2. unprotected group cards
for (r, i, take) in reversed(log):                                  # 3. release protections, lowest priority first
    x ← min(left, take); bott[i] += x; left −= x
post: Σ bott + pool part == n; bott ≤ hand
```

Atoms that match no priority group, such as atoms that exist only because the success condition references them, count as "in no group". They are bottomed in step 2 before any group card, because their minimum rule index is ∞.

---

## 5. L3: Engines

### 5.1 Interfaces (`engine/base.py`)

```python
State = tuple[tuple[int, ...], tuple[int, ...], int]           # (seen, bottomed, bits)
InitialStates(states: Mapping[State, int], denominator: int, removed: int)
RunResult(outputs: Mapping[str, int], denominator: int,
          snapshots: Mapping[tuple[int, tuple[int, ...]], tuple[tuple[int, ...], int]],
          peak_states: int)
class Engine(Protocol):
    def run(self, cq: CompiledQuery, init: InitialStates | None = None, *, limit: int = ...) -> RunResult
```

### 5.2 Exact engine (`engine/exact.py`, MATH §5)

`ExactEngine(early_resolution: bool = True, retirement: bool = True)`. The flags exist only for equivalence testing.

```text
K ← atoms.counts; pool ← atoms.pool; N ← deck_size
if init is None:
    dist ← {(x, 0⃗, 0): c for (x, c) in transitions(K, pool, hand)}; D ← C(N, hand); removed ← hand
removed_j ← removed before each batch; FD[j] ← Π_{j' > j} C(N − removed_{j'−1}, b_{j'})
resolved ← {name: 0}
for j in checkpoints:
    if j > 0 and b_j > 0:
        new ← {}
        for (s, t, bits), w in dist:
            rem ← K − s − t ; prem ← pool − (removed − Σs − Σt)
            for d, c in transitions(rem, prem, b_j): new[(s + d, t, bits)] += w·c
        dist ← new; D ×= C(N − removed, b_j); removed += b_j
        if |dist| > limit: raise StateSpaceTooLargeError
    leaves_j → set bits (merge equal keys)
    snapshots for observers at j: (marginal numerators over Σ s[mask], D)
    if early_resolution and outputs and no observer at index > j:
        known ← bits < (reserved + #leaves at ≤ j) all set
        for state: if every output's run3 is decided → add w·FD[j] to true outputs; drop state
    if retirement: for i in retire_after[j]:
        pool += K[i]; K[i] ← 0; zero s[i], t[i] in every key (merge)
for state: for output: if run2 → resolved[name] += w
return RunResult(resolved, D, snapshots, peak)
```

**Retirement by zeroing:** a retired atom's count moves into the pool, and its entries are set to 0 in every key. Indices never shift, so leaf masks stay valid. The pool-remaining formula `pool − (removed − Σs − Σt)` stays correct because the zeroed cards are now counted as pool cards already removed.

**Single-group fast path:** `hypergeom(N, K, n)` builds the PMF directly from binomials, without the state machine. The general path must agree with it (TP §7).

### 5.3 State limit (NFR-06)

Both engines count live states after building the initial distribution and after every batch. If the count exceeds `limit`, they raise `StateSpaceTooLargeError(states, limit)`. A refused query therefore costs at most `limit` states of work. Earlier versions also used an up-front estimate, but it was so loose (it multiplied in 2^#leaves) that ordinary multi-turn queries were wrongly sent to Monte Carlo, so it was removed in 0.3.0.

### 5.4 Monte Carlo (`engine/montecarlo.py`)

```python
def simulate(cq: CompiledQuery, *, trials: int, seed: int | None,
             mulligan: MulliganPlan | None = None) -> tuple[dict[str, int], int]
```

The library is a list of atom indices (pool = −1). Per trial:
1. For each mulligan depth: shuffle the full list with `random.Random(seed)`, take the first `draw` cards, apply `bottom` and the keep program, and stop at the first keep or at depth M. Without a mulligan, shuffle once and take `hand` cards.
2. Walk the checkpoints, adding batch cards from the cursor onward, evaluating leaves into bits, and finally running each output with `run2`.

The simulator shares only the compiled leaves, programs, and policy with the exact path. It shares none of the DP code (enumeration, merging, retirement, resolution, denominators).

---

### 5.5 Native engine (`native/`, `engine/native.py`, `engine/select.py`, ADR-0009, ADR-0011)

The native engine lives in the Rust workspace `native/` (ADR-0013 §1): the engine modules are in `mtgcalc-core` (`native/core`), and the PyO3 module `mtgcalc_native` is the crate `mtgcalc-native` (`native/python`, built with maturin, type stubs in `mtgcalc_native.pyi`). It is a port of §5.2 and §5.6. `native/README.md` describes the modules.

**Exactness:** weights are generic over `trait Weight`. Each call runs first as `u128` with checked arithmetic; on any overflow, `api::*` repeats it with `BigUint`.

**Validation at the boundary:**
- `Query::validate` checks that counts and the pool add up to N, that indexes are in range, that there are at most 64 bits, and that draws fit the deck.
- `Leaf::new` / `Program::new` check opcodes, operands, stack discipline and bit ranges.
- `Policy::new` / `MulliganPlan::validate` check masks and bottom counts.
- Malformed input → `Error::Invalid` → Python `ValueError`.
- More than `limit` live states → `Error::Limit` → `StateLimitExceeded` → `StateSpaceTooLargeError`.

**DP structure:** `engine::dp` drives a `Run` struct with one method per phase: `draw`, `evaluate_leaves`, `observe`, `resolve_early`, `retire`, `finish`. Transitions come from `DrawEnumerator` and are cached per (remaining vector, pool) within a batch.

**Python interface** (the GIL is released during each call):

| Function | Returns |
|---|---|
| `run(query, init, options)` | `(outputs, denominator, snapshots, peak)` |
| `mulligan(query, plan, options)` | Per depth: `(keep_weight, hands_total, outputs, denominator)` |
| `hand_values(query, plan, output, options)` | Per depth, per hand: `(hand, weight, success, denominator)` |

Arguments:
- `query` is `_flatten(cq)`;
- `plan` is `_flatten_plan(plan)` = `(rules, keep_leaves, keep_prog, bottoms, draw)`;
- `options` is `(limit, early_resolution, retirement)`.

**Adapter:** `NativeEngine` implements `run`, `mulligan` and `hand_values`. For shapes beyond its limits (more than 64 bits or more than 32 atoms) it delegates to the Python reference.

**Rust quality gates:**
- `cargo fmt --check`;
- `cargo clippy -- -D warnings`, with `clippy::pedantic` on, for every crate (the core with and without `json`, the PyO3 crate, the WebAssembly crate on its target);
- `cargo test`: the engine's 22 unit tests mirroring the Python reference cases (A1, A3, A4, bottom order, Hall, Kleene soundness, overflow fallback, validation), plus the ported modules' tests (§11.1);
- `cargo doc` with `missing_docs`;
- `unsafe_code = "forbid"`.

**Conformance:** `tests/engine/test_native_conformance.py` requires identical results from `run` (outputs, denominators, snapshots), `mulligan` and `hand_values`, for every combination of optimization switches.

### 5.6 Mulligan enumeration (`engine/mulligan.py`, `Engine.mulligan`, `Engine.hand_values`)

```python
DepthResult(keep_weight, hands_total, outputs: Mapping[str, int], denominator)
HandValue(hand, weight, success, denominator)
def hands(cq, plan, depth) -> list[(drawn hand, bottomed, weight)]
def mulligan_depths(engine: Runner, cq, plan, *, limit) -> tuple[DepthResult, ...]
def hand_values(engine: Runner, cq, plan, output, *, limit) -> tuple[tuple[HandValue, ...], ...]
```

For each depth m:
1. Enumerate the drawn compositions with `transitions(K, pool, draw)`.
2. Apply `bottom(...)` and the keep rule.
3. Seed `(kept, bottomed, keep bit)` states with denominator C(N, draw) and `removed = draw`, then run the DP.

`hand_values` runs the DP from each distinct `(kept, bottomed)` pair, with weight 1 and denominator 1, memoized across depths. `KEEP_BIT` (= 0) lives in `compile/policy.py` so that both the engine and analysis layers can use it.

## 6. L4: Analyses

### 6.1 Statistics (`analysis/stats.py`)

| Function | Algorithm |
|---|---|
| `distribution(scenario, sel, turn)` | Compile with no outputs and observer `(turn, sel)`. Snapshot numerators / D → PMF. Under a mulligan, evaluate outputs `count(sel) == k` for k = 0..n through `run_mulligan`, so the strategy-level combination is reused unchanged. |
| `threshold_table(scenario, sel, turns, ks)` | One run with observers at all turns. Rows for each (turn, k). |
| `turn_table(scenario, cond, turns)` | Outputs `t{T}` = `At(T, cond)`, one run (or one mulligan evaluation with several outputs). |

`Distribution.mean = Σ k·p_k` and `variance = Σ k²·p_k − mean²`, both exact.

### 6.2 Mulligan analysis (`analysis/mulligan.py`, MATH §9)

```python
Prepared(cq: CompiledQuery, plan: MulliganPlan | None, names: tuple[str, ...])          # analysis/prepare.py
def prepare(scenario, outputs: Mapping[str, Condition], *, turn=0, observe=()) -> Prepared
DepthOutcome(depth, hand_size, p_keep, forced: Mapping[str, Fraction], with_keep: Mapping[str, Fraction])
MulliganOutcome(depths, reach, strategy: Mapping[str, Fraction])
def run_mulligan(prep: Prepared, *, engine=None, limit) -> MulliganOutcome
def mulligan_report(scenario, success, *, turn=0, engine=None, limit) -> MulliganReport
def optimal_keep(scenario, success, *, turn=0, engine=None, limit) -> OptimalKeepReport
```

`run_mulligan` calls `engine.mulligan(cq, plan)` (§5.6) and only does the Fraction arithmetic. What each depth's enumeration computes:

```text
KEEP ← bit 0 (reserved_bits = 1)
cq ← compile_query(outputs ∪ {o+"&keep": o ∧ KEEP}, reserved_bits = 1, extra = keep rule + priority selectors)
for (h, c) in transitions(K, pool, draw):
    b ← bottom(policy, h, draw − Σh, bottoms[m]); kept ← h − b
    keep ← (m == M) or run2(keep_prog, leaf bits of kept)
    init[(kept, b, KEEP if keep else 0)] += c;   keep_w += c if keep
res ← engine.run(cq, InitialStates(init, C(N, draw), draw))
row m: p_keep = keep_w / C(N, draw); forced[o] = res[o]/D; with_keep[o] = res[o+"&keep"]/D
combine: reach_0 = 1; reach_{m+1} = reach_m·(1 − p_keep_m); P[o] = Σ reach_m · with_keep_m[o]
```

The `"&keep"` outputs are built by appending `BIT 0, AND 2` to the output's postfix program. Each output gets the strategy-level probability, so conditional queries and turn tables under a mulligan reuse this routine.

**Optimal keep (FR-48):** `engine.hand_values(cq, plan, "success")` (§5.6) gives `s_m(h)` for each depth and composition h, memoized by `(kept, b)`. Then:

```text
V_{M+1} ← −∞;  for m = M … 0: V_m = Σ_h P(h)·max(s_m(h), V_{m+1})   (keep all at M)
keep at m iff s_m(h) ≥ V_{m+1}
```

The report lists, per depth, every composition with its P, its s, and whether it is kept. Invariant (TP): `V_0 ≥ mulligan_report(any keep rule).p_success`.

### 6.3 Optimizer (`analysis/optimizer.py`, MATH §10)

```python
Variable(name: str, lo: int, hi: int, tags: frozenset[str] = frozenset())
OptimizeProblem(deck_size: int, variables: tuple[Variable, ...], query: Query,
                fixed: tuple[tuple[str, Category], ...] = (), game: GameConfig = GameConfig(),
                mulligan: MulliganConfig | None = None,
                objective: Literal["min_count", "max_probability", "min_total"] = "max_probability",  # + workers: int | None = None
                target: Fraction | None = None, budget: int | None = None,
                exhaustive_limit: int = 5000, assume_monotone: bool | None = None)
def optimize(problem, evaluate=None) -> OptimizeResult
```

- **Evaluator:** builds `Deck.from_counts(N, fixed ∪ variables)` and calls the facade. Results are memoized by the count vector.
- **`is_monotone(problem, var)`:** a polarity walk over the query. Every leaf whose selector matches the variable's card must be `>=`, `>`, or a `Demand`, under positive polarity only. No leaf may match the filler card. The query must have no `given` and no mulligan. `assume_monotone` overrides the result.
- **Search space:**
  - `_points(vs, cap, total)` enumerates points with lo ≤ x ≤ hi and Σ ≤ cap (or Σ = total), pruning branches that cannot reach the bound.
  - `count_points` counts the same points exactly by DP over the sum, to decide between exhaustive and heuristic search without enumerating.
- **Evaluator:** `MemoEvaluator(fn, workers)` memoizes by point and is a context manager that owns one thread pool per optimization.
  - It times every evaluation, and `.many(points)` only goes parallel when the average evaluation takes at least `PARALLEL_MIN_SECONDS` (2 ms). Below that, the thread hand-off costs more than it saves; measured with the native engine, where small evaluations take about 0.3 ms.
  - The first evaluation always runs serially, to get a measurement.
  - `.batch` (`workers` when parallel, else 1) sizes the early-stopping scan in `min_count`.
  - `workers` defaults to the CPU count when the native engine is active (it releases the GIL), and to 1 otherwise or when an evaluator is injected.
- **Strategies:**
  - **`min_count`** (exactly one variable):
    - If monotone: binary search, after checking that `f(hi) ≥ target` (otherwise `InfeasibleError`).
    - Otherwise: a scan in chunks of `workers`, stopping at the first count that meets the target.
    - Always proven.
  - **`_best_on(total)`:** the best point on the slice (or on Σ ≤ cap when `total` is None). Exhaustive if `count_points ≤ exhaustive_limit` (proven); otherwise local search (heuristic).
  - **`max_probability`:** if every variable is monotone, `_best_on(min(cap, Σhi))` (MATH §10.4, Lemma 10.1); otherwise `_best_on(None)`.
  - **`min_total`:** if every variable is monotone, binary search over T using `_best_on(T)` (Lemma 10.2); otherwise increasing T. Proven only if every slice search was exhaustive.
  - **Local search:**
    - Greedy: repeatedly add the most valuable single copy, evaluated as one batch.
    - Then best-improvement moves of one card from variable j to variable i, until no move improves.
- **Ranking:** higher P first, then fewer cards, then smaller counts.

---

## 7. IO

### 7.1 Decklist (`io/decklist.py`)

```python
class DeckImporter(Protocol):
    def parse(self, text: str) -> Deck: ...
def parse_decklist(text: str, fmt: Literal["auto", "plain", "moxfield", "archidekt"] = "auto") -> Deck
```

Line grammar and normalization:

- **Quantity:** `^\s*(\d+)x?\s+`
- **Tags:**
  - Archidekt `[A,B{top}]` groups: `{…}` markers are stripped, and the categories `commander`, `sideboard`, and `maybeboard` set the zone.
  - Moxfield `#tag` / `#!tag` tokens.
  - `^…^` colour tags are stripped.
- **Ignored:** set suffix `(SET) 123[a-z]?` and foil markers `*F*` / `*E*`.
- **Section headers:** `commander`, `deck`, `mainboard`, `sideboard`, `maybeboard`, `companion`, optionally preceded by `//` and followed by `:`.
- **Skipped:** blank lines and `//` comments.
- **Merging:** duplicates within a zone are merged (quantities summed, tags unioned).
- **Errors:** `ParseError(line, col)`. Input over 1 MB is rejected (NFR-14).

### 7.2 Condition text (`io/expr.py`, FR-37)

```ebnf
query      = expr [ "GIVEN" expr ] ;
expr       = implies ;
implies    = or_expr [ ("->" | "IMPLIES") implies ] ;
or_expr    = xor_expr { "OR" xor_expr } ;
xor_expr   = and_expr { "XOR" and_expr } ;          (* left-assoc, binary nodes *)
and_expr   = unary { "AND" unary } ;
unary      = "NOT" unary | postfix ;
postfix    = primary [ "@" TURN ] ;                 (* TURN = "T" INT | "turn" INT | INT *)
primary    = "(" expr ")" | "true" | "false" | func | comparison ;
func       = ("atleast" | "exactly") "(" INT { "," expr } ")"
           | "assign" "(" selector ">=" INT { "," selector ">=" INT } ")" ;
comparison = selector ( OP INT | "in" INT ".." INT ) ;
selector   = IDENT | "tag:" STRING | "card:" STRING
           | ("any" | "all" | "none") "(" selector { "," selector } ")" | "everything" ;
```

- Keywords are case-insensitive.
- `IDENT = [A-Za-z_][A-Za-z0-9_\-']*`. A tag that collides with a keyword, or isn't a valid IDENT, must be written as `tag:"…"`.
- Limits: 10 kB of input and nesting depth 64 (NFR-14).
- `format_condition` / `format_query` print canonical text. A child is parenthesized when its precedence is ≤ its parent's, which guarantees `parse(format(q)) == q`.
- Precedence, low to high: IMPLIES < OR < XOR < AND < NOT < postfix/primary.

---

### 7.3 Writing decklists (`io/decklist.py`, FR-66)

`format_decklist(deck) -> str` writes sections in the order Commander, Deck, Sideboard, Maybeboard. Each card is a line `N Name #tag ...`. `tag_token` hyphenates spaces and drops `#`. Tags are written `#`-style so that tag names such as "sideboard" are never read back as zones.

**Contract:** `parse_decklist(format_decklist(d))` equals `d`, up to hyphenation of tags (property-tested).

### 7.4 Deck import from links (`src/mtgcalc_online`, FR-65, ADR-0012)

| Module | Contract |
|---|---|
| `errors.DeckFetchError(MtgCalcError)` | The message is written for players; the original exception is chained as `__cause__`. |
| `http.get_json(url, *, timeout=15, max_bytes=5 MB)` | Sends `User-Agent: mtgcalc/<version> (deck import)` and `Accept: application/json`. Failures map to messages: 404 not found or private; 401/403 refused; 429 rate limited; 5xx site problem; other HTTP codes; unreachable or offline; oversized; non-JSON. Logs at DEBUG on the `mtgcalc_online` logger. |
| `archidekt` | `LINK` pattern (`archidekt.com/[api/]decks/<digits>`), `api_url(id)`, and `to_deck(json)`. The **first** category places a card: premier → commander zone; not `includedInDeck` → maybeboard; otherwise the library. All categories become tags. Rows with `deletedAt` are skipped. Repeated names in the same zone are merged. Malformed JSON → `DeckFetchError`. |
| `sources` | `Source(name, link, api_url, to_deck, help)`; `SOURCES = (Archidekt, Moxfield)`. `recognize(link) -> (Source, id)`. `fetch_deck(link, *, get=get_json) -> Deck`, where `get` can be injected for tests and debugging. Moxfield has `api_url=None` and `help` holds the export instructions. |

**GUI:**
- *Import* (`DeckPanel.import_button`, Enter in the link box) calls `App.import_link`.
- That runs `App.background(forms.import_deck, ...)`, which returns `ImportedDeck(text, summary)`.
- `DeckPanel.show_decklist(text)` fills the box and switches to decklist mode. The deck-size box is hidden in that mode.
- `App.background(work, done, *, button, busy, failed)` is the single worker-thread helper for questions and imports. Workers post closures to a UI-thread queue that `_poll` applies, so no worker ever touches Tk.

## 8. L5: Facade (`api.py`)

```python
def hypergeom(N: int, K: int, n: int) -> Distribution
def probability(scenario, query: Query | Condition | str, *, engine: Literal["exact", "montecarlo", "auto"] = "exact",
                limit: int = 2_000_000, trials: int = 200_000, seed: int | None = None) -> Probability | ConditionalResult
def distribution(scenario, selector, turn: int = 0) -> Distribution
def threshold_table(scenario, selector, turns, ks=None) -> ThresholdTable
def turn_table(scenario, condition, turns) -> TurnTable
def mulligan_report(scenario, success) -> MulliganReport
def optimal_keep(scenario, success) -> OptimalKeepReport
def optimize(problem) -> OptimizeResult
parse_condition = io.expr.parse_query;  format_condition = io.expr.format_query;  parse_decklist = io.decklist.parse_decklist
```

`engine="auto"` runs the exact engine. If that raises `StateSpaceTooLargeError`, it uses Monte Carlo instead and adds a warning.

---

## 8a. GUI (`src/mtgcalc_gui`, FR-80 – FR-86, ADR-0010)

### forms.py: the plain-language layer (no Tk)

| Item | Contract |
|---|---|
| `CardType(name, count, also)` | A named kind of card. `also` holds extra tags. The name itself is a tag (casefolded). |
| `DeckSetup(size, types, mode, decklist)`, `build_deck` | `mode="types"`: the card types become `Deck.from_counts`, and the remainder is filler. `mode="decklist"`: `parse_decklist`. Errors are worded for players. |
| `PlaySetup(go_first, draws_per_turn, extra_draws)` | Becomes a `GameConfig` (hand 7). Extra draws on the same turn add up. |
| `MulliganSetup(enabled, keep, protect, max_mulligans, free_first)` | Becomes a `MulliganConfig`. `keep` holds kinds of hand, each a tuple of `KeepRule(card_type, low, high)` lines (FR-105, ADR-0014); `()` means keep any hand, and the default is one kind, 2 to 5 land. `protect` holds `(type, keep up to)` in priority order. |
| `keep_condition(keep)`, `keep_rule_words` | Kinds → `Or` of kinds, each the `And` of its lines' `Between`s. A single line or single kind is not wrapped (so one line stays a plain `Between`); no kinds → `Const(True)`. A kind with no lines, or a line with low > high, is a `ValidationError`. Words: "keep a hand with 3 to 5 land, or with 2 land and 1 to 7 ramp" (an amount with low = high is one number). |
| `Requirement(kind, amount, card_type, turn)`, `Goal(requirements, combine, custom)` | Kinds: "at least" (`>=`), "at most" (`<=`), "exactly" (`==`), "none" (`== 0`). Each line is wrapped in `At(turn)`. `combine` gives `And` / `Or`. A non-empty `custom` (the typed rule) overrides the lines. |
| `goal_condition`, `goal_as_text`, `describe_goal` | Goal → condition / rule text / English. `with_turns=False` drops the per-line turns (used by the turn table). |
| `chances`, `draws`, `turn_by_turn`, `mulligan_advice`, `how_many` | One function per question. Each returns `ResultView(headline, details, headers, rows, legend)`. |
| `mulligan_advice` | Combines `mulligan_report` (your plan, plus the never-mulligan baseline = depth-0 forced keep) with `optimal_keep` (the best plan). Rows are `Your plan` and `Best possible plan`, with per-step rules and hands. |
| `how_many` | Builds an `OptimizeProblem`: the chosen types become `Variable`s, the other types are `fixed`, and the deck size comes from step 1. Modes: `need` → `min_count`, `split` → `max_probability` with budget = slots, `fewest` → `min_total`. `InfeasibleError` is reworded as advice. `need` also reports the count one below the answer. |
| `pct`, `in_words`, `turn_words` | Formatting helpers: "47.7%", "less than 0.001%", "about 5 games in 10", "by turn 3" / "in your opening hand". |
| `Settings(method, games, seed, fractions)` | The options behind the Settings dialog |

### help.py

`TIPS` (tooltips by key), `INTROS` (page intros), `GETTING_STARTED`, `WORDS`, `RULES`, and `EXAMPLES`. Each example is a full `(deck, play, mulligan, goal)` setup.

### app.py

| Part | Contents |
|---|---|
| Building blocks | `Tooltip`, `spin`, `choice` (its `postcommand` re-reads the card-type names live from step 1), `text_entry`, `RowList` (editable rows with a remove button), `toggle` |
| Step panels | `DeckPanel` (format buttons, size, types table or decklist with file loading), `PlayPanel` (go first, draws, extra draws, mulligan section) |
| `GoalBuilder` | `RowList` of `[kind][amount][type][turn]` lines, all/any, and "type my own rule" (pre-filled from the lines) |
| `QuestionPage` | Intro, inputs, an Answer button, headline, details, a `Treeview` whose label column auto-sizes, and a legend. Subclasses implement `build()` and `prepare()`; `prepare` reads the widgets on the UI thread and returns the work for the worker. |
| Pages | `ChancesPage` (with optional "only count games where"), `DrawsPage`, `TurnsPage`, `MulliganPage`, `HowManyPage` |
| `App` | Menu (Examples, Settings, Help); a scrollable left panel; the question notebook; the status line |

**Threading:**
- `App.run` builds the scenario and the work on the UI thread, then calls `gc.collect()` so Tk objects can only ever be freed on the UI thread.
- A daemon worker computes the answer and puts the `ResultView` (or the exception) on a queue.
- `_poll` drains the queue using `after(50)`.
- Errors appear in the status line, worded by `friendly()`.

## 9. Errors (`errors.py`)

```text
MtgCalcError
├── ValidationError(field, message)
├── ParseError(message, line, column)
├── StateSpaceTooLargeError(estimate, limit)
└── InfeasibleError(message)
```

---

## 11. Web app (ADR-0013)

### 11.1 Rust core, port stage 1 (`native/core/src`)

Each module ports the named Python module. Constructors validate exactly as Python's `__post_init__` does, with the same field paths and messages (`Error::Validation { field, message }`). After that, values are trusted.

| Module | Port of | Contract |
|---|---|---|
| `model::text` | `normalize_tag` | `normalize(s) = casefold(collapse_whitespace(s))`, using Python's whitespace set and full case folding. Tables are generated from Python's `unicodedata` by `tools/gen_unicode.py` and must be fresh (`--check`) |
| `model::selectors` | `model/selectors.py` | `Selector` is opaque, built by `tag`, `card`, `any_of`, `all_of`, `none_of`, `everything`. Equality is Python's: tags are normalized, card names only have whitespace collapsed |
| `model::deck` | `model/deck.py` | `Card::new(name, quantity: i64, tags, zone)`, `Deck::new(cards)`. Libraries above 65,535 cards are `Unsupported` (the engine counts in `u16`) |
| `model::game` | `model/game.py` | `GameConfig::new(...)`. `draws_through(t)` is computed in closed form (O(overrides)), equal to Python's turn-by-turn sum (unit test) |
| `model::conditions` | `model/conditions.py` | Condition constructors with Python's checks; `selectors()` in pre-order, `turns(default)` (the innermost `At` wins); `Query::new` |
| `compile::atomizer` | `compile/atomizer.py` | Distinct selectors in first-reference order. Signatures are sorted descending (Python's `sorted(..., reverse=True)`), and the all-false group is the pool |
| `compile::schedule` | `compile/schedule.py` | Checkpoints = turns ∪ {0}, `batches[j]` = draws between checkpoints |
| `compile::compiler` | `compile/compiler.py` | As LLD §4.4. The default turn is always a checkpoint. Leaves are deduplicated by (turn, test with masks), and bits are numbered by checkpoint, then discovery. Numbers above 65,535 are clamped to 65,536 (an equivalent comparison, since counts never exceed the library). More than 64 bits or 16 demands → `Unsupported` |
| `probability` | `api.probability` | Outputs `{"p"}` or `{"joint": And(c, given), "given"}`. Fractions are in lowest terms; P(c \| given) is `None` when P(given) = 0 |
| `json` | `model/serialization.py` | `probability(text) -> text` (§11.2). Never panics |
| `model::text` (stage 2) | Python's `str`/`re` | `split_lines` (`str.splitlines`), `strip`, `digit_value` (`\\d` + `int()`), `ignorecase_eq` (`(?i)`), `py_repr` (`repr`, for messages): all from generated tables |
| `compile::compiler` (stage 3) | `compile_query(observe=...)` | Observers: their selectors atomized after the outputs', their turns added as checkpoints, their atoms kept from retirement until read |
| `stats` | `analysis/stats.py` | `distributions(scenario, selector, turns)` from one run's observer snapshots; `turn_table(scenario, condition, turns)` as one run with outputs `At(t, condition)`; turns sorted, de-duplicated, non-negative, at most 200 |
| `model::mulligan` (stage 4) | `model/mulligan.py` | `PriorityGroup`, `MulliganConfig::new` with Python's checks in order; `bottom_count`, `hand_size` |
| `compile::policy` | `compile/policy.py` | `lower_bounds` (required bounds only), `build_plan` (explicit or derived quotas, keep rule via `compile_predicate`); bottoming runs in the engine's `policy` |
| `analysis` | `analysis/prepare.py`, `analysis/mulligan.py` | `prepare` (draw size as the hand, reserved keep bit, `output AND kept` companions); `run_mulligan` (law of total probability), `exact_values`, `mulligan_report`, `optimal_keep` (backward induction; keep iff success ≥ continuation) |
| `io::expr` | `io/expr.py` | Lexer with Python's alternatives in order; recursive descent with the same depth counting (max 64), messages and columns; numbers read as big integers and saturated to `i64` (no count or playable turn reaches it); printer = `format_query` |
| `optimizer` (stage 5) | `analysis/optimizer.py` | `Variable`/`Category`/`OptimizeProblem` with Python's checks in order (`validate`); `optimize` = Python's with one worker: the same candidate order, memo, bisection (`min_count`), exhaustive or bounded search, local search from the same start, first-maximum-wins ties, the same `evaluations` count and top-20 frontier; `InfeasibleError` messages identical |
| `io::decklist` | `io/decklist.py` | Each regex hand-written with Python's semantics (leftmost match, greedy `x?`/`!?` with backtracking, `$`-anchored set suffix), so no regex engine ships in the WebAssembly; `format_decklist` |

### 11.2 JSON boundary (`mtgcalc_core::json`, feature `json`)

```
request  = {"scenario": <to_dict(Scenario)>, "query": <to_dict(Query)>, "limit"?: int}
response = <to_dict(Probability)> | <to_dict(ConditionalResult)>
         | {"type": "Error", "kind": K, "field": str, "message": str}
K        = "validation" | "too_large" | "unsupported" | "malformed" | "internal"
```

- Data-transfer types use `serde` internally tagged enums with `deny_unknown_fields`. Missing fields take Python's dataclass defaults.
- Limits: requests up to 4 MiB, serde's nesting limit of 128, integers of 64 bits. A non-null `mulligan` is `unsupported` until port stage 4.
- Stage 5: `{"optimize": <to_dict(OptimizeProblem)>, "limit"?, "one_fewer"?: bool}` (nothing else) → `to_dict(OptimizeResult)`; an unreachable target is `{"kind": "infeasible", "message"}` with Python's message. `one_fewer` (one variable only) adds `"one_fewer": Fraction | null`: the chance with one card fewer than the answer (Python's `_one_fewer` in `mtgcalc_gui.forms`), `null` when the answer is already the lowest count tried.
- Stage 4: `scenario.mulligan` (or, with a decklist, `"mulligan"`) is a `to_dict(MulliganConfig)`; probabilities and tables are then strategy-level. Questions `MulliganReport`, `OptimalKeep` (Python's `to_dict`) and `MulliganAdvice` (both, `{"report", "best"}`) take a query (no `given`) or a rule.
- Stage 3: `"question": {"type": "Distributions", "selector", "turns"}` (no query) → `{"type": "Distributions", "items": [to_dict(Distribution)…]}`; `{"type": "TurnTable", "turns"}` with a query (no `given`) or a rule → `to_dict(TurnTable)`. No question means the probability.
- Stage 2: the deck may be `"decklist": text` (+ optional `"game"`) instead of `"scenario"`, and the question `"rule": text` (+ optional `"turn"`) instead of `"query"`; exactly one of each, else `malformed`. Parse errors are `{"kind": "parse", "line", "column", "message"}`. `parse_deck`, `parse_rule` and `format_rule` return `to_dict` JSON (frozensets sorted by `repr`, as Python).
- Exposed to Python as `mtgcalc_native.probability_json`, `parse_deck_json`, `parse_rule_json`, `format_rule_json` and `normalize_text` (for the conformance suite), and to the browser as `mtgcalc_wasm.probability`, `parse_deck`, `parse_rule`, `format_rule`.

### 11.3 TypeScript (`web/src`)

| Module | Contract |
|---|---|
| `forms/model.ts` | Raw form state (strings, as typed) and the checked `Setup` (mirrors `DeckSetup`, `PlaySetup`, `Goal`) |
| `forms/parse.ts` | `parseForm(form) → {ok, setup} \| {ok: false, issues: [{field, message}]}`. Every rule is a plain sentence naming the fix. The deck needs ≥ 7 cards (an opening hand); a goal turn must be ≤ the last turn the deck has cards for |
| `forms/request.ts` | `buildRequest(setup)` builds JSON equal to Python's `to_dict(build_scenario(...))` and `to_dict(Query(goal_condition(goal)))`, including the frozenset order (sorted by `repr`) |
| `forms/words.ts` | `pct`, `inWords`, `describeGoal`, `headline`: ports of the Python functions, computed exactly with `BigInt` (ties to even). Exact 0 is "never", exact 1 is "every game" |
| `forms/text.ts` | `readDecklist(core, text)` / `readRule(core, text)`: what the core read, or a plain message per known parse error ("Line 2: start the line with how many copies…", "At character 8: a number should come here…"); `ruleText` writes lines as a rule |
| `engine/core.ts` | `loadCore()`: a second core instance on the page, for synchronous parsing while typing; calculations stay in the worker. `main.tsx` renders once it is ready |
| Questions (stage 3) | `FormState.question` (`chances`/`draws`/`turns`), `drawsType`, `lastTurn`; `buildRequest` sends a `Distributions` or `TurnTable` question ("Turn by turn" uses the lines without their turns, as `goal_condition(with_turns=False)`); `readReply` builds `draws`/`turns` views (exact averages and tails with BigInt); `AnswerDetails` shows the tables in focusable, labelled scroll regions |
| Kinds of hand to keep (FR-105) | `FormState.keep`: `KeepGroupRow{id, rules: KeepRuleRow{id, cardType, min, max}[]}[]`; none means "always keep". Actions `keepRuleAdded` (an "and also" line: the first card type the kind does not count yet, 1 to 7), `keepGroupAdded` (an "or" kind: 2 to 5 of the first card type), `keepRuleChanged`, `keepRuleRemoved` (a kind left without lines goes too). Problems are per line (`keep:<id>:cardType`, `keep:<id>:range`). `buildRequest` writes Python's `keep_condition` JSON; `keepRuleWords` is Python's `keep_rule_words`. Saved forms with one keep rule (`keepType`/`keepMin`/`keepMax`) become one kind, or none for "keep any hand"; a saved kind with no lines is rejected |
| "How many should I play?" (stage 5) | `FormState.hmMode` (`one`/`share`) and `hmAim` (`best`/`target`): one → `min_count` / `max_probability`; share → `min_total` / `max_probability`, with `budget` = `hmSlots` ("cards allowed"). Saved forms from the three-mode version are upgraded (`need` → one/target, `split` → share/best, `fewest` → share/target with the deck size allowed). `hmVary` rows (card type, from, to), `hmTarget` (percent, read exactly as a decimal), `hmSlots`. `buildRequest` sends Python's `how_many` problem (other card types fixed). The question runs only when the player presses "Find the best counts" (at the end of step 3 or in the answer card; it keeps focus while working), via `useLiveAnswer` `manual`/`waiting`/`run`, since a search can take seconds. While waiting, the card shows no older answer. Choosing the question or a mode pre-fills the rows from the card types the good game uses (rows already set up are kept; one: count −10 … +16; share: 0 … their total, which also becomes the cards allowed; all capped at the deck size; choosing the aim changes no rows), so the first press answers. Ranges and cards allowed may not exceed the deck size; the "from" numbers must fit in the room the other card types leave, and within the cards allowed. The target is checked only when aiming for one. An unreachable target gets the desktop app's advice, with no bug-report details. Renaming a card type renames it wherever it was chosen |
| `forms/answer.ts` | `readReply(goal, text) → View`: an answer, or a problem with a plain headline and advice per error kind, plus technical details kept apart |
| `engine/scheduler.ts` | `LiveScheduler(transport, listener, clock)`: `submit`, `cancel`, `receive`, `crashed`. Invariants (property-tested): only the newest request is ever answered, cancelled requests never are, no request is sent twice, and the newest request is eventually answered |
| `engine/transport.ts` | Worker plumbing: `restart()` replaces the worker, messages from a replaced worker are ignored, and a crash becomes an `internal` error reply |
| `app/useLiveAnswer.ts` | One `job` string holds the request and the goal it answers. A valid form submits it; an invalid form cancels. The reply is worded with its own request's goal |
| `App.tsx` | A field's problem shows once typing has paused for 1 s, or once the field has lost focus, and never while the player is typing in it |

## 10. Traceability (requirement → LLD)

| SRS | LLD |
|---|---|
| FR-01, FR-05, FR-15 | §3.3, §3.6 |
| FR-02, FR-12, FR-36 | §3.1, §4.1 |
| FR-10 | §5.2 fast path, §8 |
| FR-11, FR-13 | §4.1, §5.2 |
| FR-14, FR-30, FR-31 | §6.1 |
| FR-20 – FR-25 | §3.4, §4.2, §4.4, §5.2 |
| FR-32 – FR-35 | §3.2, §4.3, §4.4, §8 |
| FR-37 | §7.2 |
| FR-40 – FR-47 | §3.5, §4.5, §6.2 |
| FR-48 | §6.2 optimal keep |
| FR-50 – FR-54 | §6.3, §11.1 `optimizer` |
| FR-60 – FR-64 | §3.3, §7.1 |
| FR-70, FR-71 | §5.4, §8 |
| NFR-06 | §5.3 |
| NFR-07 | §0, §3.8 |
| NFR-14 | §7, §11.2 |
| FR-90, FR-91 | §11.1, §11.2 |
| FR-92 – FR-97, FR-99 | §11.3 |
| FR-98 | HLD §4.10 (`pages.yml`) |
| FR-104 | §11.1 `optimizer`, §11.2 stage 5, §11.3 |
