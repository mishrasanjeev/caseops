import { expect, type APIRequestContext } from "@playwright/test";

import { expectStatus } from "./iplf058b";

type Json = Record<string, any>;

async function postJson(
  api: APIRequestContext,
  url: string,
  headers: Record<string, string>,
  data: Json,
  label: string,
  expected = 200,
): Promise<Json> {
  const response = await api.post(url, { headers, data });
  await expectStatus(response, expected, label);
  return (await response.json()) as Json;
}

async function uploadDocument(
  api: APIRequestContext,
  apiBase: string,
  headers: Record<string, string>,
  docketId: string,
  runId: string,
  privileged: boolean,
): Promise<string> {
  const kind = privileged ? "strategy" : "filing-pack";
  const response = await api.post(`${apiBase}/api/ip/documents/upload`, {
    headers,
    multipart: {
      metadata_json: JSON.stringify({
        taxonomy_key: "evidence",
        title: `ASTER US ${kind} ${runId}`,
        confidentiality: privileged ? "restricted" : "internal",
        is_privileged: privileged,
        client_code: "CASEOPS-QA",
        asset_type: "Trademark",
        mark: `ASTER ${runId}`,
        jurisdiction: "US",
        document_date: "2026-08-26",
        links: [{ target_type: "docket", target_id: docketId }],
      }),
      upload: {
        name: `${kind}-${runId}.txt`,
        mimeType: "text/plain",
        buffer: Buffer.from(
          `Synthetic IPLF-059B ${kind} ${runId}; no legal effect.`,
        ),
      },
    },
  });
  await expectStatus(response, 200, `upload ${kind}`);
  return ((await response.json()) as Json).document.id as string;
}

