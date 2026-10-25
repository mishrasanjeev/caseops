export type JsonFetch = (input: string, init: RequestInit) => Promise<Response>;
export type ExpoFetchFunction = (
  input: string,
  init: NonNullable<Parameters<typeof import("expo/fetch").fetch>[1]>,
) => Promise<Response>;

export function createExpoFetchAdapter(fetcher: ExpoFetchFunction): JsonFetch {
  return (input, init) => {
    if (
      init.credentials !== "omit" ||
      init.redirect !== "error" ||
      init.cache !== "no-store"
    )
      throw new Error(
        "Native fetch requires omitted cookies, refused redirects and no-store requests.",
      );
    const headers = new Headers(init.headers);
    headers.set("Cache-Control", "no-store");
    headers.set("Pragma", "no-cache");
    // Expo 58 does not implement RequestInit.cache. Forward only SDK-supported
    // options and preserve the explicit cache headers; do not cast its response.
    return fetcher(input, {
      method: init.method,
      body: init.body,
      headers,
      credentials: "omit",
      redirect: "error",
      signal: init.signal ?? undefined,
    });
  };
}
export type BytesRequestOptions = {
  signal?: AbortSignal;
  maxBytes: number;
  rangeProbe?: boolean;
};
export type BytesResponse = {
  bytes: Uint8Array<ArrayBuffer>;
  contentType: string;
  status: number;
  contentRange: string | null;
  cacheControl: string | null;
};
export const MAX_PRIVATE_BYTES = 50 * 1024 * 1024;

export function checkedBytesRequest(
  path: string,
  options: BytesRequestOptions,
): void {
  checkedApiPath(path);
  const uuid =
    "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
  if (
    !new RegExp(
      `^/api/matters/${uuid}/attachments/${uuid}/download(?:\\?inline=true)?$`,
    ).test(path)
  )
    throw new Error(
      "Only an exact private Matter attachment download is allowed.",
    );
  if (
    !options ||
    typeof options !== "object" ||
    Array.isArray(options) ||
    Object.keys(options).some(
      (key) => !["signal", "maxBytes", "rangeProbe"].includes(key),
    ) ||
    !Number.isSafeInteger(options.maxBytes) ||
    options.maxBytes < 1 ||
    options.maxBytes > MAX_PRIVATE_BYTES ||
    (options.rangeProbe !== undefined &&
      typeof options.rangeProbe !== "boolean")
  )
    throw new Error(
      "A bounded private byte request is required (maximum 50 MiB).",
    );
}

function abortedRead(): MobileApiError {
  return new MobileApiError(
    "The private response was cancelled or did not finish before the deadline.",
    0,
    "request_aborted",
  );
}

// Also bound non-cooperating injected transports/readers. Late data is disposed
// instead of escaping after the caller has already abandoned the operation.
function abortable<T>(
  work: Promise<T>,
  signal: AbortSignal,
  discard: (value: T) => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const abort = () => {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", abort);
      reject(abortedRead());
    };
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
    work.then(
      (value) => {
        if (settled) {
          discard(value);
          return;
        }
        settled = true;
        signal.removeEventListener("abort", abort);
        resolve(value);
      },
      (error: unknown) => {
        signal.removeEventListener("abort", abort);
        if (!settled) {
          settled = true;
          reject(error);
        }
      },
    );
  });
}

