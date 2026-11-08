import assert from 'node:assert/strict';
import { v1Identity, v1Version } from './v1-workflows-contract.mjs';

const creators = Object.freeze({
  patent: { route: '/api/ip/patents/families', type: 'patent_family' },
  design: { route: '/api/ip/specialist/records', type: 'design_intake' },
  trademark: { route: '/api/ip/trademark-applications/manual', type: 'trademark' },
});
const families = ['design', 'patent', 'trademark'];
const confirmationProof = Symbol('held V1 Calendar confirmation');
const sourceHash = /^[a-f0-9]{64}$/;
const docketFields = ['id', 'company_id', 'matter_id', 'record_type', 'title', 'primary_identifier', 'status',
  'is_active', 'lifecycle_version', 'access_policy_version', 'current_version', 'updated_at'];
const eventFields = ['id', 'kind', 'display_type', 'occurs_on', 'title', 'matter_id', 'matter_title', 'matter_code',
  'status', 'ip_docket_id', 'detail', 'court_label', 'court_identity', 'forum_display_order', 'hearing_time',
  'time_status', 'session_label', 'timezone'];

function keys(value, expected, code) {
  assert.ok(value && typeof value === 'object' && !Array.isArray(value), code);
  assert.deepEqual(Object.keys(value).sort(), [...expected].sort(), code);
}

function day(value) {
  assert.match(value || '', /^(?!0000)\d{4}-\d{2}-\d{2}$/, 'V1_CALENDAR_DAY_REQUIRED');
  const date = new Date(value + 'T00:00:00Z');
  assert.ok(Number.isFinite(date.valueOf()) && date.toISOString().slice(0, 10) === value, 'V1_CALENDAR_DAY_REQUIRED');
  return value;
}

function datetime(value, code) {
  // The Deadline DTO uses datetime, not AwareDatetime. SQLite can serialize
  // UTC storage without an offset; the API's docket summary is explicitly aware.
  assert.match(value || '', /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$/, code);
  day(value.slice(0, 10));
  assert.ok(Number.isFinite(Date.parse(value)), code);
}

function text(value, maximum = 255) {
  assert.ok(typeof value === 'string' && value === value.trim() && value.length > 0 && value.length <= maximum,
    'V1_CALENDAR_SCALAR_REQUIRED');
  return value;
}

function scopeOf({ sourceSha, companyId, ownerMembershipId, memberMembershipId, day: targetDay }) {
  assert.match(sourceSha || '', /^[a-f0-9]{40}$/, 'V1_CALENDAR_SOURCE_REQUIRED');
  for (const value of [companyId, ownerMembershipId, memberMembershipId]) v1Identity(value);
  assert.notEqual(ownerMembershipId, memberMembershipId, 'V1_CALENDAR_DISTINCT_MEMBER_REQUIRED');
  return { sourceSha, companyId, ownerMembershipId, memberMembershipId, day: day(targetDay) };
}

// The transport owner attaches the actual dispatched request and normally
// authenticated actor. These local validators never turn plan data into ACKs.
function acknowledged(scope, envelope, membershipId, expected, status) {
  const { request, actor, response } = envelope || {};
  assert.deepEqual(actor, { companyId: scope.companyId, membershipId }, 'V1_CALENDAR_ACK_ACTOR_MISMATCH');
  assert.equal(request?.method, expected.method, 'V1_CALENDAR_ACK_METHOD_MISMATCH');
  assert.equal(request?.route, expected.route, 'V1_CALENDAR_ACK_ROUTE_MISMATCH');
  assert.deepEqual(request.query, expected.query, 'V1_CALENDAR_ACK_QUERY_MISMATCH');
  if (Object.hasOwn(expected, 'body') || expected.method === 'GET') {
    assert.deepEqual(request.body, expected.body, 'V1_CALENDAR_ACK_BODY_MISMATCH');
  }
  assert.equal(response?.status, status, 'V1_CALENDAR_ACK_STATUS_MISMATCH');
  assert.equal(response.releaseSha, scope.sourceSha, 'V1_CALENDAR_ACK_SOURCE_MISMATCH');
  assert.match(response.requestId || '', /^[A-Za-z0-9_.:-]{1,160}$/, 'V1_CALENDAR_ACK_ID_REQUIRED');
  assert.ok(response.value && typeof response.value === 'object' && !Array.isArray(response.value), 'V1_CALENDAR_ACK_DTO_REQUIRED');
  return response;
}

function distinct(values, code) {
  assert.equal(new Set(values).size, values.length, code);
}

