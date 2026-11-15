import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { prepareV1CalendarWorkspace } from '../../apps/mobile/e2e/v1-calendar-acknowledgements.mjs';

const sha256 = value => createHash('sha256').update(value).digest('hex');

/**
 * Prepare one Calendar family from the bounded HTTPS transport's held parent
 * envelopes. The future caller must pass the actual request target and bytes,
 * then accept a response only after verified gateway permit consumption.
 */
export function createV1CalendarHostRoutes(scope, spec, parents) {
  const read = prepareV1CalendarWorkspace(scope, spec, parents);
  const { companyId, ownerMembershipId } = scope;
  const actor = { companyId, membershipId: ownerMembershipId };
  let pending;

  function hold(request, predecessorRequestId, accept) {
    const bodyBytes = request.body === undefined ? undefined : Buffer.from(JSON.stringify(request.body));
    pending = { request, bodyBytes, accept, provenance: Object.freeze({
      requestDigest: sha256(predecessorRequestId),
      ...(bodyBytes === undefined ? {} : { bodySha256: sha256(bodyBytes) }),
    }) };
  }

  hold(read.workspaceRequest, read.predecessorRequestId, envelope => {
    const proposal = read.acceptWorkspace(envelope);
    hold(proposal.proposalRequest, envelope.response.requestId, proposalEnvelope => {
      const confirmation = proposal.acceptProposal(proposalEnvelope);
      hold(confirmation.confirmationRequest, proposalEnvelope.response.requestId,
        confirmationEnvelope => confirmation.acceptConfirmation(confirmationEnvelope));
    });
  });

  return {
    nextRequest: () => structuredClone(pending?.request),
    claim({ stage, actor: role, company, membership, method, requestTarget, bodyBytes }) {
      const step = pending;
      if (!step || stage !== 'base' || role !== 'owner' || company !== companyId || membership !== ownerMembershipId
        || method !== step.request.method || requestTarget !== step.request.route) return null;
      const sameBytes = step.bodyBytes === undefined ? bodyBytes === undefined
        : Buffer.isBuffer(bodyBytes) && step.bodyBytes.equals(bodyBytes);
      if (!sameBytes) return null;
      // Dispatch can have an unknown outcome. Clear the claim before handing
      // it to transport, even when it never returns a usable acknowledgement.
      pending = undefined;
      let open = true;
      return {
        provenance: step.provenance,
        acceptResponse(response) {
          assert.ok(open, 'V1_CALENDAR_ROUTE_ACK_REPLAY_REFUSED');
          open = false;
          return step.accept({ actor, request: step.request, response });
        },
      };
    },
  };
}
