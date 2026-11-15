# ADR-0004: "By turn T" means after the draw step of turn T

**Status:** Accepted (user decision, 2026-11-13)

## Decision

- Turn 0 = the kept opening hand.
- Turn T ≥ 1 = the cards seen after the draw step of turn T.
- On the play, turn 1 has no draw by default.

## Consequences

The number of cards seen by turn T is `hand + draws_through(T)`. Rules that differ by format (for example, multiplayer games where nobody skips the first draw) are expressed through `GameConfig` and are not hard-coded.
