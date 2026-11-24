//! The rule language: parser and canonical printer (port of `mtgcalc.io.expr`, FR-37).
//!
//! ```text
//! lands >= 3 @T3 AND (any(ramp, card:"Sol Ring") >= 1) @T2 GIVEN lands >= 2
//! ```
//!
//! Precedence, loosest first: `->`/IMPLIES < OR < XOR < AND < NOT < `@` binding. The
//! lexer follows Python's `re` exactly (alternatives in order, Unicode `\s` and `\d`),
//! errors carry Python's messages and columns, and the printer parenthesizes so that
//! parsing the printed text gives the same condition back.

use num_bigint::BigUint;
use num_traits::ToPrimitive;

use crate::error::{Error, Result};
use crate::model::conditions::Cond;
use crate::model::selectors::Sel;
use crate::model::text::{digit_value, is_space, py_repr};
use crate::model::{Condition, Demand, Op, Query, Selector};

/// Longest expression accepted (NFR-14).
pub const MAX_LENGTH: usize = 10_000;
/// Deepest nesting accepted (NFR-14).
pub const MAX_DEPTH: usize = 64;

const KEYWORDS: [&str; 19] = [
    "and",
    "or",
    "xor",
    "not",
    "implies",
    "given",
    "true",
    "false",
    "in",
    "atleast",
    "exactly",
    "assign",
    "any",
    "all",
    "none",
    "everything",
    "tag",
    "card",
    "turn",
];

/// A parse error at line 1 (Python's `ParseError(message, line, column)`).
fn parse_error(message: impl Into<String>, column: usize) -> Error {
    Error::Parse {
        message: message.into(),
        line: 1,
        column,
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Kind {
    Str,
    Int,
    Arrow,
    Op,
    DotDot,
    Ident,
    Punct,
    Eof,
}

impl Kind {
    /// The token kind's name in Python's grammar (used in "expected ..." messages).
    fn name(self) -> &'static str {
        match self {
            Kind::Str => "string",
            Kind::Int => "int",
            Kind::Arrow => "arrow",
            Kind::Op => "op",
            Kind::DotDot => "dotdot",
            Kind::Ident => "ident",
            Kind::Punct => "punct",
            Kind::Eof => "eof",
        }
    }
}

#[derive(Clone, Debug)]
struct Tok {
    kind: Kind,
    text: String,
    /// 1-based column, in characters.
    col: usize,
}

impl Tok {
    /// The keyword this token spells (identifiers compare case-insensitively).
    fn word(&self) -> String {
        if self.kind == Kind::Ident {
            self.text.to_ascii_lowercase() // identifiers are ASCII
        } else {
            String::new()
        }
    }
}

fn ident_start(c: char) -> bool {
    c.is_ascii_alphabetic() || c == '_'
}

fn ident_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_'
}

/// Length in characters of an identifier at the start of `s` (0 if none):
/// `[A-Za-z_](?:[A-Za-z0-9_']|-(?=[A-Za-z0-9_]))*`.
fn ident_len(s: &[char]) -> usize {
    if !s.first().is_some_and(|&c| ident_start(c)) {
        return 0;
    }
    let mut n = 1;
    while let Some(&c) = s.get(n) {
        if ident_char(c) || c == '\'' || (c == '-' && s.get(n + 1).is_some_and(|&d| ident_char(d)))
        {
            n += 1;
        } else {
            break;
        }
    }
    n
}

/// Length of a double-quoted string at the start of `s` (0 if the alternative fails):
/// `"(?:[^"\\]|\\.)*"`, where `.` is any character but a newline.
fn string_len(s: &[char]) -> usize {
    if s.first() != Some(&'"') {
        return 0;
    }
    let mut n = 1;
    loop {
        match s.get(n) {
            Some('"') => return n + 1,
            Some('\\') => match s.get(n + 1) {
                Some(&c) if c != '\n' => n += 2,
                _ => return 0,
            },
            Some(_) => n += 1,
            None => return 0,
        }
    }
}

