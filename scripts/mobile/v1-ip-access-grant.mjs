import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import { producerTimeout } from './native-producer-host.mjs';

const creators = Object.freeze({
  patent: { route: '/api/ip/patents/families', type: 'patent_family' },
  design: { route: '/api/ip/specialist/records', type: 'design_intake' },
});
const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const panelKeys = ['docket_id', 'docket_title', 'restricted', 'access_policy_version', 'linked_matter_id', 'grants',
  'walls', 'active_internal_membership_count', 'queued_delivery_count', 'excluded_persistence'];
const grantKeys = ['id', 'subject_type', 'subject_id', 'subject_label', 'access_level', 'reason', 'effective_from',
  'expires_at', 'revoked_at', 'granted_by_membership_id', 'revoked_by_membership_id', 'record_version', 'created_at'];
const previewKeys = ['docket_id', 'access_policy_version', 'action', 'preview_token', 'affected_memberships',
  'visibility_gain_count', 'visibility_loss_count', 'queued_delivery_recheck_count', 'document_count',
  'linked_matter_id', 'linked_matter_mismatch', 'warnings', 'requires_step_up'];
const summaryKeys = ['id', 'company_id', 'matter_id', 'record_type', 'title', 'primary_identifier', 'status', 'is_active',
  'lifecycle_version', 'access_policy_version', 'current_version', 'updated_at'];
const excluded = ['portal_grants', 'access_review_campaigns', 'emergency_access_sessions'];
const initialReason = 'Initial restricted-record creator access.';
const fixtureReason = 'Synthetic native fixture: grant access to the current test member.';
const hash = value => createHash('sha256').update(value).digest('hex');

const matches = (value, regex) => typeof value === 'string' && regex.test(value);
const identity = value => matches(value, uuid);
const count = value => Number.isSafeInteger(value) && value >= 0;
const label = value => typeof value === 'string' && value.trim().length > 0 && value.length <= 255;
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
function fields(value, expected, code) {
  assert.ok(record(value) && Object.keys(value).length === expected.length
    && expected.every(key => Object.hasOwn(value, key)), code);
}

function timestamp(value, aware = false) {
  const parts = typeof value === 'string' && /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)(Z|[+-]\d{2}:\d{2})?$/.exec(value);
  if (!parts || (aware && !parts[2])) return NaN;
  return Date.parse(parts[1] + (parts[2] || 'Z'));
}

function readPanel(value, { docketId, title, matterId }, version, grantCount) {
  fields(value, panelKeys, 'V1_IP_ACL_PANEL_SHAPE');
  assert.ok(value.docket_id === docketId && value.docket_title === title && value.linked_matter_id === matterId
    && value.restricted === true && value.access_policy_version === version, 'V1_IP_ACL_PANEL_LINEAGE');
  assert.ok(Array.isArray(value.grants) && value.grants.length === grantCount
    && Array.isArray(value.walls) && value.walls.length === 0 && value.active_internal_membership_count === grantCount,
  'V1_IP_ACL_UNEXPECTED_PANEL_ACCESS');
  assert.ok(value.queued_delivery_count === 0 && isDeepStrictEqual(value.excluded_persistence, excluded),
    'V1_IP_ACL_PANEL_SCOPE');
  return value.grants;
}

function readGrant(value, subject, grantor, reason, now) {
  fields(value, grantKeys, 'V1_IP_ACL_GRANT_SHAPE');
  assert.ok(identity(value.id) && value.subject_type === 'membership' && value.subject_id === subject
    && value.granted_by_membership_id === grantor && value.access_level === 'member'
    && label(value.subject_label) && value.reason === reason && value.record_version === 0, 'V1_IP_ACL_GRANT_LINEAGE');
  assert.ok(value.expires_at === null && value.revoked_at === null && value.revoked_by_membership_id === null
    && timestamp(value.effective_from) <= now && timestamp(value.created_at) <= now, 'V1_IP_ACL_GRANT_NOT_ACTIVE');
}

/**
 * Use the current base owner panel, the admitted normal MFA ACK and the real
 * parent creator/link ACKs. sendPrivate is the exact bounded HTTPS bridge
 * after it verifies one-use gateway consumption. It must neither retain nor
 * log request bytes or preview response values. The base caller charges the
 * preceding panel read and the later member summary through its existing gate.
 */
