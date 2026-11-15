# mtgcalc Technical Reference

This reference is for people who want to **type their own rules** or **use mtgcalc from Python**. If you just want to use the app, read the beginner's guide, [`USAGE.md`](USAGE.md), instead.

Results are **exact** fractions, not simulations, unless you ask for a simulation. The examples were run against version 0.3.0, and the numbers shown are real outputs. The test suite runs every Python block in this file.

---

## 1. Install and launch

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"     # or: pip install -e .   (no dependencies needed to run)

.venv/bin/mtgcalc-gui                  # launch the test GUI   (or: python -m mtgcalc_gui)
```

Requires Python 3.12+. The GUI uses Tkinter, which is part of standard Python. On Debian/Ubuntu you may need `sudo apt install python3-tk`.

---

## 2. Key ideas

| Idea | Meaning |
|---|---|
| **Library** | The cards you shuffle. Your commander is *not* in it: a 100-card Commander deck has a 99-card library. |
| **Tags** | Labels on cards, such as `land`, `ramp`, `removal`. A card can have several tags, for example an MDFC tagged `land` and `removal`. |
| **Group** | Any way of picking cards: a tag, a card name, or a combination (§3). |
| **Seen cards** | Your kept hand plus every card drawn since. Cards you put on the bottom are not seen. |
| **Turn 0** | Your kept opening hand. |
| **"By turn T"** | After the draw step of turn T. On the play you skip the turn-1 draw, so by turn 3 you have seen 7 + 2 = 9 cards. On the draw you have seen 10. |
| **Scenario** | A deck plus game settings (hand size, play/draw, draws) plus, optionally, mulligan settings. Every question is asked about a scenario. |
| **Shared counting** | A card counts toward *every* group it belongs to, so an MDFC counts as a land *and* as removal. Use `assign(...)` (§3) when each card should count only once. |

---

## 3. The condition language

Conditions are short text expressions. The GUI and the Python API use the same syntax.

### Groups

| Write | Picks |
|---|---|
| `land` | Cards tagged `land` (case-insensitive) |
| `tag:"mana rock"` | A tag containing spaces or symbols, or a tag that is also a keyword |
| `card:"Sol Ring"` | A specific card by name |
| `any(ramp, draw)` | Cards with *either* tag |
| `all(land, ramp)` | Cards with *both* tags |
| `none(land)` | Cards *without* the tag (`none(a, b)` = neither) |
| `everything` | Every card |

### Tests

| Write | Means |
|---|---|
| `land >= 3`, `> `, `<=`, `<`, `==`, `!=` | Compare how many seen cards are in the group |
| `land in 2..4` | Between 2 and 4, inclusive |
| `assign(land >= 3, ramp >= 1)` | Every requirement can be met with **different** cards (each card used once) |
| `true`, `false` | Constants |

### Combining

| Write | Means |
|---|---|
| `A AND B`, `A OR B`, `NOT A` | The usual logic |
| `A XOR B` | Exactly one of A and B |
| `A -> B` (or `A IMPLIES B`) | "If A then B" (true whenever A is false) |
| `atleast(2, A, B, C)` | At least 2 of the listed conditions |
| `exactly(1, A, B, C)` | Exactly 1 of them |
| `( ... )` | Grouping |

Precedence, tightest first: `NOT`, `AND`, `XOR`, `OR`, `->`. When in doubt, add parentheses.

### Turns and "given"

| Write | Means |
|---|---|
| `land >= 3 @T3` | Checked by turn 3. `@3` and `@ turn 3` also work. |
| `(land >= 2 AND ramp >= 1) @T2` | Apply one turn to a whole sub-condition |
| `land >= 2 @T0 AND land >= 4 @T4` | Different turns in one question. The answer is exact: path-dependent results are not multiplied together. |
| `A GIVEN B` | Conditional probability P(A \| B) |

A test without `@` uses the **default turn** (0 unless you set it). If `@` is nested, the innermost one wins.

---

## 4. The app

The GUI is described in the beginner's guide, [`USAGE.md`](USAGE.md). In the app, **Type my own rule instead (advanced)** under any goal accepts the rule language from §3.

## 5. Python API

```python
from fractions import Fraction
from mtgcalc import *
```

### 5.1 Decks

```python
deck = Deck.from_counts(60, {"land": 24, "removal": 6})          # rest becomes filler
deck = Deck.from_counts(60, {"land": 22,
                             "mdfc": Category(2, frozenset({"land", "removal"}))})

deck = Deck((Card("Forest", 20, frozenset({"land"})),             # explicit cards
             Card("Llanowar Elves", 4, frozenset({"ramp", "creature"})),
             Card("Grizzly Bears", 16)))

