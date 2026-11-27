import type { ReactNode } from "react";

/** The words one kind of list uses (e.g. the kinds of hand to keep, or of good game). */
export interface GroupWords {
  /** For buttons and ids: "keep", "goal". */
  readonly key: string;
  /** The heading above the kinds, e.g. "Which hands do you keep?". */
  readonly heading: string;
  /** Explains how the kinds combine. */
  readonly hint: string;
  /** Above the first kind, e.g. "Keep a hand that has". */
  readonly first: string;
  /** Above every other kind, e.g. "Or keep a hand that has". */
  readonly other: string;
  /** Names a kind for screen readers, e.g. "Kind of hand" ("Kind of hand 2, line 1"). */
  readonly kind: string;
  /** Shown when there are no kinds. */
  readonly empty: string;
  /** The add-a-kind button: with no kinds, and with some. */
  readonly addFirst: string;
  readonly addOther: string;
}

interface Row {
  readonly id: string;
}

interface Group<R extends Row> {
  readonly id: string;
  readonly rules: readonly R[];
}

interface Props<R extends Row> {
  readonly words: GroupWords;
  readonly groups: readonly Group<R>[];
  /** The inputs of one line; `where` names it ("Kind of hand 1, line 2"). */
  readonly line: (row: R, where: string) => ReactNode;
  /** The problems to show under one line. */
  readonly problems: (row: R) => ReactNode;
  /** Whether a line has a problem (it is then outlined). */
  readonly hasProblem: (row: R) => boolean;
  /** The whole list in one sentence, e.g. "keep a hand with 2 to 5 land" (null: none). */
  readonly summary: string | null;
  /** Shown under the list, e.g. a problem with the whole list. */
  readonly footer?: ReactNode;
  readonly onAddLine: (group: string) => void;
  readonly onRemoveLine: (id: string) => void;
  readonly onAddGroup: () => void;
}

/** Kinds cycle through six colours (CSS `.c1` … `.c6`), so neighbouring kinds never look alike. */
export const KIND_COLORS = 6;

export function kindColor(index: number): string {
  return `c${String((index % KIND_COLORS) + 1)}`;
}

/**
 * Kinds of something, any one of which will do, each with lines that must all hold:
 * the kinds of hand to keep (step 2) and the kinds of good game (step 3) share this
 * layout and wording, so the two read the same way ("…and…", "Or…").
 */
export function LineGroups<R extends Row>(props: Props<R>): ReactNode {
  const { words, groups } = props;
  const headingId = `${words.key}-heading`;
  const hintId = `${words.key}-hint`;
  return (
    <div className="field line-groups" role="group" aria-labelledby={headingId}>
      <h3 className="group-heading" id={headingId}>
        {words.heading}
      </h3>
      <p className="hint" id={hintId}>
        {words.hint}
      </p>
      {groups.length === 0 ? (
        <p className="note">{words.empty}</p>
      ) : (
        <ol className="kinds" aria-labelledby={headingId} aria-describedby={hintId}>
          {groups.map((group, g) => {
            const kind = `${words.kind} ${String(g + 1)}`;
            const titleId = `${words.key}-kind-${group.id}`;
            return (
              <li key={group.id} className={`kind ${kindColor(g)}`} data-group={group.id}>
                {g > 0 && (
                  <span className="or-divider" aria-hidden="true">
                    or
                  </span>
                )}
                <span className="kind-title" id={titleId}>
                  {g === 0 ? words.first : words.other}
                </span>
                <ol className="lines" aria-labelledby={titleId}>
                  {group.rules.map((row, i) => {
                    const where = `${kind}, line ${String(i + 1)}`;
                    return (
                      <li key={row.id} className="goal-line" data-row={row.id}>
                        <div
                          className={`line ${props.hasProblem(row) ? "has-problem" : ""}`}
                          role="group"
                          aria-label={where}
                        >
                          <span className="joiner" aria-hidden="true">
                            {i > 0 ? "and" : ""}
                          </span>
                          {props.line(row, where)}
                          <button
                            type="button"
                            className="remove"
                            aria-label={`Remove ${where.toLowerCase()}`}
                            onClick={() => {
                              props.onRemoveLine(row.id);
                            }}
                          >
                            ×
                          </button>
                        </div>
                        {props.problems(row)}
                      </li>
                    );
                  })}
                </ol>
                <button
                  type="button"
                  id={`add-${words.key}-line-${group.id}`}
                  className="add subtle"
                  aria-label={`And also, in ${kind.toLowerCase()}: add a line`}
                  onClick={() => {
                    props.onAddLine(group.id);
                  }}
                >
                  + And also…
                </button>
              </li>
            );
          })}
        </ol>
      )}
      {props.footer}
      <button
        type="button"
        id={`add-${words.key}-kind`}
        className={`add next-kind ${kindColor(groups.length)}`}
        onClick={props.onAddGroup}
      >
        {groups.length === 0 ? words.addFirst : words.addOther}
      </button>
      {props.summary !== null && <p className="note summary">So: {props.summary}.</p>}
    </div>
  );
}
