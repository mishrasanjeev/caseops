import { expect, type APIRequestContext, type APIResponse } from "@playwright/test";

type Json = Record<string, any>;

export async function expectStatus(
  response: Pick<APIResponse, "status" | "text">,
  expected: number,
  label: string,
) {
  const detail = response.status() === expected ? "" : ` ${await response.text()}`;
  expect(response.status(), `${label}.${detail}`).toBe(expected);
}

export async function createRecordalFixture(
  api: APIRequestContext,
  apiBase: string,
  headers: Record<string, string>,
  membershipId: string,
  runId: string,
) {
  const applicationResponse = await api.post(
    `${apiBase}/api/ip/trademark-applications/manual`,
    {
      headers,
      data: {
        title: `IPLF-058B ASTER ${runId}`,
        restricted: false,
        asset_title: `ASTER ${runId}`,
        jurisdiction: "IN",
        office: "Trade Marks Registry Delhi",
        filing_phase: "filed",
        source_pending_identifier_allocation: false,
        application_number: {
          raw_value: `TM-${runId}`,
          source: "synthetic dated recordal acceptance fixture",
          effective_from: "2026-08-25",
          is_primary: true,
        },
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: {
            text: `ASTER ${runId}`,
            evidence_reference: `e2e:058b:mark:${runId}`,
          },
          classes: [
            { class_number: 9, specification: "Downloadable legal software" },
            { class_number: 42, specification: "Legal software as a service" },
          ],
          use_priority: null,
          parties: [{ role: "applicant", name: "Oldco Brands Limited" }],
          agent: null,
          filing_manifest: [
            {
              key: "representation",
              label: "Mark representation",
              required: true,
              evidence_reference: `e2e:058b:mark:${runId}`,
            },
          ],
        },
      },
    },
  );
  await expectStatus(applicationResponse, 201, "manual trademark application");
  const application = (await applicationResponse.json()) as Json;
  const docket = application.docket as Json;

  await expectStatus(
    await api.post(`${apiBase}/api/ip/document-taxonomy/seed`, { headers }),
    200,
    "seed document taxonomy",
  );
  const uploadResponse = await api.post(`${apiBase}/api/ip/documents/upload`, {
    headers,
    multipart: {
      metadata_json: JSON.stringify({
        taxonomy_key: "evidence",
        title: `Executed partial assignment ${runId}`,
        confidentiality: "internal",
        is_privileged: false,
        client_code: "CASEOPS-QA",
        asset_type: "Trademark",
        mark: `ASTER ${runId}`,
        jurisdiction: "IN",
        document_date: "2026-08-01",
        links: [{ target_type: "docket", target_id: docket.id }],
      }),
      upload: {
        name: `assignment-${runId}.txt`,
        mimeType: "text/plain",
        buffer: Buffer.from(`Synthetic IPLF-058B assignment ${runId}; no legal effect.`),
      },
    },
  });
  await expectStatus(uploadResponse, 200, "upload assignment instrument");
  const documentId = ((await uploadResponse.json()) as Json).document.id as string;

  const priorResponse = await api.post(
    `${apiBase}/api/ip/dockets/${docket.id}/title-interests`,
    {
      headers,
      data: {
        interest_type: "ownership",
        party_name: "Oldco Brands Limited",
        party_role: "registered_proprietor",
        effective_from: "2020-01-01",
        evidence_reference: documentId,
        recordal_status: "recorded",
        registry_recorded_on: "2020-02-01",
      },
    },
  );
  await expectStatus(priorResponse, 200, "prior Registry title");

  const linkResponse = await api.post(
    `${apiBase}/api/ip/dockets/${docket.id}/registry-links`,
    {
      headers,
      data: {
        application_id: application.application.id,
        provider_key: "ipindia-registry",
        office: "IP India",
        jurisdiction: "IN",
        identifier_kind: "application",
        raw_identifier: `TM-${runId}`,
        source_url: "https://ipindia.gov.in/trademark/",
        match_confidence: "1.0000",
        match_evidence: { fixture: "IPLF-058B", identifier: `TM-${runId}` },
        capability_version: "manual-evidence-v1",
      },
    },
  );
  await expectStatus(linkResponse, 201, "Registry link");
  const link = (await linkResponse.json()) as Json;
  const confirmedResponse = await api.post(
    `${apiBase}/api/ip/registry-links/${link.id}/match-decision`,
    {
      headers,
      data: {
        expected_version: link.version,
        decision: "confirm",
        reason: "Identifier and office match the synthetic acceptance right.",
      },
    },
  );
  await expectStatus(confirmedResponse, 200, "confirm Registry link");
  const confirmed = (await confirmedResponse.json()) as Json;
  const snapshotResponse = await api.post(
    `${apiBase}/api/ip/registry-links/${confirmed.id}/snapshots/manual`,
    {
      headers,
      data: {
        expected_link_version: confirmed.version,
        idempotency_key: `iplf-058b-${runId}`,
        source_url: "https://ipindia.gov.in/trademark/",
        source_retrieved_at: new Date().toISOString(),
        parser_version: "manual-normalizer-v1",
        schema_version: 1,
        attribution: { publisher: "IP India", capture_method: "manual" },
        raw_snapshot: { status: "registered", proprietor: "Registry Holdings Limited" },
        normalized_snapshot: {
          status: "registered",
          mark_name: `ASTER ${runId}`,
          parties: [{ role: "proprietor", name: "Registry Holdings Limited" }],
        },
      },
    },
  );
  await expectStatus(snapshotResponse, 201, "immutable Registry snapshot");
  const snapshot = ((await snapshotResponse.json()) as Json).snapshot as Json;

  const currentDocket = await api.get(`${apiBase}/api/ip/dockets/${docket.id}`, { headers });
  await expectStatus(currentDocket, 200, "load lifecycle version");
  const lifecycleVersion = ((await currentDocket.json()) as Json).lifecycle_version as number;
  const recordalResponse = await api.post(`${apiBase}/api/ip/recordals`, {
    headers,
    data: {
      docket_id: docket.id,
      expected_lifecycle_version: lifecycleVersion,
      responsible_membership_id: membershipId,
      reason: "Create the IPLF-058B reviewed partial assignment workspace.",
      recordal_type: "assignment",
      legal_basis: "Trade Marks Act, 1999 and applicable Trade Marks Rules",
      form_code: "TM-P",
      parties: [
        { role: "assignor", name: "Oldco Brands Limited", evidence_reference: documentId },
        { role: "assignee", name: "Nova Holdings LLP", evidence_reference: documentId },
      ],
      executed_on: "2026-08-01",
      effective_on: "2026-08-01",
      affected_registration_refs: [`TM-${runId}`],
      affected_classes: [9],
      scope_kind: "partial",
      scope_details: { goods_services: "Downloadable legal software only" },
      supporting_instrument_refs: [documentId],
      fee_cost_item_refs: [],
      deadline_rule_key: "tm_assignment_recordal_follow_up",
    },
  });
  await expectStatus(recordalResponse, 201, "create post-registration recordal");
  return {
    application,
    docket,
    documentId,
    recordal: (await recordalResponse.json()) as Json,
    snapshot,
  };
}

