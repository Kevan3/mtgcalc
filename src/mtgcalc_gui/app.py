"""The mtgcalc GUI: a guided, plain-language window (Tkinter).

Layout: steps 1-2 (your deck, how you play) on the left; one tab per question on the
right. All calculation and wording lives in :mod:`mtgcalc_gui.forms` and
:mod:`mtgcalc_gui.help`; this module only builds widgets and moves values around.
Calculations run on a worker thread so the window never freezes.
"""

from __future__ import annotations

import gc
import queue
import threading
import tkinter as tk
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from tkinter import filedialog, font, ttk
from typing import Literal, TypeVar

from mtgcalc import MtgCalcError, ParseError, Scenario, ValidationError
from mtgcalc_gui import forms
from mtgcalc_gui.forms import (
    ANY_CARD,
    FORMATS,
    KINDS,
    CardType,
    DeckSetup,
    Goal,
    HowMany,
    KeepRule,
    Kind,
    MulliganSetup,
    PlaySetup,
    Requirement,
    ResultView,
    Row,
    Settings,
    Vary,
)
from mtgcalc_gui.help import EXAMPLES, GETTING_STARTED, INTROS, RULES, TIPS, WORDS, Example

TURNS = ["opening hand", *(f"turn {t}" for t in range(1, 21))]
Getter = Callable[[], str]
T = TypeVar("T")
Work = Callable[[Scenario, Settings], ResultView]


def turn_of(label: str) -> int:
    """``"opening hand"`` -> 0, ``"turn 3"`` -> 3."""
    return 0 if label == TURNS[0] else int(label.split()[-1])


def turn_label(turn: int) -> str:
    """Inverse of :func:`turn_of`."""
    return TURNS[0] if turn == 0 else f"turn {turn}"


def number(text: str, what: str, low: int = 0) -> int:
    """Parse a whole number typed by the user, with a friendly error."""
    try:
        value = int(text.strip())
    except ValueError:
        raise ValidationError(what, f"'{text}' is not a whole number") from None
    if value < low:
        raise ValidationError(what, f"must be at least {low}")
    return value


def kind_of(text: str) -> Kind:
    """A requirement kind chosen in a drop-down."""
    for k in KINDS:
        if k == text:
            return k
    raise ValidationError("requirement", f"unknown choice '{text}'")


def friendly(e: MtgCalcError) -> str:
    """An error message for players (field name plus reason)."""
    if isinstance(e, ParseError):
        return f"your typed rule has a problem at character {e.column}: {e.message}"
    if isinstance(e, ValidationError):
        return f"{e.field}: {e.message}"
    return str(e)


# ---------------------------------------------------------------------------------------
# Small building blocks
# ---------------------------------------------------------------------------------------


class Tooltip:
    """Shows a help bubble when the mouse rests on a widget."""

    def __init__(self, widget: tk.Misc, text: str) -> None:
        self.widget, self.text = widget, text
        self.window: tk.Toplevel | None = None
        self.job: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _schedule(self, _event: object) -> None:
        self.job = self.widget.after(450, self._show)

    def _show(self) -> None:
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw,
            text=self.text,
            justify="left",
            background="#ffffe6",
            relief="solid",
            borderwidth=1,
            wraplength=380,
            padx=6,
            pady=4,
        ).pack()

    def _hide(self, _event: object) -> None:
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.window:
            self.window.destroy()
            self.window = None


def tip(widget: tk.Misc, key: str) -> None:
    """Attach the tooltip ``TIPS[key]``."""
    Tooltip(widget, TIPS[key])


def spin(
    parent: tk.Misc, value: int, low: int, high: int, width: int = 5
) -> tuple[ttk.Spinbox, Getter]:
    """A number box."""
    var = tk.StringVar(value=str(value))
    box = ttk.Spinbox(parent, from_=low, to=high, textvariable=var, width=width)
    return box, var.get


def choice(
    parent: tk.Misc,
    value: str,
    values: Sequence[str] | Callable[[], Sequence[str]],
    width: int = 12,
) -> tuple[ttk.Combobox, Getter]:
    """A drop-down list. ``values`` may be a function (re-read every time it opens)."""
    var = tk.StringVar(value=value)
    box = ttk.Combobox(parent, textvariable=var, width=width, state="readonly")
    if callable(values):
        source = values
        box.configure(postcommand=lambda: box.configure(values=list(source())))
        box.configure(values=list(source()))
    else:
        box.configure(values=list(values))
    return box, var.get


def text_entry(parent: tk.Misc, value: str, width: int = 12) -> tuple[ttk.Entry, Getter]:
    """A one-line text box."""
    var = tk.StringVar(value=value)
    return ttk.Entry(parent, textvariable=var, width=width), var.get


def toggle(widget: tk.Misc, show: bool, **pack: object) -> None:
    """Show or hide a widget managed by ``pack``."""
    if show:
        widget.pack(fill="x", anchor="w", pady=(4, 0), **pack)  # type: ignore[attr-defined]
    else:
        widget.pack_forget()  # type: ignore[attr-defined]


RowMaker = Callable[[ttk.Frame, tuple[str, ...] | None], list[Getter]]


