import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { decodeQueuePage } from '../src/domain/matter-work-queue.ts';
import { decodeAccountDeletionReceipt } from '../src/domain/privacy-requests.ts';
export { decodeQueuePage, decodeAccountDeletionReceipt };
export { readV1Reference as readReference, readV1Bytes as readBytes, v1Reference as reference, v1Identity as identity } from './v1-workflows-contract.mjs';
export const QP = Object.freeze({ inventoryId:'native-queue-privacy-2026-10-27-v1', profile:'queue-privacy-v1',
  cases:Object.freeze(['QUEUE-01','PRIVACY-01']), phases:6,sessions:2,serialMs:480000,transportMs:60000,readMs:10000,transitionMs:20000,pollMs:200,
  caseControls:Object.freeze({'QUEUE-01':24,'PRIVACY-01':24}),totalControls:49,nativeControls:160,authoritativeReads:24,
  capabilities:Object.freeze(['readQueue','readOwnPrivacy','changeAnchor','armPrivacyAckLoss','readControlReceipt','readNativeRequest','closeCaseControls','closeRunControls']),
  baseSha256:'a03af49be43afd3618688c64e0f7ac7938b8fa3e5e30b05bff00aeeb629ec4fc' });
export const hash=b=>createHash('sha256').update(b).digest('hex');
export const canonical=v=>JSON.stringify(v,Object.keys(v).sort());
export function collectQP(platform,scenarios){
  assert.ok(['android','ios'].includes(platform));assert.deepEqual(scenarios.map(x=>x.id),QP.cases);assert.ok(scenarios.every(x=>typeof x.run==='function'));
  const intended=QP.cases.map(id=>platform+':'+id);return{platform,inventoryId:QP.inventoryId,intended,discovered:[...intended],expectedPhases:6,expectedSessions:2,nativeExecution:'not-run'};
}
export function requireRequest(q){
  assert.equal(q?.readyForLive,true,'QP_PENDING');assert.equal(q.preparedOnly,false,'QP_PENDING');assert.equal(q.schemaVersion,1);assert.equal(q.inventoryId,QP.inventoryId);
  assert.match(q.expectedSourceSha||'',/^[a-f0-9]{40}$/);assert.match(q.expectedSourceFingerprint||'',/^[a-f0-9]{64}$/);assert.match(q.expectedBinaryHash||'',/^[a-f0-9]{64}$/);
  assert.ok(Number.isSafeInteger(q.expectedInputFileCount)&&q.expectedInputFileCount>0);assert.ok(['android','ios'].includes(q.platform));return q;
}
export function expectedQueue(tasks,ownership,dates,memberId,teamPeerId){
  const values=tasks.filter(x=>x.role!=='excluded'&&(ownership==='mine'?x.owner_membership_id===memberId:ownership==='team'?x.owner_membership_id===teamPeerId:x.owner_membership_id===null))
    .filter(x=>dates==='all'||(dates==='dated')===(x.due_on!==null));
  // UTC strings are normalized by the retained API schema. Preserve all six
  // fractional digits rather than converting through JS millisecond Dates.
  const stamp=v=>{const m=/^(.*T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(v);assert.ok(m);return m[1]+'.'+(m[2]||'').padEnd(6,'0');};
  return values.sort((a,b)=>Number(a.due_on===null)-Number(b.due_on===null)||(a.due_on||'').localeCompare(b.due_on||'')||stamp(a.created_at).localeCompare(stamp(b.created_at))||a.id.localeCompare(b.id));
}
export function validateDataset(d){
  assert.equal(d.kind,'actual-normal-api-queue-privacy-fixture');assert.equal(d.observed,true);assert.equal(d.automaticRetry,false);assert.equal(d.mutationUncertain,false);assert.equal(d.directDatabaseWrites,false);
  assert.equal(d.inventoryId,QP.inventoryId);assert.equal(d.tasks.length,35);assert.equal(new Set(d.tasks.map(x=>x.id)).size,35);
  assert.equal(d.tasks.filter(x=>x.role==='excluded').length,4);
  assert.equal(expectedQueue(d.tasks,'mine','all',d.membershipId,d.teamPeerId).length,27);
  assert.equal(expectedQueue(d.tasks,'team','all',d.membershipId,d.teamPeerId).length,2);
  assert.equal(expectedQueue(d.tasks,'unassigned','all',d.membershipId,d.teamPeerId).length,2);
  for(const page of d.pages){const decoded=decodeQueuePage(page.value,{ownership:page.ownership,dates:page.dates},d.membershipId);
    const expected=expectedQueue(d.tasks,page.ownership,page.dates,d.membershipId,d.teamPeerId).slice(page.after?25:0,page.after?50:25);
    assert.deepEqual(decoded.items.map(x=>x.id),expected.map(x=>x.id),'QP_EXACT_NORMAL_API_PAGE_REQUIRED');}
  assert.equal(d.pages.length,10);assert.equal(d.privacyBefore.request,null,'QP_NEW_GLOBAL_USER_REQUIRED');assert.equal(d.secondPrivacyBefore.request,null);
  assert.equal(d.anchor.id,d.pages[0].value.items.at(-1).id);assert.equal(d.anchor.matterId,d.matter.id);return d;
}
export const QP_CALL_INVENTORY=Object.freeze({
  'QUEUE-01':Object.freeze({readQueue:13,changeAnchor:2,readNativeRequest:2,closeCaseControls:1}),
  'PRIVACY-01':Object.freeze({readOwnPrivacy:4,armPrivacyAckLoss:1,readControlReceipt:1,readNativeRequest:10,closeCaseControls:1}),
  finalCleanup:1,
});
assert.equal(Object.values(QP_CALL_INVENTORY['QUEUE-01']).reduce((a,b)=>a+b),18);
assert.equal(Object.values(QP_CALL_INVENTORY['PRIVACY-01']).reduce((a,b)=>a+b),17);
assert.ok(18<=24&&17<=24&&18+17+QP_CALL_INVENTORY.finalCleanup<=49);

export function ownerRecipes(d){
 const path='/api/matters/'+d.anchor.matterId,id=d.anchor.id;
 return[['change',d.anchor.changedDueOn],['restore',d.anchor.due_on]].map(([action,due])=>({id:action,capability:'changeAnchor',caseId:'QUEUE-01',argumentsSha256:hash(Buffer.from(JSON.stringify({action}))),
  ...(action==='change'?{cleanupRecipeId:'restore'}:{}),requests:[
   {method:'GET',route:path,expectedStatuses:[200]},
   {method:'GET',route:path+'/tasks',expectedStatuses:[200]},
   {method:'PATCH',route:path+'/tasks/'+id,expectedStatuses:[200],body:{due_on:due,expected_lifecycle_version:{response:'0.lifecycle_version'},expected_updated_at:{select:{response:'1.tasks',where:{id},field:'updated_at'}}}},
  ],result:{acknowledged:true,id:{response:'2.id'},updatedAt:{response:'2.updated_at'},due_on:{response:'2.due_on'}}}));
}
