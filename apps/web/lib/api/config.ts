export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: string;
  /** RFC 7807 `type` — a machine-readable discriminator the UI can
   * switch on to render richer copy without memorising detail strings.
   * Falls back to a URL for unspecified errors. */
  problemType: string | null;
  data: unknown;

  constructor(
    status: number,
    detail: string,
    data: unknown,
    problemType: string | null = null,
  ) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.problemType = problemType;
    this.data = data;
  }
}

/**
 * Duck-typed check for an ApiError shape. Use this instead of
 * ``err instanceof ApiError`` in toast handlers.
 *
 * Why duck-typing and not instanceof: in production, the Next.js /
 * Turbopack bundler can produce two distinct copies of the
 * ``ApiError`` class when the same module is loaded via different
 * resolution paths (server-component bridge, RSC payload, dynamic
 * import). When that happens, ``new ApiError(...)`` from copy A
 * fails ``instanceof`` against the ``ApiError`` symbol in copy B,
 * the actionable backend ``detail`` is silently discarded, and the
 * user sees a generic toast instead of "The model returned
 * citations, but none matched verified authorities..." (BUG-020,
 * 2026-04-21 + 2026-04-23 reopens).
 *
 * Duck-typing on ``name === "ApiError"`` plus the public field
 * shape sidesteps the class-identity problem entirely. The class is
 * still useful for type-narrowing in tests and call sites that need
 * the strong type — production toast paths just do not depend on
 * it.
 */
export function isApiErrorShape(
  err: unknown,
): err is { detail: string; status: number; problemType: string | null; data: unknown } {
  if (!err || typeof err !== "object") return false;
  const obj = err as Record<string, unknown>;
  return (
    obj.name === "ApiError" &&
    typeof obj.detail === "string" &&
    typeof obj.status === "number"
  );
}

/**
 * Pick the actionable text out of an unknown thrown value for
 * toast.error / inline error display. Layered fallback so we
 * always show *something useful* even when the error isn't an
 * ApiError or the detail is empty.
 *
 * Order:
 *   1. ApiError-shaped errors → ``err.detail`` (the backend's
 *      actionable RFC 7807 message).
 *   2. Standard ``Error`` instances → ``err.message`` (often a
 *      Zod validation error or a network failure that the user
 *      can still act on).
 *   3. ``fallback`` — last resort, generic copy.
 *
 * Always logs the original error to ``console.error`` so the
 * devtools console retains the full object for debugging even
 * when the toast text was fallback-only. The previous duplicated
 * pattern across 36 onError handlers swallowed the original error
 * in the conditional and made BUG-020 invisible until users
 * complained.
 */
export function apiErrorMessage(err: unknown, fallback: string): string {
  // Always log the raw error so a regression to "fallback every
  // time" is debuggable from the user's devtools without us having
  // to redeploy with extra instrumentation.
  // eslint-disable-next-line no-console
  console.error("[apiErrorMessage]", err);
  if (isApiErrorShape(err) && err.detail.trim().length > 0) {
    return err.detail;
  }
  if (err instanceof Error && err.message && err.message.trim().length > 0) {
    return err.message;
  }
  return fallback;
}

/** One entry of an RFC 7807 422 body's `errors[]` (FastAPI/pydantic shape). */
export type ApiValidationIssue = { loc: Array<string | number>; msg: string; type?: string };

// Kept identical to core/problem_details.py so the browser and the API word a
// validation failure the same way, even across a deploy skew.
const VALIDATION_SOURCES = new Set(["body", "query", "path", "header", "cookie"]);
const VALIDATOR_PREFIXES = ["Value error, ", "Assertion failed, "];
const ACRONYMS: Record<string, string> = {
  id: "ID", ids: "IDs", ip: "IP", uri: "URI", url: "URL", urls: "URLs",
};
const GENERIC_PROBLEM_TITLES = new Set([
  "bad request", "unauthorized", "forbidden", "not found", "conflict",
  "unprocessable content", "unprocessable entity", "too many requests",
  "service unavailable", "gateway timeout", "internal server error", "error",
]);

/** The `errors[]` of a validation problem body, or [] when it has none. */
export function apiValidationIssues(data: unknown): ApiValidationIssue[] {
  if (!data || typeof data !== "object") return [];
  const errors = (data as Record<string, unknown>).errors;
  if (!Array.isArray(errors)) return [];
  return errors.filter((item): item is ApiValidationIssue => {
    if (!item || typeof item !== "object") return false;
    const issue = item as Record<string, unknown>;
    return Array.isArray(issue.loc) && typeof issue.msg === "string";
  });
}

