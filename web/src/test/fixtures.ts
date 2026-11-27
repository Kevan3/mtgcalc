/** Typed access to the golden cases written by tests/web/make_fixtures.py. */
import data from "../../fixtures/forms.json";
import type { Json } from "../forms/request.ts";
import type { FormState, Setup } from "../forms/model.ts";

export interface Case {
  readonly name: string;
  readonly setup: Setup;
  readonly request: { readonly scenario: Json; readonly query: Json };
  readonly answer: Json;
  readonly headline: string;
}

export interface PercentCase {
  readonly value: string;
  readonly pct: string;
  readonly inWords: string;
}

/** A case given as the web form's raw state (pasted decklists and typed rules). */
export interface FormCase {
  readonly name: string;
  readonly form: FormState;
  readonly answer: Json;
  readonly headline: string;
}

/** "How many will I draw?" / "Turn by turn", with the desktop app's table rows. */
export interface QuestionCase {
  readonly name: string;
  readonly form: FormState;
  readonly headline: string;
  /** Draws: [label, [[k, exactly, at least, at most]...]]; turns: [when, seen, chance, words]. */
  readonly rows: readonly unknown[];
}

/** Mulligans: chances with a plan, and "Should I mulligan?" (the desktop app's rows). */
export interface MulliganCase {
  readonly name: string;
  readonly form: FormState;
  /** Python's `keep_rule_words` for the case's keep rule. */
  readonly keepWords: string;
  /** Python's `to_dict(build_scenario(...))`. */
  readonly scenario: unknown;
  readonly headline: string;
  readonly details: readonly string[];
  readonly rows: readonly unknown[];
}

/** "How many should I play?": the desktop app's answer, or its message when out of reach. */
export interface HowManyCase {
  readonly name: string;
  readonly form: FormState;
  readonly headline?: string;
  readonly details?: readonly string[];
  /** [option tried, chance, in words], best first. */
  readonly rows?: readonly (readonly [string, string, string])[];
  readonly error?: string;
}

export const howManyCases = data.howManyCases as unknown as readonly HowManyCase[];
export const cases = data.cases as unknown as readonly Case[];
export const mulliganCases = data.mulliganCases as unknown as readonly MulliganCase[];
export const questionCases = data.questionCases as unknown as readonly QuestionCase[];
export const formCases = data.formCases as unknown as readonly FormCase[];
export const percentages = data.percentages as readonly PercentCase[];
