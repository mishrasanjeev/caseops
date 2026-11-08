import assert from 'node:assert/strict';
import test from 'node:test';
import { prepareV1CalendarDeadline, validateV1CalendarReadback } from './v1-calendar-acknowledgements.mjs';

const id = n => '01000000-0000-4000-8000-' + String(n).padStart(12, '0');
const time = '2026-11-08T12:00:00.000000Z';
const types = { patent: 'patent_family', design: 'design_intake', trademark: 'trademark' };
const routes = { patent: '/api/ip/patents/families', design: '/api/ip/specialist/records', trademark: '/api/ip/trademark-applications/manual' };

function fixture() {
  const scope = { sourceSha: 'a'.repeat(40), companyId: id(1), ownerMembershipId: id(2), memberMembershipId: id(3), day: '2026-11-17' };
  let sequence = 0;
  const ack = (method, route, status, value, { member = false, body, query } = {}) => ({
    request: { method, route, body, query },
    actor: { companyId: scope.companyId, membershipId: member ? scope.memberMembershipId : scope.ownerMembershipId },
    response: { status, releaseSha: scope.sourceSha, requestId: 'qa-http-' + ++sequence, value },
  });
  const entries = Object.keys(routes).map((family, index) => {
    const base = index * 20 + 10;
    const [recordId, docketId, matterId, linkId, ruleId, proposalId, deadlineId, responsibilityId, assetId]
      = Array.from({ length: 9 }, (_, offset) => id(base + offset));
    const calendarId = id(500), title = 'Synthetic ' + family + ' deadline';
    const matterTitle = 'Synthetic ' + family + ' Matter', matterCode = 'QA-CAL-' + index;
    const prefix = '/api/ip/dockets/' + docketId;
    const spec = { family, title, baseDate: '2026-11-13', jurisdiction: 'IN', ruleVersionId: ruleId, calendarVersionId: calendarId,
      ruleSourceHash: String(index + 1).repeat(64), calendarSourceHash: 'c'.repeat(64) };
    const docket = { id: docketId, company_id: scope.companyId, matter_id: matterId, record_type: types[family],
      title: 'Synthetic ' + family + ' docket', primary_identifier: null, status: 'active', is_active: true,
      lifecycle_version: 0, access_policy_version: 1, current_version: 1, updated_at: time };
    const creatorValue = family === 'trademark'
      ? { application: { id: recordId, docket_id: docketId, asset_id: assetId }, docket: { ...docket, matter_id: null }, asset: { id: assetId } }
      : { id: recordId, docket_id: docketId, asset_id: assetId, ...(family === 'patent'
        ? { record_kind: 'patent_family' } : { facts: { details: { domain: 'design' } } }) };
    const proposalBody = { title, rule_version_id: ruleId, calendar_version_id: calendarId, base_date: spec.baseDate,
      base_date_certainty: 'certain', date_precision: 'date', is_critical: false };
    const confirmationBody = { expected_version: 1,
      responsibilities: [{ membership_id: scope.ownerMembershipId, role: 'primary', accepted: true }], reminder_offsets_days: [] };
    const proposalValue = { id: proposalId, docket_id: docketId, rule_version_id: ruleId, calendar_version_id: calendarId,
      matter_deadline_id: null, supersedes_deadline_id: null, trigger_event_id: null, deadline_kind: 'legal_deadline',
      title, trigger_kind: 'synthetic_trigger', base_date: spec.baseDate, date_precision: 'date', certainty: 'certain', result_on: scope.day,
      calculation_inputs: { rule_version_id: ruleId, base_date: spec.baseDate,
        calendar: { calendar_version_id: calendarId, source_hash: spec.calendarSourceHash } },
      calculation_trace: [{ operation: 'select_trigger', trigger_kind: 'synthetic_trigger', base_date: spec.baseDate },
        { operation: 'result', date: scope.day }], explanation: 'Synthetic fixture', rule_citation: 'Synthetic rule', engine_version: 'caseops-ip-deadline-v1',
      source_version: 'fixture-' + family, is_critical: false, state: 'candidate', version: 1, confirmed_at: null,
      override_reason: null, override_evidence_ref: null, completed_evidence_ref: null, created_at: time, updated_at: time, responsibilities: [] };
    const event = { id: 'deadline:' + deadlineId, kind: 'deadline', display_type: 'filing_deadline', occurs_on: scope.day, title,
      matter_id: matterId, matter_title: matterTitle, matter_code: matterCode, status: 'open', ip_docket_id: docketId,
      detail: 'ip_deadline · legal_deadline', court_label: null, court_identity: null, forum_display_order: null,
      hearing_time: null, time_status: null, session_label: null, timezone: null };
    const parents = {
      creator: ack('POST', routes[family], 201, creatorValue),
      matter: ack('POST', '/api/matters/', 200, { id: matterId, company_id: scope.companyId, title: matterTitle, matter_code: matterCode,
        is_active: true, status: 'intake' }),
      link: ack('POST', prefix + '/matter-links', 201, { id: linkId, company_id: scope.companyId, docket_id: docketId, matter_id: matterId,
        relation_role: 'operational', retired_at: null, source: 'manual', created_by_membership_id: scope.ownerMembershipId },
      { body: { matter_id: matterId, relation_role: 'operational', expected_docket_updated_at: time } }),
      workspace: ack('GET', prefix + '/deadline-workspace', 200, { docket_id: docketId, automation_state: 'explicit_confirmation_only',
        eligible_rule_version_ids: [ruleId], eligible_responsible_membership_ids: [scope.ownerMembershipId], deadlines: [], exceptions: [], governance: {},
        rules: [{ id: ruleId, rule_kind: 'deadline', right_kind: family, status: 'active', jurisdiction: 'IN', source_hash: spec.ruleSourceHash,
          source_record_id: 'fixture-' + family, engine_compatibility: 'caseops-ip-deadline-v1', effective_from: '2026-01-01', effective_until: null,
          definition: { deadline_kind: 'legal_deadline', rule_citation: 'Synthetic rule', trigger_kind: 'synthetic_trigger' } }],
        calendars: [{ id: calendarId, status: 'active', jurisdiction: 'IN', source_hash: spec.calendarSourceHash,
          effective_from: '2026-01-01', effective_until: '2026-12-31' }] }),
    };
    const proposal = ack('POST', prefix + '/deadlines', 201, proposalValue, { body: proposalBody });
    const confirmation = ack('POST', '/api/ip/deadlines/' + proposalId + '/confirm', 200,
      { ...proposalValue, state: 'confirmed', version: 2, matter_deadline_id: deadlineId, confirmed_at: time,
        responsibilities: [{ id: responsibilityId, membership_id: scope.ownerMembershipId, role: 'primary', accepted_at: time, effective_until: null }] },
    { body: confirmationBody });
    const memberDocket = ack('GET', prefix + '/summary', 200, docket, { member: true });
    return { spec, parents, proposal, confirmation, memberDocket, event, deadlineId };
  });
  const calendar = ack('GET', '/api/calendar/events', 200, {
    range_from: scope.day, range_to: scope.day, events: [entries[2].event, ...entries.slice(0, 2).map(item => item.event)],
  }, { member: true, query: { from: scope.day, to: scope.day } });
  return { scope, entries, calendar };
}

