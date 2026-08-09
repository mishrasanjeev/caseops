import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "IpDocumentFoundation2026!";

function grantIpEntitlement(companyId: string): void {
  const python =
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session = get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'], status='manual_active', segment='law_firm', source='iplf_024a_playwright', externally_billable=False, entitlement_overrides_json={'ip_workspace': True}))",
    "session.commit()",
    "session.close()",
  ].join("; ");
  const result = spawnSync(python, ["-c", script], {
    cwd: repoRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      ...e2eEnv,
      CASEOPS_E2E_COMPANY_ID: companyId,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
}

async function bootstrap(api: APIRequestContext): Promise<{ token: string; slug: string }> {
  const slug = `doc-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 024A Document Foundation LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Document Foundation Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  grantIpEntitlement(body.company.id as string);
  return { token: body.access_token as string, slug };
}

test("IPLF-024A document foundation is tenant-safe, versioned, and deterministic", async () => {
  test.setTimeout(120_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = { Authorization: `Bearer ${tenant.token}` };

  const contract = await api.get(`${apiBaseUrl}/api/ip/documents/foundation-contract`, {
    headers,
  });
  expect(contract.status(), await contract.text()).toBe(200);
  expect(await contract.json()).toMatchObject({
    identity_owner: "ip_documents",
    version_owner: "ip_document_versions",
    link_owner: "ip_document_links",
    binary_storage_owner: "shared_document_storage",
    processing_queue_owner: "document_processing_jobs",
    processing_target_type: "ip_document_version",
    taxonomy_version: "ip-document-taxonomy-v1",
  });

  const empty = await api.get(`${apiBaseUrl}/api/ip/document-taxonomy`, { headers });
  expect(empty.status(), await empty.text()).toBe(200);
  expect((await empty.json()).entries).toEqual([]);

  const seeded = await api.post(`${apiBaseUrl}/api/ip/document-taxonomy/seed`, { headers });
  expect(seeded.status(), await seeded.text()).toBe(200);
  const seededBody = await seeded.json();
  expect(seededBody.entries).toHaveLength(14);
  expect(seededBody.entries.map((entry: { key: string }) => entry.key)).toContain(
    "trademark_filing",
  );

  const examination = seededBody.entries.find(
    (entry: { key: string }) => entry.key === "examination",
  );
  const updated = await api.put(`${apiBaseUrl}/api/ip/document-taxonomy/examination`, {
    headers,
    data: {
      expected_version: examination.version,
      label: "Examination response",
      description: "Controlled tenant category",
      sort_order: examination.sort_order,
      is_active: true,
      aliases: ["Exam report", "FER"],
    },
  });
  expect(updated.status(), await updated.text()).toBe(200);
  expect((await updated.json()).version).toBe(2);

  const stale = await api.put(`${apiBaseUrl}/api/ip/document-taxonomy/examination`, {
    headers,
    data: { expected_version: 1, label: "Stale overwrite", aliases: [] },
  });
  expect(stale.status(), await stale.text()).toBe(409);
  expect((await stale.json()).code).toBe("ip_document_taxonomy_version_conflict");

  const preview = await api.post(`${apiBaseUrl}/api/ip/documents/naming-preview`, {
    headers,
    data: {
      client_code: "ACME/01",
      asset_type: "Trademark",
      mark: "=FORMULA",
      jurisdiction: "IN",
      document_type: "Order",
      document_date: "2026-08-09",
      version: 1,
      extension: "pdf",
      existing_names: ["ACME_01_Trademark__=FORMULA_IN_Order_2026-08-09_1.pdf"],
    },
  });
  expect(preview.status(), await preview.text()).toBe(200);
  const previewBody = await preview.json();
  expect(previewBody.conflict_detected).toBe(true);
  expect(previewBody.resolved_name).toBe(
    "ACME_01_Trademark__=FORMULA_IN_Order_2026-08-09_1_2.pdf",
  );
  expect(previewBody.warnings.join(" ")).toContain("no existing name was overwritten");

  await api.dispose();
});