text = """Commander
1 Atraxa, Praetors' Voice
Deck
1 Sol Ring (CMR) 472 #ramp
36 Forest #land
62 Filler
"""                                                               # or open("deck.txt").read()
deck = parse_decklist(text)                                       # Moxfield/Archidekt/plain text
deck.size, deck.tag_counts()                                      # (99, {'land': 36, 'ramp': 1})
deck = deck.with_tags("Sol Ring", add=["fast"]).rename_tag("ramp", "accel")
```

Writing a deck back out as text, and importing from a link (`mtgcalc_online` does network I/O, so it lives outside the core):

```python
text = format_decklist(deck)              # "Commander\n1 Atraxa...\n\nDeck\n36 Forest #land\n..."
parse_decklist(text) == deck              # True (tags with spaces come back hyphenated)

from mtgcalc_online import fetch_deck, recognize, DeckFetchError
recognize("https://archidekt.com/decks/123456/my-deck")   # (Source(name='Archidekt', ...), '123456')
# fetch_deck("https://archidekt.com/decks/123456/my-deck") -> Deck   (downloads; needs internet)
# Moxfield links raise DeckFetchError explaining Moxfield's "Copy as plain text" export.
```

For debugging imports, `logging.getLogger("mtgcalc_online").setLevel(logging.DEBUG)` logs every request and its outcome. `fetch_deck(link, get=my_function)` substitutes the HTTP call.

### 5.2 Scenarios

```python
s = Scenario(deck)                                    # 7-card hand, on the play, 1 draw/turn
s = Scenario(deck, GameConfig(on_play=False, hand_size=7, draws_per_turn=1,
                              extra_draws={3: 2},      # +2 cards on turn 3
                              draw_overrides={1: 1}))  # replace the turn-1 draw count
```

### 5.3 Probabilities

```python
s = Scenario(Deck.from_counts(60, {"land": 24, "removal": 6}))

p = probability(s, "land >= 3 @T3 AND removal >= 1 @T3")
p.value, p.exact                         # 0.4774..., Fraction(64159213, 134392206)

r = probability(s, "removal >= 1 GIVEN land >= 2")
r.result.value, r.defined                # 0.5143..., True  (r.joint, r.given also available)

probability(s, "land >= 3", engine="montecarlo", trials=50_000, seed=1).ci95
probability(s, "land >= 3", engine="auto")   # exact, or simulation (with a warning) if too large
hypergeom(60, 4, 7).at_least(1)          # textbook case: 0.3995 (one of 4 copies in 7 cards)
```

Conditions can also be built in code. This is equivalent to the text form:

```python
cond = (count("land") >= 3).at(3) & (count(any_of("removal", "land")) >= 4)  # & = AND
alt = (count("land") >= 2) | ~(count("removal") < 1)              # | = OR, ~ = NOT, ^ = XOR
probability(s, Query(cond, given=alt, turn=0))                    # turn = default turn
# other builders: tag("x"), card("Sol Ring"), all_of(...), none_of(...), everything(),
# count(g).eq(2), .ne(2), .between(1, 3), a.implies(b), Assignable((Demand(g, 2), ...))
```

### 5.4 Distributions and tables

```python
d = distribution(s, tag("land"), turn=3)
d.exactly(3), d.at_least(3), d.at_most(2), d.none()   # 0.2667, 0.7887, 0.2113, 0.0064
d.mean, d.variance, d.pmf, d.cdf()                    # exact Fractions

turn_table(s, "land >= 4", turns=[4, 5, 6]).rows      # P = 0.6318, 0.7259, 0.8025
threshold_table(s, tag("land"), turns=[1, 3], ks=[2, 3, 4]).rows
```

### 5.5 Mulligans

```python
mull = MulliganConfig(
    priority=(PriorityGroup(tag("land"), quota=3),     # protect up to 3 lands (highest priority)
              PriorityGroup(tag("removal"))),          # quota derived from your conditions
    keep_rule=count("land").between(2, 5),
    max_mulligans=2,
    free_mulligans=0,                                  # 1 for multiplayer Commander
)
sm = s.with_mulligan(mull)

rep = mulligan_report(sm, "land >= 3 @T3")
rep.p_success, rep.expected_mulligans                  # 0.8898, 0.18
for row in rep.rows:                                   # depth, hand_size, p_reach,
    ...                                                # p_keep_given_reach, p_success_forced, ...

optimal_keep(sm, "land >= 3 @T3").value                # 0.9641: the best any keep rule can do
probability(sm, "land >= 3 @T3")                       # every query becomes strategy-level
```

**Which cards go to the bottom?**
1. Cards in no priority group.
2. Unprotected cards, lowest priority first.
3. Protected cards, but only if more must go, lowest priority first.

### 5.6 Optimizer

```python
q = Query(parse_condition("land >= 4"), turn=4)
optimize(OptimizeProblem(deck_size=60, variables=(Variable("land", 14, 40),),
                         query=q, objective="min_count", target=Fraction(9, 10)))
# counts=(('land', 33),), probability≈0.918, proven_optimal=True