export async function recordTransaction(
  api: APIRequestContext,
  apiBase: string,
  headers: Record<string, string>,
  membershipId: string,
  fixture: Json,
  kind: string,
  input: Json = {},
  expectedStatus = 201,
) {
  const [workspaceResponse, docketResponse] = await Promise.all([
    api.get(`${apiBase}/api/ip/recordals/${fixture.recordal.id}/workspace`, { headers }),
    api.get(`${apiBase}/api/ip/dockets/${fixture.docket.id}`, { headers }),
  ]);
  await expectStatus(workspaceResponse, 200, "recordal workspace");
  await expectStatus(docketResponse, 200, "recordal docket");
  const workspace = (await workspaceResponse.json()) as Json;
  const docket = (await docketResponse.json()) as Json;
  const needsEvidence = ["filed", "defect_noted", "corrected", "accepted", "rejected"].includes(kind);
  const response = await api.post(
    `${apiBase}/api/ip/recordals/${fixture.recordal.id}/transactions`,
    {
      headers,
      data: {
        expected_version: workspace.recordal.version,
        expected_lifecycle_version: docket.lifecycle_version,
        transaction_kind: kind,
        effective_at: new Date().toISOString(),
        responsible_membership_id: membershipId,
        reason: `IPLF-058B ${kind} reviewed in the dated acceptance journey.`,
        evidence_refs: needsEvidence ? [`evidence:${kind}:${fixture.recordal.id}`] : [],
        document_refs: kind === "corrected" ? [fixture.documentId] : [],
        deadline_refs: [],
        cost_item_refs: [],
        ...input,
      },
    },
  );
  await expectStatus(response, expectedStatus, `recordal ${kind}`);
  return expectedStatus === 201 ? ((await response.json()) as Json) : response;
}