class RowList(ttk.Frame):
    """An editable list: each row has a few inputs and a remove (x) button."""

    def __init__(
        self, master: tk.Misc, make_row: RowMaker, add_text: str, header: Sequence[str] = ()
    ) -> None:
        super().__init__(master)
        self.make_row = make_row
        self.rows: list[tuple[ttk.Frame, list[Getter]]] = []
        if header:
            head = ttk.Frame(self)
            for h in header:
                ttk.Label(head, text=h, foreground="#555").pack(side="left", padx=(0, 18))
            head.pack(anchor="w")
        self.body = ttk.Frame(self)
        self.body.pack(anchor="w", fill="x")
        ttk.Button(self, text=f"+ {add_text}", command=self.add).pack(anchor="w", pady=(2, 0))

    def add(self, values: tuple[str, ...] | None = None) -> None:
        """Append a row (with default or given values)."""
        frame = ttk.Frame(self.body)
        getters = self.make_row(frame, values)
        entry = (frame, getters)
        ttk.Button(frame, text="x", width=2, command=lambda: self._remove(entry)).pack(
            side="left", padx=4
        )
        frame.pack(anchor="w", pady=1)
        self.rows.append(entry)

    def _remove(self, entry: tuple[ttk.Frame, list[Getter]]) -> None:
        entry[0].destroy()
        self.rows.remove(entry)

    def values(self) -> list[tuple[str, ...]]:
        """Current values of every row."""
        return [tuple(g() for g in getters) for _, getters in self.rows]

    def set(self, rows: Sequence[tuple[str, ...]]) -> None:
        """Replace all rows."""
        for frame, _ in self.rows:
            frame.destroy()
        self.rows.clear()
        for r in rows:
            self.add(r)


#: Colours of the kinds (as the web app's light theme), cycled so neighbours differ.
KIND_COLORS = ("#1f5f8b", "#2b6a2f", "#6b3fa0", "#8a4600", "#006a6e", "#9c2457")


class LineGroups(ttk.Frame):
    """Kinds of something (any kind will do), each a list of lines that must all hold.

    Used for the kinds of hand to keep and the kinds of good game, so both read the same:
    "<first title>" / "Or <title>", lines with "And also", and "Or ..." for another kind.
    """

    def __init__(
        self,
        master: tk.Misc,
        make_row: RowMaker,
        titles: tuple[str, str],
        add_group: str,
        empty: str,
        default: tuple[str, ...],
    ) -> None:
        super().__init__(master)
        self.make_row = make_row
        self.titles = titles
        self.default = default
        self.kinds: list[tuple[ttk.Frame, ttk.Label, RowList]] = []
        self.bars: list[tk.Frame] = []
        self.body = ttk.Frame(self)
        self.body.pack(anchor="w", fill="x")
        self.empty = ttk.Label(self.body, text=empty, foreground="#555")
        ttk.Button(self, text=f"+ {add_group}", command=self.add).pack(anchor="w", pady=(2, 0))
        self._relabel()

    def add(self, rows: Sequence[tuple[str, ...]] | None = None) -> None:
        """Append a kind (by default with one default line)."""
        outer = ttk.Frame(self.body)
        bar = tk.Frame(outer, width=5)  # a coloured bar down the kind's left edge
        bar.pack(side="left", fill="y", padx=(0, 6))
        frame = ttk.Frame(outer)
        frame.pack(side="left", fill="x")
        head = ttk.Frame(frame)
        title = ttk.Label(head, font=("TkDefaultFont", 10, "bold"))
        title.pack(side="left")
        lines = RowList(frame, self.make_row, "And also")
        entry = (outer, title, lines)
        ttk.Button(head, text="x", width=2, command=lambda: self._remove(entry)).pack(
            side="left", padx=4
        )
        head.pack(anchor="w")
        lines.pack(anchor="w", padx=(16, 0))
        lines.set(list(rows) if rows is not None else [self.default])
        outer.pack(anchor="w", fill="x", pady=(4, 0))
        self.kinds.append(entry)
        self.bars.append(bar)
        self._relabel()

    def _remove(self, entry: tuple[ttk.Frame, ttk.Label, RowList]) -> None:
        del self.bars[self.kinds.index(entry)]
        entry[0].destroy()
        self.kinds.remove(entry)
        self._relabel()

    def _relabel(self) -> None:
        for i, (_, title, _) in enumerate(self.kinds):
            color = KIND_COLORS[i % len(KIND_COLORS)]
            title.configure(text=self.titles[0] if i == 0 else self.titles[1], foreground=color)
            self.bars[i].configure(background=color)
        if self.kinds:
            self.empty.pack_forget()
        else:
            self.empty.pack(anchor="w")

    def values(self) -> list[list[tuple[str, ...]]]:
        """Each kind's lines."""
        return [rows.values() for _, _, rows in self.kinds]

    def set(self, kinds: Sequence[Sequence[tuple[str, ...]]]) -> None:
        """Replace every kind."""
        for frame, _, _ in self.kinds:
            frame.destroy()
        self.kinds.clear()
        self.bars.clear()
        for k in kinds:
            self.add(k)
        self._relabel()


# ---------------------------------------------------------------------------------------
# Step 1 and step 2
# ---------------------------------------------------------------------------------------


