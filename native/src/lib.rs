//! Native exact engine for mtgcalc (ADR-0009).
//!
//! Computes exact draw and mulligan probabilities for Magic: The Gathering decks. This
//! crate is a faithful port of the Python reference engine in `mtgcalc.engine`; the two
//! are checked against each other bit for bit by the Python conformance suite.
//!
//! * [`engine`]: the sequential dynamic program over card-count states (MATH §5).
//! * [`mulligan`]: London-mulligan enumeration on top of the DP (MATH §9).
//! * [`api`]: entry points with automatic `u128` → big-integer fallback.
//! * `python` (feature `python`): the `PyO3` extension module `mtgcalc_native`.
//!
//! All weights are exact integers over a shared integer denominator (ADR-0002).

pub mod api;
pub mod binom;
pub mod engine;
pub mod error;
pub mod logic;
pub mod mulligan;
pub mod policy;
pub mod weight;

#[cfg(feature = "python")]
mod python;

pub use error::{Error, Result};