export async function createForeignAssociateFixture(
  api: APIRequestContext,
  apiBase: string,
  headers: Record<string, string>,
  membershipId: string,
  runId: string,
) {
  const matter = await postJson(
    api,
    `${apiBase}/api/matters/`,
    headers,
    {
      title: `IPLF-059B ASTER US filing ${runId}`,
      matter_code: `FA-${runId}`.replace(/[^A-Z0-9-]/gi, "").toUpperCase().slice(0, 78),
      practice_area: "intellectual_property",
      forum_level: "tribunal",
      status: "intake",
    },
    "create foreign filing matter",
  );
  const docket = await postJson(
    api,
    `${apiBase}/api/ip/dockets`,
    headers,
    {
      title: `ASTER US filing ${runId}`,
      matter_id: matter.id,
      restricted: false,
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: { text: "ASTER", evidence_reference: `e2e:059b:mark:${runId}` },
        classes: [
          { class_number: 9, specification: "Downloadable legal software" },
          { class_number: 42, specification: "Legal software as a service" },
        ],
        use_priority: null,
        parties: [{ role: "applicant", name: "Aster Products Private Limited" }],
        agent: null,
        filing_manifest: [{
          key: "representation",
          label: "Mark representation",
          required: true,
          evidence_reference: `e2e:059b:mark:${runId}`,
        }],
      },
    },
    "create foreign filing docket",
    201,
  );

  const taxonomy = await api.post(`${apiBase}/api/ip/document-taxonomy/seed`, { headers });
  await expectStatus(taxonomy, 200, "seed document taxonomy");
  const filingDocumentId = await uploadDocument(
    api, apiBase, headers, docket.id, runId, false,
  );
  const privilegedDocumentId = await uploadDocument(
    api, apiBase, headers, docket.id, runId, true,
  );

  const counsel = await postJson(
    api,
    `${apiBase}/api/outside-counsel/profiles`,
    headers,
    {
      name: `Liberty IP ${runId}`,
      primary_contact_name: "US Filing Partner",
      primary_contact_email: `filings-${runId}@example.com`,
      jurisdictions: ["US"],
      practice_areas: ["Trademark"],
      panel_status: "preferred",
    },
    "create preferred foreign associate",
  );
  const replacementCounsel = await postJson(
    api,
    `${apiBase}/api/outside-counsel/profiles`,
    headers,
    {
      name: `Hudson Marks ${runId}`,
      primary_contact_name: "Replacement Filing Partner",
      primary_contact_email: `replacement-${runId}@example.com`,
      jurisdictions: ["US"],
      practice_areas: ["Trademark"],
      panel_status: "active",
    },
    "create replacement foreign associate",
  );
  const assignment = await postJson(
    api,
    `${apiBase}/api/outside-counsel/assignments`,
    headers,
    {
      matter_id: matter.id,
      counsel_id: counsel.id,
      role_summary: "US trademark filing associate",
      budget_amount_minor: 250000,
      currency: "INR",
      status: "approved",
    },
    "create approved foreign-associate assignment",
  );
  const replacementAssignment = await postJson(
    api,
    `${apiBase}/api/outside-counsel/assignments`,
    headers,
    {
      matter_id: matter.id,
      counsel_id: replacementCounsel.id,
      role_summary: "Replacement US trademark filing associate",
      budget_amount_minor: 275000,
      currency: "INR",
      status: "approved",
    },
    "create replacement assignment",
  );

  const invoice = await postJson(
    api,
    `${apiBase}/api/matters/${matter.id}/invoices`,
    headers,
    {
      invoice_number: `INV-${runId}`.slice(0, 80),
      issued_on: "2026-08-26",
      due_on: "2026-09-25",
      status: "draft",
      include_uninvoiced_time_entries: false,
      manual_items: [{ description: "ASTER US filing", amount_minor: 275000 }],
    },
    "create canonical client invoice",
  );
  const cost = async (description: string, amountMinor: number, nature: "estimate" | "actual") => {
    const evidenceReference = `e2e:059b:${nature}:${runId}:${amountMinor}`;
    const updatedDocket = await postJson(
      api,
      `${apiBase}/api/ip/dockets/${docket.id}/cost-items`,
      headers,
      {
        category: "associate_fee",
        description,
        amount_minor: amountMinor,
        currency: "INR",
        evidence_reference: evidenceReference,
        billable: true,
        cost_nature: nature,
        rate_confidential: false,
        ...(nature === "actual" ? {
          billing_link_type: "invoice",
          billing_link_id: invoice.id,
        } : {}),
      },
      `create ${description}`,
    );
    const created = updatedDocket.cost_items.find(
      (row: Json) => row.evidence_reference === evidenceReference,
    );
    expect(created, `${description} must be returned in the canonical docket`).toBeTruthy();
    return created as Json;
  };
  const estimate = await cost("US filing estimate", 250000, "estimate");
  const revisedEstimate = await cost("Revised US filing estimate", 275000, "estimate");
  const actual = await cost("US filing actual", 275000, "actual");
  const spend = await postJson(
    api,
    `${apiBase}/api/outside-counsel/spend-records`,
    headers,
    {
      matter_id: matter.id,
      counsel_id: counsel.id,
      assignment_id: assignment.id,
      invoice_reference: `INV-${runId}`,
      description: "ASTER US filing invoice",
      currency: "INR",
      amount_minor: 275000,
      approved_amount_minor: 275000,
      status: "paid",
      paid_on: "2026-08-26",
    },
    "create paid associate spend",
  );
  const communication = await postJson(
    api,
    `${apiBase}/api/matters/${matter.id}/communications`,
    headers,
    {
      direction: "outbound",
      channel: "email",
      subject: `ASTER US filing instruction ${runId}`,
      body: "Approved scope and selected filing documents.",
    },
    "create approved instruction communication",
  );

  return {
    matter,
    docket,
    filingDocumentId,
    privilegedDocumentId,
    counsel,
    replacementCounsel,
    assignment,
    replacementAssignment,
    estimate,
    revisedEstimate,
    actual,
    spend,
    communication,
    invoice,
    membershipId,
    runId,
  };
}

export async function createInstruction(
  api: APIRequestContext,
  apiBase: string,
  headers: Record<string, string>,
  fixture: Json,
  suffix: string,
  selectedDocumentRefs = [fixture.filingDocumentId],
) {
  return postJson(
    api,
    `${apiBase}/api/ip/foreign-associate-instructions`,
    headers,
    {
      docket_id: fixture.docket.id,
      expected_lifecycle_version: fixture.docket.lifecycle_version,
      instruction_thread_key: `ASTER-US-${fixture.runId}-${suffix}`,
      client_authority_reference: `CLIENT-AUTH-${fixture.runId}`,
      target_jurisdiction: "US",
      outside_counsel_id: fixture.counsel.id,
      assignment_id: fixture.assignment.id,
      responsible_membership_id: fixture.membershipId,
      scope: {
        source_kind: "application",
        source_reference: `TM-US-${fixture.runId}`,
        filing_kind: "national trademark application",
        scoped_fields: { classes: [9, 42], mark: "ASTER" },
      },
      selected_document_refs: selectedDocumentRefs,
      include_privileged_documents: false,
      estimate_cost_item_id: fixture.estimate.id,
      estimate_terms: {
        tax_type: "sales_tax",
        tax_rate_percent: 8.25,
        tax_inclusive: false,
        tax_evidence_reference: `e2e:059b:tax:${fixture.runId}`,
        assumptions: ["Two classes and one response included"],
      },
      budget_policy_reference: "Foreign filing budget policy BP-2026-04",
      response_due_at: new Date(Date.now() + 72 * 60 * 60 * 1000).toISOString(),
      reason: "Create the lawyer-reviewed foreign filing instruction.",
    },
    `create foreign-associate instruction ${suffix}`,
    201,
  );
}