class DeckPanel(ttk.LabelFrame):
    """Step 1: the deck, as card types or as a pasted decklist."""

    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, text="Step 1 - Your deck", padding=8)
        formats = ttk.Frame(self)
        for name in FORMATS:
            b = ttk.Button(formats, text=name, command=partial(app.apply_format, name))
            b.pack(side="left", padx=(0, 4))
            tip(b, "format")
        formats.pack(anchor="w")

        # Only shown for card types: a decklist's size comes from the list itself.
        self.size_row = ttk.Frame(self)
        ttk.Label(self.size_row, text="Cards in your deck").pack(side="left")
        self.size_box, self.deck_size = spin(self.size_row, 60, 1, 500, 6)
        self.size_box.pack(side="left", padx=6)
        tip(self.size_box, "size")
        self.size_row.pack(anchor="w", pady=(8, 4))

        self.mode = tk.StringVar(value="types")
        modes = self.modes_row = ttk.Frame(self)
        by_types = ttk.Radiobutton(
            modes,
            text="List card types",
            value="types",
            variable=self.mode,
            command=self._mode_changed,
        )
        by_list = ttk.Radiobutton(
            modes,
            text="Decklist or link",
            value="decklist",
            variable=self.mode,
            command=self._mode_changed,
        )
        by_types.pack(side="left")
        by_list.pack(side="left", padx=8)
        tip(by_types, "mode_types")
        tip(by_list, "mode_list")
        modes.pack(anchor="w")

        self.types_frame = ttk.Frame(self)
        self.types = RowList(
            self.types_frame,
            self._type_row,
            "Add a card type",
            ("Card type", "How many", "Also counts as (optional)"),
        )
        self.types.pack(anchor="w")
        ttk.Label(
            self.types_frame, text="Cards you don't list count as 'other cards'.", foreground="#555"
        ).pack(anchor="w", pady=(4, 0))

        self.list_frame = ttk.Frame(self)
        link_row = ttk.Frame(self.list_frame)
        ttk.Label(link_row, text="Deck link").pack(side="left")
        self.link_box, self.link = text_entry(link_row, "", 34)
        self.link_box.pack(side="left", padx=4, fill="x", expand=True)
        self.link_box.bind("<Return>", lambda _e: app.import_link(self.link()))
        self.import_button = ttk.Button(
            link_row, text="Import", command=lambda: app.import_link(self.link())
        )
        self.import_button.pack(side="left")
        tip(self.link_box, "link")
        tip(self.import_button, "link")
        link_row.pack(fill="x", pady=(0, 4))
        head = ttk.Frame(self.list_frame)
        ttk.Label(head, text="One card per line, e.g. '4 Lightning Bolt #removal'").pack(
            side="left"
        )
        ttk.Button(head, text="Open file...", command=self._load).pack(side="right")
        head.pack(fill="x")
        self.decklist = tk.Text(self.list_frame, height=8, width=44, wrap="none")
        self.decklist.pack(fill="x")
        self._mode_changed()

    def _type_row(self, frame: ttk.Frame, values: tuple[str, ...] | None) -> list[Getter]:
        name, n, also = values or ("", "1", "")
        e, g1 = text_entry(frame, name, 12)
        s, g2 = spin(frame, int(n or 0), 0, 500)
        a, g3 = text_entry(frame, also, 16)
        for w, key in ((e, "type_name"), (s, "type_count"), (a, "type_also")):
            w.pack(side="left", padx=(0, 6))
            tip(w, key)
        return [g1, g2, g3]

    def _mode_changed(self) -> None:
        types = self.mode.get() == "types"
        if types:
            self.size_row.pack(anchor="w", pady=(8, 4), before=self.modes_row)
        else:
            self.size_row.pack_forget()
        toggle(self.types_frame, types)
        toggle(self.list_frame, not types)

    def _load(self) -> None:
        path = filedialog.askopenfilename(
            title="Open a decklist", filetypes=[("Text", "*.txt *.dek"), ("All", "*")]
        )
        if path:
            self.decklist.delete("1.0", "end")
            self.decklist.insert("1.0", Path(path).read_text(encoding="utf-8", errors="replace"))

    def show_decklist(self, text: str) -> None:
        """Put ``text`` in the decklist box and switch to it."""
        self.decklist.delete("1.0", "end")
        self.decklist.insert("1.0", text)
        self.mode.set("decklist")
        self._mode_changed()

    def value(self) -> DeckSetup:
        """Step 1 as a :class:`DeckSetup`."""
        types = []
        for name, n, also in self.types.values():
            if not name.strip():
                continue
            extra = tuple(a.strip() for a in also.split(",") if a.strip())
            types.append(CardType(name.strip(), number(n, f"how many '{name}'"), extra))
        mode: Literal["types", "decklist"] = (
            "decklist" if self.mode.get() == "decklist" else "types"
        )
        return DeckSetup(
            number(self.deck_size(), "cards in your deck", 1),
            tuple(types),
            mode,
            self.decklist.get("1.0", "end-1c"),
        )

    def set(self, deck: DeckSetup) -> None:
        """Fill in step 1."""
        self.size_box.set(str(deck.size))
        self.types.set([(t.name, str(t.count), ", ".join(t.also)) for t in deck.types])
        self.decklist.delete("1.0", "end")
        self.decklist.insert("1.0", deck.decklist)
        self.mode.set(deck.mode)
        self._mode_changed()


