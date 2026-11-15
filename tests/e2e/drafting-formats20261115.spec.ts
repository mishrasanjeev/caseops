/** Synthetic format workflow only; no real-model or legal-validity claim. */
import { createHash, randomUUID } from "node:crypto";
import path from "node:path";
import { expect, request, test, type APIRequestContext, type Locator } from "@playwright/test";
import type { Draft } from "../../apps/web/lib/api/schemas";
import { canonicalApiValidators } from "./support/canonical-api-validators";
import { localTransportHeaders } from "./support/cost-controls";
import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";
import { runLocalPythonFileFixture } from "./support/local-python-file-fixture";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { assertDraftPdfRender, readDraftPdfTitle } from "./support/draft_pdf_render_proof_20261111";
import { presentationFamilyFromManifest, type DraftPdfProfile } from "./support/draft_pdf_oracle_20261111";

async function json(api: APIRequestContext, url: string, method = "GET", data?: object) {
  const response = await api.fetch(url, { method, data, maxRetries: 0, maxRedirects: 0 });
  expect(response.status(), `${method} ${new URL(url).pathname}: ${await response.text()}`).toBe(200);
  return response.json();
}

for (const phone of [false, true]) {
  test(`Draft formats 2026-11-15 ${phone ? "[mobile] phone" : "desktop"}: guided deed choice, version history and exact downloads`,
    async ({ page, baseURL }, info) => {
      if (!baseURL || ![baseURL, apiBaseUrl].every(value => {
        const url = new URL(value);
        return url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
      })) throw new Error("Draft format mutation is strictly loopback-only.");
      const { draft: draftSchema } = canonicalApiValidators();
      const parseDraft = (value: unknown): Draft => {
        const parsed = draftSchema.safeParse(value);
        if (!parsed.success) throw new Error("Synthetic draft contract rejected.");
        return parsed.data;
      };
      const hasTouch = info.project.use.hasTouch === true;
      expect(hasTouch).toBe(phone);
      expect(info.project.use.isMobile === true).toBe(phone);
      if (phone) {
        expect(info.project.name).toBe("app-mobile");
        expect(page.viewportSize()?.width).toBe(393);
      } else await page.setViewportSize({ width: 1280, height: 1000 });
      const press = async (control: Locator, minimumTarget = false) => {
        await control.scrollIntoViewIfNeeded();
        await expect(control).toBeVisible();
        if (minimumTarget) {
          const bounds = await control.boundingBox();
          expect(bounds !== null && bounds.width >= 44 && bounds.height >= 44
            && bounds.x >= 0 && bounds.x + bounds.width <= page.viewportSize()!.width + 1).toBe(true);
        }
        if (hasTouch) await control.tap(); else await control.click();
      };
      const release = () => assertPublicReleaseIdentity([
        `${apiBaseUrl}/api/build`, `${baseURL}/api/release-identity`,
      ], e2eEnv.CASEOPS_RELEASE_SHA);
      await release();
      const run = randomUUID(), slug = `b3draft-${run}`, email = `${slug}@example.com`, password = `Synthetic!${run}aA9`;
      const setup = await request.newContext({ extraHTTPHeaders: localTransportHeaders(apiBaseUrl), timeout: 30_000 });
      let auth: APIRequestContext | undefined;
      try {
        const tenant = await json(setup, `${apiBaseUrl}/api/bootstrap/company`, "POST", {
          company_name: `Synthetic format fixture ${run}`, company_slug: slug, company_type: "law_firm",
          owner_full_name: "Synthetic owner", owner_email: email, owner_password: password,
        });
        auth = await request.newContext({ extraHTTPHeaders: {
          ...localTransportHeaders(apiBaseUrl), Authorization: `Bearer ${tenant.access_token}`,
        }, timeout: 30_000 });
        const matter = await json(auth, `${apiBaseUrl}/api/matters/`, "POST", {
          title: `Synthetic QA batch3 draft ${run}`, matter_code: `FORMAT-${run}`,
          practice_area: "Civil", forum_level: "high_court", status: "intake", court_name: "Delhi High Court",
        });
        let wordRequests = 0;
        await page.setExtraHTTPHeaders(localTransportHeaders(baseURL));
        await page.context().route("**/*", async route => {
          const req = route.request(), url = new URL(req.url());
          if (![new URL(baseURL).origin, new URL(apiBaseUrl).origin].includes(url.origin)) {
            throw new Error("External network forbidden in the synthetic format journey.");
          }
          if (url.origin === new URL(apiBaseUrl).origin && req.method() !== "OPTIONS") {
            expect(req.headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
          }
          if (req.method() === "GET" && url.origin === new URL(apiBaseUrl).origin
            && url.pathname.startsWith(`/api/matters/${matter.id}/drafts/`)
            && url.pathname.endsWith("/export.docx")) {
            wordRequests++;
            if (wordRequests !== 1) throw new Error("Unexpected second Word download request.");
            // Inspect the actual browser constructor, then leave its request
            // and server response unchanged. Never substitute setup's token.
            const completeHeaders = await req.allHeaders();
            expect(completeHeaders["x-caseops-automated-test"]).toBe("no-paid-providers");
            expect(Boolean(completeHeaders.cookie?.includes("caseops_session="))).toBe(true);
          }
          await route.continue();
        });
        await page.goto("/sign-in");
        await page.locator("#company-slug").fill(slug);
        await page.locator("#email").fill(email);
        await page.locator("#password").fill(password);
        await press(page.getByRole("button", { name: /^Sign in$/ }));
        await page.waitForURL(/\/app(?:[/?]|$)/);
        await page.goto(`/app/matters/${matter.id}/drafts/new?type=conveyancing_deed&solo=1`);
        const picker = page.getByRole("combobox", { name: "Deed format" });
        await expect(picker).toHaveText("Select…");
        await page.getByLabel("Parties, roles and addresses").fill("Synthetic donor and donee; supplied addresses.");
        await page.getByLabel("Background and transaction details").fill("Synthetic supplied gift background; no completed execution is presumed.");
        await page.getByLabel("Confirmed governing law and jurisdiction").fill("[Law confirmed by reviewing counsel]");
        await page.getByLabel("Terms agreed by the parties").fill("Synthetic supplied gift terms; unknown particulars remain placeholders.");
        let createRequests = 0;
        page.on("request", req => {
          if (req.method() === "POST" && new URL(req.url()).pathname === `/api/matters/${matter.id}/drafts`) createRequests++;
        });
        await press(page.getByTestId("drafting-solo-generate"), true);
        await expect(picker).toHaveAttribute("aria-invalid", "true");
        expect(createRequests).toBe(0);
        const instruments = ["Sale deed", "Mortgage deed", "Partnership deed", "Dissolution of partnership", "Relinquishment deed", "Gift deed"];
        for (const instrument of instruments) {
          await press(picker, true);
          await press(page.getByRole("option", { name: instrument, exact: true }), true);
          await expect(picker).toContainText(instrument);
        }
        const createdWait = page.waitForResponse(response => response.request().method() === "POST"
          && new URL(response.url()).pathname === `/api/matters/${matter.id}/drafts`);
        await press(page.getByTestId("drafting-solo-generate"), true);
        const createdResponse = await createdWait;
        expect(createdResponse.status()).toBe(200);
        expect(await createdResponse.finished()).toBeNull();
        const shell = parseDraft(await createdResponse.json());
        expect(createRequests).toBe(1);
        expect(shell.template_type).toBe("conveyancing_deed");
        expect(shell.draft_type).toBe("other");
        expect(shell.title).toBe("Gift deed");
        expect(shell.versions).toHaveLength(0);
        await page.waitForURL(new RegExp(`/drafts/${shell.id}$`));
        // Existing exact-owned fixture installs the negative zero-citation state
        // and one synthetic catalogue identity. It does not create legal evidence.
        const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(repoRoot, "apps", "api", ".venv",
          process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
        const fixture = await runLocalPythonFileFixture(python, path.join(repoRoot, "tests/e2e/support/ram_batch3_draft_fixture.py"), {
          cwd: repoRoot, encoding: "utf8", timeout: 30_000,
          input: JSON.stringify({ web: baseURL, api: apiBaseUrl, run, company_id: tenant.company.id,
            membership_id: tenant.membership.id, matter_id: matter.id, draft_id: shell.id }),
          env: { ...process.env, ...e2eEnv, CASEOPS_LLM_PROVIDER: "mock", CASEOPS_EMBEDDING_PROVIDER: "mock",
            PYTHONPATH: path.join(repoRoot, "apps/api/src") },
        });
        expect(fixture.status, `${fixture.stdout}\n${fixture.stderr}`).toBe(0);
        const seeded = JSON.parse(fixture.stdout) as { citation: string; version_id: string };
        const apiUrl = `${apiBaseUrl}/api/matters/${matter.id}/drafts/${shell.id}`;
        const read = async () => parseDraft(await json(auth!, apiUrl));
        const original = (await read()).versions[0];
        expect(original.verified_citation_count).toBe(0);
        expect(original.template_manifest).not.toHaveProperty("presentation_reference");
        await page.reload();
        await expect(page.getByTestId("draft-body-readonly")).toHaveText(original.body);
        await page.getByLabel("Regeneration focus", { exact: true })
          .fill(`Review only the synthetic owned catalogue record.\n- CITATION: ${seeded.citation}`);
        await press(page.getByTestId("draft-generate"));
        await expect(page.getByTestId("draft-current-revision")).toHaveText("Revision 2");
        const generated = await read();
        const second = generated.versions[1];
        expect(second.verified_citation_count).toBeGreaterThan(0);
        expect(second.citations).toContain(seeded.citation);
        expect(second.template_manifest.presentation_reference).toMatchObject({
          profile: "conveyancing_deed", family: "deed", instrument_type: "Gift deed", pdf_pages: [90, 91, 92], legal_rules_verified: false,
        });
        await expect(page.getByTestId("draft-body-readonly")).toHaveText(second.body);
        await expect(page.getByTestId("court-profile-select")).toHaveCount(0);
        await expect(page.getByTestId("draft-download-filing-bundle")).toHaveCount(0);
        await expect(page.getByTestId("filing-checklist-card")).toHaveCount(0);
        await press(page.getByTestId("draft-edit-toggle"));
        const body = "Gift deed\nBETWEEN\n[Synthetic donor]\nAND\n[Synthetic donee]\nRECITALS\n"
          + Array.from({ length: 45 }, (_, index) => `${index + 1}. Synthetic supplied paragraph ${index + 1}; amount ₹0.50.`).join("\n")
          + `\nOPERATIVE TERMS\n[Actual agreed terms]\nSCHEDULE\n[Supplied property]\nEXECUTION\n[Signature]\nDonor\n[${seeded.citation}]`;
        await page.getByTestId("draft-body-editor").fill(body);
        await press(page.getByTestId("draft-save-edit"));
        await expect(page.getByTestId("draft-current-revision")).toHaveText("Revision 3");
        await expect(page.getByTestId("draft-body-readonly")).toHaveText(body);
        for (const action of ["submit", "approve", "finalize"]) {
          await press(page.getByTestId(`draft-${action}`));
          await expect.poll(async () => (await read()).status).toBe({ submit: "in_review", approve: "approved", finalize: "finalized" }[action]);
        }
        await page.reload();
        await expect(page.getByTestId("draft-body-readonly")).toHaveText(body);
        const saved = await read(), third = saved.versions[2];
        expect(saved.versions.slice(0, 2)).toEqual([original, second]);
        expect(third.template_manifest).toEqual(second.template_manifest);
        expect(saved.current_version_id).toBe(third.id);
        expect(saved.review_required).toBe(false);
        const wordDownloadWait = page.waitForEvent("download");
        await press(page.getByTestId("draft-download-docx"));
        const wordDownload = await wordDownloadWait;
        expect(wordDownload.url()).toBe(`${apiUrl}/export.docx`);
        const wordStream = await wordDownload.createReadStream();
        if (!wordStream) throw new Error("Word download stream is absent.");
        const wordChunks: Buffer[] = [];
        for await (const chunk of wordStream) wordChunks.push(Buffer.from(chunk));
        const wordBytes = Buffer.concat(wordChunks);
        await info.attach("synthetic-format-actual-download.docx", {
          body: wordBytes,
          contentType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        });
        expect(await wordDownload.failure()).toBeNull();
        expect(wordRequests).toBe(1);
        const { default: JSZip } = await import("jszip");
        const wordPackage = await JSZip.loadAsync(wordBytes);
        const documentPart = wordPackage.file("word/document.xml");
        const corePart = wordPackage.file("docProps/core.xml");
        if (!documentPart || !corePart) throw new Error("Word document parts are absent.");
        const wordXml = await documentPart.async("string");
        const wordParagraphs = await page.evaluate(xml => {
          const document = new DOMParser().parseFromString(xml, "application/xml");
          if (document.querySelector("parsererror")) throw new Error("Word XML is malformed.");
          return Array.from(document.getElementsByTagNameNS(
            "http://schemas.openxmlformats.org/wordprocessingml/2006/main", "p",
          )).map(paragraph => Array.from(paragraph.getElementsByTagNameNS(
            "http://schemas.openxmlformats.org/wordprocessingml/2006/main", "t",
          )).map(text => text.textContent ?? "").join("")).join("\n");
        }, wordXml);
        expect(wordParagraphs.startsWith(body)).toBe(true);
        expect(await corePart.async("string"))
          .toContain("cc50806727ff07306d6fe0b0bceee500061edb10577b9c350b63e31ce35c6cd0");
        const pdfWait = page.waitForResponse(response => new URL(response.url()).pathname === `${new URL(apiUrl).pathname}/export.pdf`);
        await press(page.getByRole("tab", { name: "PDF preview" }));
        const pdfResponse = await pdfWait;
        expect(pdfResponse.status()).toBe(200);
        expect(await pdfResponse.finished()).toBeNull();
        const displayedBytes = await pdfResponse.body();
        await info.attach("synthetic-format-displayed.pdf", {
          body: displayedBytes, contentType: "application/pdf",
        });
        const profiles = await json(auth, `${apiBaseUrl}/api/drafting/court-profiles`) as { profiles: DraftPdfProfile[] };
        const profile = profiles.profiles.find(row => row.key === "generic");
        if (!profile) throw new Error("Generic document layout is absent.");
        const renderedPages = await assertDraftPdfRender(page, profile, {
          title: saved.title, body, citations: third.citations, presentationFamily: presentationFamilyFromManifest(third.template_manifest),
          pdfTitle: await readDraftPdfTitle(displayedBytes),
        }, hasTouch, async index => {
          await info.attach(`synthetic-format-pdf-page-${index}.png`, {
            body: await page.locator("[data-testid=draft-pdf-preview] canvas").screenshot(),
            contentType: "image/png",
          });
        });
        expect(renderedPages).toBeGreaterThan(1);
        const downloaded = page.waitForEvent("download");
        await press(page.getByTestId("draft-download-pdf"));
        const stream = await (await downloaded).createReadStream();
        if (!stream) throw new Error("PDF download stream is absent.");
        const chunks: Buffer[] = [];
        for await (const chunk of stream) chunks.push(Buffer.from(chunk));
        expect(createHash("sha256").update(Buffer.concat(chunks)).digest("hex"))
          .toBe(createHash("sha256").update(displayedBytes).digest("hex"));
        expect(await read()).toEqual(saved);
        await release();
      } finally {
        await auth?.dispose();
        await setup.dispose();
      }
    });
}
