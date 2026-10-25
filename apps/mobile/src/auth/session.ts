import {
  checkedBytesRequest,
  JsonTransport,
  MobileApiError,
} from "../network/http.ts";
import type { BytesRequestOptions, BytesResponse } from "../network/http.ts";
import { parseGrant, parseIdentity } from "./types.ts";
import type {
  CredentialStore,
  SessionIdentity,
  StoredCredential,
} from "./types.ts";

let sessionSequence = 0;
export class NativeSession {
  private grant: (SessionIdentity & { access_token: string }) | null = null;
  private expiresAt = 0;
  private refreshInFlight: Promise<SessionIdentity> | null = null;
  private generation = 0;
  private readonly keyPrefix = `native-session-${++sessionSequence}`;
  private readonly byteRequests = new Set<AbortController>();
  constructor(
    private readonly transport: JsonTransport,
    private readonly store: CredentialStore,
    private readonly now: () => number = Date.now,
    private readonly onInvalidated: () => void = () => {},
  ) {}

  get sessionKey(): string {
    return `${this.keyPrefix}-${this.generation}`;
  }

  private advanceGeneration(): number {
    ++this.generation;
    for (const request of this.byteRequests) request.abort();
    return this.generation;
  }

  private endLocalAuthority(): boolean {
    this.advanceGeneration();
    this.grant = null;
    this.expiresAt = 0;
    try {
      this.onInvalidated();
      return true;
    } catch {
      return false;
    }
  }

  private async invalidate(generation: number): Promise<void> {
    // A late refusal from an old request may never clear a newer sign-in.
    if (generation !== this.generation) return;
    const notified = this.endLocalAuthority();
    try {
      await this.store.clear();
    } catch {
      throw new MobileApiError(
        "Session access ended, but secure credentials could not be cleared. Revoke this device from another signed-in session.",
        401,
        "native_storage_clear_failed",
      );
    }
    if (!notified)
      throw new MobileApiError(
        "Session access ended, but private-view cleanup could not be confirmed.",
        401,
        "native_session_cleanup_failed",
      );
  }

  get identity(): SessionIdentity | null {
    if (!this.grant) return null;
    const { company, user, membership, capabilities } = this.grant;
    return {
      company: { ...company },
      user: { ...user },
      membership: { ...membership },
      capabilities: [...capabilities],
    };
  }

  private async adopt(
    input: unknown,
    generation: number,
  ): Promise<SessionIdentity> {
    const grant = parseGrant(input);
    if (generation !== this.generation) {
      await this.revokeCredential({
        refreshToken: grant.refresh_token,
        sessionId: grant.session_id,
      });
      throw new Error("The sign-in was cancelled.");
    }
    try {
      await this.store.write({
        refreshToken: grant.refresh_token,
        sessionId: grant.session_id,
      });
    } catch {
      await this.revokeCredential({
        refreshToken: grant.refresh_token,
        sessionId: grant.session_id,
      });
      this.grant = null;
      this.expiresAt = 0;
      await this.store.clear();
      this.onInvalidated();
      throw new Error(
        "Secure device storage is unavailable. Sign-in was not retained.",
      );
    }
    if (generation !== this.generation) {
      await this.revokeCredential({
        refreshToken: grant.refresh_token,
        sessionId: grant.session_id,
      });
      await this.store.clear();
      throw new Error("The sign-in was cancelled.");
    }
    this.grant = {
      company: grant.company,
      user: grant.user,
      membership: grant.membership,
      capabilities: [...grant.capabilities],
      access_token: grant.access_token,
    };
    this.expiresAt = this.now() + grant.expires_in * 1000;
    return this.identity!;
  }

  async exchange(input: {
    code: string;
    code_verifier: string;
    redirect_uri: string;
    platform: "android" | "ios";
  }): Promise<SessionIdentity> {
    const generation = this.advanceGeneration();
    const response = await this.transport.request<unknown>(
      "/api/auth/native/token",
      { method: "POST", body: JSON.stringify(input) },
    );
    return this.adopt(response, generation);
  }

  async restore(): Promise<SessionIdentity | null> {
    const credential = await this.store.read();
    if (!credential) return null;
    return this.refresh(credential);
  }

  private async refresh(
    credential?: StoredCredential,
  ): Promise<SessionIdentity> {
    if (this.refreshInFlight) return this.refreshInFlight;
    const generation = this.generation;
    this.refreshInFlight = (async () => {
      const saved = credential || (await this.store.read());
      if (!saved)
        throw new MobileApiError(
          "Sign in to this workspace again.",
          401,
          "native_session_missing",
        );
      try {
        const response = await this.transport.request<unknown>(
          "/api/auth/native/refresh",
          {
            method: "POST",
            body: JSON.stringify({ refresh_token: saved.refreshToken }),
          },
        );
        return await this.adopt(response, generation);
      } catch (error) {
        if (generation === this.generation) {
          // A lost refresh acknowledgement cannot safely replay a rotating token.
          try {
            await this.invalidate(generation);
          } finally {
            await this.revokeCredential(saved);
          }
        }
        throw error;
      }
    })();
    try {
      return await this.refreshInFlight;
    } finally {
      this.refreshInFlight = null;
    }
  }