class PlayPanel(ttk.LabelFrame):
    """Step 2: going first, draws, and the mulligan plan."""

    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, text="Step 2 - How you play", padding=8)
        self.app = app
        self.first = tk.BooleanVar(value=True)
        a = ttk.Radiobutton(
            self, text="I go first (I skip my first draw)", value=True, variable=self.first
        )
        b = ttk.Radiobutton(
            self,
            text="I draw on turn 1 (going second, or multiplayer)",
            value=False,
            variable=self.first,
        )
        a.pack(anchor="w")
        b.pack(anchor="w")
        tip(a, "go_first")
        tip(b, "go_first")

        row = ttk.Frame(self)
        ttk.Label(row, text="Cards drawn each turn").pack(side="left")
        self.draws_box, self.draws = spin(row, 1, 0, 5)
        self.draws_box.pack(side="left", padx=6)
        tip(self.draws_box, "draws")
        row.pack(anchor="w", pady=(6, 0))

        ttk.Label(self, text="Extra cards drawn on certain turns (optional)").pack(
            anchor="w", pady=(6, 0)
        )
        self.extra = RowList(self, self._extra_row, "Add extra cards")
        self.extra.pack(anchor="w")

        ttk.Separator(self).pack(fill="x", pady=8)
        self.mull_on = tk.BooleanVar(value=False)
        c = ttk.Checkbutton(
            self,
            text="I mulligan bad opening hands",
            variable=self.mull_on,
            command=self._mull_changed,
        )
        c.pack(anchor="w")
        tip(c, "mull_on")
        self.mull = ttk.Frame(self)
        keep_label = ttk.Label(self.mull, text="Which hands do you keep?")
        keep_label.pack(anchor="w")
        tip(keep_label, "keep")
        self.keep = LineGroups(
            self.mull,
            self._keep_row,
            ("Keep a hand with all of these:", "Or keep a hand with all of these:"),
            "Or keep another kind of hand",
            "No kinds of hand: you keep every hand.",
            ("land", "2", "5"),
        )
        self.keep.pack(anchor="w")

        protect_label = ttk.Label(
            self.mull, text="When I put cards on the bottom, I keep these first:"
        )
        protect_label.pack(anchor="w", pady=(6, 0))
        tip(protect_label, "protect")
        self.protect = RowList(self.mull, self._protect_row, "Add a card type")
        self.protect.pack(anchor="w")

        last = ttk.Frame(self.mull)
        ttk.Label(last, text="Mulligan at most").pack(side="left")
        self.maxm_box, self.maxm = spin(last, 2, 0, 6, 3)
        self.maxm_box.pack(side="left", padx=4)
        ttk.Label(last, text="times").pack(side="left")
        tip(self.maxm_box, "max_mull")
        last.pack(anchor="w", pady=(6, 0))
        self.free = tk.BooleanVar(value=False)
        f = ttk.Checkbutton(
            self.mull, text="My first mulligan is free (multiplayer)", variable=self.free
        )
        f.pack(anchor="w")
        tip(f, "free")
        self._mull_changed()

    def _extra_row(self, frame: ttk.Frame, values: tuple[str, ...] | None) -> list[Getter]:
        turn, n = values or ("3", "1")
        ttk.Label(frame, text="On turn").pack(side="left")
        t, g1 = spin(frame, int(turn), 1, 20, 3)
        t.pack(side="left", padx=3)
        ttk.Label(frame, text="draw").pack(side="left")
        c, g2 = spin(frame, int(n), 0, 10, 3)
        c.pack(side="left", padx=3)
        ttk.Label(frame, text="extra").pack(side="left")
        tip(frame, "extra")
        return [g1, g2]

    def _keep_row(self, frame: ttk.Frame, values: tuple[str, ...] | None) -> list[Getter]:
        name, low, high = values or ("land", "1", "7")
        lo_box, g_low = spin(frame, int(low), 0, 7, 3)
        hi_box, g_high = spin(frame, int(high), 0, 7, 3)
        type_box, g_name = choice(frame, name, self.app.type_names, 10)
        lo_box.pack(side="left", padx=2)
        ttk.Label(frame, text="to").pack(side="left")
        hi_box.pack(side="left", padx=2)
        type_box.pack(side="left", padx=2)
        tip(frame, "keep")
        return [g_name, g_low, g_high]

    def _protect_row(self, frame: ttk.Frame, values: tuple[str, ...] | None) -> list[Getter]:
        name, n = values or ("land", "3")
        box, g1 = choice(frame, name, self.app.type_names, 10)
        box.pack(side="left")
        ttk.Label(frame, text="keep up to").pack(side="left", padx=4)
        s, g2 = spin(frame, int(n), 0, 7, 3)
        s.pack(side="left")
        tip(frame, "protect")
        return [g1, g2]

    def _mull_changed(self) -> None:
        toggle(self.mull, self.mull_on.get())

    def value(self) -> tuple[PlaySetup, MulliganSetup]:
        """Step 2 as setups."""
        extra = tuple(
            (number(t, "extra cards: turn", 1), number(n, "extra cards"))
            for t, n in self.extra.values()
        )
        play = PlaySetup(self.first.get(), number(self.draws(), "cards drawn each turn"), extra)
        mull = MulliganSetup(
            enabled=self.mull_on.get(),
            keep=tuple(
                tuple(
                    KeepRule(
                        name,
                        number(low, "keep: smallest number"),
                        number(high, "keep: largest number"),
                    )
                    for name, low, high in kind
                )
                for kind in self.keep.values()
            ),
            protect=tuple((n, number(k, f"keep up to ({n})")) for n, k in self.protect.values()),
            max_mulligans=number(self.maxm(), "mulligan at most"),
            free_first=self.free.get(),
        )
        return play, mull

    def set(self, play: PlaySetup, mull: MulliganSetup) -> None:
        """Fill in step 2."""
        self.first.set(play.go_first)
        self.draws_box.set(str(play.draws_per_turn))
        self.extra.set([(str(t), str(n)) for t, n in play.extra_draws])
        self.mull_on.set(mull.enabled)
        self.keep.set(
            [[(r.card_type, str(r.low), str(r.high)) for r in kind] for kind in mull.keep]
        )
        self.protect.set([(n, str(k)) for n, k in mull.protect])
        self.maxm_box.set(str(mull.max_mulligans))
        self.free.set(mull.free_first)
        self._mull_changed()


# ---------------------------------------------------------------------------------------
# The goal builder
# ---------------------------------------------------------------------------------------


