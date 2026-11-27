import type { Dispatch, ReactNode } from "react";

import type { Action } from "../app/state.ts";
import { ANY_CARD, KINDS, MAX_TURN, type FormState, type Kind, type QuestionKind } from "../forms/model.ts";
import { parseWhole, type FieldId } from "../forms/parse.ts";
import { describeGoal, turnWords } from "../forms/words.ts";
import { HINTS, RULE_GUIDE, STEPS } from "../text/copy.ts";
import { describedBy, ProblemText, type Problem } from "./Field.tsx";
import { HowManyInputs } from "./HowManyInputs.tsx";
import { LineGroups, type GroupWords } from "./LineGroups.tsx";

interface Props {
  readonly form: FormState;
  readonly lastTurn: number;
  /** The card types a line may pick (types, or decklist tags), then "any card". */
  readonly names: readonly string[];
  /** The current lines written as a rule, to start the rule box from (null if invalid). */
  readonly linesAsRule: string | null;
  /** How to write each card-type name (as the player typed it). */
  readonly labels: Readonly<Record<string, string>>;
  readonly dispatch: Dispatch<Action>;
  readonly problem: (field: FieldId) => Problem | undefined;
  readonly touch: (field: FieldId) => void;
  /** "How many should I play?": runs the search (it runs only on request). */
  readonly onRun?: () => void;
  /** A search is running. */
  readonly running?: boolean;
}

const KIND_WORDS: Record<Kind, string> = {
  "at least": "at least",
  "at most": "at most",
  exactly: "exactly",
  none: "no",
};

const QUESTIONS: readonly (readonly [QuestionKind, string, string])[] = [
  ["chances", "What are my chances?", "How often a game goes the way you want."],
  ["draws", "How many will I draw?", "How many of one card type you will have seen, turn by turn."],
  ["turns", "Turn by turn", "How your chance of a good game grows from turn to turn."],
  [
    "howmany",
    "How many should I play?",
    "Let the calculator choose how many cards of some card types to play.",
  ],
  [
    "mulligan",
    "Should I mulligan?",
    "How good your mulligan plan is, compared with never mulliganing and with the best possible plan.",
  ],
];

/** Each question card has its own colour (the palette of the kinds, `.c1` … `.c6`). */
const QUESTION_COLORS: Record<QuestionKind, string> = {
  chances: "c1",
  draws: "c5",
  turns: "c2",
  howmany: "c4",
  mulligan: "c6",
};

export function GoalStep(props: Props): ReactNode {
  const { form, dispatch, linesAsRule } = props;
  return (
    <section aria-labelledby="goal-title" className="step c3">
      <h2 id="goal-title">{STEPS.goal}</h2>
      <fieldset className="field">
        <legend>What do you want to know?</legend>
        <div className="questions">
          {QUESTIONS.map(([kind, title, about]) => (
            <label key={kind} className={`radio question ${QUESTION_COLORS[kind]}`}>
              <input
                type="radio"
                name="question"
                checked={form.question === kind}
                onChange={() => {
                  dispatch({ type: "question", value: kind });
                }}
              />
              <strong>{title}</strong>
              <span className="about">{about}</span>
            </label>
          ))}
        </div>
      </fieldset>
      {form.question === "draws" ? (
        <DrawsInputs {...props} />
      ) : (
        <>
          {form.question === "howmany" && (
            <HowManyInputs
              form={form}
              labels={props.labels}
              dispatch={dispatch}
              problem={props.problem}
              touch={props.touch}
            />
          )}
          {form.useRule ? <RuleInput {...props} /> : <GoalLines {...props} />}
          <RuleBox {...props} linesAsRule={linesAsRule} />
          {form.question === "turns" && <LastTurn {...props} />}
          {form.question === "howmany" && props.onRun !== undefined && (
            <RunButton onRun={props.onRun} running={props.running ?? false} />
          )}
        </>
      )}
    </section>
  );
}

/**
 * Starts the search. It stays enabled (and keeps focus) while working: pressing again
 * then does nothing, as the same form is already being answered.
 */
export function RunButton({
  onRun,
  running,
}: {
  readonly onRun: () => void;
  readonly running: boolean;
}): ReactNode {
  return (
    <button type="button" className="run" aria-disabled={running || undefined} onClick={onRun}>
      {running ? "Working…" : "Find the best counts"}
    </button>
  );
}

