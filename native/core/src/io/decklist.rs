//! Text decklists: parsing and writing (port of `mtgcalc.io.decklist`, FR-60 – FR-66).
//!
//! ```text
//! 4 Lightning Bolt
//! 4x Lightning Bolt (M11) 149 *F*
//! 1 Sol Ring #ramp #!artifact            (Moxfield-style tags)
//! 1x Arcane Signet [Ramp,Mana Rock{top}]  (Archidekt-style categories)
//! ```
//!
//! Section headers (`Commander`, `Deck`, `Sideboard`, ...) switch the zone.
//!
//! Python matches each line with regular expressions. They are small, so each is written
//! out here by hand with the same semantics (Python's `\s`, `\d`, `(?i)`, leftmost match,
//! backtracking where it matters); the conformance suite compares the two on generated
//! decklists. This keeps a regex engine out of the WebAssembly download.

use std::collections::{BTreeSet, HashMap};

use crate::error::{Error, Result};
use crate::model::text::{digit_value, ignorecase_eq, is_space, normalize, split_lines, strip};
use crate::model::{Card, Deck, Zone};

/// Longest decklist accepted, in characters (NFR-14).
pub const MAX_INPUT: usize = 1_000_000;

/// Which line syntaxes to recognize.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Format {
    /// Both Moxfield `#tags` and Archidekt `[categories]`.
    Auto,
    /// Neither.
    Plain,
    /// `#tags` only.
    Moxfield,
    /// `[categories]` only.
    Archidekt,
}

fn parse_error(message: impl Into<String>, line: usize, column: usize) -> Error {
    Error::Parse {
        message: message.into(),
        line,
        column,
    }
}

const SECTIONS: [(&str, Zone); 8] = [
    ("commander", Zone::Commander),
    ("commanders", Zone::Commander),
    ("deck", Zone::Library),
    ("main", Zone::Library),
    ("mainboard", Zone::Library),
    ("sideboard", Zone::Sideboard),
    ("maybeboard", Zone::Maybeboard),
    ("companion", Zone::Sideboard),
];

/// `word` (lowercase ASCII) equals `s` under Python's `(?i)`.
fn ignorecase_word(s: &[char], word: &str) -> bool {
    s.len() == word.chars().count()
        && s.iter()
            .zip(word.chars())
            .all(|(&c, w)| ignorecase_eq(c, w))
}

fn skip_space(s: &[char], mut i: usize) -> usize {
    while s.get(i).is_some_and(|&c| is_space(c)) {
        i += 1;
    }
    i
}

/// `^\s*(?://\s*)?(commander|...|companion)\s*:?\s*$` with `(?i)`: the section's zone.
fn section(line: &[char]) -> Option<Zone> {
    let mut i = skip_space(line, 0);
    if line.get(i) == Some(&'/') && line.get(i + 1) == Some(&'/') {
        i = skip_space(line, i + 2);
    }
    // The word ends where the letters end; then optional space, ':' and space to the end.
    let start = i;
    while line.get(i).is_some_and(|c| c.is_alphabetic()) {
        i += 1;
    }
    let word = &line[start..i];
    let mut j = skip_space(line, i);
    if line.get(j) == Some(&':') {
        j = skip_space(line, j + 1);
    }
    if j != line.len() {
        return None;
    }
    // Longest names first: "commanders" before "commander", "mainboard" before "main".
    SECTIONS
        .iter()
        .find(|(name, _)| ignorecase_word(word, name))
        .map(|&(_, z)| z)
}

/// `^\s*(\d+)\s*x?\s+(.*)$` with `(?i)`: (quantity digits, start of the rest).
fn quantity(line: &[char]) -> Option<(&[char], usize)> {
    let d0 = skip_space(line, 0);
    let mut d1 = d0;
    while line.get(d1).is_some_and(|&c| digit_value(c).is_some()) {
        d1 += 1;
    }
    if d1 == d0 {
        return None;
    }
    let after_space = skip_space(line, d1);
    // Prefer the "x" (greedy `x?`), as Python does, when space follows it.
    if line
        .get(after_space)
        .is_some_and(|&c| ignorecase_eq(c, 'x'))
    {
        let rest = skip_space(line, after_space + 1);
        if rest > after_space + 1 {
            return Some((&line[d0..d1], rest));
        }
    }
    // Without the "x": at least one space, all of it consumed before the rest.
    (after_space > d1).then_some((&line[d0..d1], after_space))
}

