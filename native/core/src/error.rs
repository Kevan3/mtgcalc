//! Error type shared by the whole crate.

use std::fmt;

/// Why a computation could not produce a result.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    /// A `u128` operation would overflow. The drivers in [`crate::api`] retry with
    /// arbitrary-precision weights, so callers of the public API never see this.
    Overflow,
    /// More live states than the caller's limit (the payload is the state count).
    Limit(usize),
    /// Engine input was malformed (an index out of range, a bad opcode, ...). Input built
    /// by [`crate::compile`] never triggers this; it guards the raw engine entry points.
    Invalid(String),
    /// A user-supplied value or combination of values is invalid. Mirrors Python's
    /// `mtgcalc.errors.ValidationError`, including its field path and message.
    Validation {
        /// Dotted path of the offending input, e.g. `card[Forest].quantity`.
        field: String,
        /// Why it is invalid.
        message: String,
    },
    /// Text (a rule or a decklist) could not be read. Mirrors Python's
    /// `mtgcalc.errors.ParseError`, including its message, line and column.
    Parse {
        /// Why it could not be read.
        message: String,
        /// 1-based line.
        line: usize,
        /// 1-based column, in characters.
        column: usize,
    },
    /// No assignment of card counts can meet an optimization's target (Python's
    /// `InfeasibleError`, with its message).
    Infeasible(String),
    /// Valid input beyond what this implementation supports (ADR-0013 §3): more than 64
    /// predicate bits, a library above 65,535 cards, a feature not ported yet, ...
    Unsupported(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Overflow => write!(f, "integer overflow in u128 arithmetic"),
            Error::Limit(states) => write!(f, "state limit exceeded ({states} live states)"),
            Error::Invalid(why) => write!(f, "invalid input: {why}"),
            Error::Validation { field, message } => write!(f, "{field}: {message}"),
            Error::Parse {
                message,
                line,
                column,
            } => write!(f, "line {line}, column {column}: {message}"),
            Error::Infeasible(why) => write!(f, "infeasible: {why}"),
            Error::Unsupported(why) => write!(f, "not supported: {why}"),
        }
    }
}

impl std::error::Error for Error {}

/// Shorthand for results in this crate.
pub type Result<T> = std::result::Result<T, Error>;

/// An [`Error::Invalid`] with a formatted message.
pub(crate) fn invalid(why: impl Into<String>) -> Error {
    Error::Invalid(why.into())
}

/// An [`Error::Validation`] (Python's `ValidationError(field, message)`).
pub(crate) fn validation(field: impl Into<String>, message: impl Into<String>) -> Error {
    Error::Validation {
        field: field.into(),
        message: message.into(),
    }
}

/// An [`Error::Unsupported`].
pub(crate) fn unsupported(why: impl Into<String>) -> Error {
    Error::Unsupported(why.into())
}
