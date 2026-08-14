/**
 * Ram 2026-08-14 workbook — bulk matter upload (CaseOps_Bug_list_Ram14Aug2026).
 *
 * BUG-001  Forum hierarchy values not consistently mapped to the catalog.
 * BUG-002  DRAT/DRT and State Commission demanded exact catalog court values.
 * BUG-003  Duplicates were detected but not excluded from the submission.
 * BUG-004  Valid active owner/lawyer references were rejected.
 *
 * This drives the real Bulk Matter Upload page as a signed-in user: it uploads
 * an XLSX built the way a tester builds one (Forum picked from the template
 * dropdown, Court typed by hand), reads the rendered validation table, and
 * confirms the import. It deliberately does NOT assert against the API alone —
 * the reported failure was what the lawyer saw on the page.
 *
 * Run locally with playwright.app.config.ts, then against the deployed
 * revision with playwright.prod-ram.config.ts (which selects this file by its
 * dated name). Browser media is disabled by the production config.
 */
import {
  expect,
  test,
  type APIResponse,
  type Page,
} from "@playwright/test";

const envOr = (key: string, fallback: string): string =>
  (process.env[key] ?? "").trim() || fallback;

const BASE_URL = envOr(
  "PROD_BASE_URL",
  envOr("CASEOPS_WEB_BASE_URL", "http://127.0.0.1:3100"),
);
const BASE_HOST = new URL(BASE_URL).hostname;
const IS_LOCAL = BASE_HOST === "127.0.0.1" || BASE_HOST === "localhost";
const API_BASE_URL = envOr(
  "PROD_API_BASE_URL",
  IS_LOCAL
    ? `http://127.0.0.1:${envOr("CASEOPS_E2E_API_PORT", "8000")}`
    : "https://api.caseops.ai",
);
const RUN_ID = `${Date.now().toString(36)}-${Math.random()
  .toString(36)
  .slice(2, 8)}`.toUpperCase();
const LOCAL_TENANT_KEY = `ram-aug14-${RUN_ID.toLowerCase()}`;
const COMPANY_SLUG = envOr(
  "CASEOPS_RAM_PROD_SLUG",
  IS_LOCAL ? LOCAL_TENANT_KEY : "legal",
);
const TESTER_EMAIL = envOr(
  "CASEOPS_RAM_PROD_EMAIL",
  IS_LOCAL ? `${LOCAL_TENANT_KEY}@example.com` : "hari.gupta@gmail.com",
);
const LOCAL_TESTER_PASSWORD = "RamAug14Local!";

type LoginPayload = { access_token: string };

function requiredPassword(): string {
  const password =
    process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ||
    process.env.CASEOPS_RAM_LOCAL_PASSWORD?.trim() ||
    (IS_LOCAL ? LOCAL_TESTER_PASSWORD : "");
  if (!password) {
    throw new Error(
      "CASEOPS_RAM_PROD_PASSWORD or CASEOPS_RAM_LOCAL_PASSWORD is required " +
        "for the August 14 bulk-import regression.",
    );
  }
  return password;
}

async function expectStatus(
  response: APIResponse,
  expected: number,
  label: string,
): Promise<void> {
  if (response.status() !== expected) {
    throw new Error(
      `${label}: expected ${expected}, got ${response.status()} — ` +
        `${(await response.text()).slice(0, 400)}`,
    );
  }
}

