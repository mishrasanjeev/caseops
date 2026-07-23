/**
 * Ram 2026-07-23 deployed-production bulk Matter compatibility regression.
 *
 * This suite signs in with tester credentials supplied through environment
 * variables, verifies both deployed templates, imports one uniquely identified
 * Matter from a Windows-1252 semicolon-delimited client register, proves strict
 * Matter Code validation and commit idempotency, and leaves every created
 * Matter in the terminal Disposed state.
 *
 * Run only after the candidate commit and database migration are deployed:
 *
 *   npx playwright test --config playwright.prod-ram.config.ts \
 *     tests/e2e/ram-2026-07-23-prod.spec.ts --project tester-prod-chromium
 */
import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Download,
  type Page,
} from "@playwright/test";
import { readFile } from "node:fs/promises";
import { inflateRawSync } from "node:zlib";

const envOr = (key: string, fallback: string): string => {
  const value = (process.env[key] ?? "").trim();
  return value || fallback;
};

const PROD_BASE_URL = envOr("PROD_BASE_URL", "https://caseops.ai");
const PROD_API_BASE_URL = envOr(
  "PROD_API_BASE_URL",
  "https://api.caseops.ai",
);
const COMPANY_SLUG = envOr("CASEOPS_RAM_PROD_SLUG", "legal");
const TESTER_EMAIL = envOr(
  "CASEOPS_RAM_PROD_EMAIL",
  "hari.gupta@gmail.com",
);
const RUN_ID = `${Date.now().toString(36)}-${Math.random()
  .toString(36)
  .slice(2, 8)}`.toUpperCase();

const EXPECTED_TEMPLATE_HEADERS = [
  "Matter Title",
  "Matter Code",
  "Matter Type",
  "Practice Area",
  "Matter Status",
  "Matter Description",
  "Client Name",
  "Client Code",
  "Client Contact Number",
  "Client Email",
  "Opposing Party Name",
  "Opposing Counsel",
  "Forum",
  "Court",
  "Court Forum Number",
  "Case Number",
  "Filing Number",
  "Filing Date",
  "Matter Owner",
  "Assigned Team",
  "Responsible Lawyer",
] as const;

type HttpResponse = {
  status(): number;
  text(): Promise<string>;
};

type AuthContext = {
  company: { slug: string };
  user: { email: string };
  capabilities: string[];
};

type MatterStatus = "intake" | "active" | "on_hold" | "disposed";

type MatterRecord = {
  id: string;
  title: string;
  matter_code: string;
  status: MatterStatus;
  client_name: string | null;
  client_contact_number: string | null;
  practice_area: string;
  forum_level: string;
  court_forum_number: string | null;
  filing_date: string | null;
  updated_at: string;
};

type MatterImportRow = {
  row_number: number;
  status: "valid" | "invalid" | "created" | "failed";
  normalized: Record<string, unknown>;
  errors: string[];
  created_matter_id: string | null;
};

type MatterImportJobStatus =
  | "validated"
  | "importing"
  | "completed"
  | "completed_with_errors"
  | "cancelled"
  | "failed"
  | "expired";

type MatterImportJob = {
  id: string;
  filename: string;
  status: MatterImportJobStatus;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  created_count: number;
  failed_count: number;
  validation_error_count: number;
  rows: MatterImportRow[];
};

type MatterImportCommitResult = {
  job: MatterImportJob;
  created_matter_ids: string[];
};

let context: BrowserContext;
let page: Page;
let authenticated = false;
let importJobId: string | undefined;
let createdMatterId: string | undefined;

const importFilename = `ram-2026-07-23-bulk-${RUN_ID}.csv`;
const validCode = uniqueCode("RAM723-BULK");
const invalidCode = `RAM723/${RUN_ID}#`;
const validTitle = `M/s. Müller & Co. (Claim #${RUN_ID})`;
const practiceArea = `Production-Tech & Data / Privacy (${RUN_ID})`;
const courtForumNumber = `Court #7 / Bench-A (${RUN_ID})`;

