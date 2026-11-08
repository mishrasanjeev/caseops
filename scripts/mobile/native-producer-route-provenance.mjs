import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const successful = new Set([200, 201]);
const digest = value => createHash('sha256').update(value).digest('hex');
const v1Creators = new Map([
  ['/api/matters/', value => [['matter', value.id]]],
  ['/api/contracts/', value => [['contract', value.id]]],
  ['/api/ip/patents/families', value => [['patent', value.id], ['docket', value.docket_id]]],
  ['/api/ip/specialist/records', value => [['design', value.id], ['docket', value.docket_id]]],
  ['/api/ip/trademark-applications/manual', value => [['trademark', value.application?.id], ['docket', value.docket?.id]]],
]);
const queueCreators = new Map([
  ['/api/matters/', value => [['matter', value.id]]],
  ['/api/teams/', value => [['team', value.id]]],
]);
const normalIdentity = ['GET /api/build', 'POST /api/auth/login', 'POST /api/auth/mfa/step-up', 'GET /api/auth/me'];
const v1Fixed = [
  ...normalIdentity, 'GET /api/ip/readiness', 'GET /api/ip/domains', 'POST /api/clients/', 'POST /api/contracts/',
  'GET /api/contracts/', 'POST /api/matters/', 'POST /api/ip/patents/families', 'POST /api/ip/specialist/records',
  'POST /api/ip/trademark-applications/manual', 'POST /api/ip/operational-deadlines', 'POST /api/bootstrap/company',
  'POST /api/companies/current/users', 'POST /api/auth/mfa/enroll', 'POST /api/auth/mfa/enroll/verify',
  'GET /api/auth/security', 'GET /api/calendar/events', 'POST /api/outside-counsel/profiles',
  'POST /api/outside-counsel/assignments', 'POST /api/outside-counsel/spend-records', 'GET /api/recipient-inbox',
];
const queueFixed = [...normalIdentity, 'POST /api/companies/current/users', 'POST /api/matters/', 'POST /api/teams/',
  'GET /api/matter-work-queue', 'GET /api/account/deletion-requests'];
export function producerFixedRoutes(profile) {
  assert.ok(['v1', 'queue'].includes(profile));
  return [...(profile === 'v1' ? v1Fixed : queueFixed)];
}

function v1Paths(kind, id) {
  switch (kind) {
    case 'matter': {
      const p = '/api/matters/' + id;
      return [
        ['GET ' + p, ['base']],
        ['GET ' + p + '/workspace', ['base', 'viewer']],
        ['POST ' + p + '/tasks', ['base', 'viewer']],
        ['POST ' + p + '/hearings', ['base', 'viewer']],
        ['GET ' + p + '/access', ['base']],
        ['POST ' + p + '/access/restricted', ['base']],
        ['POST ' + p + '/access/grants', ['base']],
        ['GET /api/outside-counsel/matters/' + id + '/context', ['readthrough']],
      ];
    }
    case 'contract': {
      const p = '/api/contracts/' + id;
      return [['GET ' + p, ['base']], ['GET ' + p + '/obligations', ['readthrough']], ['POST ' + p + '/obligations', ['readthrough']]];
    }
    case 'patent':
    case 'design': {
      const p = '/api/ip/' + (kind === 'patent' ? 'patents/families/' : 'specialist/records/') + id;
      return [['GET ' + p, ['base']], ['GET ' + p + '/versions/1', ['base']]];
    }
    case 'trademark':
      return [['GET /api/ip/trademark-applications/' + id, ['base']]];
    case 'docket': {
      const p = '/api/ip/dockets/' + id;
      return [['GET ' + p + '/summary', ['base']], ['GET ' + p + '/access', ['base']],
        ['GET ' + p + '/matter-links', ['base']], ['POST ' + p + '/matter-links', ['base']]];
    }
    default: throw new Error('PRODUCER_UNREVIEWED_ACK_TYPE');
  }
}

function queuePaths(kind, id, actor) {
  if (kind === 'team') return [['POST /api/teams/' + id + '/members', ['queue']]];
  assert.equal(kind, 'matter');
  const p = '/api/matters/' + id;
  return [['POST ' + p + '/tasks', ['queue']], ...(actor === 'owner' ? [['PATCH ' + p + '/lifecycle/status', ['queue']]] : [])];
}