class GoalBuilder(ttk.Frame):
    """Kinds of good game (any will do), each with lines like "[at least] [3] [land] [turn 3]"."""

    def __init__(self, master: tk.Misc, app: App, title: str, with_turns: bool = True) -> None:
        super().__init__(master)
        self.app = app
        self.with_turns = with_turns
        label = ttk.Label(self, text=title)
        label.pack(anchor="w")
        tip(label, "goal")
        self.lines = LineGroups(
            self,
            self._line,
            ("All of these:", "Or all of these:"),
            "Or another kind of good game",
            "No lines yet: add a kind of good game.",
            ("at least", "1", "land", "turn 3"),
        )
        self.lines.pack(anchor="w")
        self.custom_on = tk.BooleanVar(value=False)
        c = ttk.Checkbutton(
            self,
            text="Type my own rule instead (advanced)",
            variable=self.custom_on,
            command=self._custom_changed,
        )
        c.pack(anchor="w", pady=(4, 0))
        tip(c, "custom")
        self.custom_frame = ttk.Frame(self)
        self.custom_box, self.custom = text_entry(self.custom_frame, "", 52)
        self.custom_box.pack(side="left")
        self.lines.add()

    def _line(self, frame: ttk.Frame, values: tuple[str, ...] | None) -> list[Getter]:
        kind, n, what, turn = values or ("at least", "1", "land", "turn 3")
        k, g1 = choice(frame, kind, KINDS, 8)
        s, g2 = spin(frame, int(n), 0, 99, 3)
        t, g3 = choice(frame, what, self.app.type_names, 10)
        getters = [g1, g2, g3]
        for w in (k, s, t):
            w.pack(side="left", padx=(0, 4))
        if self.with_turns:
            w, g4 = choice(frame, turn, TURNS, 12)
            w.pack(side="left")
            getters.append(g4)
        return getters

    def _custom_changed(self) -> None:
        on = self.custom_on.get()
        if on and not self.custom().strip():
            try:  # start from the lines, so the user sees how rules are written
                text = forms.goal_as_text(self._from_lines(), with_turns=self.with_turns)
                self.custom_box.insert(0, text)
            except MtgCalcError:
                pass
        toggle(self.custom_frame, on)

    def _from_lines(self) -> Goal:
        def requirement(vals: tuple[str, ...]) -> Requirement:
            turn = turn_of(vals[3]) if self.with_turns else 0
            return Requirement(kind_of(vals[0]), number(vals[1], "requirement"), vals[2], turn)

        return Goal(tuple(tuple(requirement(v) for v in kind) for kind in self.lines.values()))

    def value(self) -> Goal:
        """The goal (a typed rule wins when ticked)."""
        goal = self._from_lines()
        if self.custom_on.get():
            goal = Goal(goal.groups, self.custom())
        return goal

    def set(self, goal: Goal) -> None:
        """Show a goal as kinds of lines."""
        self.lines.set(
            [
                [(r.kind, str(r.amount), r.card_type, turn_label(r.turn)) for r in group]
                for group in goal.groups
            ]
        )


# ---------------------------------------------------------------------------------------
# Question pages
# ---------------------------------------------------------------------------------------


class QuestionPage(ttk.Frame):
    """Intro, inputs, an Answer button, and the answer (sentence, table, legend)."""

    intro = ""

    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, padding=10)
        self.app = app
        ttk.Label(
            self, text=INTROS[self.intro], wraplength=640, justify="left", foreground="#444"
        ).pack(anchor="w")
        self.inputs = ttk.Frame(self)
        self.inputs.pack(anchor="w", fill="x", pady=8)
        self.build(self.inputs)
        self.button = ttk.Button(self, text="Answer", command=self.run)
        self.button.pack(anchor="w")
        self.headline = ttk.Label(self, text="", wraplength=660, justify="left", font=app.big_font)
        self.headline.pack(anchor="w", pady=(10, 2))
        self.details = ttk.Label(self, text="", wraplength=660, justify="left")
        self.details.pack(anchor="w")
        self.table = ttk.Frame(self)
        self.tree = ttk.Treeview(self.table, show="tree headings", height=10)
        bar = ttk.Scrollbar(self.table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="left", fill="y")
        self.legend = ttk.Label(self, text="", wraplength=660, justify="left", foreground="#555")

    def build(self, parent: ttk.Frame) -> None:
        """Create the page's inputs."""
        raise NotImplementedError

    def prepare(self) -> Work:
        """Read the inputs (UI thread) and return the work to do (worker thread)."""
        raise NotImplementedError

    def run(self) -> None:
        """The Answer button."""
        self.app.run(self)

    def show(self, view: ResultView) -> None:
        """Display an answer."""
        self.headline.configure(text=view.headline)
        self.details.configure(text="\n".join(view.details))
        self.tree.delete(*self.tree.get_children())
        if view.rows:
            self.tree.configure(columns=view.headers[1:])
            self.tree.heading("#0", text=view.headers[0])
            self.tree.column("#0", width=self._label_width(view.rows), stretch=False)
            for h in view.headers[1:]:
                self.tree.heading(h, text=h)
                self.tree.column(h, width=115, minwidth=80, anchor="e", stretch=True)
            expand = sum(1 + len(r.children) for r in view.rows) <= 40
            for r in view.rows:
                self._insert("", r, expand)
            self.table.pack(fill="both", expand=True, pady=(8, 0))
        else:
            self.table.pack_forget()
        legend = "\n".join(f"{k}: {v}" for k, v in view.legend)
        self.legend.configure(text=legend)
        if legend:
            self.legend.pack(anchor="w", pady=(4, 0))
        else:
            self.legend.pack_forget()

    def _label_width(self, rows: Sequence[Row], depth: int = 0) -> int:
        """Pixels needed for the first column (labels plus tree indentation)."""
        widest = 200
        for r in rows:
            widest = max(
                widest,
                self.app.text_font.measure(r.values[0]) + 24 * (depth + 1),
                self._label_width(r.children, depth + 1),
            )
        return min(widest, 430)

    def _insert(self, parent: str, row: Row, expand: bool) -> None:
        iid = self.tree.insert(
            parent, "end", text=row.values[0], values=row.values[1:], open=expand
        )
        for child in row.children:
            self._insert(iid, child, expand)