export async function recordForeignAssociateTransaction(
  api: APIRequestContext,
  apiBase: string,
  headers: Record<string, string>,
  fixture: Json,
  instruction: Json,
  kind: string,
  input: Json = {},
) {
  const workspaceResponse = await api.get(
    `${apiBase}/api/ip/foreign-associate-instructions/${instruction.id}/workspace`,
    { headers },
  );
  await expectStatus(workspaceResponse, 200, `${kind} workspace`);
  const docketResponse = await api.get(`${apiBase}/api/ip/dockets/${fixture.docket.id}`, {
    headers,
  });
  await expectStatus(docketResponse, 200, `${kind} docket`);
  const workspace = (await workspaceResponse.json()) as Json;
  const docket = (await docketResponse.json()) as Json;
  const expectedVersion = workspace.instruction.row_version as number;
  const reason = `IPLF-059B ${kind} reviewed in the dated acceptance journey.`;
  try {
    const response = await api.post(
      `${apiBase}/api/ip/foreign-associate-instructions/${instruction.id}/transactions`,
      {
        headers,
        data: {
          expected_version: expectedVersion,
          expected_lifecycle_version: docket.lifecycle_version,
          transaction_kind: kind,
          effective_at: new Date().toISOString(),
          responsible_membership_id: fixture.membershipId,
          reason,
          ...input,
        },
      },
    );
    await expectStatus(response, 201, `foreign-associate ${kind}`);
    return (await response.json()) as Json;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!/ECONNRESET|socket hang up/i.test(message)) throw error;

    // A response can be lost after the server commits. Never replay this
    // mutation: reconcile the exact versioned event from authoritative state.
    const recoveryResponse = await api.get(
      `${apiBase}/api/ip/foreign-associate-instructions/${instruction.id}/workspace`,
      { headers },
    );
    await expectStatus(recoveryResponse, 200, `reconcile foreign-associate ${kind}`);
    const recovered = (await recoveryResponse.json()) as Json;
    const matchingEvents = (recovered.transactions as Json[]).filter((event) =>
      event.event_kind === "foreign_associate_instruction_transaction"
      && event.reason === reason
      && event.payload_json?.transaction_kind === kind
      && event.payload_json?.row_version_before === expectedVersion
      && event.payload_json?.row_version_after === expectedVersion + 1
    );
    expect(matchingEvents, `ambiguous ${kind} response must reconcile exactly once`).toHaveLength(1);
    expect(recovered.instruction.row_version).toBeGreaterThanOrEqual(expectedVersion + 1);

    let successor = null;
    const successorId = matchingEvents[0].payload_json?.successor_instruction_id;
    if (typeof successorId === "string" && successorId) {
      const successorResponse = await api.get(
        `${apiBase}/api/ip/foreign-associate-instructions/${successorId}`,
        { headers },
      );
      await expectStatus(successorResponse, 200, `reconcile foreign-associate ${kind} successor`);
      successor = (await successorResponse.json()) as Json;
    }
    return {
      instruction: recovered.instruction,
      event: matchingEvents[0],
      successor,
    };
  }
}