fn tokenize(text: &str) -> Result<Vec<Tok>> {
    let chars: Vec<char> = text.chars().collect();
    if chars.len() > MAX_LENGTH {
        return Err(parse_error(
            format!("expression longer than {MAX_LENGTH} characters"),
            1,
        ));
    }
    let mut toks = Vec::new();
    let mut pos = 0;
    while pos < chars.len() {
        let rest = &chars[pos..];
        let run = |pred: fn(char) -> bool| rest.iter().take_while(|&&c| pred(c)).count();
        let two: String = rest.iter().take(2).collect();
        // Python's alternatives, in order: the first that matches wins.
        let (kind, len) = if is_space(rest[0]) {
            (None, run(is_space))
        } else if let n @ 1.. = string_len(rest) {
            (Some(Kind::Str), n)
        } else if digit_value(rest[0]).is_some() {
            (Some(Kind::Int), run(|c| digit_value(c).is_some()))
        } else if two == "->" {
            (Some(Kind::Arrow), 2)
        } else if [">=", "<=", "==", "!="].contains(&two.as_str()) {
            (Some(Kind::Op), 2)
        } else if rest[0] == '<' || rest[0] == '>' {
            (Some(Kind::Op), 1)
        } else if two == ".." {
            (Some(Kind::DotDot), 2)
        } else if let n @ 1.. = ident_len(rest) {
            (Some(Kind::Ident), n)
        } else if "(),@:".contains(rest[0]) {
            (Some(Kind::Punct), 1)
        } else {
            return Err(parse_error(
                format!("unexpected character {}", py_repr(&rest[0].to_string())),
                pos + 1,
            ));
        };
        if let Some(kind) = kind {
            toks.push(Tok {
                kind,
                text: rest[..len].iter().collect(),
                col: pos + 1,
            });
        }
        pos += len;
    }
    toks.push(Tok {
        kind: Kind::Eof,
        text: String::new(),
        col: chars.len() + 1,
    });
    Ok(toks)
}

/// Python's `int()` of a run of `\d` characters, saturated into `i64` (counts never
/// exceed 65,535 and turns this large cannot be played, so saturation keeps the meaning).
fn saturate(n: &BigUint) -> i64 {
    n.to_i64().unwrap_or(i64::MAX)
}

struct Parser {
    toks: Vec<Tok>,
    i: usize,
    depth: usize,
}

impl Parser {
    fn new(text: &str) -> Result<Self> {
        Ok(Parser {
            toks: tokenize(text)?,
            i: 0,
            depth: 0,
        })
    }

    fn tok(&self) -> &Tok {
        &self.toks[self.i]
    }

    fn error(&self, msg: &str) -> Error {
        let t = self.tok();
        let found = if t.text.is_empty() {
            "end of input"
        } else {
            t.text.as_str()
        };
        parse_error(format!("{msg} (found {})", py_repr(found)), t.col)
    }

    fn take(&mut self) -> Tok {
        let t = self.toks[self.i].clone();
        self.i += 1;
        t
    }

    fn is_word(&self, words: &[&str]) -> bool {
        let w = self.tok().word();
        !w.is_empty() && words.contains(&w.as_str())
    }

    fn expect(&mut self, kind: Kind, text: Option<&str>) -> Result<Tok> {
        let t = self.tok();
        if t.kind != kind || text.is_some_and(|x| t.text != x) {
            let wanted = text.unwrap_or(kind.name());
            return Err(self.error(&format!("expected {}", py_repr(wanted))));
        }
        Ok(self.take())
    }

    fn accept(&mut self, kind: Kind, text: &str) -> bool {
        if self.tok().kind == kind && self.tok().text == text {
            self.take();
            true
        } else {
            false
        }
    }

    fn integer(&mut self) -> Result<BigUint> {
        let t = self.expect(Kind::Int, None)?;
        Ok(t.text.chars().fold(BigUint::default(), |acc, c| {
            acc * 10u8 + digit_value(c).unwrap_or(0)
        }))
    }

    fn enter(&mut self) -> Result<()> {
        self.depth += 1;
        if self.depth > MAX_DEPTH {
            return Err(self.error(&format!("nesting deeper than {MAX_DEPTH}")));
        }
        Ok(())
    }

    fn at_eof(&self) -> bool {
        self.tok().kind == Kind::Eof
    }