function prepare(scope, entry) {
  return prepareV1CalendarDeadline(scope, entry.spec, entry.parents);
}
function confirmed(scope, entry) {
  return prepare(scope, entry).acceptProposal(entry.proposal).acceptConfirmation(entry.confirmation);
}
function readback(scenario) {
  return validateV1CalendarReadback(scenario.scope, scenario.entries.map(entry => ({
    confirmation: confirmed(scenario.scope, entry), memberDocket: entry.memberDocket,
  })), scenario.calendar);
}

test('derives the owner commands from each exact current parent chain and retains full actual member rows', () => {
  const f = fixture();
  for (const entry of f.entries) {
    const pending = prepare(f.scope, entry);
    assert.deepEqual(pending.proposalRequest, { method: 'POST', route: entry.proposal.request.route, body: entry.proposal.request.body });
    const proposed = pending.acceptProposal(entry.proposal);
    assert.deepEqual(proposed.confirmationRequest, { method: 'POST', route: entry.confirmation.request.route, body: entry.confirmation.request.body });
  }
  const result = readback(f);
  assert.equal(result.day, f.scope.day);
  assert.deepEqual(result.sources.map(source => source.family), Object.keys(routes));
  assert.deepEqual(result.sources.map(source => source.event), f.entries.map(entry => entry.event));
  assert.deepEqual(result.sources.map(source => source.docket), f.entries.map(entry => entry.memberDocket.response.value));
  assert.deepEqual(result.sources.map(source => source.confirmation.matterDeadlineId), f.entries.map(entry => entry.deadlineId));
  result.sources[0].event.title = 'Changed later';
  assert.notEqual(f.entries[0].event.title, 'Changed later');
});

