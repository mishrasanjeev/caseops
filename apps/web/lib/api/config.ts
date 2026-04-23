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