/// Replaces every non-overlapping match found by `find(s, from) -> Some((start, end))`.
fn replace_all(
    s: &[char],
    with: &str,
    find: impl Fn(&[char], usize) -> Option<(usize, usize)>,
) -> Vec<char> {
    let mut out = Vec::with_capacity(s.len());
    let mut i = 0;
    while let Some((a, b)) = find(s, i) {
        out.extend_from_slice(&s[i..a]);
        out.extend(with.chars());
        // An empty match would loop forever; none of these patterns can be empty.
        i = b.max(a + 1);
    }
    out.extend_from_slice(&s[i.min(s.len())..]);
    out
}

/// `\^[^^]*\^`
fn caret(s: &[char], from: usize) -> Option<(usize, usize)> {
    let a = (from..s.len()).find(|&i| s[i] == '^')?;
    let b = (a + 1..s.len()).find(|&i| s[i] == '^')?;
    Some((a, b + 1))
}

/// `\[([^\]]*)\]`
fn bracket(s: &[char], from: usize) -> Option<(usize, usize)> {
    let mut start = from;
    loop {
        let a = (start..s.len()).find(|&i| s[i] == '[')?;
        if let Some(b) = (a + 1..s.len()).find(|&i| s[i] == ']') {
            return Some((a, b + 1));
        }
        start = a + 1; // no closing bracket after this one: try a later '['
    }
}

/// `\{[^}]*\}`
fn brace(s: &[char], from: usize) -> Option<(usize, usize)> {
    let mut start = from;
    loop {
        let a = (start..s.len()).find(|&i| s[i] == '{')?;
        if let Some(b) = (a + 1..s.len()).find(|&i| s[i] == '}') {
            return Some((a, b + 1));
        }
        start = a + 1;
    }
}

/// `(?:^|\s)#!?([^\s#]+)`: (match start, match end, tag start).
fn hashtag(s: &[char], from: usize) -> Option<(usize, usize, usize)> {
    for a in from..s.len() {
        let hash = if a == 0 && s[0] == '#' {
            0
        } else if is_space(s[a]) && s.get(a + 1) == Some(&'#') {
            a + 1
        } else {
            continue;
        };
        let mut t = hash + 1;
        if s.get(t) == Some(&'!') {
            // `!?` is greedy, but backtracks if no tag character follows it.
            let after = t + 1;
            if s.get(after).is_some_and(|&c| !is_space(c) && c != '#') {
                t = after;
            }
        }
        let mut e = t;
        while s.get(e).is_some_and(|&c| !is_space(c) && c != '#') {
            e += 1;
        }
        if e > t {
            return Some((a, e, t));
        }
    }
    None
}

/// `\s+\*[A-Z]\*`
fn foil(s: &[char], from: usize) -> Option<(usize, usize)> {
    let mut a = from;
    while a < s.len() {
        if is_space(s[a]) {
            let e = skip_space(s, a);
            if s.get(e) == Some(&'*')
                && s.get(e + 1).is_some_and(char::is_ascii_uppercase)
                && s.get(e + 2) == Some(&'*')
            {
                return Some((a, e + 3));
            }
        }
        a += 1;
    }
    None
}

/// Whether `s` is exactly `\s+\([A-Za-z0-9]{2,6}\)(?:\s+[A-Za-z0-9-]+[a-z★]?)?\s*`.
fn is_set_suffix(s: &[char]) -> bool {
    let open = skip_space(s, 0);
    if open == 0 || s.get(open) != Some(&'(') {
        return false;
    }
    let mut close = open + 1;
    while s.get(close).is_some_and(char::is_ascii_alphanumeric) {
        close += 1;
    }
    if !(2..=6).contains(&(close - open - 1)) || s.get(close) != Some(&')') {
        return false;
    }
    let after = close + 1;
    if skip_space(s, after) == s.len() {
        return true; // the optional collector-number part is absent
    }
    // `\s+[A-Za-z0-9-]+[a-z★]?\s*$`: a code of alphanumerics and hyphens, optionally
    // ending in one lowercase letter or star, then only space.
    let code_start = skip_space(s, after);
    if code_start == after {
        return false;
    }
    let in_code = |c: char| c.is_ascii_alphanumeric() || c == '-';
    let mut code_end = code_start;
    while s.get(code_end).is_some_and(|&c| in_code(c)) {
        code_end += 1;
    }
    if code_end == code_start {
        return false;
    }
    if s.get(code_end) == Some(&'★') {
        code_end += 1;
    }
    skip_space(s, code_end) == s.len()
}