function creatorIdentity(family, value, companyId) {
  if (family === 'trademark') {
    const { application, docket, asset } = value;
    const docketId = v1Identity(docket?.id);
    assert.equal(docket.company_id, companyId, 'V1_CALENDAR_CREATOR_TENANT_MISMATCH');
    assert.equal(docket.record_type, creators.trademark.type, 'V1_CALENDAR_CREATOR_TYPE_MISMATCH');
    assert.equal(application?.docket_id, docketId, 'V1_CALENDAR_CREATOR_DOCKET_MISMATCH');
    assert.equal(v1Identity(application.asset_id), v1Identity(asset?.id), 'V1_CALENDAR_CREATOR_ASSET_MISMATCH');
    return { recordId: v1Identity(application.id), docketId };
  }
  if (family === 'patent') assert.equal(value.record_kind, creators.patent.type, 'V1_CALENDAR_CREATOR_TYPE_MISMATCH');
  if (family === 'design') assert.equal(value.facts?.details?.domain, family, 'V1_CALENDAR_CREATOR_TYPE_MISMATCH');
  return { recordId: v1Identity(value.id), docketId: v1Identity(value.docket_id) };
}

function uniqueRow(rows, id, code) {
  assert.ok(Array.isArray(rows) && rows.length <= 128, code);
  const matches = rows.filter(row => row?.id === id);
  assert.equal(matches.length, 1, code);
  return matches[0];
}

function currentSelection(scope, spec, workspace, docketId) {
  assert.equal(workspace.docket_id, docketId, 'V1_CALENDAR_WORKSPACE_DOCKET_MISMATCH');
  assert.equal(workspace.automation_state, 'explicit_confirmation_only');
  for (const [values, expected, code] of [
    [workspace.eligible_rule_version_ids, spec.ruleVersionId, 'V1_CALENDAR_RULE_NOT_SELECTED'],
    [workspace.eligible_responsible_membership_ids, scope.ownerMembershipId, 'V1_CALENDAR_OWNER_NOT_ELIGIBLE'],
  ]) {
    assert.ok(Array.isArray(values) && values.length <= 128, code);
    values.forEach(value => v1Identity(value));
    assert.equal(values.filter(value => value === expected).length, 1, code);
  }
  const rule = uniqueRow(workspace.rules, spec.ruleVersionId, 'V1_CALENDAR_ACTIVE_RULE_REQUIRED');
  const calendar = uniqueRow(workspace.calendars, spec.calendarVersionId, 'V1_CALENDAR_ACTIVE_CALENDAR_REQUIRED');
  assert.equal(rule.rule_kind, 'deadline');
  assert.equal(rule.right_kind, spec.family, 'V1_CALENDAR_RULE_FAMILY_MISMATCH');
  assert.equal(rule.definition?.deadline_kind, 'legal_deadline');
  assert.equal(rule.source_hash, spec.ruleSourceHash, 'V1_CALENDAR_RULE_SOURCE_MISMATCH');
  assert.equal(calendar.source_hash, spec.calendarSourceHash, 'V1_CALENDAR_WORKING_SOURCE_MISMATCH');
  for (const item of [rule, calendar]) {
    assert.equal(item.status, 'active', 'V1_CALENDAR_SELECTION_INACTIVE');
    assert.equal(item.jurisdiction, spec.jurisdiction, 'V1_CALENDAR_JURISDICTION_MISMATCH');
    const from = day(item.effective_from), until = item.effective_until === null ? null : day(item.effective_until);
    for (const when of [spec.baseDate, scope.day]) {
      assert.ok(from <= when && (until === null || when <= until), 'V1_CALENDAR_SELECTION_OUTSIDE_EFFECTIVE_DATES');
    }
  }
  return { sourceVersion: text(rule.source_record_id, 120), engine: text(rule.engine_compatibility, 80),
    citation: text(rule.definition.rule_citation, 512), trigger: text(rule.definition.trigger_kind, 80),
    calendarSourceHash: calendar.source_hash };
}