    fn query(&mut self, turn: i64) -> Result<Query> {
        let cond = self.expr()?;
        let mut given = None;
        if self.is_word(&["given"]) {
            self.take();
            given = Some(self.expr()?);
        }
        if !self.at_eof() {
            return Err(self.error("unexpected trailing input"));
        }
        Query::new(cond, given, turn)
    }

    fn expr(&mut self) -> Result<Condition> {
        self.enter()?;
        let mut left = self.or_expr()?;
        if self.tok().kind == Kind::Arrow || self.is_word(&["implies"]) {
            self.take();
            left = Condition::implies(left, self.expr()?);
        }
        self.depth -= 1;
        Ok(left)
    }

    fn or_expr(&mut self) -> Result<Condition> {
        let mut items = vec![self.xor_expr()?];
        while self.is_word(&["or"]) {
            self.take();
            items.push(self.xor_expr()?);
        }
        if items.len() == 1 {
            return Ok(items.remove(0));
        }
        Condition::or(items)
    }

    fn xor_expr(&mut self) -> Result<Condition> {
        let mut left = self.and_expr()?;
        while self.is_word(&["xor"]) {
            self.take();
            left = Condition::xor(left, self.and_expr()?);
        }
        Ok(left)
    }

    fn and_expr(&mut self) -> Result<Condition> {
        let mut items = vec![self.unary()?];
        while self.is_word(&["and"]) {
            self.take();
            items.push(self.unary()?);
        }
        if items.len() == 1 {
            return Ok(items.remove(0));
        }
        Condition::and(items)
    }

    fn unary(&mut self) -> Result<Condition> {
        if self.is_word(&["not"]) {
            self.take();
            self.enter()?;
            let inner = self.unary()?;
            self.depth -= 1;
            return Ok(Condition::not(inner));
        }
        self.postfix()
    }

    fn postfix(&mut self) -> Result<Condition> {
        let node = self.primary()?;
        if self.accept(Kind::Punct, "@") {
            let turn = self.turn_ref()?;
            return Condition::at(saturate(&turn), node);
        }
        Ok(node)
    }

    fn turn_ref(&mut self) -> Result<BigUint> {
        if self.tok().kind == Kind::Int {
            return self.integer();
        }
        if self.is_word(&["turn"]) {
            self.take();
            return self.integer();
        }
        let t = self.tok();
        let mut chars = t.text.chars();
        let t_then_digits = matches!(chars.next(), Some('t' | 'T'))
            && !t.text[1..].is_empty()
            && t.text[1..].chars().all(|c| c.is_ascii_digit());
        if t.kind == Kind::Ident && t_then_digits {
            let digits = self.take().text[1..].to_owned();
            return Ok(digits.parse::<BigUint>().unwrap_or_default());
        }
        Err(self.error("expected a turn such as T3"))
    }

    fn primary(&mut self) -> Result<Condition> {
        if self.accept(Kind::Punct, "(") {
            let inner = self.expr()?;
            self.expect(Kind::Punct, Some(")"))?;
            return Ok(inner);
        }
        if self.is_word(&["true", "false"]) {
            return Ok(Condition::constant(self.take().word() == "true"));
        }
        if self.is_word(&["atleast", "exactly"]) {
            let kind = self.take().word();
            self.expect(Kind::Punct, Some("("))?;
            let n = saturate(&self.integer()?);
            let mut items = Vec::new();
            while self.accept(Kind::Punct, ",") {
                items.push(self.expr()?);
            }
            self.expect(Kind::Punct, Some(")"))?;
            if items.is_empty() {
                return Err(self.error(&format!("{kind} needs at least one condition")));
            }
            return if kind == "atleast" {
                Condition::at_least(n, items)
            } else {
                Condition::exactly(n, items)
            };
        }
        if self.is_word(&["assign"]) {
            self.take();
            self.expect(Kind::Punct, Some("("))?;
            let mut demands = vec![self.demand()?];
            while self.accept(Kind::Punct, ",") {
                demands.push(self.demand()?);
            }
            self.expect(Kind::Punct, Some(")"))?;
            return Condition::assignable(demands);
        }
        self.comparison()
    }

    fn demand(&mut self) -> Result<Demand> {
        let sel = self.selector()?;
        self.expect(Kind::Op, Some(">="))?;
        let need = self.integer()?;
        if need < BigUint::from(1u8) {
            return Err(self.error("demand must be at least 1"));
        }
        Demand::new(sel, saturate(&need))
    }

