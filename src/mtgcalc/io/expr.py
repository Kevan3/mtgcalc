"""Plain-text condition syntax: parser and canonical printer (LLD §7.2, FR-37, NFR-14).

Example::

    lands >= 3 @T3 AND (any(ramp, card:"Sol Ring") >= 1) @T2 GIVEN lands >= 2

Precedence, loosest first: ``->``/IMPLIES < OR < XOR < AND < NOT < ``@`` binding.
The printer parenthesizes conservatively so that ``parse(format(q)) == q`` always holds.
Hand-written recursive descent; input is never evaluated as code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mtgcalc.errors import ParseError, ValidationError
from mtgcalc.model.conditions import (
    OPS,
    And,
    Assignable,
    At,
    AtLeast,
    Between,
    Compare,
    Condition,
    Const,
    Demand,
    Exactly,
    Implies,
    Not,
    Op,
    Or,
    Query,
    Xor,
)
from mtgcalc.model.selectors import AllOf, AnyOf, CardName, Everything, NoneOf, Selector, Tag

MAX_LENGTH = 10_000
MAX_DEPTH = 64
KEYWORDS = frozenset(
    {
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
    }
)
_IDENT = r"[A-Za-z_](?:[A-Za-z0-9_']|-(?=[A-Za-z0-9_]))*"
_TOKEN = re.compile(
    rf"""(?P<ws>\s+)
    |(?P<string>"(?:[^"\\]|\\.)*")
    |(?P<int>\d+)
    |(?P<arrow>->)
    |(?P<op>>=|<=|==|!=|<|>)
    |(?P<dotdot>\.\.)
    |(?P<ident>{_IDENT})
    |(?P<punct>[(),@:])""",
    re.VERBOSE,
)
_IDENT_FULL = re.compile(_IDENT)


@dataclass(frozen=True, slots=True)
class _Tok:
    kind: str
    text: str
    col: int

    @property
    def word(self) -> str:
        return self.text.casefold() if self.kind == "ident" else ""


def _tokenize(text: str) -> list[_Tok]:
    if len(text) > MAX_LENGTH:
        raise ParseError(f"expression longer than {MAX_LENGTH} characters")
    toks: list[_Tok] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None:
            raise ParseError(f"unexpected character {text[pos]!r}", 1, pos + 1)
        kind = m.lastgroup
        assert kind is not None
        if kind != "ws":
            toks.append(_Tok(kind, m.group(), pos + 1))
        pos = m.end()
    toks.append(_Tok("eof", "", len(text) + 1))
    return toks


class _Parser:
    def __init__(self, text: str) -> None:
        self.toks = _tokenize(text)
        self.i = 0
        self.depth = 0

    # -- token helpers -----------------------------------------------------------
    @property
    def tok(self) -> _Tok:
        return self.toks[self.i]

    def error(self, msg: str) -> ParseError:
        return ParseError(f"{msg} (found {self.tok.text or 'end of input'!r})", 1, self.tok.col)

    def take(self) -> _Tok:
        t = self.tok
        self.i += 1
        return t

    def is_word(self, *words: str) -> bool:
        return self.tok.word in words

    def expect_word(self, word: str) -> None:
        if not self.is_word(word):
            raise self.error(f"expected {word!r}")
        self.take()

    def expect(self, kind: str, text: str | None = None) -> _Tok:
        if self.tok.kind != kind or (text is not None and self.tok.text != text):
            raise self.error(f"expected {text or kind!r}")
        return self.take()

    def accept(self, kind: str, text: str) -> bool:
        if self.tok.kind == kind and self.tok.text == text:
            self.take()
            return True
        return False

    def integer(self) -> int:
        return int(self.expect("int").text)

    def enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise self.error(f"nesting deeper than {MAX_DEPTH}")

    # -- grammar -----------------------------------------------------------------
    def selector_only(self) -> Selector:
        sel = self.selector()
        if self.tok.kind != "eof":
            raise self.error("unexpected trailing input")
        return sel

    def query(self, turn: int) -> Query:
        cond = self.expr()
        given = None
        if self.is_word("given"):
            self.take()
            given = self.expr()
        if self.tok.kind != "eof":
            raise self.error("unexpected trailing input")
        return Query(cond, given, turn)

    def expr(self) -> Condition:
        self.enter()
        left = self.or_expr()
        if self.tok.kind == "arrow" or self.is_word("implies"):
            self.take()
            left = Implies(left, self.expr())
        self.depth -= 1
        return left

    def or_expr(self) -> Condition:
        items = [self.xor_expr()]
        while self.is_word("or"):
            self.take()
            items.append(self.xor_expr())
        return items[0] if len(items) == 1 else Or(tuple(items))

    def xor_expr(self) -> Condition:
        left = self.and_expr()
        while self.is_word("xor"):
            self.take()
            left = Xor(left, self.and_expr())
        return left

    def and_expr(self) -> Condition:
        items = [self.unary()]
        while self.is_word("and"):
            self.take()
            items.append(self.unary())
        return items[0] if len(items) == 1 else And(tuple(items))

    def unary(self) -> Condition:
        if self.is_word("not"):
            self.take()
            self.enter()
            inner = self.unary()
            self.depth -= 1
            return Not(inner)
        return self.postfix()

    def postfix(self) -> Condition:
        node = self.primary()
        if self.accept("punct", "@"):
            node = At(self.turn_ref(), node)
        return node

    def turn_ref(self) -> int:
        if self.tok.kind == "int":
            return self.integer()
        if self.is_word("turn"):
            self.take()
            return self.integer()
        if self.tok.kind == "ident" and re.fullmatch(r"[tT]\d+", self.tok.text):
            return int(self.take().text[1:])
        raise self.error("expected a turn such as T3")

    def primary(self) -> Condition:
        if self.accept("punct", "("):
            inner = self.expr()
            self.expect("punct", ")")
            return inner
        if self.is_word("true", "false"):
            return Const(self.take().word == "true")
        if self.is_word("atleast", "exactly"):
            kind = self.take().word
            self.expect("punct", "(")
            n = self.integer()
            items: list[Condition] = []
            while self.accept("punct", ","):
                items.append(self.expr())
            self.expect("punct", ")")
            if not items:
                raise self.error(f"{kind} needs at least one condition")
            return AtLeast(n, tuple(items)) if kind == "atleast" else Exactly(n, tuple(items))
        if self.is_word("assign"):
            self.take()
            self.expect("punct", "(")
            demands = [self.demand()]
            while self.accept("punct", ","):
                demands.append(self.demand())
            self.expect("punct", ")")
            return Assignable(tuple(demands))
        return self.comparison()

    def demand(self) -> Demand:
        sel = self.selector()
        self.expect("op", ">=")
        need = self.integer()
        if need < 1:
            raise self.error("demand must be at least 1")
        return Demand(sel, need)

    def comparison(self) -> Condition:
        sel = self.selector()
        if self.is_word("in"):
            self.take()
            lo = self.integer()
            self.expect("dotdot")
            hi = self.integer()
            if lo > hi:
                raise self.error("range must satisfy lo <= hi")
            return Between(sel, lo, hi)
        op = self.expect("op").text
        assert op in OPS
        op_: Op = op  # type: ignore[assignment]
        return Compare(sel, op_, self.integer())

    def selector(self) -> Selector:
        self.enter()
        try:
            t = self.tok
            if t.kind != "ident":
                raise self.error("expected a selector")
            word = t.word
            if word in ("tag", "card"):
                self.take()
                self.expect("punct", ":")
                raw = self.expect("string").text
                value = re.sub(r"\\(.)", r"\1", raw[1:-1])
                try:
                    return Tag(value) if word == "tag" else CardName(value)
                except ValidationError as e:
                    raise self.error(e.message) from None
            if word in ("any", "all", "none"):
                self.take()
                self.expect("punct", "(")
                items = [self.selector()]
                while self.accept("punct", ","):
                    items.append(self.selector())
                self.expect("punct", ")")
                if word == "any":
                    return AnyOf(tuple(items))
                if word == "all":
                    return AllOf(tuple(items))
                return NoneOf(tuple(items))
            if word == "everything":
                self.take()
                return Everything()
            if word in KEYWORDS:
                raise self.error(f'{t.text!r} is a keyword; write tag:"{t.text}"')
            self.take()
            return Tag(t.text)
        finally:
            self.depth -= 1


def parse_query(text: str, turn: int = 0) -> Query:
    """Parse ``text`` into a :class:`Query` (default checkpoint ``turn``)."""
    try:
        return _Parser(text).query(turn)
    except RecursionError:
        raise ParseError("expression nested too deeply") from None


def parse_condition(text: str) -> Condition:
    """Parse a condition without ``GIVEN``."""
    q = parse_query(text)
    if q.given is not None:
        raise ParseError("GIVEN is not allowed here")
    return q.condition


def parse_selector(text: str) -> Selector:
    """Parse a selector such as ``land``, ``card:"Sol Ring"`` or ``any(ramp, draw)``."""
    try:
        return _Parser(text).selector_only()
    except RecursionError:
        raise ParseError("selector nested too deeply") from None


# -- printer -------------------------------------------------------------------------
_PRIMARY = (Compare, Between, AtLeast, Exactly, Assignable, Const)


def _prec(c: Condition) -> int:
    match c:
        case Implies():
            return 1
        case Or():
            return 2
        case Xor():
            return 3
        case And():
            return 4
        case Not():
            return 5
        case _:
            return 6


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def format_selector(sel: Selector) -> str:
    """Canonical text of a selector."""
    match sel:
        case Tag(name):
            ok = _IDENT_FULL.fullmatch(name) and name.casefold() not in KEYWORDS
            ok = ok and not re.fullmatch(r"[tT]\d+", name)
            return name if ok else f"tag:{_quote(name)}"
        case CardName(name):
            return f"card:{_quote(name)}"
        case AnyOf(items) | AllOf(items) | NoneOf(items):
            word = {AnyOf: "any", AllOf: "all", NoneOf: "none"}[type(sel)]
            return f"{word}({', '.join(format_selector(s) for s in items)})"
        case Everything():
            return "everything"
    raise TypeError(sel)  # pragma: no cover


def format_condition(c: Condition) -> str:
    """Canonical text of a condition; ``parse_condition(format_condition(c)) == c``."""

    def child(x: Condition, parent: int) -> str:
        s = format_condition(x)
        return f"({s})" if _prec(x) <= parent else s

    match c:
        case Compare(sel, op, v):
            return f"{format_selector(sel)} {op} {v}"
        case Between(sel, lo, hi):
            return f"{format_selector(sel)} in {lo}..{hi}"
        case Const(v):
            return "true" if v else "false"
        case AtLeast(n, items) | Exactly(n, items):
            word = "atleast" if isinstance(c, AtLeast) else "exactly"
            return f"{word}({n}, {', '.join(format_condition(i) for i in items)})"
        case Assignable(demands):
            parts = ", ".join(f"{format_selector(d.sel)} >= {d.need}" for d in demands)
            return f"assign({parts})"
        case At(t, item):
            inner = format_condition(item)
            return f"{inner} @T{t}" if isinstance(item, _PRIMARY) else f"({inner}) @T{t}"
        case Not(item):
            return f"NOT {child(item, 4)}"
        case And(items):
            return " AND ".join(child(i, 4) for i in items)
        case Or(items):
            return " OR ".join(child(i, 2) for i in items)
        case Xor(a, b):
            return f"{child(a, 3)} XOR {child(b, 3)}"
        case Implies(a, b):
            return f"{child(a, 1)} -> {child(b, 1)}"
    raise TypeError(c)  # pragma: no cover


def format_query(q: Query) -> str:
    """Canonical text of a query (the default turn is not part of the text)."""
    text = format_condition(q.condition)
    return text if q.given is None else f"{text} GIVEN {format_condition(q.given)}"