function deadlineFacts(value, target, scope) {
  assert.equal(value.docket_id, target.docketId, 'V1_CALENDAR_DEADLINE_DOCKET_MISMATCH');
  assert.equal(value.rule_version_id, target.proposalRequest.body.rule_version_id, 'V1_CALENDAR_DEADLINE_RULE_MISMATCH');
  assert.equal(value.calendar_version_id, target.proposalRequest.body.calendar_version_id, 'V1_CALENDAR_DEADLINE_CALENDAR_MISMATCH');
  assert.equal(value.base_date, target.proposalRequest.body.base_date, 'V1_CALENDAR_DEADLINE_BASE_MISMATCH');
  assert.equal(value.result_on, scope.day, 'V1_CALENDAR_DEADLINE_DAY_MISMATCH');
  assert.equal(value.title, target.proposalRequest.body.title);
  assert.equal(value.deadline_kind, 'legal_deadline');
  assert.equal(value.date_precision, 'date');
  assert.equal(value.certainty, 'certain');
  assert.equal(value.is_critical, false);
  assert.equal(value.trigger_kind, target.selection.trigger);
  assert.equal(value.source_version, target.selection.sourceVersion);
  assert.equal(value.engine_version, target.selection.engine);
  assert.equal(value.rule_citation, target.selection.citation);
  assert.equal(value.calculation_inputs?.rule_version_id, value.rule_version_id, 'V1_CALENDAR_CALCULATION_RULE_MISMATCH');
  assert.equal(value.calculation_inputs.calendar?.calendar_version_id, value.calendar_version_id, 'V1_CALENDAR_CALCULATION_CALENDAR_MISMATCH');
  assert.equal(value.calculation_inputs.calendar.source_hash, target.selection.calendarSourceHash, 'V1_CALENDAR_CALCULATION_SOURCE_MISMATCH');
  assert.equal(value.calculation_inputs.base_date, value.base_date, 'V1_CALENDAR_CALCULATION_BASE_MISMATCH');
  assert.ok(Array.isArray(value.calculation_trace) && value.calculation_trace.length <= 128, 'V1_CALENDAR_CALCULATION_TRACE_REQUIRED');
  assert.deepEqual(value.calculation_trace.at(-1), { operation: 'result', date: scope.day }, 'V1_CALENDAR_CALCULATION_RESULT_MISMATCH');
  for (const field of ['trigger_event_id', 'supersedes_deadline_id', 'override_reason', 'override_evidence_ref', 'completed_evidence_ref']) {
    assert.equal(value[field], null, 'V1_CALENDAR_UNMODIFIED_DEADLINE_REQUIRED');
  }
}