optimize(OptimizeProblem(deck_size=40,
                         variables=(Variable("land", 15, 18), Variable("ramp", 0, 4)),
                         query=Query(parse_condition("land >= 3 AND ramp >= 1"), turn=2),
                         objective="max_probability", budget=20))
# counts=(('land', 16), ('ramp', 4))

optimize(OptimizeProblem(deck_size=60, variables=(Variable("land", 16, 26),),
                         fixed=(("mdfc", Category(4, frozenset({"land"}))),),
                         query=Query(parse_condition("land >= 3"), turn=3),
                         objective="min_total", target=Fraction(85, 100)))
```

Variables become tags, so a condition refers to them by name. `Variable(..., tags=...)` adds extra tags.

| Term | Meaning |
|---|---|
| **cap** | The most cards all variables may use together: `budget`, or the room left after `fixed` (`problem.max_total`) |
| **filler** | Library cards that are in no variable or fixed category |
| **monotone** | Adding a copy of a variable can never lower P. This holds when the variable only appears in `>=` / `>` / `assign` tests and no mulligans are modelled (`is_monotone`; override with `assume_monotone=`). |
| **proven_optimal** | The answer is guaranteed best: binary search, or every candidate evaluated. Otherwise a local search found it (very likely, but not certainly, the best). |
| **evaluations** | The number of candidate decks computed exactly |

How each objective searches:
- **`min_count`:** binary search when monotone; otherwise a scan from `lo` upward.
- **`max_probability`:** when monotone, the best answer always uses the whole cap, so only splits that add up to the cap are tried. Otherwise every split within the cap is tried, or a local search is used when there are more than `exhaustive_limit` (5000) candidates.
- **`min_total`:** when monotone, binary search over the total; otherwise totals in increasing order.

`workers=` sets how many candidates are evaluated in parallel. It defaults to the number of CPUs when the native engine is installed (it releases the GIL), and to 1 otherwise. MATH §10 has the proofs.

### 5.7 Engines and speed

| Setting | Effect |
|---|---|
| `engine="exact"` (default) | Exact fractions. Raises `StateSpaceTooLargeError` if more than `limit` (2,000,000) states would be live at once. |
| `engine="auto"` | Exact, but if the engine hits `limit` it simulates instead and adds a warning |
| `engine="montecarlo"` | Simulates `trials` games (seed with `seed=`). The result has `.estimate` and `.ci95`. |
| native engine | The optional Rust engine (`native/`, see the README) is used automatically when installed. Results are identical, and `MTGCALC_ENGINE=python` forces the pure-Python engine. It covers ordinary questions (about 15–20× faster) and the whole mulligan enumeration (mulligan reports about 14×, optimal keep up to 14×). |

### 5.8 Text, saving, and errors

```python
text = format_condition(cond)                       # canonical text of a built condition
parse_condition(text) == cond                        # True: text and objects round-trip
parse_query("removal >= 1 GIVEN land >= 2", turn=2)  # a Query with a default turn
format_selector(parse_selector('any(ramp, card:"Sol Ring")'))

from mtgcalc.model.serialization import to_dict, from_dict   # JSON-ready dicts
from_dict(to_dict(sm)) == sm                                  # True: round-trips exactly
```

| Error | When |
|---|---|
| `ValidationError` | An impossible input, such as more cards than the library holds. `.field` names the culprit. |
| `ParseError` | Bad condition or decklist text. `.line` and `.column` point at the problem. |
| `StateSpaceTooLargeError` | The exact calculation would be too large. Use `engine="auto"` or `"montecarlo"`, or raise `limit=`. |
| `InfeasibleError` | The optimizer can't reach the target within your ranges. |

All of these derive from `MtgCalcError`. If P(B) = 0, `probability(... GIVEN ...)` returns `defined=False` instead of raising.

---

## 6. Tips and gotchas

- **Overlapping tags count twice by default.**

  ```text
  hand: Forest, Forest, Shatterskull Smashing (land + ramp)
    land >= 3 AND ramp >= 1         -> true   (the MDFC counts for both)
    assign(land >= 3, ramp >= 1)    -> false  (it can only be one of them)
  ```

- **Mulliganed hands draw from the rest of the deck.** The bottomed cards sit under the library and are never drawn. The tool rejects scenarios that would draw that deep.
- **Your priority list decides bottoming**, so list what you'd really keep first. `optimal_keep` shows the best keep decisions *for that bottoming order*.
- **A single wanted card survives the London mulligan.** Mulliganing to any size finds it as often as a fresh 7, as long as it's in your priority list.
- **Speed.** Typical queries take milliseconds. Many groups combined with many turns can grow large. Install the native engine, or use `engine="auto"` to fall back to simulation when needed.
- **Colour requirements** can be expressed as tags, such as `red` on red sources: `red >= 2 @T3 GIVEN land >= 3 @T3`.

For the maths behind the numbers, see [`00-math-foundations.md`](00-math-foundations.md). For the app, see [`USAGE.md`](USAGE.md).