async function signIn(page: Page): Promise<string> {
  await page.goto(`${BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(requiredPassword());
  const [login] = await Promise.all([
    page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/auth/login" &&
        response.request().method() === "POST",
      { timeout: 30_000 },
    ),
    page.locator('button[type="submit"]').click(),
  ]);
  await expectStatus(login, 200, "explicit tester sign-in");
  const payload = (await login.json()) as LoginPayload;
  expect(payload.access_token).toBeTruthy();
  await page.waitForURL(/\/app(?:[/?]|$)/);
  return payload.access_token;
}

const HEADERS = [
  "Matter Title",
  "Matter Code",
  "Practice Area",
  "Matter Status",
  "Client Name",
  "Forum",
  "Court",
  "Matter Owner",
];

/**
 * Minimal SpreadsheetML workbook. Built inline rather than with a library so
 * the spec has no extra dependency and so the bytes are exactly what a browser
 * upload would carry.
 */
function buildXlsx(rows: string[][]): Buffer {
  const esc = (value: string): string =>
    value
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  const col = (index: number): string => {
    let name = "";
    let n = index;
    while (n >= 0) {
      name = String.fromCharCode(65 + (n % 26)) + name;
      n = Math.floor(n / 26) - 1;
    }
    return name;
  };
  const sheetRows = [HEADERS, ...rows]
    .map((cells, rowIndex) => {
      const body = cells
        .map((cell, cellIndex) =>
          cell === ""
            ? ""
            : `<c r="${col(cellIndex)}${rowIndex + 1}" t="inlineStr">` +
              `<is><t xml:space="preserve">${esc(cell)}</t></is></c>`,
        )
        .join("");
      return `<row r="${rowIndex + 1}">${body}</row>`;
    })
    .join("");

  const files: Array<[string, string]> = [
    [
      "[Content_Types].xml",
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
        '<Default Extension="xml" ContentType="application/xml"/>' +
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
        "</Types>",
    ],
    [
      "_rels/.rels",
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
        "</Relationships>",
    ],
    [
      "xl/workbook.xml",
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
        '<sheets><sheet name="Matter Import" sheetId="1" r:id="rId1"/></sheets></workbook>',
    ],
    [
      "xl/_rels/workbook.xml.rels",
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
        "</Relationships>",
    ],
    [
      "xl/worksheets/sheet1.xml",
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
        `<sheetData>${sheetRows}</sheetData></worksheet>`,
    ],
  ];

  // Store-only ZIP (no compression) keeps this dependency-free.
  const crcTable: number[] = [];
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crcTable[n] = c >>> 0;
  }
  const crc32 = (buf: Buffer): number => {
    let c = 0xffffffff;
    for (const byte of buf) c = crcTable[(c ^ byte) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };

  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const [name, content] of files) {
    const nameBuf = Buffer.from(name, "utf8");
    const data = Buffer.from(content, "utf8");
    const crc = crc32(data);

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt16LE(0, 10);
    local.writeUInt16LE(0, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    local.writeUInt16LE(0, 28);
    locals.push(local, nameBuf, data);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt16LE(0, 12);
    central.writeUInt16LE(0, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBuf.length, 28);
    central.writeUInt16LE(0, 30);
    central.writeUInt16LE(0, 32);
    central.writeUInt16LE(0, 34);
    central.writeUInt16LE(0, 36);
    central.writeUInt32LE(0, 38);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, nameBuf);

    offset += local.length + nameBuf.length + data.length;
  }
  const centralBuf = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(centralBuf.length, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);
  return Buffer.concat([...locals, centralBuf, end]);
}

function code(suffix: string): string {
  return `RAM814-${suffix}-${RUN_ID}`.replace(/[^A-Z0-9-]/g, "").slice(0, 78);
}

test.describe("Ram 2026-08-14 bulk matter upload", () => {
  test.beforeAll(async ({ playwright }) => {
    if (!IS_LOCAL) return;
    const context = await playwright.request.newContext();
    const response = await context.post(
      `${API_BASE_URL}/api/bootstrap/company`,
      {
        data: {
          company_name: `Ram Aug14 ${RUN_ID}`,
          company_slug: COMPANY_SLUG,
          company_type: "law_firm",
          owner_full_name: "Ram Tester",
          owner_email: TESTER_EMAIL,
          owner_password: LOCAL_TESTER_PASSWORD,
        },
      },
    );
    await expectStatus(response, 200, "bootstrap local tenant");
    await context.dispose();
  });

  test("BUG-001/002: specialist forums import without exact catalog courts", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`${BASE_URL}/app/matters/imports`);
    await expect(page.getByTestId("matter-import-file")).toBeVisible();

    // Exactly the shapes Ram reported: Forum taken from the product's own
    // template dropdown, Court typed as a practitioner would write it.
    const rows = [
      ["DRT natural name", code("DRT"), "Commercial", "active", "Acme", "DRAT / DRT", "DRT Delhi", ""],
      ["DRT with no court", code("DRTNC"), "Commercial", "active", "Acme", "DRAT / DRT", "", ""],
      ["State Commission short", code("SC"), "Commercial", "active", "Acme", "State Commission", "Delhi State Commission", ""],
      ["Recovery outside Delhi", code("REC"), "Commercial", "active", "Acme", "Recovery Forums", "Recovery Officer Mumbai", ""],
      ["Family court matter", code("FAM"), "Civil", "active", "Acme", "Family Court", "Saket Family Court", ""],
    ];

    const [preview] = await Promise.all([
      page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/matters/imports/preview" &&
          response.request().method() === "POST",
        { timeout: 90_000 },
      ),
      page
        .getByTestId("matter-import-file")
        .setInputFiles({
          name: "ram-aug14-forums.xlsx",
          mimeType:
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          buffer: buildXlsx(rows),
        })
        .then(() => page.getByTestId("matter-import-validate").click()),
    ]);
    await expectStatus(preview, 200, "validate specialist forum rows");

    // The page must show every row ready. Before the fix these rendered as
    // "Court is not an active DRAT / DRT catalog selection".
    const confirm = page.getByTestId("matter-import-confirm");
    await expect(confirm).toHaveText(/Confirm import \(5\)/);
    await expect(confirm).toBeEnabled();
    await expect(page.getByText("Validation errors").locator("..")).toContainText("0");
    await expect(page.getByText(/is not an active .* catalog selection/)).toHaveCount(0);
    await expect(page.getByText(/Court is required for/)).toHaveCount(0);
    // BUG-001: the raw pydantic enum must never reach the page.
    await expect(page.getByText(/Input should be 'lower_court'/)).toHaveCount(0);

    const [commit] = await Promise.all([
      page.waitForResponse(
        (response) =>
          /\/api\/matters\/imports\/[^/]+\/commit$/.test(
            new URL(response.url()).pathname,
          ) && response.request().method() === "POST",
        { timeout: 120_000 },
      ),
      confirm.click(),
    ]);
    await expectStatus(commit, 200, "commit specialist forum rows");
    const committed = (await commit.json()) as {
      created_matter_ids: string[];
      job: { status: string };
    };
    expect(committed.created_matter_ids).toHaveLength(5);
    expect(committed.job.status).toBe("completed");
  });

  test("BUG-002: an exact catalog court still enriches with lineage", async ({
    page,
  }) => {
    const token = await signIn(page);
    await page.goto(`${BASE_URL}/app/matters/imports`);

    const matterCode = code("EXACT");
    const [preview] = await Promise.all([
      page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/matters/imports/preview",
        { timeout: 90_000 },
      ),
      page
        .getByTestId("matter-import-file")
        .setInputFiles({
          name: "ram-aug14-exact.xlsx",
          mimeType:
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          buffer: buildXlsx([
            ["Exact DRT bench", matterCode, "Commercial", "active", "Acme", "DRAT / DRT", "DRT-2", ""],
          ]),
        })
        .then(() => page.getByTestId("matter-import-validate").click()),
    ]);
    await expectStatus(preview, 200, "validate exact catalog court");

    const [commit] = await Promise.all([
      page.waitForResponse((response) =>
        /\/api\/matters\/imports\/[^/]+\/commit$/.test(
          new URL(response.url()).pathname,
        ),
      ),
      page.getByTestId("matter-import-confirm").click(),
    ]);
    await expectStatus(commit, 200, "commit exact catalog court");
    const { created_matter_ids: created } = (await commit.json()) as {
      created_matter_ids: string[];
    };
    expect(created).toHaveLength(1);

    // Failing open must not have cost us catalog enrichment on exact values.
    const matter = await page.request.get(
      `${API_BASE_URL}/api/matters/${created[0]}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    await expectStatus(matter, 200, "read enriched matter");
    const record = (await matter.json()) as {
      forum_catalog_entry_id: string | null;
      forum_level: string;
      forum_state: string | null;
    };
    expect(record.forum_catalog_entry_id).toBe("drt:delhi:drt-2");
    expect(record.forum_level).toBe("tribunal");
    expect(record.forum_state).toBe("Delhi");
  });

  test("BUG-003: duplicates are skipped and the original still imports", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`${BASE_URL}/app/matters/imports`);

    const keeper = code("KEEP");
    const clean = code("CLEAN");
    const [preview] = await Promise.all([
      page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/matters/imports/preview",
        { timeout: 90_000 },
      ),
      page
        .getByTestId("matter-import-file")
        .setInputFiles({
          name: "ram-aug14-dupes.xlsx",
          mimeType:
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          buffer: buildXlsx([
            ["Keeper", keeper, "Commercial", "active", "Acme", "High Court", "Delhi High Court", ""],
            ["Keeper", keeper, "Commercial", "active", "Acme", "High Court", "Delhi High Court", ""],
            ["Clean row", clean, "Commercial", "active", "Acme", "High Court", "Delhi High Court", ""],
          ]),
        })
        .then(() => page.getByTestId("matter-import-validate").click()),
    ]);
    await expectStatus(preview, 200, "validate duplicate rows");

    // Skipped, not rejected: no correction is demanded of the user.
    await expect(page.getByText("Duplicates skipped").locator("..")).toContainText("1");
    await expect(page.getByText("Validation errors").locator("..")).toContainText("0");
    await expect(page.getByText(/Skipped — already exists/)).toBeVisible();
    const confirm = page.getByTestId("matter-import-confirm");
    await expect(confirm).toHaveText(/Confirm import \(2\)/);
    await expect(confirm).toBeEnabled();

    const [commit] = await Promise.all([
      page.waitForResponse((response) =>
        /\/api\/matters\/imports\/[^/]+\/commit$/.test(
          new URL(response.url()).pathname,
        ),
      ),
      confirm.click(),
    ]);
    await expectStatus(commit, 200, "commit with duplicates skipped");
    const result = (await commit.json()) as {
      created_matter_ids: string[];
      job: { status: string; duplicate_rows: number; failed_count: number };
    };
    // The original survives; only the repeat is dropped.
    expect(result.created_matter_ids).toHaveLength(2);
    expect(result.job.duplicate_rows).toBe(1);
    expect(result.job.failed_count).toBe(0);
    expect(result.job.status).toBe("completed");
  });

  test("BUG-004: matter owner resolves by full name, not only work email", async ({
    page,
  }) => {
    const token = await signIn(page);

    const employees = await page.request.get(
      `${API_BASE_URL}/api/companies/current/employees?limit=100`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    await expectStatus(employees, 200, "read company directory");
    const payload = (await employees.json()) as Record<string, unknown>;
    const list = Object.values(payload).find(Array.isArray) as
      | Array<{ email?: string; full_name?: string }>
      | undefined;
    expect(list, "employee directory should be a list").toBeTruthy();

    // Pick a full name that belongs to exactly one active user, so the
    // assertion is about resolution and never about ambiguity.
    const names = (list ?? [])
      .map((entry) => (entry.full_name ?? "").trim())
      .filter(Boolean);
    const uniqueName = names.find(
      (name) => names.filter((other) => other === name).length === 1,
    );
    test.skip(
      !uniqueName,
      "tenant has no active user with a unique full name to resolve by",
    );

    await page.goto(`${BASE_URL}/app/matters/imports`);
    const [preview] = await Promise.all([
      page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/matters/imports/preview",
        { timeout: 90_000 },
      ),
      page
        .getByTestId("matter-import-file")
        .setInputFiles({
          name: "ram-aug14-owner.xlsx",
          mimeType:
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          buffer: buildXlsx([
            ["Owner by name", code("OWN"), "Commercial", "active", "Acme", "High Court", "Delhi High Court", uniqueName ?? ""],
          ]),
        })
        .then(() => page.getByTestId("matter-import-validate").click()),
    ]);
    await expectStatus(preview, 200, "validate owner-by-name row");

    // The reported failure text must be gone.
    await expect(
      page.getByText("Matter owner must match an active user in this company."),
    ).toHaveCount(0);
    const confirm = page.getByTestId("matter-import-confirm");
    await expect(confirm).toHaveText(/Confirm import \(1\)/);

    const job = (await preview.json()) as {
      rows: Array<{ status: string; normalized: Record<string, unknown> }>;
    };
    expect(job.rows[0].status).toBe("valid");
    expect(job.rows[0].normalized.owner_membership_id).toBeTruthy();
  });
});