class ChancesPage(QuestionPage):
    """Question 1: what are my chances?"""

    intro = "chances"

    def build(self, parent: ttk.Frame) -> None:
        self.goal = GoalBuilder(parent, self.app, "A good game is when I have")
        self.goal.pack(anchor="w")
        self.only_on = tk.BooleanVar(value=False)
        c = ttk.Checkbutton(
            parent,
            text="Only count games where... (optional)",
            variable=self.only_on,
            command=self._only_changed,
        )
        c.pack(anchor="w", pady=(8, 0))
        tip(c, "only_if")
        self.only = GoalBuilder(parent, self.app, "Only count games where I have")

    def _only_changed(self) -> None:
        toggle(self.only, self.only_on.get())

    def prepare(self) -> Work:
        goal = self.goal.value()
        only = self.only.value() if self.only_on.get() else None
        return lambda sc, st: forms.chances(sc, goal, only, st)


class DrawsPage(QuestionPage):
    """Question 2: how many will I draw?"""

    intro = "draws"

    def build(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent)
        ttk.Label(row, text="Count").pack(side="left")
        self.what_box, self.what = choice(row, "land", self.app.type_names, 12)
        self.what_box.pack(side="left", padx=4)
        tip(self.what_box, "card_type")
        ttk.Label(row, text="up to").pack(side="left")
        self.last_box, self.last = choice(row, "turn 5", TURNS, 12)
        self.last_box.pack(side="left", padx=4)
        tip(self.last_box, "last_turn")
        row.pack(anchor="w")

    def prepare(self) -> Work:
        what, last = self.what(), turn_of(self.last())
        return lambda sc, st: forms.draws(sc, what, last, st)


class TurnsPage(QuestionPage):
    """Question 3: turn by turn."""

    intro = "turns"

    def build(self, parent: ttk.Frame) -> None:
        self.goal = GoalBuilder(parent, self.app, "I want to have", with_turns=False)
        self.goal.pack(anchor="w")
        row = ttk.Frame(parent)
        ttk.Label(row, text="Show every turn up to").pack(side="left")
        self.last_box, self.last = choice(row, "turn 8", TURNS[1:], 10)
        self.last_box.pack(side="left", padx=4)
        tip(self.last_box, "last_turn")
        row.pack(anchor="w", pady=(6, 0))

    def prepare(self) -> Work:
        goal, last = self.goal.value(), turn_of(self.last())
        return lambda sc, st: forms.turn_by_turn(sc, goal, last, st)


class MulliganPage(QuestionPage):
    """Question 4: should I mulligan?"""

    intro = "mulligan"

    def build(self, parent: ttk.Frame) -> None:
        self.goal = GoalBuilder(parent, self.app, "A good game is when I have")
        self.goal.pack(anchor="w")

    def prepare(self) -> Work:
        goal = self.goal.value()
        return lambda sc, st: forms.mulligan_advice(sc, goal, st)


class HowManyPage(QuestionPage):
    """Question 5: how many should I play?"""

    intro = "howmany"
    MODES = (
        ("one", "How many of one card type should I play?"),
        ("share", "How should I share cards between card types?"),
    )
    AIMS = (
        ("best", "The best chance I can get"),
        ("target", "A target chance I choose, with as few cards as possible"),
    )

    def build(self, parent: ttk.Frame) -> None:
        self.mode = tk.StringVar(value="one")
        for value, text in self.MODES:
            r = ttk.Radiobutton(
                parent, text=text, value=value, variable=self.mode, command=self._mode_changed
            )
            r.pack(anchor="w")
            tip(r, "hm_mode")
        label = ttk.Label(parent, text="Card types the program may change:")
        label.pack(anchor="w", pady=(6, 0))
        tip(label, "hm_vary")
        self.vary = RowList(parent, self._vary_row, "Add a card type")
        self.vary.pack(anchor="w")
        self.vary.add()
        self.slots_row = ttk.Frame(parent)
        ttk.Label(self.slots_row, text="Cards allowed between them").pack(side="left")
        self.slots_box, self.slots = spin(self.slots_row, 20, 0, 500, 5)
        self.slots_box.pack(side="left", padx=4)
        tip(self.slots_box, "hm_slots")
        self.aim_box = ttk.Frame(parent)
        ttk.Label(self.aim_box, text="Aim for:").pack(anchor="w")
        self.aim = tk.StringVar(value="target")
        for value, text in self.AIMS:
            r = ttk.Radiobutton(
                self.aim_box, text=text, value=value, variable=self.aim, command=self._mode_changed
            )
            r.pack(anchor="w")
            tip(r, "hm_aim")
        self.target_row = ttk.Frame(parent)
        ttk.Label(self.target_row, text="Target chance").pack(side="left")
        self.target_box, self.target = spin(self.target_row, 90, 1, 100, 4)
        self.target_box.pack(side="left", padx=4)
        ttk.Label(self.target_row, text="%").pack(side="left")
        tip(self.target_box, "hm_target")
        self.goal = GoalBuilder(parent, self.app, "A good game is when I have")
        self.goal.set(Goal.all_of(Requirement("at least", 4, "land", 4)))
        self._mode_changed()

    def _vary_row(self, frame: ttk.Frame, values: tuple[str, ...] | None) -> list[Getter]:
        name, lo, hi = values or ("land", "14", "40")
        box, g1 = choice(frame, name, lambda: self.app.type_names(include_any=False), 10)
        box.pack(side="left")
        ttk.Label(frame, text="from").pack(side="left", padx=4)
        a, g2 = spin(frame, int(lo), 0, 500, 4)
        a.pack(side="left")
        ttk.Label(frame, text="to").pack(side="left", padx=4)
        b, g3 = spin(frame, int(hi), 0, 500, 4)
        b.pack(side="left")
        return [g1, g2, g3]

    def _mode_changed(self) -> None:
        for widget in (self.slots_row, self.aim_box, self.target_row, self.goal):
            widget.pack_forget()
        toggle(self.slots_row, self.mode.get() == "share")
        self.aim_box.pack(anchor="w", pady=(6, 0))
        toggle(self.target_row, self.aim.get() == "target")
        self.goal.pack(anchor="w", pady=(8, 0))

    def prepare(self) -> Work:
        q = HowMany(
            mode="share" if self.mode.get() == "share" else "one",
            aim="best" if self.aim.get() == "best" else "target",
            vary=tuple(
                Vary(n, number(lo, f"'{n}' from"), number(hi, f"'{n}' to"))
                for n, lo, hi in self.vary.values()
            ),
            target_percent=number(self.target(), "target chance", 1),
            slots=number(self.slots(), "cards allowed"),
            goal=self.goal.value(),
        )
        deck = self.app.deck_panel.value()
        return lambda sc, st: forms.how_many(deck, sc, q, st)


