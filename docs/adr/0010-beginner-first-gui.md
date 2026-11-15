# ADR-0010: Beginner-first GUI

**Status:** Accepted (2026-11-14, user request: "brand new user"-friendly)

## Context

The 0.2 test GUI mirrored the engine:
- users typed a rule language (`land >= 3 @T3`);
- they filled in fields named after internals (default turn, engine, quota, budget);
- they read tables headed with probability notation.

Someone unfamiliar with the machinery could not use it.

## Decision

- Organize the window as **steps** (your deck, how you play) and **questions**:
  - What are my chances?
  - How many will I draw?
  - Turn by turn
  - Should I mulligan?
  - How many should I play?
- Enter decks as a table of **card types** with "also counts as". Pasted decklists use #tags.
- Build goals from **drop-down lines**. The typed rule language remains as an opt-in "advanced" box, pre-filled from the lines so users can learn it.
- Every answer leads with a **plain sentence**, followed by a table with plain column names and a legend. Every field has hover help. There are full examples and Help windows.
- Technical options (exact vs. simulated, fractions) move to a Settings dialog.
- Combine the mulligan report and the optimal keep into one comparison: your plan vs. never mulliganing vs. the best possible plan.
- Keep all wording in `help.py` and all logic in the headless `forms.py`, so both are testable and reusable by the Phase-3 web app.

## Consequences

- Beginners can answer every Phase-1 question without learning the rule language.
- Some expressiveness is only reachable through the advanced box (XOR, `assign`, mixed nesting), by design.
- The docs split into `USAGE.md` (beginners) and `REFERENCE.md` (technical). Tests check the guide's quoted numbers.