    fn comparison(&mut self) -> Result<Condition> {
        let sel = self.selector()?;
        if self.is_word(&["in"]) {
            self.take();
            let lo = self.integer()?;
            self.expect(Kind::DotDot, None)?;
            let hi = self.integer()?;
            if lo > hi {
                return Err(self.error("range must satisfy lo <= hi"));
            }
            return Condition::between(sel, saturate(&lo), saturate(&hi));
        }
        let op = Op::parse(&self.expect(Kind::Op, None)?.text)?;
        let value = self.integer()?;
        Condition::compare(sel, op, saturate(&value))
    }

    fn selector(&mut self) -> Result<Selector> {
        self.enter()?;
        let out = self.selector_inner();
        self.depth -= 1;
        out
    }

    fn selector_inner(&mut self) -> Result<Selector> {
        let t = self.tok().clone();
        if t.kind != Kind::Ident {
            return Err(self.error("expected a selector"));
        }
        let word = t.word();
        match word.as_str() {
            "tag" | "card" => {
                self.take();
                self.expect(Kind::Punct, Some(":"))?;
                let raw = self.expect(Kind::Str, None)?.text;
                let value = unescape(&raw[1..raw.len() - 1]);
                let made = if word == "tag" {
                    Selector::tag(&value)
                } else {
                    Selector::card(&value)
                };
                made.map_err(|e| match e {
                    Error::Validation { message, .. } => self.error(&message),
                    other => other,
                })
            }
            "any" | "all" | "none" => {
                self.take();
                self.expect(Kind::Punct, Some("("))?;
                let mut items = vec![self.selector()?];
                while self.accept(Kind::Punct, ",") {
                    items.push(self.selector()?);
                }
                self.expect(Kind::Punct, Some(")"))?;
                match word.as_str() {
                    "any" => Selector::any_of(items),
                    "all" => Selector::all_of(items),
                    _ => Selector::none_of(items),
                }
            }
            "everything" => {
                self.take();
                Ok(Selector::everything())
            }
            w if KEYWORDS.contains(&w) => Err(self.error(&format!(
                "{} is a keyword; write tag:\"{}\"",
                py_repr(&t.text),
                t.text
            ))),
            _ => {
                self.take();
                Selector::tag(&t.text)
            }
        }
    }
}

/// `re.sub(r"\\(.)", r"\1", s)`: a backslash keeps the next character (not a newline).
fn unescape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\\' {
            if let Some(&next) = chars.peek() {
                if next != '\n' {
                    out.push(next);
                    chars.next();
                    continue;
                }
            }
        }
        out.push(c);
    }
    out
}

/// Parses `text` into a query (`turn` is the default checkpoint).
///
/// # Errors
/// [`Error::Parse`] with Python's message and column, or a validation error.
pub fn parse_query(text: &str, turn: i64) -> Result<Query> {
    Parser::new(text)?.query(turn)
}

/// Parses a condition without `GIVEN`.
///
/// # Errors
/// As [`parse_query`]; `GIVEN` is a parse error here.
pub fn parse_condition(text: &str) -> Result<Condition> {
    let q = parse_query(text, 0)?;
    if q.given.is_some() {
        return Err(parse_error("GIVEN is not allowed here", 1));
    }
    Ok(q.condition)
}

/// Parses a selector such as `land`, `card:"Sol Ring"` or `any(ramp, draw)`.
///
/// # Errors
/// As [`parse_query`].
pub fn parse_selector(text: &str) -> Result<Selector> {
    let mut p = Parser::new(text)?;
    let sel = p.selector()?;
    if !p.at_eof() {
        return Err(p.error("unexpected trailing input"));
    }
    Ok(sel)
}

// -- printer ---------------------------------------------------------------------------

fn quote(s: &str) -> String {
    format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""))
}

