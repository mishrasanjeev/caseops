import { array, ContractError, dateOnly, object, string } from "./contracts.ts";
import type { AuthorizedRequest } from "./repository.ts";
import { createCounselPageLease } from "./counsel-context.ts";

export const READ_PAGE_SIZE = 25;
export const createReadthroughPageLease = createCounselPageLease;
export type ReadState = "available" | "unsupported_size" | "unsupported_legacy";
export type ReadScope = {
  company_id: string;
  matter_id: string;
  matter_status: string;
  matter_is_active: boolean;
  matter_lifecycle_version: number;
};
export type Retained<T> = { id: string } & (
  | { read_state: "available"; record: T }
  | { read_state: Exclude<ReadState, "available">; record: null }
);
export type RecommendationMetadata = {
  type: string;
  title: string;
  confidence: string;
  review_required: boolean;
  status: string;
};
export type StoredJson =
  | null
  | boolean
  | number
  | string
  | StoredJson[]
  | { [key: string]: StoredJson };
export type RecommendationContent = RecommendationMetadata & {
  rationale: string;
  primary_option_index: number;
  assumptions: string[];
  missing_facts: string[];
  next_action: string | null;
  retrieved_authorities: string[];
  strategy_payload: { [key: string]: StoredJson } | null;
  analysis: {
    recommendation: string;
    risk_analysis: string[];
    legal_impact: string[];
    suggested_actions: string[];
    confidence_score: string;
    confidence_explanation: string;
  } | null;
};
export type RecommendationSummary = Retained<RecommendationMetadata> & {
  created_at: string;
  updated_at: string;
};
export type RecommendationDetail = Retained<RecommendationContent> & {
  scope: ReadScope;
  created_at: string;
  updated_at: string;
};
export type RecommendationOption = Retained<{
  label: string;
  rationale: string;
  confidence: string;
  supporting_citations: string[];
  risk_notes: string | null;
}> & { rank: number };
export type RecommendationDecision = Retained<{
  actor_membership_id: string | null;
  decision: string;
  selected_option_index: number | null;
  notes: string | null;
}> & { created_at: string };
export type HearingPack = Retained<{
  generated_by_membership_id: string | null;
  reviewed_by_membership_id: string | null;
  model_run_id: string | null;
  status: string;
  summary: string;
  review_required: boolean;
}> & {
  scope: ReadScope;
  hearing_id: string | null;
  generated_at: string;
  reviewed_at: string | null;
};
export type HearingPackItem = Retained<{
  item_type: string;
  title: string;
  body: string;
  source_ref: string | null;
}> & { rank: number; created_at: string };
export type ReadPage<T> = {
  scope: ReadScope;
  parent_id: string | null;
  kind: string;
  order: string;
  limit: number;
  items: T[];
  next_cursor: string | null;
};
type Row = Record<string, unknown>;
function id(value: unknown): string {
  const result = string(value, "retained record identity", 200);
  if (!result.trim() || /[\x00-\x1f\x7f]/.test(result))
    throw new ContractError("retained record identity");
  return result;
}
function text(value: unknown): string {
  return string(value, "retained text", 65536);
}
function bool(value: unknown): boolean {
  if (typeof value !== "boolean") throw new ContractError("retained flag");
  return value;
}
function integer(value: unknown, minimum = -Number.MAX_SAFE_INTEGER): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum
  )
    throw new ContractError("retained integer");
  return value;
}
function nullable<T>(value: unknown, decode: (input: unknown) => T): T | null {
  return value === null ? null : decode(value);
}
function strings(value: unknown): string[] {
  return array(value, "retained text list", text, 8192);
}
export function readTimestamp(value: unknown): string {
  const result = string(value, "retained timestamp", 64);
  const match =
    /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(
      result,
    );
  if (!match || !Number.isFinite(Date.parse(result)))
    throw new ContractError("retained timestamp");
  dateOnly(match[1]);
  return result;
}
function scope(value: unknown, companyId: string, matterId: string): ReadScope {
  const row = object(value, "retained Matter scope");
  if (
    id(row.company_id) !== id(companyId) ||
    id(row.matter_id) !== id(matterId)
  )
    throw new ContractError("retained Matter scope");
  return {
    company_id: companyId,
    matter_id: matterId,
    matter_status: string(row.matter_status, "retained Matter state", 64),
    matter_is_active: bool(row.matter_is_active),
    matter_lifecycle_version: integer(row.matter_lifecycle_version, 0),
  };
}
function retained<T>(row: Row, decode: (record: Row) => T): Retained<T> {
  const recordId = id(row.id);
  if (row.read_state === "available")
    return {
      id: recordId,
      read_state: "available",
      record: decode(object(row.record, "retained content")),
    };
  if (
    typeof row.read_state !== "string" ||
    !["unsupported_size", "unsupported_legacy"].includes(row.read_state) ||
    row.record !== null
  )
    throw new ContractError("retained read state");
  return {
    id: recordId,
    read_state: row.read_state as Exclude<ReadState, "available">,
    record: null,
  };
}
function metadata(row: Row): RecommendationMetadata {
  return {
    type: string(row.type, "recommendation type", 128),
    title: string(row.title, "recommendation title", 1024),
    confidence: string(row.confidence, "recorded confidence", 64),
    review_required: bool(row.review_required),
    status: string(row.status, "recorded recommendation state", 128),
  };
}
function storedObject(input: unknown): { [key: string]: StoredJson } {
  const budget = { nodes: 0 };
  function visit(value: unknown, depth: number): StoredJson {
    if (++budget.nodes > 16384 || depth > 16)
      throw new ContractError("stored structured content");
    if (value === null || typeof value === "boolean") return value;
    if (typeof value === "string") return text(value);
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (Array.isArray(value))
      return array(
        value,
        "stored structured list",
        (x) => visit(x, depth + 1),
        8192,
      );
    const row = object(value, "stored structured content"),
      keys = Object.keys(row);
    if (keys.length > 128 || keys.some((key) => key.length > 128))
      throw new ContractError("stored structured fields");
    return Object.fromEntries(
      keys.map((key) => [key, visit(row[key], depth + 1)]),
    );
  }
  const row = object(input, "stored strategy");
  return visit(row, 0) as { [key: string]: StoredJson };
}
function content(row: Row): RecommendationContent {
  return {
    ...metadata(row),
    rationale: text(row.rationale),
    primary_option_index: integer(row.primary_option_index),
    assumptions: strings(row.assumptions),
    missing_facts: strings(row.missing_facts),
    next_action: nullable(row.next_action, text),
    retrieved_authorities: strings(row.retrieved_authorities),
    strategy_payload: nullable(row.strategy_payload, storedObject),
    analysis: nullable(row.analysis, (value) => {
      const analysis = object(value, "stored analysis");
      const confidence = string(
        analysis.confidence_score,
        "stored analysis confidence",
        16,
      );
      if (!["low", "medium", "high"].includes(confidence))
        throw new ContractError("stored analysis confidence");
      return {
        recommendation: text(analysis.recommendation),
        risk_analysis: strings(analysis.risk_analysis),
        legal_impact: strings(analysis.legal_impact),
        suggested_actions: strings(analysis.suggested_actions),
        confidence_score: confidence,
        confidence_explanation: text(analysis.confidence_explanation),
      };
    }),
  };
}
export function decodeRecommendationSummary(
  value: unknown,
): RecommendationSummary {
  const row = object(value, "recommendation summary");
  return {
    ...retained(row, metadata),
    created_at: readTimestamp(row.created_at),
    updated_at: readTimestamp(row.updated_at),
  };
}
export function decodeRecommendation(
  value: unknown,
  companyId: string,
  matterId: string,
  recommendationId: string,
): RecommendationDetail {
  const row = object(value, "recommendation"),
    result = retained(row, content);
  if (result.id !== id(recommendationId))
    throw new ContractError("recommendation identity");
  return {
    ...result,
    scope: scope(row.scope, companyId, matterId),
    created_at: readTimestamp(row.created_at),
    updated_at: readTimestamp(row.updated_at),
  };
}
export function decodeRecommendationOption(
  value: unknown,
): RecommendationOption {
  const row = object(value, "recommendation option");
  return {
    ...retained(row, (item) => ({
      label: string(item.label, "option label", 1600),
      rationale: text(item.rationale),
      confidence: string(item.confidence, "recorded confidence", 64),
      supporting_citations: strings(item.supporting_citations),
      risk_notes: nullable(item.risk_notes, text),
    })),
    rank: integer(row.rank),
  };
}
export function decodeRecommendationDecision(
  value: unknown,
): RecommendationDecision {
  const row = object(value, "recorded decision");
  return {
    ...retained(row, (item) => ({
      actor_membership_id: nullable(item.actor_membership_id, id),
      decision: string(item.decision, "recorded decision", 128),
      selected_option_index: nullable(item.selected_option_index, integer),
      notes: nullable(item.notes, text),
    })),
    created_at: readTimestamp(row.created_at),
  };
}
export function decodeHearingPack(
  value: unknown,
  companyId: string,
  matterId: string,
  expected: { packId?: string; hearingId?: string },
): HearingPack {
  const row = object(value, "hearing pack");
  const result = retained(row, (item) => ({
    generated_by_membership_id: nullable(item.generated_by_membership_id, id),
    reviewed_by_membership_id: nullable(item.reviewed_by_membership_id, id),
    model_run_id: nullable(item.model_run_id, id),
    status: string(item.status, "recorded pack state", 128),
    summary: text(item.summary),
    review_required: bool(item.review_required),
  }));
  const hearingId = nullable(row.hearing_id, id);
  if (
    (expected.packId !== undefined && result.id !== id(expected.packId)) ||
    (expected.hearingId !== undefined && hearingId !== id(expected.hearingId))
  )
    throw new ContractError("hearing pack parent");
  return {
    ...result,
    scope: scope(row.scope, companyId, matterId),
    hearing_id: hearingId,
    generated_at: readTimestamp(row.generated_at),
    reviewed_at: nullable(row.reviewed_at, readTimestamp),
  };
}
export function decodeHearingPackItem(value: unknown): HearingPackItem {
  const row = object(value, "hearing pack item");
  return {
    ...retained(row, (item) => ({
      item_type: string(item.item_type, "pack item type", 160),
      title: string(item.title, "pack item title", 1024),
      body: text(item.body),
      source_ref: nullable(item.source_ref, (value) =>
        string(value, "stored source reference", 2000),
      ),
    })),
    rank: integer(row.rank),
    created_at: readTimestamp(row.created_at),
  };
}
export function decodeReadPage<T extends { id: string }>(
  value: unknown,
  companyId: string,
  matterId: string,
  parentId: string | null,
  kind: string,
  order: string,
  cursor: string | null,
  decode: (value: unknown) => T,
): ReadPage<T> {
  const row = object(value, "retained page");
  if (
    row.kind !== kind ||
    row.order !== order ||
    row.parent_id !== parentId ||
    row.limit !== READ_PAGE_SIZE
  )
    throw new ContractError("retained page scope");
  const items = array(row.items, "retained page", decode, READ_PAGE_SIZE);
  if (new Set(items.map((item) => item.id)).size !== items.length)
    throw new ContractError("duplicate retained identity");
  const next = nullable(row.next_cursor, readCursor);
  if (next !== null && (next === cursor || items.length === 0))
    throw new ContractError("retained continuation");
  return {
    scope: scope(row.scope, companyId, matterId),
    parent_id: parentId,
    kind,
    order,
    limit: READ_PAGE_SIZE,
    items,
    next_cursor: next,
  };
}
function readCursor(value: unknown): string {
  const result = string(value, "retained continuation", 4000);
  if (!result.trim() || /[\x00-\x1f\x7f]/.test(result))
    throw new ContractError("retained continuation");
  return result;
}
export function advanceReadPage(
  history: readonly (string | null)[],
  next: string,
): (string | null)[] {
  readCursor(next);
  if (
    !history.length ||
    history[0] !== null ||
    history.includes(next) ||
    history.length >= 100
  )
    throw new ContractError("retained continuation; reload the first page");
  return [...history, next];
}
export function createReadthroughRepository(
  request: AuthorizedRequest,
  companyId: string,
) {
  id(companyId);
  const base = (matterId: string) =>
    `/api/matter-readthrough/${encodeURIComponent(id(matterId))}`;
  const page = async <T extends { id: string }>(
    matterId: string,
    parentId: string | null,
    suffix: string,
    kind: string,
    order: string,
    cursor: string | null,
    decode: (value: unknown) => T,
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams({ limit: String(READ_PAGE_SIZE) });
    if (cursor !== null) query.set("cursor", readCursor(cursor));
    const value = await request(`${base(matterId)}/${suffix}?${query}`, {
      method: "GET",
      signal,
    });
    return decodeReadPage(
      value,
      companyId,
      matterId,
      parentId,
      kind,
      order,
      cursor,
      decode,
    );
  };
  return {
    recommendations: (
      matterId: string,
      cursor: string | null,
      signal?: AbortSignal,
    ) =>
      page(
        matterId,
        null,
        "recommendations",
        "recommendations",
        "created_at_desc_id_desc",
        cursor,
        decodeRecommendationSummary,
        signal,
      ),
    async recommendation(
      matterId: string,
      recommendationId: string,
      signal?: AbortSignal,
    ) {
      const value = await request(
        `${base(matterId)}/recommendations/${encodeURIComponent(id(recommendationId))}`,
        { method: "GET", signal },
      );
      return decodeRecommendation(value, companyId, matterId, recommendationId);
    },
    options: (
      matterId: string,
      recommendationId: string,
      cursor: string | null,
      signal?: AbortSignal,
    ) =>
      page(
        matterId,
        recommendationId,
        `recommendations/${encodeURIComponent(id(recommendationId))}/options`,
        "recommendation_options",
        "rank_asc_id_asc",
        cursor,
        decodeRecommendationOption,
        signal,
      ),
    decisions: (
      matterId: string,
      recommendationId: string,
      cursor: string | null,
      signal?: AbortSignal,
    ) =>
      page(
        matterId,
        recommendationId,
        `recommendations/${encodeURIComponent(id(recommendationId))}/decisions`,
        "recommendation_decisions",
        "created_at_desc_id_desc",
        cursor,
        decodeRecommendationDecision,
        signal,
      ),
    async latestPack(
      matterId: string,
      hearingId: string,
      signal?: AbortSignal,
    ) {
      const value = await request(
        `${base(matterId)}/hearings/${encodeURIComponent(id(hearingId))}/pack`,
        { method: "GET", signal },
      );
      return value === null
        ? null
        : decodeHearingPack(value, companyId, matterId, { hearingId });
    },
    async pack(matterId: string, packId: string, signal?: AbortSignal) {
      const value = await request(
        `${base(matterId)}/hearing-packs/${encodeURIComponent(id(packId))}`,
        { method: "GET", signal },
      );
      return decodeHearingPack(value, companyId, matterId, { packId });
    },
    packItems: (
      matterId: string,
      packId: string,
      cursor: string | null,
      signal?: AbortSignal,
    ) =>
      page(
        matterId,
        packId,
        `hearing-packs/${encodeURIComponent(id(packId))}/items`,
        "hearing_pack_items",
        "rank_asc_id_asc",
        cursor,
        decodeHearingPackItem,
        signal,
      ),
  };
}
export type ReadthroughRepository = ReturnType<
  typeof createReadthroughRepository
>;