function requiredPassword(): string {
  const value = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ?? "";
  if (!value) {
    throw new Error(
      "CASEOPS_RAM_PROD_PASSWORD is required for the July 23 production regression.",
    );
  }
  return value;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function uniqueCode(prefix: string): string {
  return `${prefix}-${RUN_ID}`.replace(/[^A-Z0-9-]/g, "").slice(0, 78);
}

function csvRow(values: readonly string[]): string {
  return values
    .map((value) => `"${value.replaceAll('"', '""')}"`)
    .join(";");
}

function windows1252Import(): Buffer {
  const headers = [
    "Matter Name",
    "Matter ID",
    "Area of Practice",
    "Current Status",
    "Existing Client Name",
    "Court / Forum",
    "Client Phone No.",
    "Date of Filing",
    "Court / Forum No.",
    "Matter Description",
  ];
  const text = [
    csvRow([`Client matter register export ${RUN_ID}`]),
    csvRow(headers),
    csvRow([
      validTitle,
      validCode,
      practiceArea,
      "",
      "",
      "HIGH COURT",
      "+91 (98765) 432-10",
      "23.07.2026",
      courtForumNumber,
      `Invoices #42/2026; terms (A) & (B). ${RUN_ID}`,
    ]),
    csvRow([
      `Strict invalid Matter Code ${RUN_ID}`,
      invalidCode,
      "Civil",
      "ACTIVE",
      "",
      "High Court",
      "",
      "",
      "Court #8",
      "This row must remain invalid.",
    ]),
  ].join("\r\n");

  // Every non-ASCII character in this fixture is representable in
  // Windows-1252. In particular, ü becomes byte 0xFC, which is invalid as a
  // standalone UTF-8 byte and therefore proves the deployed fallback decoder.
  return Buffer.from(text, "latin1");
}

async function expectStatus(
  response: HttpResponse,
  expected: number,
  label: string,
): Promise<void> {
  const body = response.status() === expected ? "" : ` ${await response.text()}`;
  expect(
    response.status(),
    `${label}: expected HTTP ${expected}, received ${response.status()}.${body}`,
  ).toBe(expected);
}

async function authHeaders(): Promise<Record<string, string>> {
  const cookies = await context.cookies([PROD_BASE_URL, PROD_API_BASE_URL]);
  const cookieHeader = cookies
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
  const csrf = cookies.find((cookie) => cookie.name === "caseops_csrf")?.value;
  expect(cookieHeader, "authenticated cookie jar must not be empty").not.toBe("");
  expect(csrf, "caseops_csrf cookie must exist after sign-in").toBeTruthy();
  return {
    Accept: "application/json",
    Cookie: cookieHeader,
    "Content-Type": "application/json",
    "X-CSRF-Token": csrf!,
  };
}

async function signInAsTester(): Promise<void> {
  await context.clearCookies();
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(requiredPassword());
  const loginPromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await expectStatus(await loginPromise, 200, "sign in as July 23 tester");
  await page.waitForURL(
    new RegExp(`${escapeRegExp(PROD_BASE_URL)}/app(?:[/?]|$)`),
  );

  const meResponse = await context.request.get(
    `${PROD_API_BASE_URL}/api/auth/me`,
    { headers: await authHeaders() },
  );
  await expectStatus(meResponse, 200, "read tester auth context");
  const auth = (await meResponse.json()) as AuthContext;
  authenticated = true;
  expect(auth.company.slug).toBe(COMPANY_SLUG);
  expect(auth.user.email.toLowerCase()).toBe(TESTER_EMAIL.toLowerCase());
  expect(auth.capabilities).toEqual(
    expect.arrayContaining([
      "matters:create",
      "matters:edit",
      "matters:archive",
      "matters:bulk_import",
    ]),
  );
}

async function downloadBytes(download: Download): Promise<Buffer> {
  const path = await download.path();
  expect(path, "download must have a local temporary path").not.toBeNull();
  return readFile(path!);
}

function findEndOfCentralDirectory(bytes: Buffer): number {
  const signature = 0x06054b50;
  const lowerBound = Math.max(0, bytes.length - 65_557);
  for (let offset = bytes.length - 22; offset >= lowerBound; offset -= 1) {
    if (bytes.readUInt32LE(offset) === signature) return offset;
  }
  throw new Error("Downloaded XLSX has no ZIP end-of-central-directory record.");
}

function readZipEntry(bytes: Buffer, targetName: string): Buffer {
  const eocd = findEndOfCentralDirectory(bytes);
  const entryCount = bytes.readUInt16LE(eocd + 10);
  let cursor = bytes.readUInt32LE(eocd + 16);

  for (let index = 0; index < entryCount; index += 1) {
    if (bytes.readUInt32LE(cursor) !== 0x02014b50) {
      throw new Error("Downloaded XLSX has an invalid ZIP central directory.");
    }
    const compressionMethod = bytes.readUInt16LE(cursor + 10);
    const compressedSize = bytes.readUInt32LE(cursor + 20);
    const filenameLength = bytes.readUInt16LE(cursor + 28);
    const extraLength = bytes.readUInt16LE(cursor + 30);
    const commentLength = bytes.readUInt16LE(cursor + 32);
    const localHeaderOffset = bytes.readUInt32LE(cursor + 42);
    const filename = bytes
      .subarray(cursor + 46, cursor + 46 + filenameLength)
      .toString("utf8");

    if (filename === targetName) {
      if (bytes.readUInt32LE(localHeaderOffset) !== 0x04034b50) {
        throw new Error(`Downloaded XLSX entry ${targetName} has no local header.`);
      }
      const localFilenameLength = bytes.readUInt16LE(localHeaderOffset + 26);
      const localExtraLength = bytes.readUInt16LE(localHeaderOffset + 28);
      const dataStart =
        localHeaderOffset + 30 + localFilenameLength + localExtraLength;
      const compressed = bytes.subarray(
        dataStart,
        dataStart + compressedSize,
      );
      if (compressionMethod === 0) return Buffer.from(compressed);
      if (compressionMethod === 8) return inflateRawSync(compressed);
      throw new Error(
        `Downloaded XLSX entry ${targetName} uses unsupported ZIP method ${compressionMethod}.`,
      );
    }

    cursor += 46 + filenameLength + extraLength + commentLength;
  }

  throw new Error(`Downloaded XLSX is missing ${targetName}.`);
}

function decodeXmlText(value: string): string {
  const entities = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&apos;": "'",
  } as const;
  return value.replace(
    /&(amp|lt|gt|quot|apos);/g,
    (entity) => entities[entity as keyof typeof entities],
  );
}

