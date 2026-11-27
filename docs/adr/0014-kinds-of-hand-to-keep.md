# ADR-0014: Kinds of hand to keep (several keep rules)

**Status:** Accepted (2026-11-26)

## Context

Both apps offered one keep rule: a range of one card type ("keep a hand with 2 to 5 land"). Players' real rules are richer. They need two or more card types at once ("2 to 5 land and some ramp"), or one of several acceptable hands ("3 to 5 land, or 2 land with ramp"). The engine already accepts any condition as the keep rule (`MulliganConfig.keep_rule`, evaluated on the kept hand, MATH §9). Only the plain-language layers limited it.

We considered these options:
1. **All lines must hold (AND).** This can't express "this hand or that hand".
2. **Any line may hold (OR).** This can't express "land and ramp".
3. **A list with an all/any switch,** like the goal lines. This covers either case but not mixtures such as "3 to 5 land, or 2 land and ramp", which is the most common real rule.
4. **Kinds of hand: an OR of ANDs.** Each kind is a list of lines that must all hold, and a hand that fits any kind is kept. Every keep rule built from ranges can be written this way (disjunctive normal form).
5. **Different rules per hand size** (looser after a mulligan). This would change the model and both engines (`MulliganConfig` holds one rule), and players did not ask for it.

## Decision

- Option 4, with the same rule at every hand size.
- `mtgcalc_gui.forms.MulliganSetup.keep: tuple[tuple[KeepRule, ...], ...]` replaces `keep_type`/`keep_min`/`keep_max`. `keep_condition` builds `Or(And(Between...))`, without wrapping a single line or kind, so the old one-line rule still serializes as a plain `Between`. No kinds means `Const(True)` ("keep every hand"), which replaces the old "keep any hand" choice.
- The web form mirrors it (`FormState.keep`, kinds of lines with stable ids). Its request JSON and its words are checked against Python's in the golden cases, and saved forms are upgraded.
- The screens say it in players' words: "Keep a hand that has … and … / Or keep a hand that has …", "+ And also…", "+ Or keep another kind of hand", plus the whole rule restated in one sentence.

## Consequences

- No engine, model or serialization change, and no change to the Rust core or the WebAssembly.
- `MulliganSetup` changes shape. It belongs to the GUI package, not the public `mtgcalc.api`, so the core API is unaffected.
- Derived bottoming quotas (`lower_bounds`) already treat `Or` and `And` alike. The apps always give explicit quotas anyway.
- A per-hand-size rule remains possible later. It would need `MulliganConfig` to hold one rule per depth, in both engines.