/**
 * Host-side evidence projection only. The caller must supply the authenticated
 * identity and the successful response of the actual bounded HTTP constructor.
 * Neither a plan's IDs nor an arbitrary object field can admit a route.
 */
export function producerRouteProvenance(profile, sourceSha) {
  assert.ok(['v1', 'queue'].includes(profile));
  assert.match(sourceSha, /^[a-f0-9]{40}$/);
  const creators = profile === 'v1' ? v1Creators : queueCreators;
  const acknowledged = new Set(), literal = new Map();
  let inbox;
  const validCreator = (stage, actor, path) => profile === 'v1'
    ? (stage === 'base' && actor === 'owner') || (stage === 'viewer' && actor === 'owner' && path === '/api/matters/')
    : stage === 'queue' && (actor === 'owner' || (actor === 'foreign-owner' && path === '/api/matters/'));
  const validCompany = company => typeof company === 'string' && uuid.test(company);
  return {
    bindInbox({ company, matter, membership }) {
      assert.ok(profile === 'v1' && !inbox && [company, matter, membership].every(validCompany), 'PRODUCER_INBOX_SCOPE_REQUIRED');
      inbox = { company, matter, membership };
    },
    observe({ stage, actor, company, membership, method, path, response }) {
      const pick = method === 'POST' && creators.get(path);
      if (!pick || !successful.has(response.status)) return;
      assert.ok(validCreator(stage, actor, path) && validCompany(company) && validCompany(membership), 'PRODUCER_CREATOR_SCOPE_REFUSED');
      assert.equal(response.releaseSha, sourceSha, 'PRODUCER_CREATOR_SOURCE_CHANGED');
      const { requestId, value } = response;
      assert.ok(typeof requestId === 'string' && /^[a-zA-Z0-9_.:-]{1,160}$/.test(requestId)
        && !acknowledged.has(requestId) && acknowledged.size < 64, 'PRODUCER_CREATOR_ACK_REQUIRED');
      assert.ok(value && typeof value === 'object' && !Array.isArray(value), 'PRODUCER_CREATOR_VALUE_REQUIRED');
      if (Object.hasOwn(value, 'company_id')) assert.equal(value.company_id, company, 'PRODUCER_CREATOR_COMPANY_CHANGED');
      const routes = new Map();
      for (const [kind, id] of pick(value)) {
        assert.ok(typeof id === 'string' && uuid.test(id), 'PRODUCER_CREATOR_TYPED_ID_REQUIRED');
        for (const [route, stages] of (profile === 'v1' ? v1Paths(kind, id) : queuePaths(kind, id, actor))) {
          if (stage === 'viewer' && !stages.includes('viewer')) continue;
          assert.ok(!routes.has(route) && !literal.has(route), 'PRODUCER_CREATOR_DUPLICATE_ROUTE');
          routes.set(route, { stage, actor, company, membership, stages, requestDigest: digest(requestId) });
        }
      }
      acknowledged.add(requestId);
      for (const [route, provenance] of routes) literal.set(route, provenance);
    },
    allow({ stage, actor, company, membership, method, path }) {
      const route = method + ' ' + path;
      if (stage === 'inbox' && actor === 'member' && inbox?.company === company && inbox.membership === membership) {
        const parent = '/api/matters/' + inbox.matter;
        if (route === 'POST ' + parent + '/hearings' || route === 'GET ' + parent + '/workspace') {
          const item = literal.get('GET ' + parent + '/workspace');
          if (item?.company === company && item.stage === 'base') return { requestDigest: item.requestDigest };
        }
      }
      const item = literal.get(route);
      if (!item || item.company !== company || !item.stages.includes(stage)) return null;
      const sameActor = item.actor === actor && item.membership === membership;
      const viewerRead = item.stage === 'viewer' && stage === 'viewer' && actor === 'viewer'
        && method === 'GET' && path.endsWith('/workspace');
      if ((!sameActor && !viewerRead) || (item.stage === 'base' && stage === 'viewer')) return null;
      return { requestDigest: item.requestDigest };
    },
  };
}
