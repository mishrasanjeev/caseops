import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import type { PatentParty, PatentPartyPage } from "../../apps/web/lib/api/ip-patents";
import { apiBaseUrl, patentRunId, patentScreenshot } from "./support/patent-acceptance";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { assertPatentControlsFit } from "./support/patent-layout";
import { bootstrapPatentTenant, enablePatentWorkspace, signInPatentTenant } from "./support/patent-acceptance";

test.use({ extraHTTPHeaders: noPaidProviderHeaders });

// UJ-29 / PAT-01 / IPLF-080-FAMILY and COMPAT: sourced facts, not ownership decisions.
for (const kind of ["family", "application"] as const) {
  for (const width of [393, 768, 1280]) {
    test(`IPLF-080 ${kind} parties retain source, replacement history and closure at ${width}px`, async ({ page, playwright }, testInfo) => {
      const run = patentRunId();
    const tenant = await bootstrapPatentTenant(page.request);
      const headers = { ...await enablePatentWorkspace(page.request, tenant), ...noPaidProviderHeaders };
      const client = await page.request.post(`${apiBaseUrl}/api/clients`, {
        headers, data: { name: `Party journey client ${run}`, client_type: "corporate" },
      });
      expect(client.status(), await client.text()).toBe(200);
      const clientId = (await client.json()).id;
      const familyResponse = await page.request.post(`${apiBaseUrl}/api/ip/patents/families`, {
        headers: { ...headers, "Idempotency-Key": crypto.randomUUID() }, data: {
          title: `Sourced party family ${run}`, client_id: clientId, disclosure_date: "2026-09-05",
          disclosure_narrative: "Private invention party evidence.",
        },
      });
      expect(familyResponse.status(), await familyResponse.text()).toBe(201);
      const family = await familyResponse.json();
      const taxonomy = await page.request.post(`${apiBaseUrl}/api/ip/document-taxonomy/seed`, { headers });
      expect(taxonomy.status(), await taxonomy.text()).toBe(200);
      const bytes = Buffer.from(`Synthetic signed party source with original and corrected address facts. ${run} `.repeat(30));
      const upload = await page.request.post(`${apiBaseUrl}/api/ip/documents/upload`, {
        headers, multipart: {
          metadata_json: JSON.stringify({ taxonomy_key: "evidence", title: "Signed party source", confidentiality: "restricted",
            is_privileged: true, client_code: "PARTY", asset_type: "Patent", mark: "Substrate", jurisdiction: "IN",
            document_date: "2026-09-05", links: [{ target_type: "docket", target_id: family.docket_id }] }),
          upload: { name: "signed-party-source.txt", mimeType: "text/plain", buffer: bytes },
        },
      });
      expect(upload.status(), await upload.text()).toBe(200);
      const uploaded = await upload.json();
      expect(uploaded.outcome).toBe("created");
      const document = uploaded.document;
      expect(document).not.toBeNull();
      const source = { kind: "document_version", document_id: document.id,
        document_version_id: document.versions[0].id, content_sha256: document.versions[0].sha256_hex };
      let record = family;
      if (kind === "application") {
        const created = await page.request.post(`${apiBaseUrl}/api/ip/patents/applications`, {
          headers: { ...headers, "Idempotency-Key": crypto.randomUUID() }, data: {
            family_id: family.id, expected_family_version: family.version, expected_family_lifecycle_version: family.lifecycle_version,
            facts: { title: "Sourced party application", application_kind: "complete", jurisdiction: "IN", office: "IP India",
              filing_date: "2026-09-05", source, identifiers: [], source_pending_identifier_allocation: true },
          },
        });
        expect(created.status(), await created.text()).toBe(201);
        record = await created.json();
      }
      const endpoint = `${apiBaseUrl}/api/ip/patents/dockets/${record.docket_id}/parties`;
      await signInPatentTenant(page, tenant);
      await page.setViewportSize({ width, height: 900 });
      // Open the exact server-returned family; the bounded index is not a
      // reliable locator for a newly-created record in retained QA data.
      await page.goto(`/app/ip/patents/${family.id}`);
      await expect(page).toHaveURL(`/app/ip/patents/${family.id}`);
      await expect(page.getByRole("heading", { name: family.facts.title, level: 1, exact: true })).toBeVisible();
      if (kind === "application") {
        await page.getByRole("tab", { name: "Applications", exact: true }).click();
        await page.getByRole("link", { name: record.facts.title, exact: true }).click();
        await expect(page).toHaveURL(`/app/ip/patents/applications/${record.id}`);
        await expect(page.getByRole("heading", { name: record.facts.title, level: 1, exact: true })).toBeVisible();
      }
      const recordUrl = page.url();
      await page.getByRole("tab", { name: "Parties", exact: true }).click();
      const roles = ["inventor", "applicant", "proprietor", "agent", "licensee"];
      let original: PatentParty | undefined;
      let originalCommand: { key: string; data: unknown } | undefined;
      for (const [index, role] of roles.entries()) {
        await page.getByRole("button", { name: "Add party", exact: true }).click();
        const form = page.getByRole("form", { name: "Add patent party", exact: true });
        await form.getByLabel("Party role", { exact: true }).selectOption(role);
        await form.getByLabel("Party name", { exact: true }).fill(`Recorded ${role}`);
        await form.getByLabel("Linked client", { exact: true }).selectOption(clientId);
        await form.getByLabel("Address lines", { exact: true }).fill("Original address\nUnit 2");
        await form.getByLabel("City", { exact: true }).fill("Delhi");
        await form.getByLabel("State or region", { exact: true }).fill("Delhi");
        await form.getByLabel("Postal code", { exact: true }).fill("110001");
        await form.getByLabel("Country code", { exact: true }).fill("IN");
        await form.getByLabel("Effective from", { exact: true }).fill("2026-09-01");
        await form.getByLabel("Party source version", { exact: true }).selectOption(source.document_version_id);
        await form.getByLabel("Party change reason", { exact: true }).fill("Record exact signed party source facts.");
        await assertPatentControlsFit(page);
        const saving = page.waitForResponse((response) => response.url() === endpoint && response.request().method() === "POST");
        await form.getByRole("button", { name: "Save party facts", exact: true }).click();
        const savedResponse = await saving;
        expect(savedResponse.status(), await savedResponse.text()).toBe(201);
        if (index === 0) {
          const request = savedResponse.request();
          const key = request.headers()["idempotency-key"];
          expect(key).toBeTruthy();
          originalCommand = { key, data: request.postDataJSON() };
          const replay = await page.request.post(endpoint, { headers: { ...headers, "Idempotency-Key": key }, data: originalCommand.data });
          expect(replay.status(), await replay.text()).toBe(201);
          expect(await replay.json()).toEqual(await savedResponse.json());
        }
        await expect(page.getByRole("heading", { name: `Recorded ${role}`, exact: true })).toBeVisible();
        const stored = await page.request.get(endpoint, { headers });
        expect(stored.status(), await stored.text()).toBe(200);
        const current: PatentPartyPage = await stored.json();
        expect(current.collection_sequence).toBe(index + 1);
        const saved = current.parties.find((row) => row.fact.role === role);
        if (!saved) throw new Error(`The saved ${role} was absent from the authoritative party list.`);
        expect(saved.fact).toEqual({ role, name: `Recorded ${role}`, client_id: clientId,
          address: { address_lines: ["Original address", "Unit 2"], city: "Delhi", region: "Delhi", postal_code: "110001", country_code: "IN" },
          effective_from: "2026-09-01", effective_until: null, source });
        if (index === 0) original = saved;
      }
      if (!original) throw new Error("The original inventor was not persisted.");
      await page.reload();
      await page.getByRole("tab", { name: "Parties", exact: true }).click();
      await expect(page.getByRole("list", { name: "Recorded patent parties" }).getByRole("listitem")).toHaveCount(5);
      const inventor = page.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Recorded inventor", exact: true }) });
      await inventor.getByRole("button", { name: "Replace facts", exact: true }).click();
      const form = page.getByRole("form", { name: "Replace patent party", exact: true });
      await expect(form.getByLabel("Address lines", { exact: true })).toHaveValue("Original address\nUnit 2");
      await form.getByLabel("Party name", { exact: true }).fill("Corrected inventor");
      await form.getByLabel("Address lines", { exact: true }).fill("Corrected sourced address");
      await form.getByLabel("Effective from", { exact: true }).fill("2026-09-05");
      await form.getByLabel("Party change reason", { exact: true }).fill("Retain the original filed party while recording the correction.");
      if (width === 1280) {
        for (const boundary of [639, 640, 641, 767, 768, 769, 1023, 1024, 1025]) {
          await page.setViewportSize({ width: boundary, height: 900 });
          await assertPatentControlsFit(page);
        }
        await page.setViewportSize({ width, height: 900 });
      }
      await patentScreenshot(page, testInfo, `patent-${kind}-party-editor-${width}.png`);
      await form.getByRole("button", { name: "Save party facts", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Corrected inventor", exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Recorded inventor", exact: true })).toHaveCount(0);
      await page.getByLabel("Include superseded facts", { exact: true }).check();
      const historical = page.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Recorded inventor", exact: true }) });
      await expect(historical).toContainText("Superseded");
      await expect(historical.getByRole("button", { name: "Replace facts" })).toHaveCount(0);
      const downloading = page.waitForEvent("download");
      await historical.getByRole("button", { name: "Download source version", exact: true }).click();
      const downloaded = await downloading;
      const target = testInfo.outputPath("original-party-source.txt");
      await downloaded.saveAs(target);
      expect(createHash("sha256").update(await readFile(target)).digest("hex")).toBe(source.content_sha256);
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(source.content_sha256);
      const retained = await page.request.get(`${endpoint}/${original.id}`, { headers });
      expect(retained.status(), await retained.text()).toBe(200);
      expect(await retained.json()).toEqual({ ...original, is_current: false });
      const stale = await page.request.post(endpoint, { headers: { ...headers, "Idempotency-Key": crypto.randomUUID() }, data: {
        expected_version: record.version, expected_lifecycle_version: 0, expected_party_sequence: 5,
        fact: original.fact, reason: "Stale party replacement must be rejected.", supersedes_party_id: original.id,
      } });
      expect(stale.status(), await stale.text()).toBe(409);
      const otherApi = await playwright.request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
      try {
        const other = await bootstrapPatentTenant(otherApi, true);
        const denied = await otherApi.get(endpoint, { headers: { Authorization: `Bearer ${other.access_token}` } });
        expect(denied.status(), await denied.text()).toBe(404);
      } finally { await otherApi.dispose(); }
      await page.getByRole("tab", { name: "Lifecycle", exact: true }).click();
      await page.getByLabel("Effective date and time", { exact: true }).fill("2026-09-07T10:00");
      await page.getByLabel("Reason", { exact: true }).fill("Explicitly close this patent record and preserve party history.");
      await page.getByLabel("Outcome", { exact: true }).fill("closed");
      await page.getByLabel("Instruction or evidence reference", { exact: true }).fill("local-fixture:party-record-close");
      await page.getByRole("button", { name: "Preview lifecycle change" }).click();
      await page.getByLabel("I confirm this lifecycle change and its recorded impacts.").check();
      await page.getByRole("button", { name: "Confirm lifecycle change" }).click();
      await expect(page.getByRole("list", { name: "Lifecycle events" })).toContainText("local-fixture:party-record-close");
      await page.goto(recordUrl);
      await page.getByRole("tab", { name: "Parties", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Corrected inventor", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Add party", exact: true })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Replace facts", exact: true })).toHaveCount(0);
      const closedWrite = await page.request.post(endpoint, { headers: { ...headers, "Idempotency-Key": crypto.randomUUID() }, data: {
        expected_version: record.version, expected_lifecycle_version: 1, expected_party_sequence: 6,
        fact: original.fact, reason: "A closed record may not accept party mutations.",
      } });
      expect(closedWrite.status(), await closedWrite.text()).toBe(404);
      if (!originalCommand) throw new Error("The original browser creation command was not captured.");
      const closedReplay = await page.request.post(endpoint, {
        headers: { ...headers, "Idempotency-Key": originalCommand.key }, data: originalCommand.data,
      });
      expect(closedReplay.status(), await closedReplay.text()).toBe(404);
      const retainedAfterReplay = await page.request.get(`${endpoint}/${original.id}`, { headers });
      expect(retainedAfterReplay.status(), await retainedAfterReplay.text()).toBe(200);
      expect(await retainedAfterReplay.json()).toEqual({ ...original, is_current: false });
      await page.getByLabel("Include superseded facts", { exact: true }).check();
      await expect(page.getByRole("list", { name: "Recorded patent parties" }).getByRole("listitem")).toHaveCount(6);
      await assertPatentControlsFit(page);
      await patentScreenshot(page, testInfo, `patent-${kind}-party-history-${width}.png`);
      if (kind === "application") {
        const unchanged = await page.request.get(`${apiBaseUrl}/api/ip/patents/families/${family.id}`, { headers });
        expect(await unchanged.json()).toEqual(family);
      }
    });
  }
}