/** "How many will I draw?": which card type, up to which turn. */
function DrawsInputs(props: Props): ReactNode {
  const { form, names, labels, dispatch, problem } = props;
  const p = problem("drawsType");
  const options = names.includes(form.drawsType) ? names : ["", ...names];
  return (
    <>
      <div className={`field ${p ? "has-problem" : ""}`}>
        <label htmlFor="draws-type">Which card type?</label>
        <select
          id="draws-type"
          data-field="drawsType"
          value={form.drawsType}
          aria-invalid={p ? true : undefined}
          aria-describedby={p?.id}
          onChange={(e) => {
            dispatch({ type: "drawsType", value: e.target.value });
          }}
        >
          {options.map((name) => (
            <option key={name} value={name}>
              {name === ""
                ? "choose a card type"
                : name === ANY_CARD
                  ? "cards of any type"
                  : (labels[name] ?? name)}
            </option>
          ))}
        </select>
        <ProblemText problem={p} />
      </div>
      <LastTurn {...props} />
    </>
  );
}

/** "Up to which turn?" for the table questions. */
function LastTurn({ form, lastTurn, dispatch, problem }: Props): ReactNode {
  const p = problem("lastTurn");
  const chosen = parseWhole(form.lastTurn) ?? 0;
  const turns = Array.from({ length: Math.min(MAX_TURN, Math.max(lastTurn, chosen)) + 1 }, (_, t) => t);
  return (
    <div className={`field ${p ? "has-problem" : ""}`}>
      <label htmlFor="last-turn">Show every turn up to</label>
      <select
        id="last-turn"
        data-field="lastTurn"
        value={String(chosen)}
        aria-invalid={p ? true : undefined}
        aria-describedby={p?.id}
        onChange={(e) => {
          dispatch({ type: "lastTurn", value: e.target.value });
        }}
      >
        {turns.map((t) => (
          <option key={t} value={String(t)}>
            {t === 0 ? "the opening hand" : `turn ${String(t)}`}
          </option>
        ))}
      </select>
      <ProblemText problem={p} />
    </div>
  );
}

/** "Write my own rule instead". */
function RuleBox({ form, dispatch, linesAsRule }: Props): ReactNode {
  return (
    <label className="checkbox">
      <input
        type="checkbox"
        checked={form.useRule}
        onChange={(e) => {
          dispatch({
            type: "useRule",
            value: e.target.checked,
            ...(linesAsRule === null ? {} : { prefill: linesAsRule }),
          });
        }}
      />
      Write my own rule instead (for experienced players)
    </label>
  );
}