/** Derive the two finite owner commands only from the held typed ACK chain. */
export function prepareV1CalendarDeadline(scopeInput, spec, { creator, matter, link, workspace }) {
  const scope = scopeOf(scopeInput), { family } = spec;
  assert.ok(Object.hasOwn(creators, family), 'V1_CALENDAR_FAMILY_REQUIRED');
  const baseDate = day(spec.baseDate);
  assert.ok(baseDate <= scope.day, 'V1_CALENDAR_BASE_AFTER_RESULT');
  assert.match(spec.jurisdiction || '', /^[A-Z]{2}$/);
  for (const hash of [spec.ruleSourceHash, spec.calendarSourceHash]) assert.match(hash || '', sourceHash);
  const owner = scope.ownerMembershipId;
  const creatorAck = acknowledged(scope, creator, owner, { method: 'POST', route: creators[family].route }, 201);
  const { recordId, docketId } = creatorIdentity(family, creatorAck.value, scope.companyId);
  const matterAck = acknowledged(scope, matter, owner, { method: 'POST', route: '/api/matters/' }, 200);
  const matterId = v1Identity(matterAck.value.id);
  distinct([recordId, docketId, matterId], 'V1_CALENDAR_DISTINCT_PARENT_IDENTITY_REQUIRED');
  assert.equal(matterAck.value.company_id, scope.companyId, 'V1_CALENDAR_MATTER_TENANT_MISMATCH');
  assert.equal(matterAck.value.is_active, true);
  assert.ok(['intake', 'active', 'on_hold'].includes(matterAck.value.status), 'V1_CALENDAR_MATTER_NOT_OPERATIONAL');
  const matterTitle = text(matterAck.value.title), matterCode = text(matterAck.value.matter_code);
  const prefix = '/api/ip/dockets/' + docketId;
  const linkAck = acknowledged(scope, link, owner, { method: 'POST', route: prefix + '/matter-links' }, 201);
  const edge = linkAck.value;
  v1Identity(edge.id);
  assert.equal(edge.company_id, scope.companyId);
  assert.equal(edge.docket_id, docketId, 'V1_CALENDAR_LINK_DOCKET_MISMATCH');
  assert.equal(edge.matter_id, matterId, 'V1_CALENDAR_LINK_MATTER_MISMATCH');
  assert.equal(edge.relation_role, 'operational');
  assert.equal(edge.source, 'manual');
  assert.equal(edge.retired_at, null);
  assert.equal(edge.created_by_membership_id, owner, 'V1_CALENDAR_LINK_ACTOR_MISMATCH');
  assert.equal(link.request.body?.matter_id, matterId, 'V1_CALENDAR_LINK_MATTER_MISMATCH');
  assert.equal(link.request.body?.relation_role, 'operational');
  const workspaceAck = acknowledged(scope, workspace, owner, { method: 'GET', route: prefix + '/deadline-workspace' }, 200);
  const ruleVersionId = v1Identity(spec.ruleVersionId), calendarVersionId = v1Identity(spec.calendarVersionId);
  const selection = currentSelection(scope, spec, workspaceAck.value, docketId);
  const ackIds = [creatorAck.requestId, matterAck.requestId, linkAck.requestId, workspaceAck.requestId];
  distinct(ackIds, 'V1_CALENDAR_DUPLICATE_ACK');
  const proposalRequest = { method: 'POST', route: prefix + '/deadlines', body: {
    title: text(spec.title), rule_version_id: ruleVersionId, calendar_version_id: calendarVersionId,
    base_date: baseDate, base_date_certainty: 'certain', date_precision: 'date', is_critical: false,
  } };
  const target = { docketId, proposalRequest, selection };
  return {
    proposalRequest: structuredClone(proposalRequest),
    acceptProposal(proposal) {
      const proposalAck = acknowledged(scope, proposal, owner, proposalRequest, 201);
      deadlineFacts(proposalAck.value, target, scope);
      const proposalId = v1Identity(proposalAck.value.id);
      const proposalReceipts = [...ackIds, proposalAck.requestId];
      distinct(proposalReceipts, 'V1_CALENDAR_DUPLICATE_ACK');
      assert.equal(proposalAck.value.state, 'candidate');
      assert.equal(proposalAck.value.version, 1);
      assert.equal(proposalAck.value.matter_deadline_id, null);
      assert.equal(proposalAck.value.confirmed_at, null);
      assert.deepEqual(proposalAck.value.responsibilities, []);
      const confirmationRequest = { method: 'POST', route: '/api/ip/deadlines/' + proposalId + '/confirm', body: {
        expected_version: proposalAck.value.version, responsibilities: [{ membership_id: owner, role: 'primary', accepted: true }],
        reminder_offsets_days: [],
      } };
      return {
        confirmationRequest: structuredClone(confirmationRequest),
        acceptConfirmation(confirmation) {
          const confirmed = acknowledged(scope, confirmation, owner, confirmationRequest, 200);
          const value = confirmed.value;
          deadlineFacts(value, target, scope);
          assert.equal(value.id, proposalId, 'V1_CALENDAR_CONFIRMED_PROPOSAL_MISMATCH');
          assert.equal(value.state, 'confirmed');
          assert.equal(value.version, confirmationRequest.body.expected_version + 1, 'V1_CALENDAR_CONFIRMATION_VERSION_MISMATCH');
          const matterDeadlineId = v1Identity(value.matter_deadline_id);
          distinct([proposalId, matterDeadlineId], 'V1_CALENDAR_PROJECTION_IDENTITY_MISMATCH');
          datetime(value.confirmed_at, 'V1_CALENDAR_CONFIRMED_AT_REQUIRED');
          assert.ok(Array.isArray(value.responsibilities) && value.responsibilities.length === 1, 'V1_CALENDAR_PRIMARY_REQUIRED');
          const [primary] = value.responsibilities;
          v1Identity(primary.id);
          assert.equal(primary.membership_id, owner, 'V1_CALENDAR_PRIMARY_OWNER_MISMATCH');
          assert.equal(primary.role, 'primary');
          assert.equal(primary.effective_until, null);
          datetime(primary.accepted_at, 'V1_CALENDAR_PRIMARY_ACCEPTED_AT_REQUIRED');
          const receipts = Object.freeze([...proposalReceipts, confirmed.requestId]);
          distinct(receipts, 'V1_CALENDAR_DUPLICATE_ACK');
          const proof = { scope: Object.freeze(scope), family, recordId, docketId, matterId, matterTitle, matterCode,
            title: proposalRequest.body.title, proposalId, matterDeadlineId, version: value.version, receipts,
            ruleVersionId, calendarVersionId, baseDate };
          Object.defineProperty(proof, confirmationProof, { value: true });
          return Object.freeze(proof);
        },
      };
    },
  };
}

