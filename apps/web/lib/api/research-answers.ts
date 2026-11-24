import { apiRequest } from "./client";
import type { components } from "./openapi-types";

type S = components["schemas"];
// The server always serializes defaulted fields; OpenAPI marks them optional.
type Defined<T> = { [K in keyof T]-?: Exclude<T[K], undefined> };

export type ResearchCitedText = Defined<S["ResearchCitedText"]>;
export type ResearchTimelineRow = Omit<Defined<S["ResearchTimelineRow"]>, "detail"> & {
  detail: ResearchCitedText;
};
export type ResearchSection = Omit<Defined<S["ResearchSection"]>, "paragraphs" | "steps" | "timeline"> & {
  paragraphs: ResearchCitedText[];
  steps: ResearchCitedText[];
  timeline: ResearchTimelineRow[];
};
export type ResearchAuthorityEntry = Defined<S["ResearchAuthorityEntry"]>;
export type ResearchSource = Omit<Defined<S["ResearchSource"]>, "source_action" | "treatment_signal"> & {
  source_action: Defined<S["SourceActionRecord"]> | null;
  treatment_signal: Defined<S["ResearchTreatmentSignal"]> | null;
};
export type ResearchAnswerBody = Omit<
  Defined<S["ResearchAnswerBody"]>,
  "short_answer" | "key_points" | "sections" | "authorities" | "verification" | "matter_facts"
> & {
  short_answer: ResearchCitedText;
  key_points: ResearchCitedText[];
  sections: ResearchSection[];
  authorities: ResearchAuthorityEntry[];
  verification: Defined<S["ResearchVerification"]>;
  matter_facts: Defined<S["ResearchMatterFact"]>[];
};
export type ResearchAnswerRecord = Omit<Defined<S["ResearchAnswerRecord"]>, "answer" | "sources"> & {
  answer: ResearchAnswerBody | null;
  sources: ResearchSource[];
};
export type ResearchAnswerSummary = Defined<S["ResearchAnswerSummary"]>;

const BASE = "/api/research/answers";

export function researchAnswerPending(record: ResearchAnswerRecord | undefined): boolean {
  return record?.status === "queued" || record?.status === "running";
}

export async function createResearchAnswer(input: {
  query: string;
  contextMatterId?: string | null;
}): Promise<ResearchAnswerRecord> {
  return apiRequest(BASE, {
    method: "POST",
    body: { query: input.query, context_matter_id: input.contextMatterId ?? null },
  });
}

export async function fetchResearchAnswer(
  id: string,
  options: { signal?: AbortSignal } = {},
): Promise<ResearchAnswerRecord> {
  return apiRequest(`${BASE}/${encodeURIComponent(id)}`, { signal: options.signal });
}

export async function listResearchAnswers(
  options: { matterId?: string | null; signal?: AbortSignal } = {},
): Promise<{ items: ResearchAnswerSummary[] }> {
  const query = options.matterId ? `?matter_id=${encodeURIComponent(options.matterId)}` : "";
  return apiRequest(`${BASE}${query}`, { signal: options.signal });
}

export async function saveResearchAnswerToMatter(
  id: string,
  matterId: string,
): Promise<ResearchAnswerRecord> {
  return apiRequest(`${BASE}/${encodeURIComponent(id)}/save`, {
    method: "POST",
    body: { matter_id: matterId },
  });
}
