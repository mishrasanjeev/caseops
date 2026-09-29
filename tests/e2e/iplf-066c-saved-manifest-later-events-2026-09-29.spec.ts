/** Draft/document sister proof. Review has no unchanged-document producer. */
import { expect, request, test, type APIRequestContext } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl } from "./support/env";
import { expectStatus } from "./support/iplf058b";
import {
  assertLaterAudit, frozenQaBody, isLoopback, runLoopbackSavedManifestFixture, settledGeneration,
  type SavedManifestFixture,
} from "./support/saved-manifest-document-proof";

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

test("IPLF-UJ-66C Draft/document sister: benignly retired outputs stay revoked after later events and restored access", async ({ page }, testInfo) => {
  test.setTimeout(900_000);
  const web = String(testInfo.project.use.baseURL).replace(/\/$/, "");
  const local = isLoopback(web);
  const api = (local ? process.env.CASEOPS_API_BASE_URL || apiBaseUrl : required("PROD_API_BASE_URL")).replace(/\/$/, "");
  expect(isLoopback(api), "browser/API must agree on local versus production runtime").toBe(local);
  const sha = required(local ? "CASEOPS_RELEASE_SHA" : "CASEOPS_EXPECTED_RELEASE_SHA");
  expect(sha).toMatch(/^[0-9a-f]{40}$/);
  const slug = process.env.CASEOPS_IP_QA_SLUG || "caseops-ip-qa";
  const email = process.env.CASEOPS_IP_QA_EMAIL || "ip-qa-bot@caseops.ai";
  const password = local ? process.env.CASEOPS_IP_QA_PASSWORD || "SavedManifestDocker2026!Safe" : required("CASEOPS_IP_QA_PASSWORD");
  expect(slug).toMatch(/^caseops-ip-qa/);
  const owner = await request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
  try {
    const identities = async () => {
      for (const [base, route] of [[api, "/api/build"], [web, "/api/release-identity"]]) {
        const response = await owner.get(base + route);
        await expectStatus(response, 200, "exact candidate identity");
        expect((await response.json()).release_sha).toBe(sha);
      }
    };
    await identities();
    if (local) runLoopbackSavedManifestFixture(api, web, "seed", {
      QA_SLUG: slug, QA_EMAIL: email, QA_PASSWORD: password, QA_SHA: sha,
    });
    const login = await owner.post(`${api}/api/auth/login`, {
      data: { company_slug: slug, email, password },
    });
    await expectStatus(login, 200, "existing dedicated QA owner login");
    const ownerIdentity = await login.json();
    const ownerHeaders = { ...noPaidProviderHeaders, Authorization: `Bearer ${ownerIdentity.access_token}` };
    const code = `SAVED-MANIFEST-${sha.slice(0, 12).toUpperCase()}`;
    const matters = await owner.get(`${api}/api/matters/`, { params: { q: code, limit: 20 } });
    await expectStatus(matters, 200, "release-owned saved-output fixture discovery");
    const anchors = (await matters.json()).matters.filter((matter: { matter_code: string }) => matter.matter_code === code);
    expect(anchors).toHaveLength(1);
    const root = `${api}/api/matters/${anchors[0].id}/drafts`;
    const listed = await owner.get(root);
    await expectStatus(listed, 200, "discover immutable control and retained output identities");
    const control = (await listed.json()).drafts.find((draft: { title: string }) => draft.title === `${code} unchanged control`);
    expect(control, "missing retained control is a failed fixture, never a skip").toBeTruthy();
    const fixture = control.versions[0].context_manifest.qa_saved_manifest_fixture as SavedManifestFixture;
    expect(fixture.schema).toBe("caseops.saved-manifest-document-sister-qa.v1");
    expect(fixture.release_sha).toBe(sha);
    expect(fixture.anchor_id).toBe(anchors[0].id);
    expect(fixture.owner_membership_id).toBe(ownerIdentity.membership.id);
    expect(fixture.captured_generation_id).not.toBe(fixture.benign_generation_id);
    expect(control.versions[0].source_manifest).toHaveLength(1);
    expect(control.versions[0].source_manifest[0]).toMatchObject({
      schema: "caseops.private-saved-output-source.v1", generation_id: fixture.captured_generation_id,
      source_type: "matter_document", source_id: fixture.cases.control.attachment_id,
      source_version: fixture.cases.control.source_version,
    });
    if (!local) {
      expect(fixture.post_event_generation_id, "release seed must contain completed serialized rebuild evidence").toBeTruthy();
      expect(fixture.post_event_generation_id).not.toBe(fixture.captured_generation_id);
      expect(fixture.post_event_generation_id).not.toBe(fixture.benign_generation_id);
      expect(Number.isFinite(Date.parse(fixture.post_event_activated_at || ""))).toBe(true);
      expect(fixture.later_event_audit_ids?.access).toHaveLength(2);
      expect(fixture.later_event_audit_ids?.tombstone).toHaveLength(2);
    }
    const memberLogin = await page.request.post(`${api}/api/auth/login`, {
      data: { company_slug: slug, email: fixture.member_email, password },
      headers: noPaidProviderHeaders,
    });
    await expectStatus(memberLogin, 200, "dedicated QA member login");
    const memberIdentity = await memberLogin.json();
    expect(memberIdentity.membership.id).toBe(fixture.membership_id);
    await page.goto(web);
    await page.evaluate((identity) => window.localStorage.setItem("caseops.session.context", JSON.stringify({
      company: identity.company, user: identity.user, membership: identity.membership, capabilities: identity.capabilities,
    })), memberIdentity);
    const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${memberIdentity.access_token}` };
    const draftsUrl = `${web}/app/matters/${fixture.anchor_id}/drafts`;
    const visibleControl = async () => {
      await page.goto(draftsUrl);
      await page.reload();
      await expect(page.getByTestId(`draft-row-${fixture.cases.control.draft_id}`)).toBeVisible();
    };
    const blocked = async (name: "access" | "tombstone") => {
      const target = fixture.cases[name];
      const source = await page.request.get(`${api}/api/matters/${target.matter_id}`, { headers });
      await expectStatus(source, 200, "restored source authorization");
      expect((await source.json()).status).toBe("intake");
      const workspace = await page.request.get(`${api}/api/matters/${target.matter_id}/workspace`, { headers });
      await expectStatus(workspace, 200, "restored document workspace");
      const document = (await workspace.json()).attachments.find((row: { id: string }) => row.id === target.attachment_id);
      expect(document.sha256_hex).toBe(target.source_version);
      await visibleControl();
      await expect(page.getByTestId(`draft-row-${target.draft_id}`)).toHaveCount(0);
      for (const suffix of ["", "/export.docx", "/export.pdf"]) {
        const response = await page.request.get(`${root}/${target.draft_id}${suffix}`, { headers });
        await expectStatus(response, 409, "retained stale output must remain fail-closed");
        expect(await response.text()).toContain("Private source access or generation changed");
      }
      await page.goto(`${draftsUrl}/${target.draft_id}`);
      await page.reload();
      await expect(page.getByRole("heading", { name: "Could not load this draft" })).toBeVisible();
      await expect(page.getByTestId("draft-body-readonly")).toHaveCount(0);
      await expect(page.getByTestId("draft-download-docx")).toHaveCount(0);
      await expect(page.getByTestId("draft-download-pdf")).toHaveCount(0);
      await expect(page.getByTestId("draft-generate")).toHaveCount(0);
      await expect(page.getByText(frozenQaBody(fixture, name), { exact: true })).toHaveCount(0);
      await assertLaterAudit(owner, api, fixture, name);
    };
    const initialGeneration = fixture.benign_generation_id;
    const baseline = await Promise.all((["access", "tombstone"] as const).map(async (name) => {
      const response = await page.request.get(`${root}/${fixture.cases[name].draft_id}`, { headers });
      expect([200, 409]).toContain(response.status());
      return response.status();
    }));
    expect(baseline.every((status) => status === baseline[0]), "partial/interrupted evidence cannot certify a fresh or retained run").toBe(true);
    if (!local) expect(baseline).toEqual([409, 409]);
    if (local && baseline[0] === 200) {
      await visibleControl();
      for (const name of ["access", "tombstone"] as const) {
        const target = fixture.cases[name];
        await expect(page.getByTestId(`draft-row-${target.draft_id}`)).toBeVisible();
        const detail = await page.request.get(`${root}/${target.draft_id}`, { headers });
        const draft = await detail.json();
        const version = draft.versions[0];
        expect(version.id).toBe(target.version_id);
        expect(version.body).toBe(frozenQaBody(fixture, name));
        expect(version.model_run_id).toBeNull();
        expect(version.source_manifest).toHaveLength(1);
        expect(version.source_manifest[0]).toMatchObject({
          schema: "caseops.private-saved-output-source.v1", generation_id: fixture.captured_generation_id,
          source_type: "matter_document", source_id: target.attachment_id, source_version: target.source_version,
        });
        await page.goto(`${draftsUrl}/${target.draft_id}`);
        await page.reload();
        await expect(page.getByTestId("draft-body-readonly")).toHaveText(frozenQaBody(fixture, name));
        // No invented authority/approval may turn this citation-free fixture
        // into an exportable legal draft. Later rejection must precede this gate.
        for (const extension of ["docx", "pdf"]) {
          const exported = await page.request.get(`${root}/${target.draft_id}/export.${extension}`, { headers });
          await expectStatus(exported, 422, "unchanged synthetic draft retains the citation safety gate");
          expect((await exported.json()).type).toBe("verified_citations_required");
        }
        const editedBody = frozenQaBody(fixture, name) + " Manual QA edit.";
        const edited = await page.request.patch(`${root}/${target.draft_id}`, {
          headers, data: { body: editedBody },
        });
        await expectStatus(edited, 200, "legitimate manual writer retains the frozen source contract");
        const editedDraft = await edited.json();
        expect(editedDraft.versions).toHaveLength(2);
        expect(editedDraft.versions[1].source_manifest).toEqual(version.source_manifest);
        expect(editedDraft.versions[1].model_run_id).toBeNull();
        await page.reload();
        await expect(page.getByTestId("draft-body-readonly")).toHaveText(editedBody);
      }
      const access = fixture.cases.access;
      const wall = await owner.post(`${api}/api/matters/${access.matter_id}/access/walls`, {
        headers: ownerHeaders,
        data: { excluded_membership_id: fixture.membership_id, reason: "Synthetic saved-manifest later-event canary." },
      });
      await expectStatus(wall, 200, "legitimate later ethical-wall event");
      const wallId = (await wall.json()).id;
      try {
        const denied = await page.request.get(`${api}/api/matters/${access.matter_id}`, { headers });
        await expectStatus(denied, 404, "ethical wall must actually revoke member access");
      } finally {
        await expectStatus(await owner.delete(`${api}/api/matters/${access.matter_id}/access/walls/${wallId}`, { headers: ownerHeaders }), 204, "restore source access without rewriting output");
      }
      const sourceId = fixture.cases.tombstone.matter_id;
      const lifecycle = async (to: "disposed" | "intake") => {
        const read = await owner.get(`${api}/api/matters/${sourceId}`);
        await expectStatus(read, 200, "source lifecycle concurrency token");
        const current = await read.json();
        expect(current.status).toBe(to === "disposed" ? "intake" : "disposed");
        const response = await owner.patch(`${api}/api/matters/${sourceId}/lifecycle/status`, { headers: ownerHeaders, data: {
          to_status: to, expected_from_status: current.status, expected_updated_at: current.updated_at,
          reason: "Synthetic saved-manifest later-event proof; restore source, never saved output.",
        } });
        await expectStatus(response, 200, "legitimate lifecycle source event");
      };
      await lifecycle("disposed");
      await lifecycle("intake");
      await identities();
      runLoopbackSavedManifestFixture(api, web, "rebuild", { QA_COMPANY_ID: ownerIdentity.company.id });
      await settledGeneration(owner, api, initialGeneration);
    } else if (local) {
      await settledGeneration(owner, api, initialGeneration);
    }
    const width = async () => {
      const metrics = await page.evaluate(() => ({
        document: document.documentElement.scrollWidth, viewport: window.innerWidth,
      }));
      expect(metrics.document, "read surface must not overflow the viewport").toBeLessThanOrEqual(metrics.viewport);
    };
    for (const viewport of [{ width: 1280, height: 900 }, { width: 360, height: 800 }]) {
      await page.setViewportSize(viewport);
      for (const name of ["access", "tombstone"] as const) {
        await blocked(name);
        await width();
        await visibleControl();
        await width();
        await expect(page.getByTestId(`draft-row-${fixture.cases[name].draft_id}`)).toHaveCount(0);
      }
      // Unrelated saved content and download affordance remain usable after
      // the same events/rebuild, at both widths, without duplicate mutations.
      await page.goto(`${draftsUrl}/${fixture.cases.control.draft_id}`);
      await page.reload();
      const body = page.getByTestId("draft-body-readonly");
      const download = page.getByTestId("draft-download-docx");
      await expect(body).toBeVisible();
      await expect(body).toHaveText(frozenQaBody(fixture, "control"));
      await expect(download).toBeVisible();
      await body.scrollIntoViewIfNeeded();
      await expect(body).toBeInViewport();
      await download.scrollIntoViewIfNeeded();
      await expect(download).toBeInViewport();
      await width();
      const bodyBox = await body.boundingBox();
      const downloadBox = await download.boundingBox();
      expect(bodyBox).not.toBeNull();
      expect(downloadBox).not.toBeNull();
      expect(downloadBox!.x).toBeGreaterThanOrEqual(0);
      expect(downloadBox!.x + downloadBox!.width).toBeLessThanOrEqual(viewport.width);
      expect(bodyBox!.width, "visible control body cannot collapse").toBeGreaterThan(100);
      expect(downloadBox!.x + downloadBox!.width <= bodyBox!.x ||
        bodyBox!.x + bodyBox!.width <= downloadBox!.x ||
        downloadBox!.y + downloadBox!.height <= bodyBox!.y ||
        bodyBox!.y + bodyBox!.height <= downloadBox!.y,
      "control body and download action must not overlap").toBe(true);
    }
    await identities();
    console.log(`IPLF-UJ-66C exact release ${sha}: Draft/document sister proof; Review original remains unprobeable.`);
  } finally {
    await owner.dispose();
  }
});
