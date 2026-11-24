//! WebAssembly bindings of the mtgcalc core for the web app (ADR-0013).
//!
//! The crate holds no logic: each export forwards to [`mtgcalc_core`], so everything
//! the browser computes is the code the conformance suite checks against Python.
//! Strings cross the boundary as JSON (ADR-0013 §3); answers never throw.

use wasm_bindgen::prelude::wasm_bindgen;

/// Answers a probability request (see [`mtgcalc_core::json`] for the format).
///
/// Returns a `Probability`, `ConditionalResult` or `Error` object as JSON text.
#[wasm_bindgen]
#[must_use]
pub fn probability(request: &str) -> String {
    mtgcalc_core::json::probability(request)
}

/// A pasted decklist as a `Deck` object (Python's `to_dict` format), or an error.
#[wasm_bindgen]
#[must_use]
pub fn parse_deck(text: &str) -> String {
    mtgcalc_core::json::parse_deck(text)
}

/// A typed rule as a `Query` object (default turn `turn`), or an error.
#[wasm_bindgen]
#[must_use]
pub fn parse_rule(text: &str, turn: i32) -> String {
    mtgcalc_core::json::parse_rule(text, i64::from(turn))
}

/// The rule-language text of a `Query` object: `{"type": "Rule", "text": ...}`.
#[wasm_bindgen]
#[must_use]
pub fn format_rule(query: &str) -> String {
    mtgcalc_core::json::format_rule(query)
}

/// The core's version, shown in the web app's "about" text.
#[wasm_bindgen]
#[must_use]
pub fn version() -> String {
    env!("CARGO_PKG_VERSION").to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The binding forwards unchanged: same text in, same text out as the core.
    #[test]
    fn forwards_to_the_core() {
        let request = r#"{"scenario": {"type": "Scenario", "deck": {"type": "Deck", "cards": [{"type": "Card", "name": "Forest", "quantity": 60}]}}, "query": {"type": "Query", "condition": {"type": "Const", "value": true}}}"#;
        assert_eq!(
            probability(request),
            mtgcalc_core::json::probability(request)
        );
        assert!(probability("not json").contains("malformed"));
        assert_ne!(version(), "");
    }
}