/** Field names of a `loc`, without the request source, list indices or pydantic tags. */
function fieldSegments(loc: ReadonlyArray<string | number>): string[] {
  return loc.filter((segment, position): segment is string =>
    typeof segment === "string"
    && !(position === 0 && VALIDATION_SOURCES.has(segment))
    && !/[[(]/.test(segment));
}

function humanizeWords(value: string): string {
  return value.split(/[_-]+/).filter(Boolean)
    .map(word => ACRONYMS[word.toLowerCase()] ?? word.toLowerCase()).join(" ");
}

function sentenceCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/** `["body", "publications", 0, "class_numbers"]` -> `Publications › Class numbers`. */
export function humanizeApiFieldPath(loc: ReadonlyArray<string | number>): string {
  return fieldSegments(loc).map(segment => sentenceCase(humanizeWords(segment))).join(" › ");
}

function validationMessage(message: string): string {
  const prefix = VALIDATOR_PREFIXES.find(candidate => message.startsWith(candidate));
  return prefix ? message.slice(prefix.length) : message;
}

/** `<Field path>: <message>` lines joined like the API's own 422 detail. */
export function describeValidationIssues(issues: readonly ApiValidationIssue[]): string {
  return issues.map(issue => {
    const field = humanizeApiFieldPath(issue.loc);
    const message = validationMessage(issue.msg);
    return field ? `${field}: ${message}` : message;
  }).join("; ");
}

/**
 * Human text for a structured refusal such as
 * `{"code": "ip_opposition_opponent_not_ready", "gaps": ["forum_required"]}`,
 * which the problem envelope otherwise reduces to its status title
 * ("Conflict"). Returns null when the body carries neither.
 */
export function describeStructuredProblem(body: Record<string, unknown>, message?: string | null): string | null {
  const code = typeof body.code === "string" && body.code.trim() ? body.code : null;
  const gaps = Array.isArray(body.gaps)
    ? body.gaps.filter((gap): gap is string => typeof gap === "string" && gap.trim().length > 0)
    : [];
  if (!code && gaps.length === 0) return null;
  const specific = message && !GENERIC_PROBLEM_TITLES.has(message.trim().toLowerCase()) ? message.trim() : null;
  const lead = specific ?? (code ? `${sentenceCase(humanizeWords(code))}.` : "This action cannot be completed yet.");
  if (gaps.length === 0) return lead;
  const missing = gaps.map(gap => humanizeWords(gap.replace(/_required$/, ""))).join("; ");
  return `${lead} Missing: ${missing}.`;
}

/** Key for a validation failure that names no field (a whole-request rule). */
export const API_FORM_ERROR_KEY = "_form";

/**
 * Map a 422's `errors[]` onto form fields, so each message can sit under the
 * field it belongs to (`aria-invalid` + `aria-describedby`) instead of in a
 * toast that names nothing.
 *
 * Keys of `fieldMap` are API field paths without the request source and list
 * indices, dot-joined (`publications.class_numbers`), or any contiguous part
 * of one (`class_numbers`, `goods_services`, `goods_services.45`); values are
 * form control ids. The longest match wins, then the one nearest the leaf. An unmapped failure is returned under its own
 * dotted path, and one that names no field under {@link API_FORM_ERROR_KEY}.
 * Messages never include the submitted value. Several failures on one field
 * are joined.
 */
export function apiFieldErrors(err: unknown, fieldMap: Readonly<Record<string, string>> = {}): Record<string, string> {
  if (!isApiErrorShape(err)) return {};
  const fields: Record<string, string> = {};
  for (const issue of apiValidationIssues(err.data)) {
    const segments = fieldSegments(issue.loc);
    let key: string | undefined;
    // Longest sub-path first; at equal length the one nearest the leaf.
    for (let size = segments.length; size > 0 && key === undefined; size -= 1) {
      for (let start = segments.length - size; start >= 0 && key === undefined; start -= 1) {
        key = fieldMap[segments.slice(start, start + size).join(".")];
      }
    }
    key ??= segments.join(".") || API_FORM_ERROR_KEY;
    const message = validationMessage(issue.msg);
    fields[key] = fields[key] ? `${fields[key]}; ${message}` : message;
  }
  return fields;
}

/** Thrown when the network itself failed (DNS, offline, CORS, aborted by a
 * browser extension, etc.) — i.e. no HTTP response came back at all. This
 * is distinct from ApiError, which represents a response with a non-2xx
 * status. Callers that want to render a different UI for "API unreachable"
 * check `err instanceof NetworkError`.
 */
export class NetworkError extends Error {
  cause: unknown;
  constructor(message: string, cause: unknown) {
    super(message);
    this.name = "NetworkError";
    this.cause = cause;
  }
}

export function isNetworkError(err: unknown): err is NetworkError {
  return err instanceof NetworkError;
}