export async function exerciseForeignAssociateJourney(
  api: APIRequestContext,
  apiBase: string,
  headers: Record<string, string>,
  fixture: Json,
) {
  const normal = await createInstruction(api, apiBase, headers, fixture, "NORMAL");
  await recordForeignAssociateTransaction(api, apiBase, headers, fixture, normal, "approve");
  await recordForeignAssociateTransaction(api, apiBase, headers, fixture, normal, "dispatch", {
    external_dispatch_reference: `mail:dispatch:${fixture.runId}`,
    external_delivery_reference: `mail:delivered:${fixture.runId}`,
    external_delivered_at: new Date().toISOString(),
    evidence_refs: [`https://example.com/evidence/dispatch/${fixture.runId}`],
  });

  const workspaceBeforeAck = await api.get(
    `${apiBase}/api/ip/foreign-associate-instructions/${normal.id}/workspace`,
    { headers },
  );
  await expectStatus(workspaceBeforeAck, 200, "delivery-without-acknowledgement workspace");
  const delivered = (await workspaceBeforeAck.json()) as Json;
  expect(delivered.delivery_status).toBe("delivered");
  expect(delivered.acknowledgement_status).toBe("outstanding");

  const currentDocket = await api.get(`${apiBase}/api/ip/dockets/${fixture.docket.id}`, { headers });
  await expectStatus(currentDocket, 200, "load reminder lifecycle");
  const reminderResponse = await api.post(
    `${apiBase}/api/ip/foreign-associate-instructions/${normal.id}/reminders`,
    {
      headers,
      data: {
        expected_version: delivered.instruction.row_version,
        expected_lifecycle_version: ((await currentDocket.json()) as Json).lifecycle_version,
        reminder_offsets_hours: [48, 24, 0],
        channels: ["in_app", "email"],
        escalation_after_hours: 12,
        escalation_membership_id: fixture.membershipId,
      },
    },
  );
  await expectStatus(reminderResponse, 200, "schedule acknowledgement reminders");
  const reminderResult = (await reminderResponse.json()) as Json;
  expect(reminderResult.created_count).toBe(8);

  await recordForeignAssociateTransaction(api, apiBase, headers, fixture, normal, "acknowledge", {
    acknowledgement_reference: `ACK-${fixture.runId}`,
  });
  await recordForeignAssociateTransaction(api, apiBase, headers, fixture, normal, "record_query", {
    evidence_refs: [`https://example.com/evidence/query/${fixture.runId}`],
    document_refs: [fixture.filingDocumentId],
  });
  await recordForeignAssociateTransaction(
    api, apiBase, headers, fixture, normal, "approve_substantive_response", {
      evidence_refs: [`https://example.com/evidence/response/${fixture.runId}`],
      document_refs: [fixture.filingDocumentId],
    },
  );
  await recordForeignAssociateTransaction(api, apiBase, headers, fixture, normal, "approve_fee_change", {
    evidence_refs: [`https://example.com/evidence/estimate/${fixture.runId}`],
    replacement_estimate_cost_item_id: fixture.revisedEstimate.id,
    replacement_estimate_terms: {
      tax_type: "sales_tax",
      tax_rate_percent: 8.25,
      tax_inclusive: false,
      tax_evidence_reference: `e2e:059b:revised-tax:${fixture.runId}`,
      assumptions: ["Expedited filing included"],
    },
  });
  await recordForeignAssociateTransaction(api, apiBase, headers, fixture, normal, "report_filing", {
    filing_identifier: `US-TM-${fixture.runId}`,
    evidence_refs: [`https://example.com/evidence/filing/${fixture.runId}`],
    document_refs: [fixture.filingDocumentId],
  });
  await recordForeignAssociateTransaction(
    api, apiBase, headers, fixture, normal, "verify_filing_evidence", {
      evidence_refs: [`https://example.com/evidence/registry/${fixture.runId}`],
    },
  );
  await recordForeignAssociateTransaction(api, apiBase, headers, fixture, normal, "link_invoice", {
    actual_cost_item_id: fixture.actual.id,
    spend_record_id: fixture.spend.id,
  });
  const reconciliation = await api.post(
    `${apiBase}/api/ip/dockets/${fixture.docket.id}/cost-items/reconcile`,
    { headers },
  );
  await expectStatus(reconciliation, 200, "reconcile filing cost to client billing");
  expect(((await reconciliation.json()) as Json).matched_count).toBe(1);
  const completed = await recordForeignAssociateTransaction(
    api, apiBase, headers, fixture, normal, "complete",
  );
  expect(completed.instruction.status).toBe("completed");

  const refused = await createInstruction(api, apiBase, headers, fixture, "REASSIGN");
  await recordForeignAssociateTransaction(api, apiBase, headers, fixture, refused, "approve");
  await recordForeignAssociateTransaction(api, apiBase, headers, fixture, refused, "dispatch", {
    external_dispatch_reference: `mail:reassign:${fixture.runId}`,
  });
  await recordForeignAssociateTransaction(api, apiBase, headers, fixture, refused, "refuse", {
    evidence_refs: [`https://example.com/evidence/refusal/${fixture.runId}`],
  });
  const reassigned = await recordForeignAssociateTransaction(
    api, apiBase, headers, fixture, refused, "reassign", {
      evidence_refs: [`https://example.com/evidence/reassignment/${fixture.runId}`],
      replacement_outside_counsel_id: fixture.replacementCounsel.id,
      replacement_assignment_id: fixture.replacementAssignment.id,
      replacement_estimate_cost_item_id: fixture.revisedEstimate.id,
      replacement_estimate_terms: {
        tax_type: "sales_tax",
        tax_rate_percent: 8.25,
        tax_inclusive: false,
        tax_evidence_reference: `e2e:059b:replacement-tax:${fixture.runId}`,
        assumptions: ["Prior correspondence retained"],
      },
      replacement_response_due_at: new Date(Date.now() + 96 * 60 * 60 * 1000).toISOString(),
    },
  );
  expect(reassigned.successor.outside_counsel_id).toBe(fixture.replacementCounsel.id);

  return { normal, completed: completed.instruction, refused, reassigned: reassigned.successor };
}