# ---------------------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------------------


def text_window(master: tk.Misc, title: str, body: str) -> tk.Toplevel:
    """A read-only help window."""
    win = tk.Toplevel(master)
    win.title(title)
    text = tk.Text(win, width=88, height=36, wrap="word", font="TkFixedFont", padx=10, pady=8)
    text.insert("1.0", body)
    text.configure(state="disabled")
    text.pack(fill="both", expand=True)
    return win


class SettingsDialog(tk.Toplevel):
    """Technical options most people never need."""

    METHODS = (
        ("exact", "Calculate exactly (recommended)"),
        ("montecarlo", "Simulate games (approximate; answers show a range)"),
        ("auto", "Calculate exactly, but simulate if a question is too big"),
    )

    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.title("Settings")
        self.app = app
        s = app.settings
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both")
        self.method = tk.StringVar(value=s.method)
        ttk.Label(frame, text="How answers are worked out").pack(anchor="w")
        for value, text in self.METHODS:
            ttk.Radiobutton(frame, text=text, value=value, variable=self.method).pack(anchor="w")
        row = ttk.Frame(frame)
        ttk.Label(row, text="Games to simulate").pack(side="left")
        self.games_box, self.games = spin(row, s.games, 1000, 10_000_000, 10)
        self.games_box.pack(side="left", padx=4)
        row.pack(anchor="w", pady=(4, 0))
        self.fractions = tk.BooleanVar(value=s.fractions)
        ttk.Checkbutton(
            frame, text="Also show exact fractions (e.g. 1/3)", variable=self.fractions
        ).pack(anchor="w", pady=(8, 0))
        ttk.Button(frame, text="OK", command=self.save).pack(anchor="e", pady=(10, 0))

    def save(self) -> None:
        """Store the settings and close."""
        try:
            games = number(self.games(), "games to simulate", 1)
        except MtgCalcError as e:
            self.app.set_status(friendly(e), error=True)
            return
        method = self.method.get()
        self.app.settings = Settings(
            method="montecarlo"
            if method == "montecarlo"
            else "auto"
            if method == "auto"
            else "exact",
            games=games,
            fractions=self.fractions.get(),
        )
        self.destroy()


# ---------------------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------------------