/// Canonical text of a selector.
#[must_use]
pub fn format_selector(sel: &Selector) -> String {
    match &sel.0 {
        Sel::Tag(name) => {
            let chars: Vec<char> = name.chars().collect();
            let plain = ident_len(&chars) == chars.len()
                && !KEYWORDS.contains(&name.to_ascii_lowercase().as_str())
                && !(name.len() > 1
                    && name.starts_with(['t', 'T'])
                    && name[1..].chars().all(|c| c.is_ascii_digit()));
            if plain {
                name.clone()
            } else {
                format!("tag:{}", quote(name))
            }
        }
        Sel::CardName(name) => format!("card:{}", quote(name)),
        Sel::AnyOf(items) | Sel::AllOf(items) | Sel::NoneOf(items) => {
            let word = match &sel.0 {
                Sel::AnyOf(_) => "any",
                Sel::AllOf(_) => "all",
                _ => "none",
            };
            let inner: Vec<String> = items.iter().map(format_selector).collect();
            format!("{word}({})", inner.join(", "))
        }
        Sel::Everything => "everything".to_owned(),
    }
}

fn precedence(c: &Condition) -> u8 {
    match &c.0 {
        Cond::Implies(..) => 1,
        Cond::Or(_) => 2,
        Cond::Xor(..) => 3,
        Cond::And(_) => 4,
        Cond::Not(_) => 5,
        _ => 6,
    }
}

fn op_text(op: Op) -> &'static str {
    match op {
        Op::Eq => "==",
        Op::Ne => "!=",
        Op::Lt => "<",
        Op::Le => "<=",
        Op::Gt => ">",
        Op::Ge => ">=",
    }
}

/// Canonical text of a condition; parsing it gives the same condition back.
#[must_use]
pub fn format_condition(c: &Condition) -> String {
    let child = |x: &Condition, parent: u8| {
        let s = format_condition(x);
        if precedence(x) <= parent {
            format!("({s})")
        } else {
            s
        }
    };
    let join = |items: &[Condition], sep: &str, parent: u8| {
        items
            .iter()
            .map(|i| child(i, parent))
            .collect::<Vec<_>>()
            .join(sep)
    };
    match &c.0 {
        Cond::Compare { sel, op, value } => {
            format!("{} {} {value}", format_selector(sel), op_text(*op))
        }
        Cond::Between { sel, lo, hi } => format!("{} in {lo}..{hi}", format_selector(sel)),
        Cond::Const(v) => (if *v { "true" } else { "false" }).to_owned(),
        Cond::AtLeast(n, items) | Cond::Exactly(n, items) => {
            let word = if matches!(c.0, Cond::AtLeast(..)) {
                "atleast"
            } else {
                "exactly"
            };
            let inner: Vec<String> = items.iter().map(format_condition).collect();
            format!("{word}({n}, {})", inner.join(", "))
        }
        Cond::Assignable(demands) => {
            let parts: Vec<String> = demands
                .iter()
                .map(|d| format!("{} >= {}", format_selector(&d.sel), d.need))
                .collect();
            format!("assign({})", parts.join(", "))
        }
        Cond::At(t, item) => {
            let inner = format_condition(item);
            let primary = matches!(
                item.0,
                Cond::Compare { .. }
                    | Cond::Between { .. }
                    | Cond::AtLeast(..)
                    | Cond::Exactly(..)
                    | Cond::Assignable(_)
                    | Cond::Const(_)
            );
            if primary {
                format!("{inner} @T{t}")
            } else {
                format!("({inner}) @T{t}")
            }
        }
        Cond::Not(item) => format!("NOT {}", child(item, 4)),
        Cond::And(items) => join(items, " AND ", 4),
        Cond::Or(items) => join(items, " OR ", 2),
        Cond::Xor(a, b) => format!("{} XOR {}", child(a, 3), child(b, 3)),
        Cond::Implies(a, b) => format!("{} -> {}", child(a, 1), child(b, 1)),
    }
}

