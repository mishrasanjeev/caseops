import assert from 'node:assert/strict';
import { createV1CalendarHostRoutes } from './v1-calendar-host-routes.mjs';
import { grantV1IpMemberAccess } from './v1-ip-access-host.mjs';
import { producerHash, producerTimeout } from './native-producer-host.mjs';
import { validateV1CalendarReadback } from '../../apps/mobile/e2e/v1-calendar-acknowledgements.mjs';

/** All request effects consume the base phase's original budget. Confirmation
 * proofs remain in this closure until actual member summaries and feed agree. */
export async function produceV1CalendarCatalogue(host, scope, families, {
  memberCredentialEvidence, charge, onAcknowledged, remaining, now = Date.now,
}) {
  assert.deepEqual(families.map(x => x.spec.family).sort(), ['design', 'patent', 'trademark']);
  assert.equal(typeof charge, 'function'); assert.equal(typeof onAcknowledged, 'function');
  producerTimeout(remaining());
  const owner = host.getActorIdentity('owner');
  assert.equal(owner?.company?.id, scope.companyId); assert.equal(owner?.membership?.id, scope.ownerMembershipId);
  const ack = (key, method, route, response) => {
    assert.equal(response.releaseSha, scope.sourceSha, 'V1_CALENDAR_SERVING_SOURCE_CHANGED');
    onAcknowledged({ key, method, route, status: response.status, requestId: response.requestId, releaseSha: response.releaseSha });
  };
  const call = async (key, actor, request) => {
    const timeoutMs = producerTimeout(remaining()); charge({ key, method: request.method, route: request.route });
    const response = await host.request({ ...request, actor, producerStage: 'base', timeoutMs, automaticRetry: false });
    ack(key, request.method, request.route, response);
    return { actor: { companyId: scope.companyId, membershipId: actor === 'owner' ? scope.ownerMembershipId : scope.memberMembershipId }, request, response };
  };
  const currentMember = await host.login('member', memberCredentialEvidence, {
    remaining, charge: request => charge({ ...request, key: 'calendar-member-' + request.key }),
    onAcknowledged: response => onAcknowledged({ ...response, key: 'calendar-member-' + response.key }),
  });
  assert.equal(currentMember?.company?.id, scope.companyId);
  assert.equal(currentMember?.membership?.id, scope.memberMembershipId);
  const member = host.getActorIdentity('member');
  assert.equal(member?.company?.id, scope.companyId); assert.equal(member?.membership?.id, scope.memberMembershipId);
  const entries = [];
  for (const { spec, parents } of families) {
    const { family } = spec;
    if (family !== 'trademark') {
      const docketId = parents.creator.response.value.docket_id;
      const panel = await call('calendar-' + family + '-panel', 'owner', { method: 'GET', route: '/api/ip/dockets/' + docketId + '/access' });
      const grant = await grantV1IpMemberAccess(host, scope, family, { ...parents, panel },
        { charge, remaining, now, onAcknowledged });
      entries.push({ family, spec, parents, grant });
    } else entries.push({ family, spec, parents });
  }
  for (const entry of entries) {
    const chain = createV1CalendarHostRoutes(scope, entry.spec, entry.parents);
    for (const phase of ['workspace', 'proposal', 'confirmation']) {
      const request = chain.nextRequest(); assert.ok(request, 'V1_CALENDAR_EXACT_NEXT_STEP_REQUIRED');
      const key = 'calendar-' + entry.family + '-' + phase;
      charge({ key, method: request.method, route: request.route });
      const response = await host.requestCalendar({ ...request, actor: 'owner', producerStage: 'base',
        timeoutMs: producerTimeout(remaining()), automaticRetry: false }, chain);
      onAcknowledged({ key, method: request.method, route: request.route, status: response.status, requestId: response.requestId, releaseSha: scope.sourceSha });
      if (phase === 'confirmation') entry.confirmation = response.projection;
      else assert.equal(response.projection, undefined);
    }
    assert.equal(chain.nextRequest(), undefined);
  }
  for (const entry of entries) {
    const route = '/api/ip/dockets/' + entry.confirmation.docketId + '/summary';
    const request = { method: 'GET', route }, key = 'calendar-' + entry.family + '-member-summary';
    let claimed = false;
    const chain = { claim(attempt) {
      assert.equal(claimed, false, 'V1_CALENDAR_MEMBER_READ_REPLAY_REFUSED');
      assert.deepEqual([attempt.stage, attempt.actor, attempt.company, attempt.membership, attempt.method, attempt.requestTarget, attempt.bodyBytes],
        ['base', 'member', scope.companyId, scope.memberMembershipId, 'GET', route, undefined]);
      claimed = true; let accepted = false;
      return { provenance: { requestDigest: producerHash(entry.confirmation.receipts.at(-1)) }, acceptResponse(response) {
        assert.equal(accepted, false, 'V1_CALENDAR_MEMBER_ACK_REPLAY_REFUSED'); accepted = true;
        return { actor: { companyId: scope.companyId, membershipId: scope.memberMembershipId }, request, response };
      } };
    } };
    charge({ key, method: 'GET', route });
    const response = await host.requestMemberDocket({ ...request, actor: 'member', producerStage: 'base',
      timeoutMs: producerTimeout(remaining()), automaticRetry: false }, chain);
    assert.equal(claimed, true); entry.memberDocket = response.projection;
    ack(key, 'GET', route, entry.memberDocket.response);
    if (entry.grant) entry.grant.acceptMemberSummary(entry.memberDocket);
  }
  const calendar = await call('calendar-member-feed', 'member', { method: 'GET', route: '/api/calendar/events', query: { from: scope.day, to: scope.day } });
  return validateV1CalendarReadback(scope, entries, calendar);
}