/// Removes the first (leftmost) set-code suffix, as `re.sub` does with `$` anchoring.
fn strip_set_suffix(s: &[char]) -> Vec<char> {
    for a in 0..s.len() {
        if is_space(s[a]) && (a == 0 || !is_space(s[a - 1])) && is_set_suffix(&s[a..]) {
            return s[..a].to_vec();
        }
    }
    s.to_vec()
}

fn strip_archidekt(rest: &[char], tags: &mut BTreeSet<String>) -> (Vec<char>, Option<Zone>) {
    let mut zone = None;
    let mut from = 0;
    while let Some((a, b)) = bracket(rest, from) {
        let inside: String = rest[a + 1..b - 1].iter().collect();
        for raw in inside.split(',') {
            let chars: Vec<char> = raw.chars().collect();
            let cleaned: String = replace_all(&chars, "", brace).iter().collect();
            let cat = strip(&cleaned);
            if cat.is_empty() {
                continue;
            }
            let lower = crate::model::text::casefold(cat);
            let section = SECTIONS.iter().find(|(name, _)| lower == *name);
            match section {
                Some(&(name, z)) if !matches!(name, "deck" | "main" | "mainboard") => {
                    zone = Some(z);
                }
                _ => {
                    tags.insert(normalize(cat));
                }
            }
        }
        from = b;
    }
    (replace_all(rest, " ", bracket), zone)
}

fn strip_moxfield(rest: &[char], tags: &mut BTreeSet<String>) -> Vec<char> {
    let mut from = 0;
    while let Some((_, e, t)) = hashtag(rest, from) {
        tags.insert(normalize(&rest[t..e].iter().collect::<String>()));
        from = e;
    }
    replace_all(rest, " ", |s, i| hashtag(s, i).map(|(a, e, _)| (a, e)))
}

/// Python's `int()` of a quantity, saturated (a quantity this large is unsupported anyway).
fn quantity_value(digits: &[char]) -> i64 {
    digits
        .iter()
        .try_fold(0i64, |acc, &c| {
            acc.checked_mul(10)?
                .checked_add(i64::from(digit_value(c).unwrap_or(0)))
        })
        .unwrap_or(i64::MAX)
}

