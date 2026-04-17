export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: string;
  data: unknown;

  constructor(status: number, detail: string, data: unknown) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.data = data;
  }
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