function cancelBody(body: ReadableStream<Uint8Array> | null): void {
  try {
    void body?.cancel().catch(() => {});
  } catch {
    /* Abort still owns native cancellation. */
  }
}

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

  async requestBytes(
    path: string,
    options: BytesRequestOptions,
    accessToken: string,
  ): Promise<BytesResponse> {
    checkedBytesRequest(path, options);
    if (!accessToken)
      throw new MobileApiError(
        "Sign in to continue.",
        401,
        "native_session_missing",
      );
    const { maxBytes, rangeProbe = false } = options;
    const controller = new AbortController();
    const supplied = options.signal;
    const forwardAbort = () => controller.abort();
    supplied?.addEventListener("abort", forwardAbort, { once: true });
    if (supplied?.aborted) controller.abort();
    const deadline = setTimeout(() => controller.abort(), this.timeoutMs);
    const deadlineAt = Date.now() + this.timeoutMs;
    let response: Response | undefined;
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    const chunks: Uint8Array<ArrayBuffer>[] = [];
    let output: Uint8Array<ArrayBuffer> | undefined;
    let completed = false;
    try {
      if (controller.signal.aborted) throw abortedRead();
      const headers = new Headers({
        Accept: "application/octet-stream, application/pdf, image/*",
        Authorization: `Bearer ${accessToken}`,
        "Cache-Control": "no-store",
        Pragma: "no-cache",
        "X-CaseOps-Client": "native",
      });
      if (this.automated)
        headers.set("X-CaseOps-Automated-Test", "no-paid-providers");
      if (rangeProbe) headers.set("Range", "bytes=0-0");
      const url = `${this.origin}${path}`;
      response = await abortable(
        this.fetcher(url, {
          method: "GET",
          headers,
          signal: controller.signal,
          credentials: "omit",
          redirect: "error",
          cache: "no-store",
        }),
        controller.signal,
        (late) => cancelBody(late.body),
      );
      if (
        response.redirected ||
        (response.status >= 300 && response.status < 400) ||
        (response.url && response.url !== url)
      )
        throw new MobileApiError(
          "The private source changed location. Reload its record securely.",
          0,
          "unsafe_redirect",
        );
      if (!response.ok) {
        // Never parse an unbounded JSON/HTML error body on this private path.
        throw new MobileApiError(
          response.status === 403
            ? "You no longer have access to this file."
            : "The private file could not be read. Reload its record.",
          response.status,
          "private_bytes_rejected",
        );
      }
      if (response.status !== (rangeProbe ? 206 : 200))
        throw new MobileApiError(
          "The server returned an unsupported private byte response.",
          response.status,
          "invalid_byte_response",
        );
      const metadata = (name: string, max: number): string | null => {
        const value = response!.headers.get(name);
        if (
          value !== null &&
          (value.length > max || /[\x00-\x1f\x7f]/.test(value))
        )
          throw new MobileApiError(
            "The private response metadata could not be verified.",
            response!.status,
            "invalid_byte_response",
          );
        return value;
      };
      const contentType = metadata("Content-Type", 512);
      const contentRange = metadata("Content-Range", 256);
      const cacheControl = metadata("Cache-Control", 1024);
      if (!contentType?.trim())
        throw new MobileApiError(
          "The private file type was not supplied.",
          response.status,
          "invalid_byte_response",
        );
      const cap = rangeProbe ? 1 : maxBytes;
      const length = metadata("Content-Length", 32);
      let declaredLength: number | null = null;
      if (length !== null) {
        if (
          !/^(0|[1-9]\d*)$/.test(length) ||
          !Number.isSafeInteger(Number(length))
        )
          throw new MobileApiError(
            "The private response length could not be verified.",
            response.status,
            "invalid_byte_response",
          );
        declaredLength = Number(length);
        if (declaredLength > cap)
          throw new MobileApiError(
            "The file exceeds the permitted private-viewing size.",
            response.status,
            "private_bytes_too_large",
          );
      }
      if (rangeProbe) {
        const range = /^bytes 0-0\/([1-9]\d*)$/.exec(contentRange ?? "");
        if (
          !range ||
          !Number.isSafeInteger(Number(range[1])) ||
          (declaredLength !== null && declaredLength !== 1)
        )
          throw new MobileApiError(
            "The source did not return the requested one-byte range.",
            response.status,
            "invalid_byte_range",
          );
      } else if (contentRange !== null) {
        throw new MobileApiError(
          "An unexpected partial private response was returned.",
          response.status,
          "invalid_byte_range",
        );
      }
      if (!response.body)
        throw new MobileApiError(
          "A streaming private response is required.",
          response.status,
          "invalid_byte_response",
        );
      reader = response.body.getReader();
      let size = 0;
      let allocated = 0;
      let tailUsed = 0;
      while (true) {
        if (controller.signal.aborted || Date.now() >= deadlineAt)
          throw abortedRead();
        const chunk = await abortable(
          reader.read(),
          controller.signal,
          (late) => {
            if (!late.done && late.value instanceof Uint8Array)
              late.value.fill(0);
          },
        );
        if (chunk.done) break;
        if (!(chunk.value instanceof Uint8Array))
          throw new MobileApiError(
            "The private stream returned invalid bytes.",
            response.status,
            "invalid_byte_response",
          );
        const value = chunk.value;
        try {
          if (controller.signal.aborted || Date.now() >= deadlineAt)
            throw abortedRead();
          if (value.byteLength > cap - size)
            throw new MobileApiError(
              "The file exceeds the permitted private-viewing size.",
              response.status,
              "private_bytes_too_large",
            );
          size += value.byteLength;
          // Fixed-size slabs bound metadata even if a peer sends tiny chunks.
          let offset = 0;
          while (offset < value.byteLength) {
            let tail = chunks[chunks.length - 1];
            if (!tail || tailUsed === tail.length) {
              tail = new Uint8Array(Math.min(64 * 1024, cap - allocated));
              allocated += tail.length;
              chunks.push(tail);
              tailUsed = 0;
            }
            const length = Math.min(
              tail.length - tailUsed,
              value.byteLength - offset,
            );
            tail.set(value.subarray(offset, offset + length), tailUsed);
            tailUsed += length;
            offset += length;
          }
        } finally {
          value.fill(0);
        }
      }
      if (controller.signal.aborted || Date.now() >= deadlineAt)
        throw abortedRead();
      if (
        (declaredLength !== null && size !== declaredLength) ||
        (rangeProbe && size !== 1)
      )
        throw new MobileApiError(
          "The private response ended with an unexpected byte count.",
          response.status,
          rangeProbe ? "invalid_byte_range" : "invalid_byte_response",
        );
      output = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        const length = Math.min(chunk.length, size - offset);
        output.set(chunk.subarray(0, length), offset);
        offset += length;
      }
      if (controller.signal.aborted || Date.now() >= deadlineAt)
        throw abortedRead();
      completed = true;
      return {
        bytes: output,
        contentType,
        status: response.status,
        contentRange,
        cacheControl,
      };
    } catch (error) {
      if (error instanceof MobileApiError) throw error;
      throw new MobileApiError(
        "The private file could not be read. Check the connection and reload its record.",
        0,
        controller.signal.aborted ? "request_aborted" : "network_error",
      );
    } finally {
      if (!completed) {
        // Native Expo cancellation is driven by this signal as well as cancel().
        if (reader) {
          try {
            void reader.cancel().catch(() => {});
          } catch {
            /* Already closed. */
          }
        } else if (response) cancelBody(response.body);
        controller.abort();
        output?.fill(0);
      }
      for (const chunk of chunks) chunk.fill(0);
      try {
        reader?.releaseLock();
      } catch {
        /* A pending cancellation owns cleanup. */
      }
      clearTimeout(deadline);
      supplied?.removeEventListener("abort", forwardAbort);
    }
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
