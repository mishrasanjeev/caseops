import assert from 'node:assert/strict';
import { createV1IpAccessGrant } from './v1-ip-access-grant.mjs';
import { producerHash } from './native-producer-host.mjs';

/** The preview value exists only between the actual bounded transport and the
 * canonical grant validator. Public producer events contain no preview token. */
export async function grantV1IpMemberAccess(host, scope, family, parents, budgets) {
  const identity = host.getActorIdentity('owner');
  assert.equal(identity?.company?.id, scope.companyId, 'V1_IP_ACCESS_HOST_ACTOR_REQUIRED');
  assert.equal(identity?.membership?.id, scope.ownerMembershipId, 'V1_IP_ACCESS_HOST_ACTOR_REQUIRED');
  assert.deepEqual(Object.keys(parents).sort(), ['creator', 'link', 'matter', 'panel']);
  const grant = createV1IpAccessGrant(scope, family, {
    ...parents, mfa: host.getMfaAcknowledgement('owner'),
  }, budgets);
  return grant(async input => {
    let claimed = false;
    const chain = { claim(attempt) {
      assert.equal(claimed, false, 'V1_IP_ACCESS_HOST_REPLAY_REFUSED');
      assert.deepEqual([attempt.stage, attempt.actor, attempt.company, attempt.membership, attempt.method, attempt.requestTarget],
        ['base', 'owner', scope.companyId, scope.ownerMembershipId, 'POST', input.route], 'V1_IP_ACCESS_HOST_DISPATCH_CHANGED');
      assert.ok(Buffer.isBuffer(attempt.bodyBytes) && attempt.bodyBytes.equals(input.bodyBytes)
        && producerHash(attempt.bodyBytes) === input.provenance.bodySha256, 'V1_IP_ACCESS_HOST_BYTES_CHANGED');
      claimed = true;
      let accepted = false;
      return { provenance: input.provenance, acceptResponse(response) {
        assert.equal(accepted, false, 'V1_IP_ACCESS_HOST_ACK_REPLAY_REFUSED'); accepted = true;
        return { actor: { companyId: scope.companyId, membershipId: scope.ownerMembershipId },
          request: { method: input.method, route: input.route, bodySha256: input.provenance.bodySha256 }, response };
      } };
    } };
    const result = await host.requestIpAccess({ ...input, producerStage: 'base' }, chain);
    assert.equal(claimed, true, 'V1_IP_ACCESS_HOST_TYPED_CLAIM_REQUIRED');
    if (budgets.onAcknowledged) {
      const { status, requestId, releaseSha } = result.projection.response;
      budgets.onAcknowledged({ key: 'ip-' + family + '-grant-' + (input.route.endsWith('/preview') ? 'preview' : 'apply'),
        method: input.method, route: input.route, status, requestId, releaseSha });
    }
    return result.projection;
  });
}