/** Step 3 as a typed rule (FR-37), with a short guide to the rule language. */
function RuleInput({ form, dispatch, problem, touch }: Props): ReactNode {
  const p = problem("rule");
  return (
    <div className={`field ${p ? "has-problem" : ""}`}>
      <h3 className="group-heading">What is a good game?</h3>
      <label htmlFor="rule">Your rule</label>
      <p className="hint" id="rule-hint">
        {HINTS.rule}
      </p>
      <textarea
        id="rule"
        data-field="rule"
        rows={3}
        spellCheck={false}
        value={form.rule}
        aria-invalid={p ? true : undefined}
        aria-describedby={describedBy("rule-hint", p?.id)}
        onBlur={() => {
          touch("rule");
        }}
        onChange={(e) => {
          dispatch({ type: "rule", value: e.target.value });
        }}
      />
      <ProblemText problem={p} />
      <details>
        <summary>How to write rules</summary>
        <dl className="rule-guide">
          {RULE_GUIDE.map(([example, meaning]) => (
            <div key={example}>
              <dt>
                <code>{example}</code>
              </dt>
              <dd>{meaning}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}

/** The words of the kinds of good game (shared layout with the keep rules: LineGroups). */
function goalWords(everyTurn: boolean): GroupWords {
  return {
    key: "goal",
    heading: everyTurn ? "What is a good game? (at every turn)" : "What is a good game?",
    hint: HINTS.goal,
    first: "A good game has",
    other: "Or a good game has",
    kind: "Good game",
    empty: "No good game yet: add one.",
    addFirst: "+ Add a good game",
    addOther: "+ Or another kind of good game",
  };
}

/** The good game in words from the lines as typed, or null while a number is unfinished. */
export function goalSummary(form: FormState, labels: Readonly<Record<string, string>>): string | null {
  const groups = form.goal.map((g) =>
    g.rules.map((r) => ({
      kind: r.kind,
      amount: r.kind === "none" ? 0 : parseWhole(r.amount),
      cardType: r.cardType,
      turn: parseWhole(r.turn) ?? 0,
    })),
  );
  if (groups.length === 0) return null;
  if (groups.some((g) => g.some((r) => r.amount === null || r.cardType === ""))) return null;
  const goal = { groups: groups.map((g) => g.map((r) => ({ ...r, amount: r.amount ?? 0 }))) };
  return `a good game has ${describeGoal(goal, labels, form.question !== "turns")}`;
}

/** Step 3 as kinds of good game, each with lines ("at least 3 land by turn 3"). */
function GoalLines({ form, names, labels, lastTurn, dispatch, problem, touch }: Props): ReactNode {
  const fields = (id: string): FieldId[] => [`goal:${id}:amount`, `goal:${id}:cardType`, `goal:${id}:turn`];
  return (
    <LineGroups
      words={goalWords(form.question === "turns")}
      groups={form.goal}
      summary={goalSummary(form, labels)}
      hasProblem={(row) => fields(row.id).some((f) => problem(f) !== undefined)}
      problems={(row) => (
        <>
          {fields(row.id).map((f) => (
            <ProblemText key={f} problem={problem(f)} />
          ))}
        </>
      )}
      footer={
        <>
          <ProblemText problem={problem("goal")} />
          {form.question !== "turns" && <p className="hint">{HINTS.turn}</p>}
        </>
      }
      onAddLine={(group) => {
        dispatch({ type: "goalLineAdded", group });
      }}
      onRemoveLine={(id) => {
        dispatch({ type: "goalRemoved", id });
      }}
      onAddGroup={() => {
        dispatch({ type: "goalGroupAdded" });
      }}
      line={(row, where) => {
        const amountP = problem(`goal:${row.id}:amount`);
        const typeP = problem(`goal:${row.id}:cardType`);
        const turnP = problem(`goal:${row.id}:turn`);
        const turn = parseWhole(row.turn) ?? 0;
        const turns = Array.from({ length: Math.max(lastTurn, turn) + 1 }, (_, t) => t).filter(
          (t) => t <= MAX_TURN,
        );
        const options = names.includes(row.cardType) ? names : ["", ...names];
        return (
          <>
            <select
              aria-label={`${where}: how many`}
              value={row.kind}
              onChange={(e) => {
                dispatch({ type: "goalChanged", id: row.id, patch: { kind: e.target.value as Kind } });
              }}
            >
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {KIND_WORDS[k]}
                </option>
              ))}
            </select>
            {row.kind !== "none" && (
              <input
                type="text"
                inputMode="numeric"
                autoComplete="off"
                className="small"
                aria-label={`${where}: number of cards`}
                value={row.amount}
                aria-invalid={amountP ? true : undefined}
                aria-describedby={amountP?.id}
                data-field={`goal:${row.id}:amount`}
                onBlur={() => {
                  touch(`goal:${row.id}:amount`);
                }}
                onChange={(e) => {
                  dispatch({ type: "goalChanged", id: row.id, patch: { amount: e.target.value } });
                }}
              />
            )}
            <select
              aria-label={`${where}: card type`}
              data-field={`goal:${row.id}:cardType`}
              value={row.cardType}
              aria-invalid={typeP ? true : undefined}
              aria-describedby={typeP?.id}
              onChange={(e) => {
                dispatch({ type: "goalChanged", id: row.id, patch: { cardType: e.target.value } });
              }}
            >
              {options.map((name) => (
                <option key={name} value={name}>
                  {name === ""
                    ? "choose a card type"
                    : name === ANY_CARD
                      ? "cards of any type"
                      : (labels[name] ?? name)}
                </option>
              ))}
            </select>
            {form.question !== "turns" && (
              <select
                aria-label={`${where}: when`}
                data-field={`goal:${row.id}:turn`}
                value={String(turn)}
                aria-invalid={turnP ? true : undefined}
                aria-describedby={turnP?.id}
                onChange={(e) => {
                  dispatch({ type: "goalChanged", id: row.id, patch: { turn: e.target.value } });
                }}
              >
                {turns.map((t) => (
                  <option key={t} value={String(t)}>
                    {turnWords(t)}
                  </option>
                ))}
              </select>
            )}
          </>
        );
      }}
    />
  );
}
