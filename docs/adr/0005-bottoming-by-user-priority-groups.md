# ADR-0005: London-mulligan bottoming is driven by user-given priority groups

**Status:** Accepted (user decision, 2026-11-13)

## Context

Which cards go to the bottom determines the mulligan results. Inferring priorities automatically from the conditions is opaque.

## Decision

The user supplies an ordered list of groups (selector plus an optional keep quota). Cards are bottomed in this order:

1. cards in no group
2. unprotected cards, lowest priority first
3. cards released from protection, lowest priority first

A missing quota is derived from the conditions' lower bounds on that group (LLD §4.5).

## Consequences

- The behaviour is transparent and deterministic, and can be memoized per hand composition.
- An optimal bottom policy (FR-44) remains possible as a separate strategy.
