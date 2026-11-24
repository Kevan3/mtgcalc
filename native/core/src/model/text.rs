//! Text normalization identical to Python's (`mtgcalc.model.deck.normalize_tag`).
//!
//! Python writes `" ".join(s.split())` to collapse whitespace and `.casefold()` to
//! compare case-insensitively. Both use Python's own Unicode definitions, which differ
//! from Rust's `char::is_whitespace` and `str::to_lowercase` (for example, U+001C is
//! whitespace in Python, and `ß` case-folds to `ss`). The tables in the private
//! `unicode_tables` module are generated from Python, and the conformance suite checks
//! every code point.

use std::fmt::Write as _;

use super::unicode_tables::{
    CASEFOLD, DIGITS, IGNORECASE_EXTRA, LINE_BREAKS, PRINTABLE, WHITESPACE,
};

/// Python's `str.isspace()` (also what `re`'s `\s` matches).
#[must_use]
pub fn is_space(c: char) -> bool {
    WHITESPACE.binary_search(&c).is_ok()
}

/// The value Python's `int()` gives a character that `re`'s `\d` matches, if any.
#[must_use]
pub fn digit_value(c: char) -> Option<u8> {
    DIGITS
        .binary_search_by_key(&c, |&(d, _)| d)
        .ok()
        .map(|i| DIGITS[i].1)
}

/// Python's `str.isprintable()` for one character.
#[must_use]
pub fn is_printable(c: char) -> bool {
    let code = u32::from(c);
    PRINTABLE
        .binary_search_by(|&(lo, hi)| {
            if hi < code {
                std::cmp::Ordering::Less
            } else if lo > code {
                std::cmp::Ordering::Greater
            } else {
                std::cmp::Ordering::Equal
            }
        })
        .is_ok()
}

/// Whether `re` with `(?i)` matches `c` against the lowercase ASCII letter `letter`.
#[must_use]
pub fn ignorecase_eq(c: char, letter: char) -> bool {
    c.to_ascii_lowercase() == letter || IGNORECASE_EXTRA.iter().any(|&(x, l)| x == c && l == letter)
}

/// Python's `str.strip()` (Python's whitespace, at both ends).
#[must_use]
pub fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

/// Python's `str.splitlines()`: breaks at every line boundary (`\r\n` counts as one), and
/// a final boundary does not start an empty last line.
#[must_use]
pub fn split_lines(s: &str) -> Vec<&str> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut iter = s.char_indices().peekable();
    while let Some((i, c)) = iter.next() {
        if LINE_BREAKS.binary_search(&c).is_ok() {
            lines.push(&s[start..i]);
            let mut end = i + c.len_utf8();
            if c == '\r' {
                if let Some(&(j, '\n')) = iter.peek() {
                    iter.next();
                    end = j + 1;
                }
            }
            start = end;
        }
    }
    if start < s.len() {
        lines.push(&s[start..]);
    }
    lines
}

/// Python's `repr()` of a string, for error messages identical to Python's.
#[must_use]
pub fn py_repr(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for c in s.chars() {
        let code = u32::from(c);
        match c {
            _ if c == quote || c == '\\' => {
                out.push('\\');
                out.push(c);
            }
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            _ if code < 0x20 || code == 0x7f => {
                let _ = write!(out, "\\x{code:02x}");
            }
            _ if code < 0x7f || is_printable(c) => out.push(c),
            _ if code <= 0xff => {
                let _ = write!(out, "\\x{code:02x}");
            }
            _ if code <= 0xffff => {
                let _ = write!(out, "\\u{code:04x}");
            }
            _ => {
                let _ = write!(out, "\\U{code:08x}");
            }
        }
    }
    out.push(quote);
    out
}

/// `" ".join(s.split())`: trims and collapses every run of whitespace to one space.
#[must_use]
pub fn collapse_whitespace(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for word in s.split(is_space).filter(|w| !w.is_empty()) {
        if !out.is_empty() {
            out.push(' ');
        }
        out.push_str(word);
    }
    out
}

/// Python's `str.casefold()` (full Unicode case folding).
#[must_use]
pub fn casefold(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match CASEFOLD.binary_search_by_key(&c, |&(from, _)| from) {
            Ok(i) => out.push_str(CASEFOLD[i].1),
            Err(_) => out.push(c),
        }
    }
    out
}

/// Canonical tag or card-name key: whitespace collapsed, then case-folded.
#[must_use]
pub fn normalize(s: &str) -> String {
    casefold(&collapse_whitespace(s))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tables_are_sorted_for_binary_search() {
        assert!(WHITESPACE.windows(2).all(|w| w[0] < w[1]));
        assert!(CASEFOLD.windows(2).all(|w| w[0].0 < w[1].0));
    }

    #[test]
    fn collapses_whitespace_like_python_split() {
        assert_eq!(collapse_whitespace("  Sol \t\n Ring  "), "Sol Ring");
        assert_eq!(collapse_whitespace("a\u{1c}b"), "a b"); // Python whitespace, not Rust's
        assert_eq!(collapse_whitespace("a\u{3000}b"), "a b");
        assert_eq!(collapse_whitespace(" \t "), "");
        assert_eq!(collapse_whitespace(""), "");
    }

    #[test]
    fn casefolds_like_python() {
        assert_eq!(casefold("LAND"), "land");
        assert_eq!(casefold("Straße"), "strasse"); // to_lowercase would keep ß
        assert_eq!(casefold("ΣΊΣΥΦΟΣ"), "σίσυφοσ"); // no final-sigma context rule
        assert_eq!(casefold("ﬁ"), "fi");
    }

    #[test]
    fn python_string_helpers() {
        assert_eq!(digit_value('7'), Some(7));
        assert_eq!(digit_value('\u{663}'), Some(3)); // Arabic-Indic three
        assert_eq!(digit_value('x'), None);
        assert!(
            ignorecase_eq('K', 'k')
                && ignorecase_eq('\u{212a}', 'k')
                && ignorecase_eq('\u{17f}', 's')
        );
        assert!(!ignorecase_eq('k', 's'));
        assert_eq!(strip("\u{1c} a b \t"), "a b");
        assert_eq!(
            split_lines("a\r\nb\rc\n\nd\u{2028}e\n"),
            vec!["a", "b", "c", "", "d", "e"]
        );
        assert_eq!(split_lines(""), Vec::<&str>::new());
        assert_eq!(py_repr("a'b"), "\"a'b\"");
        assert_eq!(py_repr("a'\"b"), "'a\\'\"b'");
        assert_eq!(
            py_repr("\u{0}\u{200b}\u{1F600}\t"),
            "'\\x00\\u200b\u{1F600}\\t'"
        );
        assert_eq!(py_repr("\u{e9}\u{378}"), "'\u{e9}\\u0378'");
    }

    #[test]
    fn normalize_combines_both() {
        assert_eq!(normalize("  Card   DRAW "), "card draw");
    }
}
