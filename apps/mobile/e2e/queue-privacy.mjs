import assert from 'node:assert/strict';
import { collectQP, decodeQueuePage, decodeAccountDeletionReceipt, expectedQueue, hash } from './queue-privacy-contract.mjs';
import { find, findQuery, read, visible, selector, dispatchNativeClick, home } from './native-ui.mjs';
import { traffic,delta,readOnlyTraffic } from './journeys.mjs';
import { displayDay } from '../src/domain/contracts.ts';
const event=(c,boundary,facts={})=>c.record({type:'queue_privacy_assertion',boundary,...facts});
const consume=c=>assert.ok(++c.nativeOperations<=160,'QP_NATIVE_CONTROL_BOUND');
async function tap(c,id){consume(c);const e=await find(c,'id',id,{scroll:true});assert.equal(await e.isEnabled(),true);await dispatchNativeClick(c,e,'id',id);}
async function fact(c,id){consume(c);return read(c,'id',id,{scroll:true});}
async function wait(c,id,value){let terminal;await c.driver.waitUntil(async()=>{try{const e=await visible(c.driver,selector(c.platform,'id',id));return!!e&&(value===undefined||await e.getText()===value);}catch(e){terminal=e;return true;}},{timeout:20000,interval:200,timeoutMsg:'QP_NATIVE_STATE_REQUIRED'});if(terminal)throw terminal;}
async function absent(c,id){consume(c);assert.equal((await c.driver.$$(selector(c.platform,'id',id))).length,0,'QP_PRIVATE_OLD_CONTROL_REMAINS');}
async function control(c,name,args={}){assert.ok(++c.controlCalls<=24,'QP_CASE_CONTROL_BOUND');return c.controls[name]({caseId:c.caseId,...args});}
async function segment(c,group,label){
 const observed=c.fixture.qp.nativeSelectors;assert.equal(observed.observed,true);assert.equal(observed.udid,c.fixture.udid);assert.deepEqual(observed.buildReceipt,c.fixture.buildReceipt);
 const r=observed.segments[group]?.[label];assert.ok(r&&r.group===group&&r.label===label);assert.ok(r.query.startsWith(c.platform==='ios'?'-ios predicate string:':'android='));
 const scope=r.scopeQuery?await findQuery(c,r.scopeQuery,{scroll:true}):c.driver,e=await visible(scope,r.query);assert.ok(e);assert.equal(await e.getAttribute(r.labelAttribute),label);consume(c);await dispatchNativeClick(c,e);
}
async function rows(c,page){
 await wait(c,'matter-task-queue');consume(c);
 const attribute=c.platform==='ios'?'name':'resource-id';let terminal;
 await c.driver.waitUntil(async()=>{try{
  const elements=await c.driver.$$(`//*[starts-with(@${attribute}, 'queue-task-')]`);assert.ok(elements.length<=64);
  const ids=[];for(const e of elements){const id=await e.getAttribute(attribute);if(/^queue-task-[a-f0-9-]{36}$/.test(id))ids.push(id.slice(11));}
  assert.deepEqual(ids,[...new Set(ids)],'QP_DUPLICATE_NATIVE_ROW');
  assert.ok(ids.every(id=>c.fixture.qp.dataset.tasks.some(t=>t.id===id&&t.role!=='excluded')),'QP_UNAUTHORIZED_OR_UNBOUND_NATIVE_ROW');
  return JSON.stringify(ids)===JSON.stringify(page.items.map(x=>x.id));
 }catch(error){terminal=error;return true;}},{timeout:20000,interval:200,timeoutMsg:'QP_EXACT_NATIVE_PAGE_IDENTITIES'});if(terminal)throw terminal;
 assert.equal((await c.driver.$$(selector(c.platform,'id','queue-next'))).length,page.next_cursor?1:0);
}
async function queue(c,ownership,dates,cursor=null){
 assert.ok(++c.authoritativeReads<=24);const r=await control(c,'readQueue',{ownership,dates,...(cursor?{cursor}:{})});assert.equal(r.status,200);
 return decodeQueuePage(r.value,{ownership,dates},c.fixture.membershipId);
}
async function taskFacts(c,item){
 const values={'queue-task-title':item.title,'queue-task-id':item.id,'queue-task-matter':`${item.matter.matter_code} · ${item.matter.title}`,
 'queue-task-status':item.status.replaceAll('_',' '),'queue-task-priority':item.priority,'queue-task-due':item.due_on?displayDay(item.due_on):'No due date recorded','queue-task-assignment':'Assigned to you',
 'queue-task-created':item.created_at,'queue-task-updated':item.updated_at,'queue-task-lifecycle':String(item.matter.lifecycle_version)};
 for(const[id,value]of Object.entries(values))assert.equal(await fact(c,id),value,'QP_EXACT_TASK_FACT');
}
async function selectQueue(c,ownership,dates){
 if(c.selected.ownership!==ownership){await segment(c,'Task ownership',{mine:'Mine',team:'Team',unassigned:'Unassigned'}[ownership]);c.selected.ownership=ownership;}
 if(c.selected.dates!==dates){await segment(c,'Task dates',{all:'All dates',dated:'Dated',undated:'Undated'}[dates]);c.selected.dates=dates;}
 const page=await queue(c,ownership,dates);await rows(c,page);return page;
}
async function ownPrivacy(c,actor='member'){assert.ok(++c.authoritativeReads<=24);const r=await control(c,'readOwnPrivacy',{actor});assert.equal(r.status,200);return r.value.request===null?null:decodeAccountDeletionReceipt(r.value.request);}
async function completedNativeRead(c,afterSequence){
 const deadline=Date.now()+20000;for(let attempt=0;attempt<4;attempt++){
  assert.ok(Date.now()<deadline);assert.ok(++c.controlCalls<=24);const result=await c.controls.readNativeRequest({caseId:c.caseId,method:'GET',route:'/api/account/deletion-requests',afterSequence},{deadline});
  assert.ok(result.requests.length<=1,'QP_RELOAD_REPLAY');if(result.requests.length){assert.equal(result.requests[0].status,200);return result.requests[0];}
  if(attempt<3)await new Promise(r=>setTimeout(r,Math.min(200,Math.max(0,deadline-Date.now()))));
 }throw Error('QP_EXPLICIT_NATIVE_RELOAD_NOT_COMPLETED');
}
async function receiptFacts(c,r){for(const[id,value]of Object.entries({'privacy-request-id':r.id,'privacy-request-operation':r.operation_id,
 'privacy-request-requested-at':r.requested_at,'privacy-request-status':'Received','privacy-request-not-completed':'Not completed'}))assert.equal(await fact(c,id),value);}
