import { JsonTransport, MobileApiError } from "../network/http.ts";
import { parseGrant } from "./types.ts";
import type {
  CredentialStore,
  SessionIdentity,
  StoredCredential,
} from "./types.ts";

export class NativeSession {
  private grant: (SessionIdentity & { access_token: string }) | null = null;
  private expiresAt = 0;
  private refreshInFlight: Promise<SessionIdentity> | null = null;
  private generation = 0;
  constructor(
    private readonly transport: JsonTransport,
    private readonly store: CredentialStore,
    private readonly now: () => number = Date.now,
    private readonly onInvalidated: () => void = () => {},
  ) {}

  get identity(): SessionIdentity | null {
    if (!this.grant) return null;
    const { company, user, membership, capabilities } = this.grant;
    return { company, user, membership, capabilities: [...capabilities] };
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
    const generation = ++this.generation;
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
        this.grant = null;
        this.expiresAt = 0;
        await this.revokeCredential(saved);
        // A lost refresh acknowledgement cannot safely replay a rotating token.
        await this.store.clear();
        this.onInvalidated();
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
    const identity = await this.request<SessionIdentity>("/api/auth/me");
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
    return identity;
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
        ++this.generation;
        this.grant = null;
        this.expiresAt = 0;
        await this.store.clear();
        this.onInvalidated();
      }
      throw error;
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
    ++this.generation;
    this.grant = null;
    this.expiresAt = 0;
    this.onInvalidated();
    const credential = await this.store.read();
    await this.store.clear();
    if (credential && !(await this.revokeCredential(credential))) {
      throw new Error(
        "Signed out on this device. Server revocation could not be confirmed; revoke the device from another signed-in session.",
      );
    }
  }
}