/** Return only the three full rows and actual member-visible docket summaries. */
export function validateV1CalendarReadback(scopeInput, entries, calendar) {
  const scope = scopeOf(scopeInput), member = scope.memberMembershipId;
  assert.ok(Array.isArray(entries) && entries.length === families.length, 'V1_CALENDAR_THREE_FAMILIES_REQUIRED');
  const proofs = entries.map(entry => entry.confirmation);
  for (const proof of proofs) {
    assert.equal(proof?.[confirmationProof], true, 'V1_CALENDAR_HELD_CONFIRMATION_REQUIRED');
    assert.deepEqual(proof.scope, scope, 'V1_CALENDAR_CONFIRMATION_SCOPE_MISMATCH');
  }
  assert.deepEqual(proofs.map(proof => proof.family).sort(), families, 'V1_CALENDAR_THREE_FAMILIES_REQUIRED');
  for (const key of ['recordId', 'docketId', 'matterId', 'proposalId', 'matterDeadlineId']) {
    distinct(proofs.map(proof => proof[key]), 'V1_CALENDAR_DISTINCT_FAMILY_IDENTITY_REQUIRED');
  }
  const feed = acknowledged(scope, calendar, member, { method: 'GET', route: '/api/calendar/events',
    query: { from: scope.day, to: scope.day } }, 200);
  keys(feed.value, ['range_from', 'range_to', 'events'], 'V1_CALENDAR_FEED_SHAPE_MISMATCH');
  assert.equal(feed.value.range_from, scope.day);
  assert.equal(feed.value.range_to, scope.day);
  const ids = [feed.requestId, ...proofs.flatMap(proof => proof.receipts)];
  const sources = entries.map(({ confirmation: proof, memberDocket }) => {
    const summary = acknowledged(scope, memberDocket, member, { method: 'GET', route: '/api/ip/dockets/' + proof.docketId + '/summary' }, 200);
    ids.push(summary.requestId);
    const docket = summary.value;
    keys(docket, docketFields, 'V1_CALENDAR_DOCKET_SUMMARY_SHAPE_MISMATCH');
    assert.equal(docket.id, proof.docketId);
    assert.equal(docket.company_id, scope.companyId, 'V1_CALENDAR_MEMBER_DOCKET_TENANT_MISMATCH');
    assert.equal(docket.matter_id, proof.matterId, 'V1_CALENDAR_MEMBER_DOCKET_MATTER_MISMATCH');
    assert.equal(docket.record_type, creators[proof.family].type, 'V1_CALENDAR_MEMBER_DOCKET_TYPE_MISMATCH');
    assert.equal(docket.is_active, true);
    text(docket.title);
    text(docket.status, 64);
    assert.ok(docket.primary_identifier === null || typeof docket.primary_identifier === 'string');
    for (const number of [docket.lifecycle_version, docket.access_policy_version, docket.current_version]) {
      assert.ok(Number.isSafeInteger(number) && number >= 0);
    }
    v1Version(docket.updated_at, 'task');
    const event = uniqueRow(feed.value.events, 'deadline:' + proof.matterDeadlineId, 'V1_CALENDAR_EXACT_EVENT_REQUIRED');
    keys(event, eventFields, 'V1_CALENDAR_EVENT_SHAPE_MISMATCH');
    assert.equal(event.kind, 'deadline');
    assert.equal(event.display_type, 'filing_deadline');
    assert.equal(event.status, 'open');
    assert.equal(event.occurs_on, scope.day, 'V1_CALENDAR_EVENT_DAY_MISMATCH');
    assert.equal(event.ip_docket_id, proof.docketId, 'V1_CALENDAR_EVENT_DOCKET_MISMATCH');
    assert.equal(event.matter_id, proof.matterId, 'V1_CALENDAR_EVENT_MATTER_MISMATCH');
    assert.equal(event.matter_title, proof.matterTitle);
    assert.equal(event.matter_code, proof.matterCode);
    assert.equal(event.title, proof.title);
    assert.equal(event.detail, 'ip_deadline · legal_deadline');
    for (const field of eventFields.slice(-7)) assert.equal(event[field], null, 'V1_CALENDAR_EVENT_HEARING_FACT_REFUSED');
    return { family: proof.family, docket: structuredClone(docket), event: structuredClone(event),
      confirmation: { id: proof.proposalId, docketId: proof.docketId, matterId: proof.matterId,
        matterDeadlineId: proof.matterDeadlineId, resultOn: scope.day, version: proof.version,
        baseDate: proof.baseDate, ruleVersionId: proof.ruleVersionId, calendarVersionId: proof.calendarVersionId } };
  });
  distinct(ids, 'V1_CALENDAR_DUPLICATE_ACK');
  return { day: scope.day, sources };
}