export function createV1IpAccessGrant(scope, family, { creator, matter, link, panel, mfa }, {
  charge, remaining, now = Date.now,
}) {
  const { sourceSha, companyId, ownerMembershipId, memberMembershipId } = scope;
  assert.ok(matches(sourceSha, /^[a-f0-9]{40}$/) && [companyId, ownerMembershipId, memberMembershipId].every(identity)
    && ownerMembershipId !== memberMembershipId && Object.hasOwn(creators, family), 'V1_IP_ACL_SCOPE_REQUIRED');
  assert.ok(typeof charge === 'function' && typeof remaining === 'function', 'V1_IP_ACL_BASE_BUDGET_REQUIRED');
  const seen = new Set();
  function acknowledge(envelope, membershipId, method, route, status, bodySha256) {
    const { actor, request, response } = envelope || {};
    assert.ok(actor?.companyId === companyId && actor.membershipId === membershipId, 'V1_IP_ACL_ACK_ACTOR');
    assert.ok(request?.method === method && request.route === route && request.query === undefined
      && request.bodySha256 === bodySha256 && (method !== 'GET' || request.body === undefined)
      && (bodySha256 === undefined || request.body === undefined), 'V1_IP_ACL_ACK_REQUEST');
    assert.ok(response?.status === status && response.releaseSha === sourceSha
      && matches(response.requestId, /^[A-Za-z0-9_.:-]{1,160}$/) && !seen.has(response.requestId)
      && record(response.value), 'V1_IP_ACL_ACK_REQUIRED');
    seen.add(response.requestId);
    return response;
  }

  const ownerAck = (envelope, method, route, status, bodySha256) =>
    acknowledge(envelope, ownerMembershipId, method, route, status, bodySha256);
  const expected = creators[family];
  const created = ownerAck(creator, 'POST', expected.route, 201).value;
  assert.ok(family === 'patent' ? created.record_kind === expected.type : created.facts?.details?.domain === family,
    'V1_IP_ACL_CREATOR_TYPE');
  const { docket_id: docketId, id: recordId } = created;
  const title = created.facts?.title;
  const createdMatter = ownerAck(matter, 'POST', '/api/matters/', 200).value;
  const matterId = createdMatter.id;
  assert.ok([recordId, docketId, matterId].every(identity) && new Set([recordId, docketId, matterId]).size === 3
    && label(title) && createdMatter.company_id === companyId && createdMatter.is_active === true
    && ['intake', 'active', 'on_hold'].includes(createdMatter.status), 'V1_IP_ACL_CREATOR_LINEAGE');
  const prefix = '/api/ip/dockets/' + docketId;
  const edge = ownerAck(link, 'POST', prefix + '/matter-links', 201).value;
  assert.ok(identity(edge.id) && edge.company_id === companyId && edge.docket_id === docketId && edge.matter_id === matterId
    && edge.relation_role === 'operational' && edge.source === 'manual' && edge.retired_at === null
    && edge.created_by_membership_id === ownerMembershipId && link.request.body?.matter_id === matterId
    && link.request.body?.relation_role === 'operational', 'V1_IP_ACL_LINK_LINEAGE');

  const mfaAck = ownerAck(mfa, 'POST', '/api/auth/mfa/step-up', 200);
  assert.ok(mfa.request.body === undefined && mfa.request.verificationMethod === 'totp'
    && ['step_up', 'record_access_change'].includes(mfa.request.purpose), 'V1_IP_ACL_NORMAL_MFA_REQUIRED');
  fields(mfaAck.value, ['status', 'expires_at'], 'V1_IP_ACL_NORMAL_MFA_REQUIRED');
  const expiresAt = timestamp(mfaAck.value.expires_at, true);
  assert.ok(mfaAck.value.status === 'verified' && Number.isFinite(expiresAt), 'V1_IP_ACL_NORMAL_MFA_REQUIRED');

  // Both normal restricted creators seed one owner grant at version one.
  const panelAck = ownerAck(panel, 'GET', prefix + '/access', 200);
  const target = { docketId, title, matterId };
  const priorVersion = 1;
  const [prior] = readPanel(panelAck.value, target, priorVersion, 1);
  readGrant(prior, ownerMembershipId, ownerMembershipId, initialReason, now());
  const ownerGrant = structuredClone(prior);
  const payload = { action: 'grant', expected_access_policy_version: priorVersion, subject_type: 'membership',
    subject_id: memberMembershipId, reason: fixtureReason };
  let started = false;

  return async function grantMember(sendPrivate) {
    assert.ok(!started && typeof sendPrivate === 'function', 'V1_IP_ACL_PAIR_REPLAY_REFUSED');
    started = true;
    async function exchange(operation, bodyBytes, predecessor) {
      try {
        const route = prefix + '/access/' + operation;
        const timeoutMs = producerTimeout(remaining());
        assert.ok(expiresAt > now() + timeoutMs, 'V1_IP_ACL_MFA_TOO_OLD');
        const bodySha256 = hash(bodyBytes);
        charge({ key: 'ip-' + family + '-grant-' + operation, method: 'POST', route });
        let response;
        try {
          response = await sendPrivate({ actor: 'owner', method: 'POST', route, bodyBytes, timeoutMs, automaticRetry: false,
            provenance: { requestDigest: hash(predecessor), bodySha256 } });
        } catch {
          throw new Error('V1_IP_ACL_TRANSPORT_INCOMPLETE_NO_REPLAY');
        }
        return ownerAck(response, 'POST', route, 200, bodySha256);
      } finally {
        bodyBytes.fill(0);
      }
    }

    async function previewApplyBytes() {
      const { requestId, value } = await exchange('preview', Buffer.from(JSON.stringify(payload)), panelAck.requestId);
      fields(value, previewKeys, 'V1_IP_ACL_PREVIEW_SHAPE');
      assert.ok(value.docket_id === docketId && value.linked_matter_id === matterId && value.access_policy_version === priorVersion
        && value.action === 'grant' && value.requires_step_up === true && matches(value.preview_token, /^[a-f0-9]{64}$/),
      'V1_IP_ACL_PREVIEW_LINEAGE');
      assert.ok(value.visibility_gain_count === 1 && value.visibility_loss_count === 0 && value.queued_delivery_recheck_count === 0
        && count(value.document_count) && value.linked_matter_mismatch === false
        && Array.isArray(value.warnings) && value.warnings.length === 0, 'V1_IP_ACL_PREVIEW_EFFECT');
      assert.ok(Array.isArray(value.affected_memberships) && value.affected_memberships.length === 1, 'V1_IP_ACL_ONE_MEMBER_GAIN');
      const [affected] = value.affected_memberships;
      fields(affected, ['membership_id', 'label', 'before_visible', 'after_visible', 'linked_matter_visible'], 'V1_IP_ACL_PREVIEW_MEMBER_SHAPE');
      assert.ok(affected.membership_id === memberMembershipId && label(affected.label) && affected.before_visible === false
        && affected.after_visible === true && affected.linked_matter_visible === true, 'V1_IP_ACL_ONE_MEMBER_GAIN');
      return { previewId: requestId, memberLabel: affected.label,
        applyBytes: Buffer.from(JSON.stringify({ ...payload, preview_token: value.preview_token })) };
    }

    const { applyBytes, previewId, memberLabel } = await previewApplyBytes();
    const applied = await exchange('apply', applyBytes, previewId);
    const changed = applied.value;
    fields(changed, ['action', 'invalidation_operation_id', 'visibility_gain_count', 'visibility_loss_count',
      'queued_delivery_recheck_count', 'panel'], 'V1_IP_ACL_APPLY_SHAPE');
    assert.ok(changed.action === 'grant' && identity(changed.invalidation_operation_id) && changed.visibility_gain_count === 1
      && changed.visibility_loss_count === 0 && changed.queued_delivery_recheck_count === 0, 'V1_IP_ACL_APPLY_EFFECT');
    const version = priorVersion + 1;
    const grants = readPanel(changed.panel, target, version, 2);
    const unchanged = grants.find(item => item?.id === ownerGrant.id);
    assert.ok(isDeepStrictEqual(unchanged, ownerGrant), 'V1_IP_ACL_OWNER_GRANT_CHANGED');
    const added = grants.find(item => item?.id !== ownerGrant.id);
    readGrant(added, memberMembershipId, ownerMembershipId, fixtureReason, now());
    assert.ok(added.subject_label === memberLabel && ![docketId, matterId, recordId, changed.invalidation_operation_id].includes(added.id),
      'V1_IP_ACL_DISTINCT_GRANT_IDENTITY');
    const receipt = Object.freeze({ companyId, sourceSha, family, docketId, matterId, membershipId: memberMembershipId,
      grantId: added.id, grantVersion: added.record_version, accessPolicyVersion: version,
      invalidationOperationId: changed.invalidation_operation_id, panelAckSha256: hash(panelAck.requestId),
      previewAckSha256: hash(previewId), applyAckSha256: hash(applied.requestId) });
    let accepted = false;
    return {
      receipt,
      acceptMemberSummary(envelope) {
        assert.ok(!accepted, 'V1_IP_ACL_MEMBER_READ_REPLAY_REFUSED');
        accepted = true;
        const summary = acknowledge(envelope, memberMembershipId, 'GET', prefix + '/summary', 200);
        const docket = summary.value;
        fields(docket, summaryKeys, 'V1_IP_ACL_MEMBER_SUMMARY_SHAPE');
        assert.ok(docket.id === docketId && docket.company_id === companyId && docket.matter_id === matterId
          && docket.record_type === expected.type && docket.title === title && docket.is_active === true
          && docket.access_policy_version === version && count(docket.lifecycle_version) && count(docket.current_version)
          && (docket.primary_identifier === null || label(docket.primary_identifier)) && label(docket.status)
          && Number.isFinite(timestamp(docket.updated_at, true)), 'V1_IP_ACL_MEMBER_SUMMARY_LINEAGE');
        return Object.freeze({ ...receipt, memberSummaryAckSha256: hash(summary.requestId) });
      },
    };
  };
}