/// Parses a text decklist; cards with the same name in the same zone are merged.
///
/// # Errors
/// [`Error::Parse`] with Python's line, column and message; validation errors from the
/// deck itself (as Python).
pub fn parse_decklist(text: &str, fmt: Format) -> Result<Deck> {
    if text.chars().count() > MAX_INPUT {
        return Err(parse_error(
            format!("decklist longer than {MAX_INPUT} characters"),
            1,
            1,
        ));
    }
    let use_arch = matches!(fmt, Format::Auto | Format::Archidekt);
    let use_mox = matches!(fmt, Format::Auto | Format::Moxfield);
    let mut zone = Zone::Library;
    let mut order: Vec<(Zone, String)> = Vec::new();
    let mut merged: HashMap<(Zone, String), (String, i64, BTreeSet<String>)> = HashMap::new();
    for (index, raw) in split_lines(text).into_iter().enumerate() {
        let lineno = index + 1;
        let line: Vec<char> = strip(raw).chars().collect();
        if line.is_empty() {
            continue;
        }
        if let Some(z) = section(&line) {
            zone = z;
            continue;
        }
        if line.starts_with(&['/', '/']) {
            continue;
        }
        let Some((digits, rest_at)) = quantity(&line) else {
            return Err(parse_error("expected '<quantity> <card name>'", lineno, 1));
        };
        let qty = quantity_value(digits);
        if qty < 1 {
            return Err(parse_error("quantity must be at least 1", lineno, 1));
        }
        let mut tags = BTreeSet::new();
        let mut card_zone = None;
        let mut rest = replace_all(&line[rest_at..], " ", caret);
        if use_arch {
            let (r, z) = strip_archidekt(&rest, &mut tags);
            rest = r;
            card_zone = z;
        }
        if use_mox {
            rest = strip_moxfield(&rest, &mut tags);
        }
        rest = replace_all(&rest, " ", foil);
        rest = strip_set_suffix(&rest);
        let name = crate::model::text::collapse_whitespace(&rest.iter().collect::<String>());
        if name.is_empty() {
            return Err(parse_error("missing card name", lineno, rest_at + 1));
        }
        let z = card_zone.unwrap_or(zone);
        let key = (z, normalize(&name));
        let entry = merged.entry(key.clone()).or_insert_with(|| {
            order.push(key);
            (name, 0, BTreeSet::new())
        });
        entry.1 = entry.1.saturating_add(qty);
        entry.2.extend(tags);
    }
    if merged.is_empty() {
        return Err(parse_error("decklist is empty", 1, 1));
    }
    let cards = order
        .iter()
        .map(|key| {
            let (name, qty, tags) = &merged[key];
            Card::new(name, *qty, &tags.iter().cloned().collect::<Vec<_>>(), key.0)
        })
        .collect::<Result<Vec<_>>>()?;
    Deck::new(cards)
}

/// A tag as a single `#word`: spaces become hyphens, `#` is dropped.
#[must_use]
pub fn tag_token(tag: &str) -> String {
    let words: Vec<&str> = tag
        .split('#')
        .flat_map(|p| p.split(is_space))
        .filter(|w| !w.is_empty())
        .collect();
    words.join("-")
}

/// Writes `deck` as text that [`parse_decklist`] reads back (tags as `#tags`).
#[must_use]
pub fn format_decklist(deck: &Deck) -> String {
    let headers = [
        (Zone::Commander, "Commander"),
        (Zone::Library, "Deck"),
        (Zone::Sideboard, "Sideboard"),
        (Zone::Maybeboard, "Maybeboard"),
    ];
    let mut lines: Vec<String> = Vec::new();
    for (zone, header) in headers {
        let cards: Vec<&Card> = deck.cards().iter().filter(|c| c.zone() == zone).collect();
        if cards.is_empty() {
            continue;
        }
        if !lines.is_empty() {
            lines.push(String::new());
        }
        lines.push(header.to_owned());
        for c in cards {
            let mut tags = String::new();
            for token in c.tags().map(tag_token).filter(|t| !t.is_empty()) {
                tags.push_str(" #");
                tags.push_str(&token);
            }
            lines.push(format!("{} {}{tags}", c.quantity(), c.name()));
        }
    }
    lines.join("\n") + "\n"
}

#[cfg(test)]
mod tests {
    use super::*;

    fn summary(deck: &Deck) -> Vec<String> {
        deck.cards()
            .iter()
            .map(|c| {
                format!(
                    "{} {} [{}] {}",
                    c.quantity(),
                    c.name(),
                    c.tags().collect::<Vec<_>>().join(","),
                    c.zone().as_str()
                )
            })
            .collect()
    }

