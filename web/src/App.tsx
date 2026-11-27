import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";

import { EXAMPLES, initialState, reducer, type Action } from "./app/state.ts";
import { loadState, saveState } from "./app/storage.ts";
import { useLiveAnswer } from "./app/useLiveAnswer.ts";
import { useFocusedField, useSettled } from "./app/useSettled.ts";
import { AnswerDetails } from "./components/AnswerDetails.tsx";
import { AnswerPanel } from "./components/AnswerPanel.tsx";
import { DeckStep } from "./components/DeckStep.tsx";
import type { Problem } from "./components/Field.tsx";
import { GoalStep } from "./components/GoalStep.tsx";
import { PlayStep } from "./components/PlayStep.tsx";
import type { WorkerFactory } from "./engine/transport.ts";
import { MAX_TURN } from "./forms/model.ts";
import type { Core } from "./engine/core.ts";
import {
  lastPlayableTurn,
  offeredNames,
  parseForm,
  parseWhole,
  typeLabels,
  type FieldId,
} from "./forms/parse.ts";
import { buildRequest } from "./forms/request.ts";
import { readDecklist, ruleText } from "./forms/text.ts";
import { ABOUT, INTRO, TITLE } from "./text/copy.ts";

/** How long typing must pause before a problem is shown anyway (FR-94). */
export const SETTLE_MS = 1000;

/** Problems about a whole section rather than one input. */
const SECTION_OF: Partial<Record<FieldId, string>> = { types: "type:", goal: "goal:", protect: "protect:" };

interface Props {
  /** The core on the page, for reading decklists and rules while typing. */
  readonly core: Core;
  readonly makeWorker?: WorkerFactory;
  /** Remember the form in this browser (off in tests). */
  readonly remember?: boolean;
}

