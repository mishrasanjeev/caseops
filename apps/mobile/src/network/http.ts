export type JsonFetch = (input: string, init: RequestInit) => Promise<Response>;

export class MobileApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
    public readonly outcome: "rejected" | "unknown" = "rejected",
  ) {
    super(message);
    this.name = "MobileApiError";
  }
}

export function checkedOrigin(value: string, development: boolean): string {
  const url = new URL(value);
  const local = ["localhost", "127.0.0.1", "[::1]", "10.0.2.2"].includes(
    url.hostname,
  );
  if (
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== "/"
  ) {
    throw new Error(
      "The API setting must be an origin, without credentials or a path.",
    );
  }
  if (
    url.protocol !== "https:" &&
    !(development && local && url.protocol === "http:")
  ) {
    throw new Error(
      "CaseOps requires HTTPS. Only local development may use HTTP.",
    );
  }
  return url.origin;
}

export function checkedApiPath(path: string): string {
  if (
    !path.startsWith("/api/") ||
    path.includes("\\") ||
    /[\r\n#]/.test(path)
  ) {
    throw new Error("Only same-origin CaseOps API paths are allowed.");
  }
  const parsed = new URL(path, "https://caseops.invalid");
  if (
    parsed.origin !== "https://caseops.invalid" ||
    !parsed.pathname.startsWith("/api/")
  ) {
    throw new Error("The API path is outside the CaseOps application.");
  }
  if (/^\/api\/(portal|platform)(\/|$)/.test(parsed.pathname)) {
    throw new Error(
      "This app uses the tenant account, not the portal or platform realm.",
    );
  }
  return path;
}

export class JsonTransport {
  readonly origin: string;
  constructor(
    origin: string,
    development: boolean,
    private readonly automated: boolean,
    private readonly fetcher: JsonFetch = fetch,
    private readonly timeoutMs = 20_000,
  ) {
    this.origin = checkedOrigin(origin, development);
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0)
      throw new Error("Invalid request deadline.");
  }

  async request<T>(
    path: string,
    init: RequestInit = {},
    accessToken?: string,
  ): Promise<T> {
    checkedApiPath(path);
    const method = (init.method || "GET").toUpperCase();
    const mutation = !["GET", "HEAD", "OPTIONS"].includes(method);
    const headers = new Headers(init.headers);
    if (headers.has("Cookie") || headers.has("Authorization")) {
      throw new Error("The session owns authentication headers.");
    }
    headers.set("Accept", "application/json");
    headers.set("Cache-Control", "no-store");
    headers.set("X-CaseOps-Client", "native");
    if (this.automated)
      headers.set("X-CaseOps-Automated-Test", "no-paid-providers");
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    if (typeof init.body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const controller = new AbortController();
    const supplied = init.signal;
    const forwardAbort = () => controller.abort();
    supplied?.addEventListener("abort", forwardAbort, { once: true });
    if (supplied?.aborted) controller.abort();
    const deadline = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetcher(`${this.origin}${path}`, {
        ...init,
        method,
        headers,
        signal: controller.signal,
        credentials: "omit",
        redirect: "error",
        cache: "no-store",
      });
      if (
        response.redirected ||
        (response.url && new URL(response.url).origin !== this.origin)
      ) {
        throw new MobileApiError(
          "The server changed location. Reopen CaseOps securely.",
          0,
          "unsafe_redirect",
          mutation ? "unknown" : "rejected",
        );
      }
      if (response.status === 204) return undefined as T;
      let body: unknown;
      try {
        body = await response.json();
      } catch {
        if (controller.signal.aborted) {
          throw new MobileApiError(
            mutation
              ? "The save outcome is unknown. Reload the record before submitting anything again."
              : "The response did not finish before the deadline. Reload when connected.",
            0,
            "request_aborted",
            mutation ? "unknown" : "rejected",
          );
        }
        throw new MobileApiError(
          "The server response could not be read. Reload the record before trying again.",
          response.status,
          "invalid_response",
          mutation ? "unknown" : "rejected",
        );
      }
      if (!response.ok) {
        const problem =
          body && typeof body === "object"
            ? (body as Record<string, unknown>)
            : {};
        const message =
          typeof problem.detail === "string"
            ? problem.detail.slice(0, 600)
            : typeof problem.message === "string"
              ? problem.message.slice(0, 600)
              : response.status === 403
                ? "You no longer have access to this work."
                : "CaseOps could not complete the request.";
        throw new MobileApiError(
          message,
          response.status,
          typeof problem.code === "string" ? problem.code : "request_rejected",
        );
      }
      return body as T;
    } catch (error) {
      if (error instanceof MobileApiError) throw error;
      throw new MobileApiError(
        mutation
          ? "The save outcome is unknown. Reload the record before submitting anything again."
          : "CaseOps could not be reached. Check your connection and retry.",
        0,
        controller.signal.aborted ? "request_aborted" : "network_error",
        mutation ? "unknown" : "rejected",
      );
    } finally {
      clearTimeout(deadline);
      supplied?.removeEventListener("abort", forwardAbort);
    }
  }
}