    fn err(text: &str) -> (String, usize, usize) {
        match parse_decklist(text, Format::Auto).unwrap_err() {
            Error::Parse {
                message,
                line,
                column,
            } => (message, line, column),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn reads_every_line_shape() {
        let text = "Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n4x Lightning Bolt (M11) 149 *F*\n\
                    1 Sol Ring #ramp #!artifact\n1x Arcane Signet [Ramp,Mana Rock{top}]\n\
                    2 Forest\n2 FOREST #land\n// a comment\nSideboard:\n1 Pyroblast\n1 Duress [Maybeboard]\n";
        assert_eq!(
            summary(&parse_decklist(text, Format::Auto).unwrap()),
            vec![
                "1 Atraxa, Praetors' Voice [] commander",
                "4 Lightning Bolt [] library",
                "1 Sol Ring [artifact,ramp] library",
                "1 Arcane Signet [mana rock,ramp] library",
                "4 Forest [land] library",
                "1 Pyroblast [] sideboard",
                "1 Duress [] maybeboard",
            ]
        );
    }

    #[test]
    fn formats_select_what_is_stripped() {
        let plain = parse_decklist("1 Sol Ring #ramp [Rock]", Format::Plain).unwrap();
        assert_eq!(
            summary(&plain),
            vec!["1 Sol Ring #ramp [Rock] []  library".replace("[]  ", "[] ")]
        );
        let mox = parse_decklist("1 Sol Ring #ramp [Rock]", Format::Moxfield).unwrap();
        assert_eq!(summary(&mox), vec!["1 Sol Ring [Rock] [ramp] library"]);
    }

    #[test]
    fn quantities_follow_pythons_regex() {
        assert_eq!(
            summary(&parse_decklist("4 x Bolt", Format::Auto).unwrap()),
            vec!["4 Bolt [] library"]
        );
        assert_eq!(
            summary(&parse_decklist("4 xavier", Format::Auto).unwrap()),
            vec!["4 xavier [] library"]
        );
        assert_eq!(
            summary(&parse_decklist("4 x", Format::Auto).unwrap()),
            vec!["4 x [] library"]
        );
        assert_eq!(
            summary(&parse_decklist("\u{663} Bolt", Format::Auto).unwrap()),
            vec!["3 Bolt [] library"]
        );
        assert_eq!(
            err("Bolt"),
            ("expected '<quantity> <card name>'".into(), 1, 1)
        );
        assert_eq!(
            err("4x"),
            ("expected '<quantity> <card name>'".into(), 1, 1)
        );
        assert_eq!(
            err("\n0 Bolt"),
            ("quantity must be at least 1".into(), 2, 1)
        );
        assert_eq!(err("4 #ramp"), ("missing card name".into(), 1, 3));
        assert_eq!(err(""), ("decklist is empty".into(), 1, 1));
    }

    #[test]
    fn section_names_use_pythons_ignorecase() {
        let deck = parse_decklist("\u{17f}ideboard\n1 A\nDECK:\n1 B", Format::Auto).unwrap(); // long s
        let dotless = parse_decklist("ma\u{131}n\n1 A\nDEC\u{212a}\n1 B", Format::Auto).unwrap(); // ı, Kelvin sign
        assert_eq!(summary(&dotless), vec!["1 A [] library", "1 B [] library"]);
        assert_eq!(summary(&deck), vec!["1 A [] sideboard", "1 B [] library"]);
        // A commented "Commanders" header still switches zone (Python: then the library is empty).
        let only_commander = parse_decklist("// Commanders :\n1 A", Format::Auto);
        assert!(matches!(only_commander, Err(Error::Validation { .. })));
    }

    #[test]
    fn set_suffixes_and_hashtags() {
        assert_eq!(
            summary(&parse_decklist("1 Bolt (2X2) 117a", Format::Auto).unwrap()),
            vec!["1 Bolt [] library"]
        );
        assert_eq!(
            summary(&parse_decklist("1 Bolt (SLD) 12★", Format::Auto).unwrap()),
            vec!["1 Bolt [] library"]
        );
        assert_eq!(
            summary(&parse_decklist("1 Bolt (X) 1", Format::Auto).unwrap()),
            vec!["1 Bolt (X) 1 [] library"]
        );
        assert_eq!(
            summary(&parse_decklist("1 A#b #c#d #!", Format::Auto).unwrap()),
            vec!["1 A#b #d [!,c] library"]
        );
    }

    #[test]
    fn writes_text_that_reads_back() {
        let deck = parse_decklist(
            "Commander\n1 Atraxa\nDeck\n2 Sol Ring #ramp #mana-rock\n",
            Format::Auto,
        )
        .unwrap();
        let text = format_decklist(&deck);
        assert_eq!(
            text,
            "Commander\n1 Atraxa\n\nDeck\n2 Sol Ring #mana-rock #ramp\n"
        );
        assert_eq!(parse_decklist(&text, Format::Auto).unwrap(), deck);
        assert_eq!(tag_token(" mana  #rock "), "mana-rock");
    }
}
