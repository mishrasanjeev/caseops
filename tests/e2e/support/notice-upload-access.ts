import { createHmac, randomBytes, randomUUID } from "node:crypto";
import { expect, request, type APIRequestContext, type APIResponse, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./cost-controls";

type Credentials = { email: string; password: string };
type Identity = {
  access_token: string;
  company: { id: string; slug: string };
  membership: { id: string; role: string };
  user: { id: string; email: string };
  capabilities: string[];
};
export type Notice = {
  id: string; subject: string; updated_at: string; status: string;
  source_kind: string; has_file: boolean; filename: string | null;
  size_bytes: number | null; owner_membership_id: string | null;
  matter_links: Array<{ matter_id: string }>;
};
export type Matter = {
  id: string; matter_code: string; status: string; updated_at: string;
  assignee_membership_id: string | null;
};

const managedEmail = "notice-acl-20261008@example.com";
const managedName = "Notice ACL 2026-10-08 fixture";
const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
const required = (name: string) => {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for notice acceptance; missing setup is not a skip.`);
  return value;
};

export async function status(response: APIResponse, expected: number, label: string) {
  // Never include authentication responses, cookies or credentials in evidence.
  expect(response.status(), `${label}: HTTP ${response.status()}`).toBe(expected);
}

export class NoticeAcceptance {
  readonly apiUrl: string;
  readonly webUrl: string;
  readonly local: boolean;
  readonly slug: string;
  readonly run = `${Date.now().toString(36)}-${randomUUID().slice(0, 8)}`;
  readonly notices = new Set<string>();
  readonly matters = new Set<string>();
  owner!: Identity;
  denied!: Identity;
  ownerApi!: APIRequestContext;
  deniedApi!: APIRequestContext;
  private readonly ownerCredentials: Credentials;
  private readonly deniedCredentials: Credentials;
  private readonly manageDenied: boolean;
  private managedMembership?: string;
  private readonly expectedSha?: string;

  constructor(baseURL: string) {
    const web = new URL(baseURL);
    const suppliedApi = process.env.PROD_API_BASE_URL?.trim();
    const localApi = `http://127.0.0.1:${process.env.CASEOPS_E2E_API_PORT || "8000"}`;
    // Docker's dynamic port wins. An inherited live URL must never redirect
    // a loopback acceptance run into production.
    const api = new URL(loopback(web)
      ? process.env.CASEOPS_E2E_API_PORT ? localApi
        : suppliedApi && loopback(new URL(suppliedApi)) ? suppliedApi : localApi
      : required("PROD_API_BASE_URL"));
    if (loopback(web) !== loopback(api)) throw new Error("Notice acceptance refuses mixed local/live endpoints.");
    this.local = loopback(web) && loopback(api);
    this.webUrl = web.origin;
    this.apiUrl = api.origin;
    this.expectedSha = process.env.CASEOPS_EXPECTED_RELEASE_SHA?.trim() || process.env.CASEOPS_RELEASE_SHA?.trim();
    if (!this.local) {
      if (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai") {
        throw new Error("Live notice acceptance is restricted to the canonical production origins.");
      }
      this.expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA");
    }
    if (this.expectedSha && !/^[a-f0-9]{40}$/.test(this.expectedSha)) {
      throw new Error("Notice acceptance requires a full 40-character release SHA.");
    }
    this.slug = this.local ? `notice-acl-${this.run}` : required("CASEOPS_NOTICE_QA_SLUG");
    if (!this.local && !["test-legal", "caseops-qa"].includes(this.slug)) {
      throw new Error("Notice acceptance may mutate only test-legal or existing caseops-qa, never a real tenant.");
    }
    this.manageDenied = this.local || process.env.CASEOPS_NOTICE_CREATE_TEST_LEGAL_MEMBER === "true";
    if (!this.local && this.manageDenied && this.slug !== "test-legal") {
      throw new Error("caseops-qa requires an existing denied actor; account writes are forbidden.");
    }
    this.ownerCredentials = this.local
      ? { email: `owner-${this.run}@example.com`, password: `Notice!${randomBytes(18).toString("hex")}` }
      : { email: required("CASEOPS_NOTICE_OWNER_EMAIL"), password: required("CASEOPS_NOTICE_OWNER_PASSWORD") };
    const deniedEmail = this.local ? `denied-${this.run}@example.com`
      : this.manageDenied ? managedEmail : required("CASEOPS_NOTICE_DENIED_EMAIL");
    this.deniedCredentials = {
      email: deniedEmail,
      password: this.manageDenied
        ? `NoticeFixture!${createHmac("sha256", this.ownerCredentials.password)
            .update(`caseops:notice-acl:2026-10-08:${this.slug}:${deniedEmail}`)
            .digest("base64url")}`
        : required("CASEOPS_NOTICE_DENIED_PASSWORD"),
    };
    if (!this.local && this.manageDenied && process.env.CASEOPS_NOTICE_DENIED_EMAIL && process.env.CASEOPS_NOTICE_DENIED_EMAIL !== managedEmail) {
      throw new Error("Managed notice fixtures cannot modify an arbitrary supplied denied account.");
    }
  }

  async assertRelease(api: APIRequestContext = this.ownerApi) {
    if (!this.expectedSha) return; // Unstamped loopback is local evidence only.
    for (const endpoint of [`${this.apiUrl}/api/build`, `${this.webUrl}/api/release-identity`]) {
      const response = await api.get(endpoint, { headers: noPaidProviderHeaders });
      await status(response, 200, "read exact serving release");
      expect((await response.json()).release_sha, endpoint).toBe(this.expectedSha);
    }
  }

  private async authenticate(credentials: Credentials): Promise<[Identity, APIRequestContext]> {
    const loginApi = await request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
    try {
      const response = await loginApi.post(`${this.apiUrl}/api/auth/login`, {
        data: { company_slug: this.slug, ...credentials },
      });
      await status(response, 200, "authenticate dedicated notice actor");
      const identity = await response.json() as Identity;
      expect(identity.company.slug).toBe(this.slug);
      expect(identity.user.email.toLowerCase()).toBe(credentials.email.toLowerCase());
      expect(identity.access_token).toBeTruthy();
      const api = await request.newContext({
        extraHTTPHeaders: { ...noPaidProviderHeaders, Authorization: `Bearer ${identity.access_token}` },
      });
      return [identity, api];
    } finally {
      await loginApi.dispose();
    }
  }

  async start() {
    const preflight = await request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
    try {
      await this.assertRelease(preflight);
      if (this.local) {
        const response = await preflight.post(`${this.apiUrl}/api/bootstrap/company`, {
          data: { company_name: `Notice acceptance ${this.run}`, company_slug: this.slug,
            company_type: "law_firm", owner_full_name: "Notice acceptance owner",
            owner_email: this.ownerCredentials.email, owner_password: this.ownerCredentials.password },
        });
        await status(response, 200, "bootstrap loopback-only notice tenant");
      }
    } finally {
      await preflight.dispose();
    }
    [this.owner, this.ownerApi] = await this.authenticate(this.ownerCredentials);
    expect(this.owner.membership.role, "restricted Matter owner positive control").toBe("owner");
    expect(this.owner.capabilities).toEqual(expect.arrayContaining(["documents:upload", "documents:manage", "matters:create", "matters:archive"]));

    if (this.manageDenied) {
      await this.assertRelease();
      const usersResponse = await this.ownerApi.get(`${this.apiUrl}/api/companies/current/users`);
      await status(usersResponse, 200, "inspect bounded fixed-identity fixture reuse");
      const directory = await usersResponse.json();
      expect(directory.company_id).toBe(this.owner.company.id);
      const matches = directory.users.filter((user: { email: string }) => user.email === this.deniedCredentials.email);
      expect(matches.length, "fixed fixture identity must be unambiguous").toBeLessThanOrEqual(1);
      if (matches.length) {
        const existing = matches[0];
        expect(existing).toMatchObject({ full_name: managedName, role: "partner", user_active: false });
        // Never take over a fixture already in use by an overlapping run.
        expect(existing.membership_active, "managed fixture must be inactive before reuse").toBe(false);
        this.managedMembership = existing.membership_id;
        const activated = await this.ownerApi.patch(`${this.apiUrl}/api/companies/current/users/${existing.membership_id}`, { data: { is_active: true } });
        await status(activated, 200, "activate this dedicated test fixture");
        expect(await activated.json()).toMatchObject({ membership_active: true, user_active: true });
      } else {
        const created = await this.ownerApi.post(`${this.apiUrl}/api/companies/current/users`, {
          data: { full_name: managedName, ...this.deniedCredentials, role: "partner" },
        });
        await status(created, 200, "create single dedicated test fixture");
        this.managedMembership = (await created.json()).membership_id;
      }
    }
    [this.denied, this.deniedApi] = await this.authenticate(this.deniedCredentials);
    expect(this.denied.company.id).toBe(this.owner.company.id);
    expect(this.denied.membership.id).not.toBe(this.owner.membership.id);
    expect(this.denied.user.id).not.toBe(this.owner.user.id);
    expect(this.denied.membership.role).not.toBe("owner");
    expect(this.denied.capabilities, "denial must not be a missing upload/manage capability").toEqual(
      expect.arrayContaining(["documents:upload", "documents:manage"]),
    );
  }

  async signIn(page: Page, actor: "owner" | "denied") {
    await page.goto(`${this.webUrl}/sign-in`);
    const credentials = actor === "owner" ? this.ownerCredentials : this.deniedCredentials;
    await page.locator("#company-slug").fill(this.slug);
    await page.locator("#email").fill(credentials.email);
    await page.locator("#password").fill(credentials.password);
    const login = page.waitForResponse(r => new URL(r.url()).pathname === "/api/auth/login" && r.request().method() === "POST");
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    expect((await login).status(), "browser notice actor authentication").toBe(200);
    await page.waitForURL(/\/app(?:[/?]|$)/);
    const current = await page.request.get(`${this.apiUrl}/api/companies/current`);
    await status(current, 200, "check independently authenticated browser actor");
    const context = await current.json();
    expect(context.company.id).toBe(this.owner.company.id);
    expect(context.membership.id).toBe(this[actor].membership.id);
  }

  async createMatter(code: string, restricted: boolean): Promise<Matter> {
    const response = await this.ownerApi.post(`${this.apiUrl}/api/matters/`, {
      data: { matter_code: code, title: `${restricted ? "Restricted" : "Visible"} notice Matter ${code}`,
        practice_area: "Litigation", forum_level: "high_court", status: "active",
        assignee_membership_id: null, team_id: null },
    });
    await status(response, 200, "create unassigned notice Matter");
    const matter = await response.json() as Matter;
    this.matters.add(matter.id);
    expect(matter.assignee_membership_id).toBeNull();
    if (restricted) {
      const restriction = await this.ownerApi.post(`${this.apiUrl}/api/matters/${matter.id}/access/restricted`, { data: { restricted: true } });
      await status(restriction, 200, "restrict unassigned Matter");
    }
    const access = await this.ownerApi.get(`${this.apiUrl}/api/matters/${matter.id}/access`);
    await status(access, 200, "prove exact Matter access fixture");
    expect(await access.json()).toMatchObject({ matter_id: matter.id, restricted_access: restricted, grants: [], walls: [] });
    const persisted = await this.ownerApi.get(`${this.apiUrl}/api/matters/${matter.id}`);
    await status(persisted, 200, "owner reads persisted unassigned Matter");
    expect((await persisted.json()).assignee_membership_id).toBeNull();
    await status(await this.deniedApi.get(`${this.apiUrl}/api/matters/${matter.id}`), restricted ? 404 : 200, "establish denied actor Matter boundary");
    return matter;
  }

  async readNotice(id: string): Promise<Notice> {
    const response = await this.ownerApi.get(`${this.apiUrl}/api/notices/${id}`);
    await status(response, 200, "owner notice read");
    return response.json();
  }

  async createLinkedNotice(subject: string, matter: Matter, body: string): Promise<Notice> {
    const created = await this.ownerApi.post(`${this.apiUrl}/api/notices/`, {
      data: { subject, direction: "received", matter_ids: [matter.id], owner_membership_id: this.owner.membership.id },
    });
    await status(created, 201, "create linked notice");
    const notice = await created.json() as Notice;
    this.notices.add(notice.id);
    const upload = await this.ownerApi.post(`${this.apiUrl}/api/notices/${notice.id}/file`, {
      multipart: { expected_updated_at: notice.updated_at, file: { name: "linked-proof.txt", mimeType: "text/plain", buffer: Buffer.from(body) } },
    });
    await status(upload, 200, "owner linked notice first upload");
    return upload.json();
  }

  async close() {
    const failures: Array<{ label: string; message: string }> = [];
    // Attempt every cleanup even when one fails; retain the auditable records.
    const clean = async (label: string, fn: () => Promise<void>) => {
      try { await fn(); } catch (error) {
        failures.push({ label, message: error instanceof Error ? error.message : "Unknown cleanup failure" });
      }
    };
    if (this.ownerApi) {
      for (const id of this.notices) await clean(`close notice ${id}`, async () => {
        const notice = await this.readNotice(id);
        const response = await this.ownerApi.patch(`${this.apiUrl}/api/notices/${id}`, {
          data: { status: "Closed", expected_updated_at: notice.updated_at },
        });
        await status(response, 200, "close fixture notice");
        expect((await this.readNotice(id)).status).toBe("Closed");
      });
      for (const id of this.matters) await clean(`dispose Matter ${id}`, async () => {
        const read = await this.ownerApi.get(`${this.apiUrl}/api/matters/${id}`);
        await status(read, 200, "read fixture before lifecycle cleanup");
        const matter = await read.json() as Matter;
        if (matter.status === "disposed") return;
        const response = await this.ownerApi.patch(`${this.apiUrl}/api/matters/${id}/lifecycle/status`, {
          data: { to_status: "disposed", expected_from_status: matter.status, expected_updated_at: matter.updated_at,
            reason: "Notice 2026-10-08 acceptance completed; retain terminal audit evidence." },
        });
        await status(response, 200, "dispose fixture through dedicated lifecycle endpoint");
        const persisted = await this.ownerApi.get(`${this.apiUrl}/api/matters/${id}`);
        await status(persisted, 200, "read retained terminal fixture");
        expect((await persisted.json()).status).toBe("disposed");
      });
      if (this.managedMembership) await clean("deactivate managed notice actor", async () => {
        const response = await this.ownerApi.patch(`${this.apiUrl}/api/companies/current/users/${this.managedMembership}`, { data: { is_active: false } });
        await status(response, 200, "deactivate managed notice actor");
        expect(await response.json()).toMatchObject({ membership_active: false, user_active: false });
        if (this.deniedApi) {
          const rejected = await this.deniedApi.get(`${this.apiUrl}/api/companies/current`);
          await status(rejected, 403, "deactivated fixture session is inactive");
          expect((await rejected.json()).detail).toBe("The current session is no longer active.");
        }
      });
      await clean("release identity after cleanup", () => this.assertRelease());
    }
    await this.deniedApi?.dispose();
    await this.ownerApi?.dispose();
    expect(failures, "Cleanup failures require attention; no fixture is silently reopened or retried.").toEqual([]);
  }
}