class App(tk.Tk):
    """Main window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("MTG odds calculator")
        self.geometry("1320x880")
        self.settings = Settings()
        self.big_font = font.Font(size=12, weight="bold")
        self.text_font = font.nametofont("TkDefaultFont")
        self.status = tk.StringVar(
            value="Welcome! Describe your deck on the left, then pick a question on the "
            "right. New here? Try the Examples menu or Help > Getting started."
        )
        self._ui: queue.Queue[Callable[[], None]] = (
            queue.Queue()
        )  # results to apply on the UI thread
        self._busy = False
        self._build_menu()

        panes = ttk.PanedWindow(self, orient="horizontal")
        left = self._scrollable(panes)
        self.deck_panel = DeckPanel(left, self)
        self.deck_panel.pack(fill="x", padx=4, pady=4)
        self.play_panel = PlayPanel(left, self)
        self.play_panel.pack(fill="x", padx=4, pady=4)
        ttk.Button(left, text="Check my deck", command=self.check).pack(anchor="w", padx=8)
        self.pages = ttk.Notebook(panes)
        for title, cls in (
            ("What are my chances?", ChancesPage),
            ("How many will I draw?", DrawsPage),
            ("Turn by turn", TurnsPage),
            ("Should I mulligan?", MulliganPage),
            ("How many should I play?", HowManyPage),
        ):
            self.pages.add(cls(self.pages, self), text=title)
        panes.add(self.pages, weight=1)
        panes.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        self.status_label = ttk.Label(
            self, textvariable=self.status, padding=(8, 4), wraplength=1250
        )
        self.status_label.pack(fill="x")
        self.load_example(next(iter(EXAMPLES.values())), announce=False)

    def _build_menu(self) -> None:
        bar = tk.Menu(self)
        examples = tk.Menu(bar, tearoff=False)
        for name, ex in EXAMPLES.items():
            examples.add_command(label=name, command=partial(self.load_example, ex))
        bar.add_cascade(label="Examples", menu=examples)
        bar.add_command(label="Settings", command=lambda: SettingsDialog(self))
        helpm = tk.Menu(bar, tearoff=False)
        for title, body in (
            ("Getting started", GETTING_STARTED),
            ("What the words mean", WORDS),
            ("Writing your own rules", RULES),
        ):
            helpm.add_command(label=title, command=partial(text_window, self, title, body))
        bar.add_cascade(label="Help", menu=helpm)
        self.configure(menu=bar)

    def _scrollable(self, panes: ttk.PanedWindow) -> ttk.Frame:
        outer = ttk.Frame(panes)
        canvas = tk.Canvas(outer, width=480, highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="left", fill="y")
        panes.add(outer, weight=0)
        return inner

    # -- shared helpers ---------------------------------------------------------------------
    def question_pages(self) -> list[QuestionPage]:
        """The question tabs, in order."""
        return [w for w in self.pages.winfo_children() if isinstance(w, QuestionPage)]

    def type_names(self, include_any: bool = True) -> list[str]:
        """Card type names for the drop-downs (read live from step 1)."""
        try:
            names = forms.type_names(self.deck_panel.value())
        except MtgCalcError:
            names = [ANY_CARD]
        return names if include_any else [n for n in names if n != ANY_CARD]

    def apply_format(self, name: str) -> None:
        """Format buttons: deck size, going first, free mulligan."""
        size, first, free = FORMATS[name]
        self.deck_panel.size_box.set(str(size))
        self.play_panel.first.set(first)
        self.play_panel.free.set(free)
        who = "you go first" if first else "everyone draws on turn 1"
        self.set_status(f"{name}: {size} cards, {who}{', first mulligan free' if free else ''}.")

    def load_example(self, ex: Example, announce: bool = True) -> None:
        """Fill everything in from an example."""
        self.deck_panel.set(ex.deck)
        self.play_panel.set(ex.play, ex.mulligan)
        for page in self.question_pages():
            goal = getattr(page, "goal", None)
            if isinstance(goal, GoalBuilder) and goal.with_turns:
                goal.set(ex.goal)
        if announce:
            self.set_status("Example loaded. Pick a question on the right and press Answer.")

    def scenario(self) -> Scenario | None:
        """Steps 1-2 as a scenario, or ``None`` (with the problem shown at the bottom)."""
        try:
            play, mull = self.play_panel.value()
            return forms.build_scenario(self.deck_panel.value(), play, mull)
        except MtgCalcError as e:
            self.set_status(f"Please check your deck: {friendly(e)}", error=True)
            return None

    def check(self) -> None:
        """The 'Check my deck' button."""
        sc = self.scenario()
        if sc is not None:
            self.set_status(forms.describe_scenario(sc))

    # -- answering questions ---------------------------------------------------------------
    def run(self, page: QuestionPage) -> None:
        """Answer a question on a worker thread."""
        sc = self.scenario()
        if sc is None:
            return
        try:
            work = page.prepare()
        except MtgCalcError as e:
            self.set_status(f"Please check the question: {friendly(e)}", error=True)
            return
        settings = self.settings

        def answered(view: ResultView) -> None:
            page.show(view)
            self.set_status("Done. Hover over any field for an explanation.")

        self.background(
            lambda: work(sc, settings),
            answered,
            button=page.button,
            busy="Working it out...",
            failed="Can't answer that yet",
        )

    def import_link(self, link: str) -> None:
        """Download the deck at ``link`` into the decklist box (worker thread)."""

        def imported(result: forms.ImportedDeck) -> None:
            self.deck_panel.show_decklist(result.text)
            self.set_status(result.summary)

        self.background(
            lambda: forms.import_deck(link),
            imported,
            button=self.deck_panel.import_button,
            busy="Downloading the deck...",
            failed="Could not import the deck",
        )

    def background(
        self,
        work: Callable[[], T],
        done: Callable[[T], None],
        *,
        button: ttk.Button,
        busy: str,
        failed: str,
    ) -> None:
        """Run ``work`` on a worker thread, then ``done(result)`` on the UI thread.

        Only one job runs at a time. Errors are shown at the bottom of the window as
        ``"<failed>: <reason>"``; they are never swallowed.
        """
        if self._busy:
            return
        self._busy = True
        button.configure(state="disabled")
        self.set_status(busy)
        # Free leftover Tk objects (e.g. from removed rows) here on the UI thread. Otherwise
        # Python's garbage collector may free them on the worker thread, and Tk objects
        # must only ever be touched from the UI thread.
        gc.collect()

        def finish(apply: Callable[[], None]) -> None:  # runs on the UI thread
            self._busy = False
            button.configure(state="normal")
            apply()

        def job() -> None:  # runs on the worker thread; never touches Tk
            try:
                result = work()
            except MtgCalcError as e:
                message = f"{failed}: {friendly(e)}"
                self._ui.put(partial(finish, partial(self.set_status, message, True)))
            except Exception as e:  # unexpected: show the type to help debugging
                message = f"Something went wrong ({type(e).__name__}: {e})."
                self._ui.put(partial(finish, partial(self.set_status, message, True)))
            else:
                self._ui.put(partial(finish, partial(done, result)))

        threading.Thread(target=job, daemon=True).start()
        self.after(50, self._poll)

    def _poll(self) -> None:
        """Apply finished jobs on the UI thread; keep polling while one is running."""
        try:
            apply = self._ui.get_nowait()
        except queue.Empty:
            self.after(50, self._poll)
            return
        apply()

    def set_status(self, text: str, error: bool = False) -> None:
        """Show a message at the bottom of the window."""
        self.status.set(text)
        self.status_label.configure(foreground="#b00020" if error else "")


def main() -> None:
    """Launch the GUI."""
    App().mainloop()


if __name__ == "__main__":
    main()
