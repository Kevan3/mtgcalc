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
    /// The input was malformed (an index out of range, a bad opcode, ...).
    Invalid(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Overflow => write!(f, "integer overflow in u128 arithmetic"),
            Error::Limit(states) => write!(f, "state limit exceeded ({states} live states)"),
            Error::Invalid(why) => write!(f, "invalid input: {why}"),
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
