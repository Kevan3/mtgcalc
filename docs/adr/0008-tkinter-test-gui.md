# ADR-0008: Tkinter test GUI as a separate package with a headless form layer

**Status:** Accepted (2026-11-14)

## Context

A GUI is needed now to exercise the calculator by hand. The production UI will be a web app (Phase 3). The core must stay pure (NFR-07) and dependency-free (NFR-13).

## Decision

- Build the test GUI with Tkinter/ttk (standard library) as `mtgcalc_gui`, separate from `mtgcalc`.
- Split it into `forms` (pure: strings → model → `ResultView`) and `app` (a thin Tk view).
- Run calculations on a worker thread, with queue polling.

## Consequences

- No new runtime dependencies, and nothing to remove when the web app arrives. The `forms` layer (input formats, result tables) is reusable as a reference for the web UI.
- Almost all GUI logic is unit-tested without a display. The Tk view has smoke tests that skip when no display is present.
- Tk looks dated. That is acceptable for a test tool.
