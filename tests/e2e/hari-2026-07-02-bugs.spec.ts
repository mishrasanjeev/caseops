/**
 * Hari 2026-07-02 workbook regressions.
 *
 * BUG-001: Context Research must not render corrupted authority title,
 * summary, or snippet text. If the only indexed match is unreadable, omit it
 * from result cards and show an explicit omitted-record notice.
 * BUG-00X: Matter cockpit must expose a first-class Notices section backed by
 * notice-classified matter attachments.
 */
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";
import { makeUploadFixture } from "./support/helpers";

const PASSWORD = "HariJul02Bugs!";
const CHEQUE_QUERY =
  "Cheque bounced due to insufficient funds and notice was sent after 35 days";

function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

function apiPython(): { command: string; args: string[] } {
  const direct =
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  if (fs.existsSync(direct)) {
    return { command: direct, args: [] };
  }
  return {
    command: "uv",
    args: ["--directory", "apps/api", "run", "--no-sync", "python"],
  };
}

function seedScreenshotGarbledAuthority(): string {
  const python = apiPython();
  const code = String.raw`
from datetime import date
from uuid import uuid4

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityDocumentType,
    MatterForumLevel,
)
from caseops_api.db.session import get_session_factory

suffix = uuid4().hex[:10]
garbled_title = "[2003] 3 -- f.t 'II'. 178"
garbled_chunk = (
    "[2003] 3 -- f.t 'II'. 178, ; 3ffillllll mi aRT 'A III' 1Tfffi "
    ".mi -- aRT .. 12 -- d, 2002. lila l?1t. tt. 1950, 27 3TR 28 "
    "JTR. SIftIII'l cff. fcIrlTT ;ifo1l. C1>lx mt fl 4<1i fclr "
    "q1fiun'l llC1>lll1a fcIrq -- fl .wf. fcIrnl -- <ITT -j+t H."
)
text = (
    "Section 138 cheque notice insufficient funds after 35 days. "
    f"{garbled_chunk} {garbled_chunk}"
)
with get_session_factory()() as session:
    document = AuthorityDocument(
        source="e2e_hari_2026_07_02_garbled",
        adapter_name="caseops-e2e-hari-2026-07-02",
        court_name="Supreme Court of India",
        forum_level=MatterForumLevel.SUPREME_COURT,
        document_type=AuthorityDocumentType.JUDGMENT,
        title=garbled_title,
        case_reference=f"CRL.A. H702-{suffix}/2026",
        bench_name=None,
        neutral_citation=None,
        decision_date=date(2026, 7, 2),
        canonical_key=f"e2e-hari-2026-07-02-garbled-{suffix}",
        source_reference="https://official.example.test/hari-2026-07-02-garbled.pdf",
        summary=garbled_chunk,
        document_text=text,
        extracted_char_count=len(text),
    )
    document.chunks = [
        AuthorityDocumentChunk(chunk_index=0, content=text, token_count=len(text.split()))
    ]
    session.add(document)
    session.flush()
    print(document.id)
    session.commit()
`;
  const result = spawnSync(python.command, [...python.args, "-c", code], {
    cwd: repoRoot,
    env: { ...process.env, ...e2eEnv },
    encoding: "utf8",
  });
  expect(result.status, result.stderr || result.stdout).toBe(0);
  return result.stdout.trim().split(/\s+/).at(-1) ?? "";
}

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ token: string; ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari 2026-07-02 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari Jul02 Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  return { token: (await resp.json()).access_token as string, ownerEmail };
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

async function createMatter(
  api: APIRequestContext,
  token: string,
  code: string,
): Promise<string> {
  const resp = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      title: `Hari Jul02 notice matter ${code}`,
      matter_code: code,
      practice_area: "Litigation",
      forum_level: "high_court",
      status: "intake",
      court_name: "Delhi High Court",
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  return ((await resp.json()) as { id: string }).id;
}

test.describe("Hari 2026-07-02 bugs", () => {
  test.setTimeout(150_000);

  test("BUG-001: Context Research omits corrupted authority content from real API results", async ({
    page,
  }) => {
    const authorityId = seedScreenshotGarbledAuthority();
    expect(authorityId).toBeTruthy();

    const api = await request.newContext();
    const slug = unique("h70201");
    const { ownerEmail } = await bootstrap(api, slug);
    await api.dispose();

    await signIn(page, slug, ownerEmail);
    await page.goto("/app/research");
    await page.getByTestId("research-mode-contextual").click();
    await page.getByTestId("research-query-input").fill(CHEQUE_QUERY);
    await page.getByTestId("research-query-submit").click();

    await expect(page.getByText(/not readable enough to preview/i)).toBeVisible();
    await expect(page.getByText(/\[2003\] 3 -- f\.t/i)).toHaveCount(0);
    await expect(page.getByTestId("research-result-garbled")).toHaveCount(0);
  });

  test("BUG-00X: Matter cockpit exposes Notices and uploads notice attachments", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h70202");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterCode = unique("H702N").toUpperCase();
    const matterId = await createMatter(api, token, matterCode);
    await api.dispose();

    await signIn(page, slug, ownerEmail);
    await page.goto(`/app/matters/${matterId}`);
    const cockpitTabs = page.getByRole("navigation", {
      name: /Matter cockpit tabs/i,
    });
    await cockpitTabs.getByRole("link", { name: "Notices", exact: true }).click();
    await page.waitForURL(/\/notices$/);
    await expect(
      page.getByRole("heading", { name: "Notices", exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/No notices on file/i)).toBeVisible();

    const filePath = makeUploadFixture(
      `${matterCode.toLowerCase()}-demand-notice.txt`,
      "Demand notice under Section 138 for Hari 2026-07-02 regression.",
    );
    const uploadResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/matters/${matterId}/attachments`) &&
        response.request().method() === "POST",
    );
    await page.setInputFiles('[data-testid="matter-notice-file-input"]', filePath);
    expect((await uploadResponse).status()).toBe(200);

    await expect(page.getByTestId("matter-notice-row")).toContainText(
      path.basename(filePath),
    );
    await expect(page.getByTestId("matter-notice-row")).toContainText(
      /pending|indexed|needs_ocr/i,
    );

    await page.goto(`/app/matters/${matterId}/documents`);
    await expect(page.getByText(path.basename(filePath)).first()).toBeVisible();
    await expect(page.getByText("Notice").first()).toBeVisible();
  });
});
