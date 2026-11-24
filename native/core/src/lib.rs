//! The pure Rust core of mtgcalc (ADR-0009, ADR-0011, ADR-0013).
//!
//! Computes exact draw and mulligan probabilities for Magic: The Gathering decks. Every
//! module is a faithful port of a Python module in `mtgcalc`; the two are checked against
//! each other bit for bit by the Python conformance suite. The crate has no Python or
//! JavaScript dependencies: `mtgcalc-native` (`PyO3`) and `mtgcalc-wasm` wrap it.
//!
//! * [`model`]: validated decks, selectors, conditions and game settings.
//! * [`compile`]: atomization, the draw schedule and the condition compiler.
//! * [`io`]: the rule language and text decklists.
//! * [`engine`]: the sequential dynamic program over card-count states (MATH §5).
//! * [`mulligan`]: London-mulligan enumeration on top of the DP (MATH §9).
//! * [`api`]: engine entry points with automatic `u128` → big-integer fallback.
//! * [`analysis`]: preparing questions, and the mulligan analyses (report, optimal keep).
//! * [`probability`]: exact P(condition) and P(condition | given) for a scenario.
//! * [`stats`]: count distributions and turn tables.
//! * [`optimizer`]: choosing card counts.
//! * `json` (feature `json`): the JSON boundary used by the web app (ADR-0013 §3).
//!
//! All weights are exact integers over a shared integer denominator (ADR-0002).

pub mod analysis;
pub mod api;
pub mod binom;
pub mod compile;
pub mod engine;
pub mod error;
pub mod io;
#[cfg(feature = "json")]
pub mod json;
pub mod logic;
pub mod model;
pub mod mulligan;
pub mod optimizer;
pub mod policy;
pub mod probability;
pub mod stats;
pub mod weight;
pub use error::{Error, Result};
