//! Text input and output (port of `mtgcalc.io`): the rule language and decklists.
//! Both parsers take untrusted text: sizes and nesting are bounded (NFR-14), and nothing
//! is ever evaluated as code.

pub mod decklist;
pub mod expr;

pub use decklist::{format_decklist, parse_decklist, Format};
pub use expr::{
    format_condition, format_query, format_selector, parse_condition, parse_query, parse_selector,
};
