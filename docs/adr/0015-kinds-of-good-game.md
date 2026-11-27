# ADR-0015: Kinds of good game, like the kinds of hand to keep

**Status:** Accepted (2026-11-26)

## Context

ADR-0014 gave the keep rules "kinds of hand": any kind will do, and each kind needs all its lines. The good game still used one switch: every line ("all") or at least one ("any"). The two sections then looked and behaved differently, although both describe "which situations count". The switch also cannot say "3 land and removal by turn 3, or 4 land by turn 4" without a typed rule.

We considered two options:
1. Keep the all/any meaning and only restyle the good-game lines to look like the keep rules.
2. Give the good game the same structure: an OR of ANDs.

## Decision

- Option 2, as the user chose. `Goal(groups, custom)` replaces `Goal(requirements, combine, custom)`. `goal_condition` builds `Or(And(...))` the way `keep_condition` does, without wrapping a single line or kind, so goals made with the old switch produce exactly the same conditions as before. `Goal.all_of` and `Goal.any_of` build those shapes.
- One layout serves both lists: `components/LineGroups.tsx` on the web and `LineGroups` in the desktop app. They share headings, "Or …" titles, "and" lines, "+ And also…", "+ Or …", an empty state, and (on the web) a "So: …" sentence.
- Saved web forms are upgraded: "all" becomes one kind, and "any" becomes one kind per line.
- The words join lines with "and" and kinds with "or". Kinds of one line each still read "A or B", and ", or" is used once a kind has several lines.

## Consequences

- No engine, Rust core or WebAssembly change.
- `mtgcalc_gui.forms.Goal` changes shape. It belongs to the GUI package, not to `mtgcalc.api`.
- The golden fixtures now include mixed goals. They exposed an unrelated rounding difference (Python formatted averages from floats), which was fixed by rounding exact values exactly in Python.