  async revalidate(): Promise<SessionIdentity> {
    const raw = await this.request<unknown>("/api/auth/me");
    let identity: SessionIdentity;
    try {
      identity = parseIdentity(raw);
    } catch {
      try {
        await this.signOut();
      } catch {
        /* Local authority is already cleared. */
      }
      throw new Error(
        "The workspace identity could not be verified. Sign in again.",
      );
    }
    if (
      !this.grant ||
      identity.company.id !== this.grant.company.id ||
      identity.user.id !== this.grant.user.id ||
      identity.membership.id !== this.grant.membership.id
    ) {
      await this.signOut();
      throw new Error("The workspace identity changed. Sign in again.");
    }
    this.grant = { ...this.grant, ...identity };
    return this.identity!;
  }

  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    if (!this.grant || this.now() >= this.expiresAt - 30_000)
      await this.refresh();
    const generation = this.generation;
    const grant = this.grant;
    if (!grant)
      throw new MobileApiError(
        "Sign in to continue.",
        401,
        "native_session_missing",
      );
    try {
      const result = await this.transport.request<T>(
        path,
        init,
        grant.access_token,
      );
      if (generation !== this.generation)
        throw new MobileApiError(
          "This session has ended.",
          401,
          "native_session_ended",
        );
      return result;
    } catch (error) {
      if (error instanceof MobileApiError && error.status === 401) {
        await this.invalidate(generation);
      }
      throw error;
    }
  }

  async requestBytes(
    path: string,
    options: BytesRequestOptions,
  ): Promise<BytesResponse> {
    checkedBytesRequest(path, options);
    options = {
      maxBytes: options.maxBytes,
      rangeProbe: options.rangeProbe,
      signal: options.signal,
    };
    if (options.signal?.aborted)
      throw new MobileApiError(
        "The private file read was cancelled.",
        0,
        "request_aborted",
      );
    const generation = this.generation;
    const controller = new AbortController();
    const forwardAbort = () => controller.abort();
    options.signal?.addEventListener("abort", forwardAbort, { once: true });
    if (options.signal?.aborted) controller.abort();
    this.byteRequests.add(controller);
    let result: BytesResponse | undefined;
    try {
      if (!this.grant || this.now() >= this.expiresAt - 30_000) {
        let abort!: () => void;
        const cancelled = new Promise<never>((_resolve, reject) => {
          abort = () =>
            reject(
              new MobileApiError(
                "The private file read was cancelled.",
                0,
                "request_aborted",
              ),
            );
          controller.signal.addEventListener("abort", abort, { once: true });
          if (controller.signal.aborted) abort();
        });
        // Cancelling one viewer must not cancel a shared rotating refresh.
        try {
          await Promise.race([this.refresh(), cancelled]);
        } finally {
          controller.signal.removeEventListener("abort", abort);
        }
      }
      if (generation !== this.generation || !this.grant)
        throw new MobileApiError(
          "This session has ended.",
          401,
          "native_session_ended",
        );
      const grant = this.grant;
      const expiresAt = this.expiresAt;
      result = await this.transport.requestBytes(
        path,
        { ...options, signal: controller.signal },
        grant.access_token,
      );
      if (
        generation !== this.generation ||
        !this.grant ||
        this.grant.company.id !== grant.company.id ||
        this.grant.user.id !== grant.user.id ||
        this.grant.membership.id !== grant.membership.id
      )
        throw new MobileApiError(
          "This session has ended.",
          401,
          "native_session_ended",
        );
      if (this.now() >= expiresAt)
        throw new MobileApiError(
          "This session expired while the file was loading. Sign in again.",
          401,
          "native_session_expired",
        );
      if (controller.signal.aborted)
        throw new MobileApiError(
          "The private file read was cancelled.",
          0,
          "request_aborted",
        );
      return result;
    } catch (error) {
      result?.bytes.fill(0);
      if (generation !== this.generation)
        throw new MobileApiError(
          "This session has ended.",
          401,
          "native_session_ended",
        );
      if (error instanceof MobileApiError && error.status === 401)
        await this.invalidate(generation);
      throw error;
    } finally {
      this.byteRequests.delete(controller);
      options.signal?.removeEventListener("abort", forwardAbort);
    }
  }

  private async revokeCredential(
    credential: StoredCredential,
  ): Promise<boolean> {
    try {
      await this.transport.request("/api/auth/native/logout", {
        method: "POST",
        body: JSON.stringify({ refresh_token: credential.refreshToken }),
      });
      return true;
    } catch {
      return false;
    }
  }

  async signOut(): Promise<void> {
    const notified = this.endLocalAuthority();
    let credential: StoredCredential | null = null;
    let readFailed = false;
    let clearFailed = false;
    try {
      credential = await this.store.read();
    } catch {
      readFailed = true;
    }
    // Reading a damaged keychain must not bypass a best-effort purge.
    try {
      await this.store.clear();
    } catch {
      clearFailed = true;
    }
    const revoked = credential
      ? await this.revokeCredential(credential)
      : !readFailed;
    if (clearFailed)
      throw new Error(
        "Session access ended, but secure credentials could not be cleared. Revoke this device from another signed-in session before using it again.",
      );
    if (!revoked) {
      throw new Error(
        "Signed out on this device. Server revocation could not be confirmed; revoke the device from another signed-in session.",
      );
    }
    if (!notified)
      throw new Error(
        "Signed out on this device, but private-view cleanup could not be confirmed.",
      );
  }
}