/// Canonical text of a query (the default turn is not part of the text).
#[must_use]
pub fn format_query(q: &Query) -> String {
    let text = format_condition(&q.condition);
    match &q.given {
        None => text,
        Some(g) => format!("{text} GIVEN {}", format_condition(g)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse_err(text: &str) -> (String, usize) {
        match parse_query(text, 0).unwrap_err() {
            Error::Parse {
                message, column, ..
            } => (message, column),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn parses_and_prints_round_trip() {
        for text in [
            "land >= 3",
            "land >= 3 @T3 AND removal >= 1 @T3",
            "(land >= 3 AND ramp >= 1) @T2",
            "NOT (a == 1 OR b != 2)",
            "a < 1 XOR b > 2",
            "a >= 1 -> b >= 1",
            "land in 2..4",
            "card:\"Sol Ring\" >= 1",
            "tag:\"mana rock\" >= 1",
            "any(ramp, draw) >= 2",
            "all(land, ramp) >= 1",
            "none(land) >= 4",
            "everything >= 9",
            "atleast(2, a >= 1, b >= 1, c >= 1)",
            "exactly(1, a >= 1, b >= 1)",
            "assign(land >= 3, ramp >= 1)",
            "true AND false",
            "tag:\"and\" >= 1",
            "tag:\"t3\" >= 1",
        ] {
            let q = parse_query(text, 0).unwrap();
            assert_eq!(format_query(&q), text, "{text}");
            assert_eq!(parse_query(&format_query(&q), 0).unwrap(), q);
        }
        let q = parse_query("a >= 1 GIVEN b >= 1", 2).unwrap();
        assert_eq!(format_query(&q), "a >= 1 GIVEN b >= 1");
        assert_eq!(q.turn, 2);
    }

    #[test]
    fn turns_and_keywords_are_flexible() {
        let a = parse_query("land >= 3 @ T3", 0).unwrap();
        for text in [
            "land >= 3 @t3",
            "land >= 3 @3",
            "land >= 3 @ turn 3",
            "LAND >= 3 @T3",
        ] {
            assert_eq!(
                format_query(&parse_query(text, 0).unwrap()),
                format_query(&a),
                "{text}"
            );
        }
        assert_eq!(
            parse_query("a>=1 and b>=1", 0).unwrap(),
            parse_query("a >= 1 AND b >= 1", 0).unwrap()
        );
    }

    #[test]
    fn errors_match_python() {
        assert_eq!(
            parse_err("land >= "),
            ("expected 'int' (found 'end of input')".into(), 9)
        );
        assert_eq!(
            parse_err("land ! 3"),
            ("unexpected character '!'".into(), 6)
        );
        assert_eq!(
            parse_err("and >= 1"),
            (
                "'and' is a keyword; write tag:\"and\" (found 'and')".into(),
                1
            )
        );
        assert_eq!(
            parse_err("land in 4..2"),
            (
                "range must satisfy lo <= hi (found 'end of input')".into(),
                13
            )
        );
        assert_eq!(
            parse_err("land >= 1 @x"),
            ("expected a turn such as T3 (found 'x')".into(), 12)
        );
        assert_eq!(
            parse_err("atleast(1)"),
            (
                "atleast needs at least one condition (found 'end of input')".into(),
                11
            )
        );
        assert_eq!(
            parse_err("tag:\"  \" >= 1"),
            ("tag name must not be empty (found '>=')".into(), 10)
        );
        assert_eq!(parse_err("\"open"), ("unexpected character '\"'".into(), 1));
        assert!(matches!(
            parse_condition("a >= 1 GIVEN b >= 1"),
            Err(Error::Parse { .. })
        ));
        let deep = format!("{}a >= 1{}", "(".repeat(70), ")".repeat(70));
        assert!(parse_err(&deep).0.starts_with("nesting deeper than 64"));
        assert!(parse_err(&"x".repeat(MAX_LENGTH + 1))
            .0
            .starts_with("expression longer"));
    }

    #[test]
    fn numbers_are_python_ints() {
        // Arabic-Indic digits are \d in Python's re, and int() reads them.
        assert_eq!(
            parse_query("land >= \u{663}", 0).unwrap(),
            parse_query("land >= 3", 0).unwrap()
        );
        // Huge numbers keep their meaning (no count reaches them).
        let huge = parse_query("land < 99999999999999999999999", 0).unwrap();
        assert_eq!(format_query(&huge), format!("land < {}", i64::MAX));
    }

    #[test]
    fn selectors_parse_alone() {
        assert_eq!(
            format_selector(&parse_selector("any(ramp, card:\"Sol Ring\")").unwrap()),
            "any(ramp, card:\"Sol Ring\")"
        );
        assert!(parse_selector("ramp extra").is_err());
        assert_eq!(unescape(r#"a\"b\\c"#), "a\"b\\c");
    }
}