function xlsxTemplateHeaders(bytes: Buffer): string[] {
  expect(bytes.subarray(0, 2).toString("ascii")).toBe("PK");
  const worksheet = readZipEntry(bytes, "xl/worksheets/sheet1.xml").toString(
    "utf8",
  );
  const firstRow = worksheet.match(
    /<row\b[^>]*\br="1"[^>]*>([\s\S]*?)<\/row>/,
  )?.[1];
  expect(firstRow, "XLSX template must contain row 1").toBeTruthy();
  return [...firstRow!.matchAll(/<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g)].map(
    (match) => decodeXmlText(match[1]),
  );
}

async function getMatter(matterId: string): Promise<MatterRecord> {
  const response = await context.request.get(
    `${PROD_API_BASE_URL}/api/matters/${matterId}`,
    { headers: await authHeaders() },
  );
  await expectStatus(response, 200, `read matter ${matterId}`);
  return (await response.json()) as MatterRecord;
}

async function disposeMatter(matter: MatterRecord): Promise<void> {
  const current = await getMatter(matter.id);
  if (current.status === "disposed") return;
  const response = await context.request.patch(
    `${PROD_API_BASE_URL}/api/matters/${current.id}/lifecycle/status`,
    {
      headers: await authHeaders(),
      data: {
        to_status: "disposed",
        expected_from_status: current.status,
        expected_updated_at: current.updated_at,
        reason: "July 23 bulk-import production regression cleanup completed.",
      },
    },
  );
  await expectStatus(response, 200, `dispose ${current.matter_code}`);
}