const parentFailures = [
  ['wrong creator endpoint', e => { e.parents.creator.request.route = routes.design; }, /ACK_ROUTE_MISMATCH/],
  ['wrong creator status', e => { e.parents.creator.response.status = 200; }, /ACK_STATUS_MISMATCH/],
  ['creator wrong family', e => { e.parents.creator.response.value.record_kind = 'patent_application'; }, /CREATOR_TYPE_MISMATCH/],
  ['foreign linked Matter', e => { e.parents.matter.response.value.company_id = id(700); }, /MATTER_TENANT_MISMATCH/],
  ['link points to another Matter', e => { e.parents.link.response.value.matter_id = id(700); }, /LINK_MATTER_MISMATCH/],
  ['link receipt is owned by another actor', e => { e.parents.link.response.value.created_by_membership_id = id(700); }, /LINK_ACTOR_MISMATCH/],
  ['a present rule lacks active selection', e => { e.parents.workspace.response.value.eligible_rule_version_ids = []; }, /RULE_NOT_SELECTED/],
  ['a selected rule is retired', e => { e.parents.workspace.response.value.rules[0].status = 'retired'; }, /SELECTION_INACTIVE/],
  ['working calendar jurisdiction is wrong', e => { e.parents.workspace.response.value.calendars[0].jurisdiction = 'US'; }, /JURISDICTION_MISMATCH/],
  ['an invalid calendar date', e => { e.parents.workspace.response.value.calendars[0].effective_from = '2026-02-30'; }, /DAY_REQUIRED/],
  ['a retained calendar has expired before the result', e => { e.parents.workspace.response.value.calendars[0].effective_until = '2026-11-16'; }, /OUTSIDE_EFFECTIVE_DATES/],
  ['a calendar with another source hash', e => { e.parents.workspace.response.value.calendars[0].source_hash = 'd'.repeat(64); }, /WORKING_SOURCE_MISMATCH/],
  ['the mobile member is eligible but the owner is not', e => { e.parents.workspace.response.value.eligible_responsible_membership_ids = [id(3)]; }, /OWNER_NOT_ELIGIBLE/],
  ['a duplicate matched calendar', e => { e.parents.workspace.response.value.calendars.push(e.parents.workspace.response.value.calendars[0]); }, /ACTIVE_CALENDAR_REQUIRED/],
  ['two stages share one ACK ID', e => { e.parents.workspace.response.requestId = e.parents.link.response.requestId; }, /DUPLICATE_ACK/],
];
for (const [name, mutate, reason] of parentFailures) {
  test('refuses ' + name, () => {
    const f = fixture(), e = f.entries[0];
    mutate(e);
    assert.throws(() => prepare(f.scope, e), reason);
  });
}

test('checks Design facts and the two Trademark docket witnesses', () => {
  const f = fixture(), design = f.entries[1], trademark = f.entries[2];
  design.parents.creator.response.value.facts.details.domain = 'copyright';
  assert.throws(() => prepare(f.scope, design), /CREATOR_TYPE_MISMATCH/);
  trademark.parents.creator.response.value.application.docket_id = id(700);
  assert.throws(() => prepare(f.scope, trademark), /CREATOR_DOCKET_MISMATCH/);
});