export function App({ core, makeWorker, remember = true }: Props): ReactNode {
  const [state, dispatch] = useReducer(
    reducer,
    undefined,
    () => (remember ? loadState() : null) ?? initialState(),
  );
  const { form } = state;
  const parsed = useMemo(() => parseForm(form, core), [form, core]);
  const answered = useLiveAnswer(parsed, form.types, ...(makeWorker ? [makeWorker] : []));
  // "How many should I play?" shows only results for the form as it is now: a search not
  // yet run, or a form with a problem, would show numbers for a setup that is gone.
  const hideOld = answered.waiting || (form.question === "howmany" && answered.invalid);
  const live = hideOld ? { ...answered, view: null } : answered;
  const labels = useMemo(
    () => (form.deckMode === "list" ? {} : typeLabels(form.types)),
    [form.deckMode, form.types],
  );
  // What the decklist says, shown even while other parts of the form have problems.
  const decklist = useMemo(() => {
    if (form.deckMode !== "list") return undefined;
    const read = readDecklist(core, form.decklist);
    return read.ok ? read.value : undefined;
  }, [core, form.deckMode, form.decklist]);
  const names = useMemo(() => offeredNames(form, decklist), [form, decklist]);
  // The lines written as a rule, to start the rule box from.
  const linesAsRule = useMemo(() => {
    if (!parsed.ok || form.useRule) return null;
    const query = buildRequest({ ...parsed.setup, question: { kind: "chances" } })["query"] as {
      condition: unknown;
    };
    return ruleText(core, query.condition);
  }, [core, parsed, form.useRule]);

  useEffect(() => {
    if (remember) saveState(state);
  }, [state, remember]);

  // Problems: never while the player is typing in that field. A field's problem shows once
  // they leave it; a section's (e.g. "your types add up to too many") once they are not
  // typing in that section; anything else once typing has paused.
  const [touched, setTouched] = useState<ReadonlySet<FieldId>>(new Set());
  const focused = useFocusedField();
  const settled = useSettled(form, SETTLE_MS);
  const touch = useCallback((field: FieldId) => {
    setTouched((t) => (t.has(field) ? t : new Set(t).add(field)));
  }, []);
  const visible = useCallback(
    (field: FieldId): boolean => {
      if (settled) return true;
      // Not typing anywhere (e.g. a button was just pressed): say everything at once.
      if (focused === null) return true;
      const section = SECTION_OF[field];
      if (section !== undefined) return !focused.startsWith(section);
      return touched.has(field) && focused !== field;
    },
    [settled, focused, touched],
  );
  const problem = useCallback(
    (field: FieldId): Problem | undefined => {
      if (parsed.ok || !visible(field)) return undefined;
      const issue = parsed.issues.find((i) => i.field === field);
      return issue && { id: `problem-${field.replaceAll(":", "-")}`, message: issue.message };
    },
    [parsed, visible],
  );
  const note = useCallback(
    (field: FieldId): Problem | undefined => {
      if (!visible(field)) return undefined;
      const n = parsed.notes.find((i) => i.field === field);
      return n && { id: `note-${field.replaceAll(":", "-")}`, message: n.message };
    },
    [parsed, visible],
  );
  const firstProblem = parsed.ok ? null : (parsed.issues.find((i) => visible(i.field))?.message ?? null);

  // Keyboard focus follows rows: into a new row, or to the section's add button when a
  // row is removed (instead of falling back to the top of the page).
  const focusTarget = useRef<string | null>(null);
  useEffect(() => {
    if (focusTarget.current === null) return;
    document.querySelector<HTMLElement>(focusTarget.current)?.focus();
    focusTarget.current = null;
  });
  const act = useCallback(
    (action: Action) => {
      dispatch(action);
      if (action.type === "typeAdded")
        focusTarget.current = `[data-field="type:${String(state.nextId)}:name"]`;
      if (action.type === "goalLineAdded")
        focusTarget.current = `[data-row="${String(state.nextId)}"] select`;
      if (action.type === "goalGroupAdded")
        focusTarget.current = `[data-row="${String(state.nextId + 1)}"] select`;
      if (action.type === "typeRemoved") focusTarget.current = "#add-type";
      if (action.type === "goalRemoved") {
        // To the kind's "and also" button, or (if that was its last line) to "add a kind".
        const group = state.form.goal.find((g) => g.rules.some((r) => r.id === action.id));
        focusTarget.current =
          group !== undefined && group.rules.length > 1 ? `#add-goal-line-${group.id}` : "#add-goal-kind";
      }
      if (action.type === "protectAdded") focusTarget.current = `[data-row="${String(state.nextId)}"] select`;
      if (action.type === "protectRemoved") focusTarget.current = "#add-protect";
      if (action.type === "varyAdded") focusTarget.current = `[data-row="${String(state.nextId)}"] select`;
      if (action.type === "varyRemoved") focusTarget.current = "#add-vary";
      if (action.type === "keepRuleAdded")
        focusTarget.current = `[data-row="${String(state.nextId)}"] select`;
      if (action.type === "keepGroupAdded")
        focusTarget.current = `[data-row="${String(state.nextId + 1)}"] select`;
      if (action.type === "keepRuleRemoved") {
        // To the kind's "and also" button, or (if that was its last line) to "add a kind".
        const group = state.form.keep.find((g) => g.rules.some((r) => r.id === action.id));
        focusTarget.current =
          group !== undefined && group.rules.length > 1 ? `#add-keep-line-${group.id}` : "#add-keep-kind";
      }
    },
    [state.nextId, state.form.keep, state.form.goal],
  );

  const size = form.deckMode === "list" ? (decklist?.size ?? null) : parseWhole(form.deckSize);
  const draws = parseWhole(form.drawsPerTurn);
  const lastTurn =
    size !== null && draws !== null
      ? lastPlayableTurn({ goFirst: form.goFirst, drawsPerTurn: draws }, size)
      : MAX_TURN;

  return (
    <div className="page">
      <header>
        <h1>{TITLE}</h1>
        <p className="intro">{INTRO}</p>
        <div className="examples">
          <span id="examples-label">Start from an example (this replaces your setup):</span>
          <div className="buttons" role="group" aria-labelledby="examples-label">
            {EXAMPLES.map((example) => (
              <button
                key={example.title}
                type="button"
                className="choice"
                onClick={() => {
                  act({ type: "load", example });
                }}
              >
                {example.title}
              </button>
            ))}
          </div>
        </div>
      </header>
      <main
        className={`layout ${live.view !== null && live.view.kind !== "answer" && live.view.kind !== "problem" ? "wide-answer" : ""}`}
      >
        <div className="answer-column">
          <AnswerPanel live={live} problem={firstProblem} />
          <AnswerDetails view={live.view} stale={live.busy || live.invalid} />
        </div>
        <form
          className="steps"
          aria-label="Your deck and goal"
          onSubmit={(e) => {
            e.preventDefault();
          }}
        >
          <DeckStep
            form={form}
            decklist={decklist}
            dispatch={act}
            problem={problem}
            note={note}
            touch={touch}
          />
          <PlayStep
            form={form}
            names={names}
            labels={labels}
            dispatch={act}
            problem={problem}
            touch={touch}
          />
          <GoalStep
            form={form}
            names={names}
            linesAsRule={linesAsRule}
            labels={labels}
            lastTurn={lastTurn}
            dispatch={act}
            problem={problem}
            touch={touch}
            onRun={live.run}
            running={live.busy}
          />
        </form>
      </main>
      <footer>
        <p>{ABOUT}</p>
      </footer>
    </div>
  );
}