async function discoverRunMatters(): Promise<MatterRecord[]> {
  const response = await context.request.get(
    `${PROD_API_BASE_URL}/api/matters/`,
    {
      headers: await authHeaders(),
      params: { q: RUN_ID, limit: 100 },
    },
  );
  await expectStatus(response, 200, "discover July 23 production matters");
  return ((await response.json()) as { matters: MatterRecord[] }).matters;
}

async function cancelValidatedImport(jobId: string): Promise<void> {
  const readResponse = await context.request.get(
    `${PROD_API_BASE_URL}/api/matters/imports/${jobId}`,
    { headers: await authHeaders() },
  );
  await expectStatus(readResponse, 200, `read import job ${jobId} for cleanup`);
  const job = (await readResponse.json()) as MatterImportJob;
  if (job.status !== "validated") return;

  const cancelResponse = await context.request.post(
    `${PROD_API_BASE_URL}/api/matters/imports/${jobId}/cancel`,
    { headers: await authHeaders() },
  );
  await expectStatus(cancelResponse, 200, `cancel import job ${jobId}`);
  expect(((await cancelResponse.json()) as MatterImportJob).status).toBe(
    "cancelled",
  );
}

test.describe.serial("Ram 2026-07-23 deployed bulk Matter compatibility", () => {
  test.setTimeout(240_000);

  test.beforeAll(async ({ browser }: { browser: Browser }) => {
    context = await browser.newContext({
      storageState: { cookies: [], origins: [] },
    });
    page = await context.newPage();
    await signInAsTester();
  });

  test.afterAll(async () => {
    const cleanupFailures: string[] = [];
    if (context) {
      if (authenticated) {
        if (importJobId) {
          try {
            await cancelValidatedImport(importJobId);
          } catch (error) {
            cleanupFailures.push(
              `import ${importJobId}: ${
                error instanceof Error ? error.message : String(error)
              }`,
            );
          }
        }

        try {
          const discovered = await discoverRunMatters();
          const records = new Map(
            discovered.map((matter) => [matter.id, matter] as const),
          );
          if (createdMatterId && !records.has(createdMatterId)) {
            records.set(createdMatterId, await getMatter(createdMatterId));
          }
          for (const matter of records.values()) {
            try {
              await disposeMatter(matter);
            } catch (error) {
              cleanupFailures.push(
                `${matter.matter_code}: ${
                  error instanceof Error ? error.message : String(error)
                }`,
              );
            }
          }
        } catch (error) {
          cleanupFailures.push(
            `discovery: ${error instanceof Error ? error.message : String(error)}`,
          );
        }
      }

      try {
        await context.close();
      } catch (error) {
        cleanupFailures.push(
          `context close: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }
    expect(
      cleanupFailures,
      "production regression cleanup must cancel previews and leave no test Matter operational",
    ).toEqual([]);
  });

  test("downloads templates, validates compatibility, commits once, and reopens history", async () => {
    expect(decodeXmlText("&amp;lt;&lt;")).toBe("&lt;<");

    await page.goto(`${PROD_BASE_URL}/app/matters/imports`);
    await expect(
      page.getByRole("heading", { name: "Bulk upload matters" }),
    ).toBeVisible();

    const csvDownloadPromise = page.waitForEvent("download");
    await page.getByTestId("matter-import-template-csv").click();
    const csvDownload = await csvDownloadPromise;
    expect(csvDownload.suggestedFilename()).toBe(
      "caseops-matter-import-template.csv",
    );
    const csvTemplate = (await downloadBytes(csvDownload))
      .toString("utf8")
      .replace(/^\uFEFF/, "");
    const csvHeaders = csvTemplate.split(/\r?\n/, 1)[0].split(",");
    expect(csvHeaders).toEqual(EXPECTED_TEMPLATE_HEADERS);
    expect(csvHeaders).toHaveLength(21);
    expect(csvHeaders.indexOf("Court Forum Number")).toBe(
      csvHeaders.indexOf("Court") + 1,
    );

    const xlsxButton = page.getByTestId("matter-import-template-xlsx");
    await expect(xlsxButton).toBeEnabled();
    const xlsxDownloadPromise = page.waitForEvent("download");
    await xlsxButton.click();
    const xlsxDownload = await xlsxDownloadPromise;
    expect(xlsxDownload.suggestedFilename()).toBe(
      "caseops-matter-import-template.xlsx",
    );
    const xlsxHeaders = xlsxTemplateHeaders(
      await downloadBytes(xlsxDownload),
    );
    expect(xlsxHeaders).toEqual(EXPECTED_TEMPLATE_HEADERS);
    expect(xlsxHeaders).toHaveLength(21);
    expect(xlsxHeaders.indexOf("Court Forum Number")).toBe(
      xlsxHeaders.indexOf("Court") + 1,
    );

    await page.getByTestId("matter-import-file").setInputFiles({
      name: importFilename,
      mimeType: "application/vnd.ms-excel",
      buffer: windows1252Import(),
    });
    const previewPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/matters/imports/preview" &&
        response.request().method() === "POST",
    );
    await page.getByTestId("matter-import-validate").click();
    const previewResponse = await previewPromise;
    let preview: MatterImportJob | undefined;
    if (previewResponse.status() >= 200 && previewResponse.status() < 300) {
      preview = (await previewResponse.json()) as MatterImportJob;
      importJobId = preview.id;
    }
    await expectStatus(previewResponse, 200, "preview production bulk import");
    expect(preview, "preview job must be captured for cleanup").toBeDefined();
    expect(preview).toMatchObject({
      filename: importFilename,
      status: "validated",
      total_rows: 2,
      valid_rows: 1,
      invalid_rows: 1,
    });
    expect(preview!.validation_error_count).toBeGreaterThanOrEqual(1);

    const validRow = preview!.rows.find(
      (row) => row.normalized.matter_code === validCode,
    );
    expect(validRow).toBeDefined();
    expect(validRow).toMatchObject({ row_number: 3, status: "valid" });
    expect(validRow!.normalized).toMatchObject({
      title: validTitle,
      matter_code: validCode,
      practice_area: practiceArea,
      matter_status: "active",
      forum_level: "high_court",
      client_contact_number: "+91 (98765) 432-10",
      filing_date: "2026-07-23",
      court_forum_number: courtForumNumber,
    });
    expect(validRow!.normalized.client_name).toBeUndefined();

    const invalidRow = preview!.rows.find(
      (row) => row.normalized.matter_code === invalidCode,
    );
    expect(invalidRow).toBeDefined();
    expect(invalidRow).toMatchObject({ row_number: 4, status: "invalid" });
    expect(invalidRow!.errors.join(" ")).toMatch(
      /letters, numbers, and hyphens/i,
    );

    await expect(page.getByText(validTitle)).toBeVisible();
    await expect(page.getByText(validCode)).toBeVisible();
    await expect(page.getByText(invalidCode)).toBeVisible();
    await expect(page.getByText(courtForumNumber)).toBeVisible();
    await expect(
      page.getByText(/letters, numbers, and hyphens/i),
    ).toBeVisible();
    await expect(page.getByTestId("matter-import-confirm")).toContainText(
      "Confirm import (1)",
    );

    const errorDownloadPromise = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Download error report" })
      .click();
    const errorDownload = await errorDownloadPromise;
    expect(errorDownload.suggestedFilename()).toBe(
      `matter-import-errors-${preview!.id}.csv`,
    );
    const errorReport = (await downloadBytes(errorDownload))
      .toString("utf8")
      .replace(/^\uFEFF/, "");
    expect(errorReport).toContain(
      "Row Number,Matter Code,Matter Title,Status,Errors",
    );
    expect(errorReport).toContain(invalidCode);
    expect(errorReport).toMatch(/letters, numbers, and hyphens/i);
    expect(errorReport).not.toContain(validCode);

    const commitPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/matters/imports/${preview!.id}/commit` &&
        response.request().method() === "POST",
    );
    await page.getByTestId("matter-import-confirm").click();
    const commitResponse = await commitPromise;
    let committed: MatterImportCommitResult | undefined;
    if (commitResponse.status() >= 200 && commitResponse.status() < 300) {
      committed = (await commitResponse.json()) as MatterImportCommitResult;
      createdMatterId = committed.created_matter_ids[0];
    }
    await expectStatus(commitResponse, 200, "commit production bulk import");
    expect(committed, "commit result must be captured for cleanup").toBeDefined();
    expect(committed!.job).toMatchObject({
      id: preview!.id,
      status: "completed_with_errors",
      total_rows: 2,
      valid_rows: 1,
      invalid_rows: 1,
      created_count: 1,
      failed_count: 1,
    });
    expect(committed!.created_matter_ids).toHaveLength(1);
    expect(createdMatterId).toBeTruthy();
    await expect(
      page.getByText("completed with errors").first(),
    ).toBeVisible();

    const matter = await getMatter(createdMatterId!);
    expect(matter).toMatchObject({
      id: createdMatterId,
      title: validTitle,
      matter_code: validCode,
      status: "active",
      client_name: null,
      client_contact_number: "+91 (98765) 432-10",
      practice_area: practiceArea,
      forum_level: "high_court",
      court_forum_number: courtForumNumber,
      filing_date: "2026-07-23",
    });

    const retryResponse = await context.request.post(
      `${PROD_API_BASE_URL}/api/matters/imports/${preview!.id}/commit`,
      { headers: await authHeaders() },
    );
    await expectStatus(retryResponse, 200, "retry terminal production import");
    const retried = (await retryResponse.json()) as MatterImportCommitResult;
    expect(retried.job).toMatchObject({
      id: preview!.id,
      status: "completed_with_errors",
      created_count: 1,
      failed_count: 1,
    });
    expect(retried.created_matter_ids).toEqual(
      committed!.created_matter_ids,
    );

    const listResponse = await context.request.get(
      `${PROD_API_BASE_URL}/api/matters/`,
      {
        headers: await authHeaders(),
        params: { q: validCode, limit: 100 },
      },
    );
    await expectStatus(listResponse, 200, "verify idempotent Matter count");
    const exactMatches = (
      (await listResponse.json()) as { matters: MatterRecord[] }
    ).matters.filter((candidate) => candidate.matter_code === validCode);
    expect(exactMatches).toHaveLength(1);
    expect(exactMatches[0].id).toBe(createdMatterId);

    const historyPromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/matters/imports/history" &&
        url.searchParams.get("q") === importFilename &&
        response.request().method() === "GET"
      );
    });
    await page.getByLabel("Search").fill(importFilename);
    await page.getByRole("button", { name: "Search" }).click();
    const historyResponse = await historyPromise;
    await expectStatus(historyResponse, 200, "search production import history");
    const history = (await historyResponse.json()) as {
      imports: MatterImportJob[];
      total: number;
    };
    expect(history.imports.map((job) => job.id)).toContain(preview!.id);

    const historyRow = page
      .getByRole("row")
      .filter({ hasText: importFilename });
    await expect(historyRow).toHaveCount(1);
    const detailPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/matters/imports/${preview!.id}` &&
        response.request().method() === "GET",
    );
    await historyRow.click();
    const detailResponse = await detailPromise;
    await expectStatus(detailResponse, 200, "reopen production import history");
    const detail = (await detailResponse.json()) as MatterImportJob;
    expect(detail).toMatchObject({
      id: preview!.id,
      status: "completed_with_errors",
      created_count: 1,
      failed_count: 1,
    });
    await expect(page.getByText(validCode)).toBeVisible();
    await expect(page.getByText(courtForumNumber)).toBeVisible();
    await expect(page.getByText(invalidCode)).toBeVisible();
  });
});
