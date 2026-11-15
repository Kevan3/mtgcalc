"""Exception hierarchy for mtgcalc (LLD §9).

Every error raised deliberately by the library derives from :class:`MtgCalcError`, so
callers can catch library failures without catching programming errors.
"""

from __future__ import annotations


class MtgCalcError(Exception):
    """Base class for all deliberate mtgcalc errors."""


class ValidationError(MtgCalcError, ValueError):
    """An input value or combination of inputs is invalid (FR-04, NFR-12).

    Attributes:
        field: Dotted path of the offending input field.
        message: Human-readable reason.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


class ParseError(MtgCalcError, ValueError):
    """Text input (decklist or condition expression) could not be parsed."""

    def __init__(self, message: str, line: int = 1, column: int = 1) -> None:
        super().__init__(f"line {line}, column {column}: {message}")
        self.message = message
        self.line = line
        self.column = column


class StateSpaceTooLargeError(MtgCalcError):
    """The exact engine would exceed its configured state limit (NFR-06)."""

    def __init__(self, estimate: int, limit: int) -> None:
        super().__init__(
            f"exact computation needs about {estimate:,} states (limit {limit:,}); "
            "use engine='montecarlo' or engine='auto', or raise the limit"
        )
        self.estimate = estimate
        self.limit = limit


class InfeasibleError(MtgCalcError):
    """An optimization target cannot be met within the given bounds."""
