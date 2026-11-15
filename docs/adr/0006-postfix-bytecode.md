# ADR-0006: Postfix bytecode for compiled Boolean programs

**Status:** Accepted

## Decision

Condition outputs compile to flat postfix integer programs over predicate bits. The opcodes are BIT, CONST, NOT, AND n, OR n, XOR, IMPLIES, ATLEAST k n, and EXACTLY k n.

## Consequences

- One small interpreter serves both two-valued and Kleene three-valued evaluation.
- Programs are hashable, serializable, and trivially portable to a native engine.
- Composing programs (for example, `o ∧ KEEP` for mulligans) is just concatenation.