export const queuePrivacyScenarios=Object.freeze([
 {id:'QUEUE-01',run:async c=>{
  const before=await traffic(c);await home(c,'work');await wait(c,'matter-task-queue');c.selected={ownership:'mine',dates:'all'};
  const page=await queue(c,'mine','all');assert.equal(page.items.length,25);assert.ok(page.next_cursor);await rows(c,page);
  await tap(c,'queue-next');const second=await queue(c,'mine','all',page.next_cursor);assert.equal(second.items.length,2);assert.equal(second.next_cursor,null);await rows(c,second);
  await tap(c,'queue-task-'+second.items[1].id);await wait(c,'queue-task-detail');await taskFacts(c,second.items[1]);await tap(c,'queue-back');await rows(c,second);
  await tap(c,'queue-first');await rows(c,page);
  for(const ownership of['mine','team','unassigned'])for(const dates of['all','dated','undated']){
   if(ownership==='mine'&&dates==='all')continue;const actual=await selectQueue(c,ownership,dates);
   assert.deepEqual(actual.items.map(x=>x.id),expectedQueue(c.fixture.qp.dataset.tasks,ownership,dates,c.fixture.membershipId,c.fixture.qp.dataset.teamPeerId).slice(0,25).map(x=>x.id));
   if(ownership==='team')assert.match(await fact(c,'queue-ownership-meaning'),/Your own and unassigned tasks are excluded/);
  }
  const current=await selectQueue(c,'mine','all');assert.equal(current.items.at(-1).id,c.fixture.qp.dataset.anchor.id);
  const changed=await control(c,'changeAnchor',{action:'change'});assert.equal(changed.acknowledged,true);assert.equal(changed.id,c.fixture.qp.dataset.anchor.id);
  const staleBefore=await traffic(c);await tap(c,'queue-next');await wait(c,'queue-stale');await absent(c,'queue-next');await absent(c,'queue-task-detail');
  const requests=(await control(c,'readNativeRequest',{method:'GET',route:'/api/matter-work-queue',afterSequence:staleBefore.lastSequence})).requests;
  assert.equal(requests.length,1);assert.equal(requests[0].status,409);assert.equal(requests[0].queryObservation.cursorSha256,hash(Buffer.from(current.next_cursor)));
  await tap(c,'queue-first');const fresh=await queue(c,'mine','all');await rows(c,fresh);assert.notEqual(fresh.items.at(-1).id,current.items.at(-1).id);
  const restored=await control(c,'changeAnchor',{action:'restore'});assert.equal(restored.acknowledged,true);assert.equal(restored.id,changed.id);
  await tap(c,'queue-first');const reloaded=await queue(c,'mine','all');await rows(c,reloaded);assert.deepEqual(reloaded.items.map(x=>x.id),page.items.map(x=>x.id));
  assert.equal(reloaded.items.at(-1).due_on,page.items.at(-1).due_on);assert.equal(reloaded.items.at(-1).updated_at,restored.updatedAt);assert.notEqual(restored.updatedAt,page.items.at(-1).updated_at);
  await tap(c,'queue-task-'+page.items[0].id);await wait(c,'queue-task-detail');await tap(c,'queue-open-matter');await wait(c,'screen-matter');assert.equal(await fact(c,'matter-code'),page.items[0].matter.matter_code);
  await home(c,'work');await wait(c,'matter-task-queue');await absent(c,'queue-task-detail');
  const native=await control(c,'readNativeRequest',{method:'POST',route:'/api/account/deletion-requests',afterSequence:before.lastSequence});assert.equal(native.requests.length,0);
  readOnlyTraffic(delta(before,await traffic(c)));event(c,'queue-complete',{firstPageIds:page.items.map(x=>x.id),secondPageIds:second.items.map(x=>x.id),anchor:changed.id,restored:true,staleRejected:true,nativeBusinessWrites:0});
 }},
 {id:'PRIVACY-01',run:async c=>{
  const before=await traffic(c);await tap(c,'account-open');await wait(c,'privacy-request-state','No received request is recorded');assert.equal(await ownPrivacy(c),null);
  await tap(c,'privacy-request-start');await wait(c,'privacy-request-confirmation');await tap(c,'privacy-request-cancel');await wait(c,'privacy-request-state','No received request is recorded');
  const noPost=await control(c,'readNativeRequest',{method:'POST',route:'/api/account/deletion-requests',afterSequence:before.lastSequence});assert.equal(noPost.requests.length,0);
  const arm=await control(c,'armPrivacyAckLoss');await tap(c,'privacy-request-start');await tap(c,'privacy-request-confirm');
  await wait(c,'privacy-request-state','Acknowledgement unconfirmed');await absent(c,'privacy-request-start');await absent(c,'privacy-request-confirm');
  // UI Unknown follows the gateway's completed successful-upstream record, so
  // this is one explicit read, never a hidden20-iteration receipt poll.
  const ack=await control(c,'readControlReceipt',{id:arm.id});assert.equal(ack.requestsForwarded,1);assert.equal(ack.upstreamAcknowledged,true);assert.equal(ack.upstreamStatus,202);
  const receipt=decodeAccountDeletionReceipt(ack.responseObservation);assert.deepEqual(await ownPrivacy(c),receipt);
  const reloadBefore=await traffic(c);await tap(c,'privacy-request-reload');await completedNativeRead(c,reloadBefore.lastSequence);await wait(c,'privacy-request-state','Request received');await receiptFacts(c,receipt);assert.deepEqual(await ownPrivacy(c),receipt);
  await tap(c,'back');const revisitBefore=await traffic(c);await tap(c,'account-open');await completedNativeRead(c,revisitBefore.lastSequence);await wait(c,'privacy-request-state','Request received');await receiptFacts(c,receipt);await absent(c,'privacy-request-start');
  const posts=(await control(c,'readNativeRequest',{method:'POST',route:'/api/account/deletion-requests',afterSequence:before.lastSequence})).requests;
  assert.equal(posts.length,1);assert.equal(posts[0].status,202);assert.deepEqual(posts[0].bodyObservation.keys,['confirmation','operation_id']);assert.deepEqual(posts[0].responseObservation,receipt);
  await c.switchActor('second-company');await tap(c,'account-open');await wait(c,'privacy-request-state','No received request is recorded');await absent(c,'privacy-request-receipt');assert.equal(await ownPrivacy(c,'second-company'),null);
  event(c,'privacy-complete',{receipt,onePost:true,unknownAcknowledgementReconciledByGet:true,otherUserReceiptAbsent:true,deletionCompleted:false});
 }},
]);
export const collectQueuePrivacy=platform=>collectQP(platform,queuePrivacyScenarios);