const confirmationFailures = [
  ['proposal repeats an earlier ACK before deriving confirmation', e => {
    e.proposal.response.requestId = e.parents.workspace.response.requestId;
  }, /DUPLICATE_ACK/],
  ['proposal for a different rule', e => { e.proposal.response.value.rule_version_id = id(700); }, /DEADLINE_RULE_MISMATCH/],
  ['proposal for a different day', e => { e.proposal.response.value.result_on = '2026-11-16'; }, /DEADLINE_DAY_MISMATCH/],
  ['proposal calculation used a different calendar source', e => {
    e.proposal.response.value.calculation_inputs.calendar.source_hash = 'f'.repeat(64);
  }, /CALCULATION_SOURCE_MISMATCH/],
  ['proposal calculation trace gives another result', e => {
    e.proposal.response.value.calculation_trace.at(-1).date = '2026-11-16';
  }, /CALCULATION_RESULT_MISMATCH/],
  ['proposal sent with changed body', e => { e.proposal.request.body.is_critical = true; }, /ACK_BODY_MISMATCH/],
  ['confirmation addressed by a guessed proposal ID', e => { e.confirmation.request.route = '/api/ip/deadlines/' + id(700) + '/confirm'; }, /ACK_ROUTE_MISMATCH/],
  ['confirmation submitted by the mobile member', e => { e.confirmation.actor.membershipId = id(3); }, /ACK_ACTOR_MISMATCH/],
  ['confirmation changes the proposal version', e => { e.confirmation.response.value.version = 3; }, /CONFIRMATION_VERSION_MISMATCH/],
  ['confirmation supplies a foreign proposal ID', e => { e.confirmation.response.value.id = id(700); }, /CONFIRMED_PROPOSAL_MISMATCH/],
  ['confirmation binds an unaccepted primary', e => { e.confirmation.response.value.responsibilities[0].accepted_at = null; }, /PRIMARY_ACCEPTED_AT_REQUIRED/],
  ['confirmation promotes the proposal to projection identity', e => { e.confirmation.response.value.matter_deadline_id = e.proposal.response.value.id; }, /PROJECTION_IDENTITY_MISMATCH/],
  ['confirmation adds a reminder request', e => { e.confirmation.request.body.reminder_offsets_days.push(1); }, /ACK_BODY_MISMATCH/],
];
for (const [name, mutate, reason] of confirmationFailures) {
  test('refuses ' + name, () => {
    const f = fixture(), e = f.entries[0];
    mutate(e);
    assert.throws(() => confirmed(f.scope, e), reason);
  });
}

const readbackFailures = [
  ['owner Calendar read in place of member read', f => { f.calendar.actor.membershipId = f.scope.ownerMembershipId; }, /ACK_ACTOR_MISMATCH/],
  ['a wider Calendar request', f => { f.calendar.request.query.to = '2026-11-18'; }, /ACK_QUERY_MISMATCH/],
  ['raw confirmation UUID as Calendar row ID', f => { f.entries[0].event.id = f.entries[0].deadlineId; }, /EXACT_EVENT_REQUIRED/],
  ['duplicate exact Calendar rows', f => { f.calendar.response.value.events.push(f.entries[0].event); }, /EXACT_EVENT_REQUIRED/],
  ['right Calendar ID but wrong docket', f => { f.entries[0].event.ip_docket_id = id(700); }, /EVENT_DOCKET_MISMATCH/],
  ['right Calendar ID but wrong Matter', f => { f.entries[0].event.matter_id = id(700); }, /EVENT_MATTER_MISMATCH/],
  ['right Calendar ID but wrong day', f => { f.entries[0].event.occurs_on = '2026-11-18'; }, /EVENT_DAY_MISMATCH/],
  ['member docket from another company', f => { f.entries[0].memberDocket.response.value.company_id = id(700); }, /MEMBER_DOCKET_TENANT_MISMATCH/],
  ['owner summary in place of member read', f => { f.entries[0].memberDocket.actor.membershipId = f.scope.ownerMembershipId; }, /ACK_ACTOR_MISMATCH/],
  ['member summary has the wrong family', f => { f.entries[0].memberDocket.response.value.record_type = 'trademark'; }, /MEMBER_DOCKET_TYPE_MISMATCH/],
  ['fewer than three distinct family proofs', f => { f.entries.pop(); }, /THREE_FAMILIES_REQUIRED/],
];
for (const [name, mutate, reason] of readbackFailures) {
  test('refuses ' + name, () => {
    const f = fixture();
    mutate(f);
    assert.throws(() => readback(f), reason);
  });
}

test('a serialized proof cannot stand in for a held typed confirmation', () => {
  const f = fixture(), entries = f.entries.map(e => ({ confirmation: confirmed(f.scope, e), memberDocket: e.memberDocket }));
  entries[0].confirmation = JSON.parse(JSON.stringify(entries[0].confirmation));
  assert.throws(() => validateV1CalendarReadback(f.scope, entries, f.calendar), /HELD_CONFIRMATION_REQUIRED/);
});
