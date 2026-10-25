import {
  VIEWER_LIMITS,
  decodeDocxText,
  normalizeMime,
  originalPath,
  sourceKey,
  sourcePath,
  validateBytes,
  validateSource,
  viewerFormat,
} from "./contracts.ts";
import type {
  PurgeReason,
  ViewerContent,
  ViewerPorts,
  ViewerSource,
} from "./contracts.ts";

export type ViewerState = Readonly<{
  phase:
    | "idle"
    | "loading"
    | "ready"
    | "renewing"
    | "blocked"
    | "unsupported"
    | "closed";
  revision: number;
  message: string;
  expiresAt: number;
}>;
export type ViewerClock = {
  now: () => number;
  setTimeout: (callback: () => void, ms: number) => unknown;
  clearTimeout: (timer: unknown) => void;
};
const realClock: ViewerClock = {
  now: () => Date.now(),
  setTimeout: (callback, ms) => setTimeout(callback, ms),
  clearTimeout: (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
};

export class PrivateViewerController {
  private state: ViewerState = {
    phase: "idle",
    revision: 0,
    message: "",
    expiresAt: 0,
  };
  private listeners = new Set<() => void>();
  private abort: AbortController | null = null;
  private timer: unknown;
  private bytes: ViewerContent | null = null;
  private generation = 0;
  private unsubscribe: (() => void) | null = null;
  readonly source: ViewerSource;
  constructor(
    source: ViewerSource,
    private ports: ViewerPorts,
    private clock: ViewerClock = realClock,
    private clearVisible: (() => Promise<void>) | null = null,
  ) {
    this.source = validateSource(source);
  }
  getSnapshot = (): ViewerState => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private publish(phase: ViewerState["phase"], message = "", expiresAt = 0) {
    this.state = {
      phase,
      message,
      expiresAt,
      revision: this.state.revision + 1,
    };
    for (const listener of this.listeners) listener();
  }
  private stop() {
    this.generation++;
    this.abort?.abort();
    this.abort = null;
    this.clock.clearTimeout(this.timer);
    this.timer = undefined;
  }
  private wipe() {
    this.bytes?.bytes.fill(0);
    this.bytes = null;
  }
  purge = (reason: PurgeReason = "closed") => {
    this.stop();
    this.wipe();
    this.publish(
      reason === "closed" ? "closed" : "blocked",
      reason === "source-changed"
        ? "This source changed. Return to Files and open the current record."
        : "This private document was cleared. Reopen it after access is checked.",
    );
  };
  dispose = () => {
    this.purge("closed");
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.listeners.clear();
  };
  rendererFailed = () => {
    this.stop();
    this.wipe();
    this.publish(
      "unsupported",
      "This document could not be safely displayed. No external viewer or download was opened.",
    );
  };
  copyContent(): ViewerContent | null {
    if (
      this.state.phase !== "ready" ||
      this.clock.now() >= this.state.expiresAt ||
      !this.bytes
    )
      return null;
    return { ...this.bytes, bytes: this.bytes.bytes.slice() };
  }
  private async authorized(signal: AbortSignal): Promise<number> {
    const started = this.clock.now();
    const current = validateSource(
      await this.ports.revalidate(this.source, { signal }),
    );
    if (signal.aborted || sourceKey(current) !== sourceKey(this.source))
      throw new Error("Source changed");
    const probe = await this.ports.requestBytes(originalPath(this.source), {
      signal,
      maxBytes: 1,
      rangeProbe: true,
    });
    try {
      if (
        probe.status !== 206 ||
        probe.bytes.length !== 1 ||
        probe.contentRange !== `bytes 0-0/${this.source.sizeBytes}`
      )
        throw new Error("Source probe failed");
      const format = viewerFormat(this.source);
      const expected =
        format?.kind === "docx-text"
          ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          : format?.mime;
      if (normalizeMime(probe.contentType) !== expected)
        throw new Error("Source type changed");
      if (!/\bno-store\b/i.test(probe.cacheControl || ""))
        throw new Error("Private cache policy unavailable");
    } finally {
      probe.bytes.fill(0);
    }
    const expiry = started + VIEWER_LIMITS.leaseMs;
    if (signal.aborted || this.clock.now() >= expiry)
      throw new Error("Source check expired");
    return expiry;
  }
  open = async (): Promise<void> => {
    // Effect replay is a fresh access check; construction itself has no effects.
    if (this.state.phase === "closed") this.publish("idle");
    this.unsubscribe ??= this.ports.subscribeInvalidation((reason) =>
      this.purge(reason),
    );
    await this.load(false);
  };
  private async load(renewal: boolean): Promise<void> {
    if (this.state.phase === "closed") return;
    this.stop();
    if (!renewal) this.wipe();
    const format = viewerFormat(this.source);
    if (
      !format ||
      this.source.sizeBytes > VIEWER_LIMITS.maxBytes ||
      (format.kind === "docx-text" && !this.ports.requestDocxPreview)
    ) {
      this.wipe();
      this.publish(
        "unsupported",
        this.source.sizeBytes > VIEWER_LIMITS.maxBytes
          ? "This file exceeds the private viewer's 20 MiB limit."
          : "This file type is not supported in the private viewer.",
      );
      return;
    }
    const run = this.generation;
    const abort = new AbortController();
    this.abort = abort;
    const cleared = renewal ? this.clearVisible?.() : null;
    // The native host acknowledges the removal commit before renewal I/O.
    this.publish(
      renewal ? "renewing" : "loading",
      renewal ? "Checking current document access" : "Opening private document",
    );
    const deadline = this.clock.setTimeout(() => {
      if (run !== this.generation) return;
      this.stop();
      this.wipe();
      this.publish(
        "blocked",
        "The document access check timed out. Reopen to try again.",
      );
    }, VIEWER_LIMITS.requestMs);
    let incoming: Uint8Array | null = null;
    try {
      if (renewal) {
        if (!cleared) throw new Error("No display clear acknowledgement");
        await cleared;
        if (run !== this.generation || abort.signal.aborted) return;
      }
      let expiresAt = await this.authorized(abort.signal);
      if (run !== this.generation || abort.signal.aborted) return;
      if (!this.bytes) {
        if (format.kind === "docx-text") {
          const preview = await this.ports.requestDocxPreview!(
            sourcePath(this.source),
            { signal: abort.signal, maxBytes: VIEWER_LIMITS.textBytes },
          );
          if (!/\bno-store\b/i.test(preview.cacheControl || ""))
            throw new Error("Private preview cache policy unavailable");
          const parsed = decodeDocxText(preview.value, this.source);
          incoming = new TextEncoder().encode(JSON.stringify(parsed));
          validateBytes(incoming, format.kind, format.mime);
        } else {
          const response = await this.ports.requestBytes(
            sourcePath(this.source),
            {
              signal: abort.signal,
              maxBytes: ["text", "docx-text"].includes(format.kind)
                ? VIEWER_LIMITS.textBytes
                : VIEWER_LIMITS.maxBytes,
            },
          );
          incoming = response.bytes;
          if (
            response.status !== 200 ||
            normalizeMime(response.contentType) !== format.mime ||
            !/\bno-store\b/i.test(response.cacheControl || "")
          )
            throw new Error("Invalid private response");
          validateBytes(incoming, format.kind, format.mime);
          if (
            incoming.length !== this.source.sizeBytes ||
            (await this.ports.sha256(incoming)) !== this.source.sha256
          )
            throw new Error("Source bytes changed");
          if (format.kind === "text") {
            const text = new TextDecoder("utf-8", { fatal: true }).decode(
              incoming,
            );
            if (
              text.includes("\0") ||
              text.length > VIEWER_LIMITS.maxTextCharacters
            )
              throw new Error("Unsafe text encoding");
          }
        }
        // Recheck access after all I/O and hashing, before handing any bytes to a renderer.
        expiresAt = await this.authorized(abort.signal);
        if (run !== this.generation || abort.signal.aborted) return;
        this.bytes = { ...format, bytes: incoming };
        incoming = null;
      }
      if (
        run !== this.generation ||
        abort.signal.aborted ||
        this.clock.now() >= expiresAt
      )
        return;
      this.publish("ready", "", expiresAt);
      this.timer = this.clock.setTimeout(
        () => {
          void this.load(true);
        },
        Math.max(0, expiresAt - this.clock.now()),
      );
    } catch {
      if (run === this.generation) {
        this.stop();
        this.wipe();
        this.publish(
          "blocked",
          "Current access, source identity or private response policy could not be verified. Return to Files and reopen the document.",
        );
      }
    } finally {
      incoming?.fill(0);
      this.clock.clearTimeout(deadline);
    }
  }
}
