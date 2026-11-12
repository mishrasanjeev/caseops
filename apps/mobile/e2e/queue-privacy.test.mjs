import { bindObserverTestIdentity } from '../../../scripts/mobile/qa-observer-test-fixture.mjs';
import { validateAndroidTransport } from './local-run.mjs';
import { validateBuildReceipt, validateCoreFixture } from './fixture-contract.mjs';
import { attestAndroidBinary, attestLocalQAAndroidBinary } from './installed-android.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { QP,QP_AUTH_AND_NATIVE_BASE_ROUTES,QP_CALL_INVENTORY,expectedQueue,hash,decodeAccountDeletionReceipt } from './queue-privacy-contract.mjs';
import { produceQueuePrivacy,pendingProducer,QP_PRODUCER } from './queue-privacy-fixture.mjs';
import { androidQueuePage, assertQPPrivacyControlsAbsent, collectQueuePrivacy, queuePrivacyScenarios, resolveAndroidComposeQueueSegment, selectQueueSegment, waitForQPPrivacyControl } from './queue-privacy.mjs';
import { writePrivatePeer,ownerRecipes,composeQPFixture } from '../../../scripts/mobile/prepare-queue-privacy-fixture.mjs';
import { admitQPBeforeMembers,pendingQPRequest,withQPActor,logoutQPAccount,resolveQPAuthDockerReceipt } from '../../../scripts/mobile/run-queue-privacy.mjs';
import { createControls,V1_CONTROL_PROTOCOL } from '../../../scripts/mobile/queue-privacy-controls.mjs';
import { composeQPRegistration } from '../../../scripts/mobile/queue-privacy-registration.mjs';
import { pendingQueuePrivacyHost,runQueuePrivacyProducer } from '../../../scripts/mobile/produce-queue-privacy-fixture.mjs';
import { createProducerStore,producerTimeout } from '../../../scripts/mobile/native-producer-host.mjs';
import { spawnSync } from 'node:child_process';
import * as queueEvidence from './queue-privacy.mjs';
import { createMatterWorkQueueController, createMatterWorkQueueRepository } from '../src/domain/matter-work-queue.ts';
const ROOT=path.resolve(fileURLToPath(new URL('../../../',import.meta.url))),id=n=>'00000000-0000-4000-8000-'+n.toString(16).padStart(12,'0');

function beforeRegistrationAuthDouble(bind){
 const objects=new Map(),reads=[],r=(name,value)=>{const ref={path:'/synthetic/'+name+'.json',sha256:'e'.repeat(64)};if(value!==undefined)objects.set(ref.path,value);return ref;};
 const sha=bind?.source.sourceSha??'a'.repeat(40),project=bind?.isolation.project??'caseops-mobile-20261112-01234567',run=bind?.isolation.gatewayRunId??'qp-'+'1'.repeat(24),source=bind?.source??{sourceSha:sha,sourceFingerprint:'b'.repeat(64),inputFileCount:244,sourceDirty:false};
 const container=(service,n)=>({id:n.toString(16).padStart(64,'0'),name:`/${project}-${service}-1`,image:'sha256:'+'c'.repeat(64),project,networks:[project+'_private'],mounts:[{type:'bind',name:null,source:'/owned/'+service,destination:'/fixture-state',readWrite:service==='gateway'}]});
 const oldRuntime={kind:'actual-qp-runtime-inventory',sourceSha:sha,project,runId:run,containers:['api','gateway','migrate','postgres','scanner','valkey','web'].map((s,n)=>container(s,n+1))};
 const newRuntime=structuredClone(oldRuntime);newRuntime.containers[1].id='f'.repeat(64);
 const receipt=runtime=>({environment:'docker-integration',syntheticDataOnly:true,productionAccessed:false,metroLaunched:false,backendSha:sha,webSha:sha,project,gatewayRunId:run,
  backendRevision:'exact-api',webRevision:'exact-web',source:{api:{head:sha,fingerprint:'api',dirty:false},web:{head:sha,fingerprint:'web',dirty:false}},apiOrigin:'https://10.0.2.2:9743',webOrigin:'https://10.0.2.2:4743',gatewayUrl:'https://127.0.0.1:9743',webGatewayUrl:'https://127.0.0.1:4743',publicCA:'/owned/ca.crt',composeSha256:'d'.repeat(64),fixtureSourceHashes:{gateway:'c'.repeat(64)},gatewayImplementationSha256:'c'.repeat(64),tlsProof:{strictDefaultTLS:true,verificationDisabled:false},apiWebPostgresScannerNetworkInternal:true,
  containers:runtime.containers.map(({mounts,...value})=>structuredClone(value))});
 const generated=receipt(newRuntime),after=bind?.isolation??generated;
 if(bind)Object.assign(after,{...generated,...after,containers:generated.containers});
 const before={...structuredClone(after),containers:receipt(oldRuntime).containers},beforeRef=r('before-receipt',before),afterRef=bind?.q.dockerReceipt??r('after-receipt',after);
 objects.set(afterRef.path,after);
 const controls=bind?.controls??{gatewayImplementationEvidence:r('implementation'),registrationEvidence:r('registration')};
 const q=bind?.q??{dockerReceipt:afterRef,controlsEvidence:r('controls'),members:[{authObservation:r('member-auth')},{authObservation:r('foreign-auth')}]};
 const oldConfig={CASEOPS_MOBILE_PROJECT:project,CASEOPS_MOBILE_GATEWAY_RUN_ID:run,CASEOPS_MOBILE_API_SHA:sha,CASEOPS_MOBILE_WEB_SHA:sha,CASEOPS_MOBILE_V1_CONTROLS:'0',UNCHANGED_PUBLIC_ORIGIN:before.apiOrigin};
 const newConfig={...oldConfig,CASEOPS_MOBILE_V1_CONTROLS:'1',CASEOPS_MOBILE_V1_PROFILE:QP.profile,CASEOPS_MOBILE_V1_IMPLEMENTATION_SHA256:controls.gatewayImplementationEvidence.sha256,CASEOPS_MOBILE_V1_REGISTRATION_SHA256:controls.registrationEvidence.sha256,CASEOPS_MOBILE_V1_REGISTRATION:'/fixture-state/'+path.basename(controls.registrationEvidence.path)};
 const oldStatus={runId:run,lastSequence:0,requests:[],markerRejected:0,routeRejected:0,overflow:false,implementationSha256:before.gatewayImplementationSha256,v1ControlsEnabled:false};
 const newStatus={...oldStatus,v1ControlsEnabled:true,v1ControlProfile:QP.profile,v1ControlsImplementationSha256:controls.gatewayImplementationEvidence.sha256,v1RegistrationSha256:controls.registrationEvidence.sha256};
 const activation={sourceSha:sha,project,runId:run,finalDockerReceipt:afterRef,registrationEvidence:controls.registrationEvidence,controlsEvidence:q.controlsEvidence,actualActiveGateway:true,actualNativeAcceptance:false,secondsRemaining:478};
 const transition={schemaVersion:1,kind:'actual-qp-auth-before-registration',sourceSha:sha,beforeDockerReceipt:beforeRef,afterDockerReceipt:afterRef,
  beforeRuntimeEvidence:r('runtime-before',oldRuntime),afterRuntimeEvidence:r('runtime-after',newRuntime),beforeConfiguration:r('config-before',oldConfig),afterConfiguration:r('config-after',newConfig),beforeGatewayStatus:r('status-before',oldStatus),afterGatewayStatus:r('status-after',newStatus),activationEvidence:r('activation',activation),authObservations:q.members.map(m=>m.authObservation)};
 q.preRegistrationAuthEvidence=r('transition',transition);
 const io={read:ref=>{reads.push(ref.path);assert.ok(objects.has(ref.path));return objects.get(ref.path);},source,isolation:after,controls};
 return{q,io,objects,reads,transition,before,after,oldRuntime,newRuntime,oldConfig,newConfig,oldStatus,newStatus,activation,beforeRef,run:()=>resolveQPAuthDockerReceipt(q,io)};
}

test('Queue pre-registration auth keeps the original observation receipt and requires an exact unchanged runtime transition',()=>{
 const x=beforeRegistrationAuthDouble(),before=JSON.stringify([...x.objects]);const actual=x.run();
 assert.deepEqual(actual,x.beforeRef);assert.equal(JSON.stringify([...x.objects]),before,'evidence objects remain unchanged');
 const legacy=beforeRegistrationAuthDouble();delete legacy.q.preRegistrationAuthEvidence;assert.deepEqual(legacy.run(),legacy.q.dockerReceipt);assert.equal(legacy.reads.length,0);
 legacy.q.preRegistrationAuthEvidence=null;assert.deepEqual(legacy.run(),legacy.q.dockerReceipt);assert.equal(legacy.reads.length,0);
 assert.equal(QP.serialMs,480000);assert.equal(QP.totalControls,49);
});

test('Queue pre-registration auth rejects source, process, mount, configuration, ledger, actor and lease substitutions',()=>{
 const mutations=[
  x=>x.transition.extra=true,x=>x.transition.sourceSha='f'.repeat(40),x=>x.transition.afterDockerReceipt=x.beforeRef,
  x=>x.transition.authObservations.reverse(),x=>x.transition.beforeDockerReceipt=x.q.dockerReceipt,
  x=>x.before.backendRevision='other-api',x=>x.before.publicCA='/other/ca',x=>delete x.before.composeSha256,
  x=>x.before.productionAccessed=true,x=>x.before.tlsProof.verificationDisabled=true,
  x=>x.newRuntime.containers[0].id='d'.repeat(64),x=>x.newRuntime.containers[0].mounts[0].source='/other/data',
  x=>x.newRuntime.containers[1].mounts[0].readWrite=false,x=>x.oldRuntime.containers.pop(),
  x=>x.oldRuntime.containers.push(structuredClone(x.oldRuntime.containers[0])),
  x=>x.newConfig.UNCHANGED_PUBLIC_ORIGIN='https://elsewhere.invalid',x=>x.oldConfig.CASEOPS_MOBILE_V1_CONTROLS='1',
  x=>x.newConfig.CASEOPS_MOBILE_V1_REGISTRATION='/fixture-state/other.json',
  x=>x.newStatus.v1RegistrationSha256='a'.repeat(64),x=>x.oldStatus.overflow=true,x=>x.oldStatus.markerRejected=1,
  x=>x.newStatus.v1ControlsImplementationSha256='a'.repeat(64),
  x=>x.oldStatus.requests.push({sequence:1}),x=>x.activation.secondsRemaining=480,
  x=>x.activation.actualNativeAcceptance=true,x=>x.activation.finalDockerReceipt=x.beforeRef,
 ];
 for(const mutate of mutations){const x=beforeRegistrationAuthDouble();mutate(x);assert.throws(x.run);}
});

test('invalid pre-registration auth evidence refuses complete Queue admission before either credential reader',async()=>{
 const x=await admissionDouble();try{
  x.q.preRegistrationAuthEvidence={path:'/synthetic/unreviewed-auth-transition.json',sha256:'e'.repeat(64)};
  x.map.set(x.q.preRegistrationAuthEvidence.path,{kind:'unreviewed'});
  await assert.rejects(x.run());assert.equal(x.calls.some(v=>v.startsWith('PRIVATE:')),false);
 }finally{x.close();}
});

test('complete Queue admission accepts pre-registration observations only through their unchanged source/runtime transition',async()=>{
 const x=await admissionDouble();try{
  const bound=beforeRegistrationAuthDouble({q:x.q,source:x.source,isolation:x.map.get(x.q.dockerReceipt.path),controls:x.controls});
  for(const [file,value]of bound.objects)x.map.set(file,value);
  for(const member of x.q.members)x.map.get(member.authObservation.path).dockerReceipt=bound.beforeRef;
  const result=await x.run();assert.equal(result.members.length,2);assert.equal(x.calls.filter(value=>value.startsWith('PRIVATE:')).length,2);
  for(const member of x.q.members)assert.deepEqual(x.map.get(member.authObservation.path).dockerReceipt,bound.beforeRef);
  assert.deepEqual(x.q.dockerReceipt,bound.transition.afterDockerReceipt);
  x.q.preRegistrationAuthEvidence=null;
  await assert.rejects(x.run());assert.equal(x.calls.filter(value=>value.startsWith('PRIVATE:')).length,2);
 }finally{x.close();}
});

test('Queue terminal publication permits the first visible ready-row action without a second render or retry',async()=>{
 const fixture=producerDouble();let controller;
 try{
  const dataset=await fixture.run(),page=dataset.pages[0].value,calls=[],ready=[];let selection;
  const repository=createMatterWorkQueueRepository(async(path)=>{calls.push(path);return structuredClone(page);},dataset.membershipId);
  controller=createMatterWorkQueueController(repository,()=>true);
  controller.subscribe(()=>{
   const view=controller.getSnapshot();
   if(view.phase==='ready'){
    ready.push(view.busy);
    if(!selection)selection=()=>controller.showTask(view,view.page.items[0]);
   }
  });
  controller.activate();const loaded=controller.firstPage(controller.getSnapshot());await loaded;
  const selected=await selection();
  assert.equal(selected,true,'the callback exposed by the first ready observation must remain current');
  assert.deepEqual(ready,[false]);assert.equal(calls.length,2);assert.equal(controller.getSnapshot().phase,'detail');
 }finally{controller?.dispose();fixture.close();}
});

test('Queue terminal publication leaves a newly admitted continuation lease owned after the preceding read completes',async()=>{
 const fixture=producerDouble();let controller,resolveContinuation;
 try{
  const dataset=await fixture.run(),calls=[],pending=new Promise(resolve=>{resolveContinuation=resolve;});let continuation,attempted=false;
  const repository=createMatterWorkQueueRepository(async(path,init)=>{
   calls.push({path,signal:init.signal});return calls.length===1?structuredClone(dataset.pages[0].value):pending;
  },dataset.membershipId);
  controller=createMatterWorkQueueController(repository,()=>true);
  controller.subscribe(()=>{const view=controller.getSnapshot();if(view.phase==='ready'&&!attempted){attempted=true;continuation=controller.nextPage(view);}});
  controller.activate();await controller.firstPage(controller.getSnapshot());
  assert.equal(calls.length,2);assert.equal(controller.getSnapshot().phase,'loading');assert.equal(controller.getSnapshot().busy,true);assert.equal(calls[1].signal.aborted,false);
  resolveContinuation(structuredClone(dataset.pages[1].value));const continued=await continuation;assert.equal(continued,true);
  assert.equal(controller.getSnapshot().phase,'ready');assert.equal(controller.getSnapshot().busy,false);
  assert.deepEqual(controller.getSnapshot().page.items.map(x=>x.id),dataset.pages[1].value.items.map(x=>x.id));
 }finally{resolveContinuation?.(structuredClone({}));controller?.dispose();fixture.close();}
});

test('Queue terminal publication makes its explicit error reload usable and still rejects a retained old view',async()=>{
 const fixture=producerDouble();let controller;
 try{
  const dataset=await fixture.run(),calls=[],errors=[];let reload;
  const repository=createMatterWorkQueueRepository(async(path)=>{calls.push(path);if(calls.length===1)throw Error('synthetic bounded read failure');return structuredClone(dataset.pages[0].value);},dataset.membershipId);
  controller=createMatterWorkQueueController(repository,()=>true);
  controller.subscribe(()=>{const view=controller.getSnapshot();if(view.phase==='error'){
   errors.push({busy:view.busy,page:view.page,selected:view.selected});
   if(!reload)reload=()=>controller.firstPage(view);
  }});
  controller.activate();const old=controller.getSnapshot();await controller.firstPage(old);const reloaded=await reload();assert.equal(reloaded,true);
  assert.deepEqual(errors,[{busy:false,page:null,selected:null}]);assert.equal(calls.length,2);assert.equal(controller.getSnapshot().phase,'ready');
  const refused=await controller.firstPage(old);assert.equal(refused,false);assert.equal(calls.length,2);
 }finally{controller?.dispose();fixture.close();}
});
function observedCursorExchange() {
 const delivered=hash(Buffer.from('independently-encrypted-native-cursor'));
 const page={sequence:10,method:'GET',route:'/api/matter-work-queue',status:200,
  queryObservation:{ownership:'mine',dates:'all',cursorSha256:null},
  responseObservation:{nextCursorSha256:delivered,anchorIdSha256:hash(Buffer.from(id(14)))}};
 const stale={sequence:11,method:'GET',route:'/api/matter-work-queue',status:409,
  queryObservation:{ownership:'mine',dates:'all',cursorSha256:delivered}};
 return {records:[page,stale],scope:{afterSequence:9,staleAfterSequence:10,anchorId:id(14)}};
}
test('stale Queue continuation binds the delivered native cursor rather than another encrypted read',()=>{
 assert.equal(typeof queueEvidence.assertObservedStaleQueueCursor,'function');
 const x=observedCursorExchange(),ownerCursor=hash(Buffer.from('separately-encrypted-owner-cursor'));
 assert.notEqual(ownerCursor,x.records[0].responseObservation.nextCursorSha256);
 const proof=queueEvidence.assertObservedStaleQueueCursor(x.records,x.scope);
 assert.equal(proof.deliveredCursorSha256,x.records[1].queryObservation.cursorSha256);
 assert.equal(proof.nativePageSequence,10);assert.equal(proof.staleRequestSequence,11);
});
test('stale Queue cursor proof rejects missing, substituted or wrong-anchor native page evidence',()=>{
 assert.equal(typeof queueEvidence.assertObservedStaleQueueCursor,'function');
 for(const edit of [x=>delete x.records[0].responseObservation,
  x=>x.records[0].responseObservation.nextCursorSha256=hash(Buffer.from('another-response')),
  x=>x.records[0].responseObservation.anchorIdSha256=hash(Buffer.from(id(15))),
  x=>x.records[0].queryObservation.ownership='team',
  x=>x.records[0].sequence=9]){
  const x=observedCursorExchange();edit(x);assert.throws(()=>queueEvidence.assertObservedStaleQueueCursor(x.records,x.scope));
 }
});
test('stale Queue cursor proof preserves exact single request, status, scope and ordering guards',()=>{
 assert.equal(typeof queueEvidence.assertObservedStaleQueueCursor,'function');
 for(const edit of [x=>x.records.push({...x.records[1],sequence:12}),x=>x.records[1].status=200,
  x=>x.records[1].queryObservation.dates='dated',x=>x.records.reverse(),
  x=>x.records[1].sequence=10,x=>x.records[1].queryObservation.cursorSha256=null]){
  const x=observedCursorExchange();edit(x);assert.throws(()=>queueEvidence.assertObservedStaleQueueCursor(x.records,x.scope));
 }
});
function anchorControlDouble({changeError,restoreError}={}){
 const calls=[],events=[],anchor={id:id(14)};
 const c={caseId:'QUEUE-01',controlCalls:0,record:event=>events.push(event),fixture:{qp:{dataset:{anchor}}},controls:{
  changeAnchor:async input=>{calls.push(input.action);if(input.action==='change'&&changeError)throw changeError;
   if(input.action==='restore'&&restoreError)throw restoreError;return {acknowledged:true,id:anchor.id,updatedAt:'2026-11-12T08:00:00Z'};},
 }};
 return {c,calls,events};
}
test('acknowledged Queue anchor change restores once after the original body fails',async()=>{
 assert.equal(typeof queueEvidence.withQPAnchorRestoration,'function');
 const x=anchorControlDouble(),original=new Error('synthetic body failure');
 await assert.rejects(queueEvidence.withQPAnchorRestoration(x.c,async()=>{throw original;}),error=>error===original);
 assert.deepEqual(x.calls,['change','restore']);assert.equal(x.c.controlCalls,2);
});
test('normal Queue anchor restoration is not replayed by completion cleanup',async()=>{
 assert.equal(typeof queueEvidence.withQPAnchorRestoration,'function');
 const x=anchorControlDouble();await queueEvidence.withQPAnchorRestoration(x.c,async({restore})=>{await restore();});
 assert.deepEqual(x.calls,['change','restore']);
 assert.deepEqual(x.events,[]);
});
test('unknown Queue change or restoration outcomes are never replayed',async()=>{
 assert.equal(typeof queueEvidence.withQPAnchorRestoration,'function');
 const unknown=new Error('synthetic unknown mutation');
 const change=anchorControlDouble({changeError:unknown});
 await assert.rejects(queueEvidence.withQPAnchorRestoration(change.c,async()=>{}),error=>error===unknown);assert.deepEqual(change.calls,['change']);
 const restore=anchorControlDouble({restoreError:unknown});
 await assert.rejects(queueEvidence.withQPAnchorRestoration(restore.c,async({restore})=>{await restore();}),error=>error===unknown);
 assert.deepEqual(restore.calls,['change','restore']);
});
test('Queue body and cleanup failures retain both original errors without another restoration',async()=>{
 assert.equal(typeof queueEvidence.withQPAnchorRestoration,'function');
 const original=new Error('synthetic original'),cleanup=new Error('synthetic cleanup'),x=anchorControlDouble({restoreError:cleanup});
 await assert.rejects(queueEvidence.withQPAnchorRestoration(x.c,async()=>{throw original;}),error=>error instanceof AggregateError&&error.errors[0]===original&&error.errors[1]===cleanup);
 assert.deepEqual(x.calls,['change','restore']);
 assert.deepEqual(x.events.map(event=>event.type),['qp_queue_body_failure','qp_queue_restore_failure']);
});
function pythonCompleted(child,phase){
 const diagnostic=JSON.stringify({phase,status:child.status,signal:child.signal,errorCode:child.error?.code??null,errorMessage:child.error?.message??null,stdout:child.stdout??'',stderr:child.stderr??''});
 assert.equal(child.error,undefined,diagnostic);assert.equal(child.status,0,diagnostic);
}
function fixturePython(deadline){
 let python=process.env.CASEOPS_MOBILE_PRODUCER_PYTHON;
 if(python===undefined){
  const discovered=spawnSync('python3',['-c','import sys; print(sys.executable)'],{encoding:'utf8',timeout:producerTimeout(deadline-performance.now()),maxBuffer:65536,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
  pythonCompleted(discovered,'python3-discovery');python=discovered.stdout.trim();
 }
 assert.ok(typeof python==='string'&&path.isAbsolute(python)&&path.normalize(python)===python,'QP_ABSOLUTE_TEST_HOST_PYTHON_REQUIRED');return python;
}
function producerDouble(){
 const dir=fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'qp-producer-'));const calls=[],events=[],privateFiles=[],claims=[];const parents=new Map(),tasks=[],teams=new Map();let serial=100,clock=0,peers=0;
 const plan={...pendingProducer(),readyForLive:true,preparedOnly:false,sourceSha:'a'.repeat(40),runId:'qp-'+id(80),companyId:id(1),membershipId:id(2),ownerMembershipId:id(3),foreignOwnerMembershipId:id(4),memberUserId:id(5),secondUserId:id(6),legalDay:'2026-10-27',privatePeerFiles:[path.join(dir,'peer-one.json'),path.join(dir,'peer-two.json')],baseActorEvidence:{path:'/synthetic/base',sha256:'a'.repeat(64)},admissionEvidence:{path:'/synthetic/admit',sha256:'b'.repeat(64)}};
 for(const name of ['buildReceipt','dockerReceipt','installedEvidence','codeClosure'])plan[name]={path:'/synthetic/'+name,sha256:'e'.repeat(64)};
 const stamp=()=>`2026-10-27T00:00:00.${String(++clock).padStart(6,'0')}Z`;
 const request=async(actor,method,raw,body,options)=>{
  calls.push({actor,method,route:raw,body,options});assert.equal(options.headers['X-CaseOps-Automated-Test'],'no-paid-providers');assert.equal(options.redirect,'error');const url=new URL(raw,'https://synthetic.invalid');const route=url.pathname;
  if(route==='/api/auth/me')return{status:200,value:{user:{id:actor==='member'?id(5):actor==='second-company'?id(6):actor==='owner'?id(7):id(8)},membership:{id:actor==='member'?id(2):actor==='owner'?id(3):actor==='second-company'?id(40):id(4)},company:{id:['foreign-owner','second-company'].includes(actor)?id(41):id(1)}}};
  if(route==='/api/companies/current/users'){assert.equal(privateFiles.length,peers+1);assert.equal(fs.statSync(plan.privatePeerFiles[peers]).mode&0o777,0o600);return{status:200,value:{membership_id:id(20+peers),user_id:id(30+peers++)}};}
  if(route==='/api/matters/'&&method==='POST'){const m={id:id(serial++),...body,company_id:actor==='foreign-owner'?id(41):id(1),is_active:true,lifecycle_version:0,updated_at:stamp()};parents.set(m.id,m);return{status:200,value:m};}
  if(route==='/api/teams/'&&method==='POST'){const t={id:id(serial++),...body,members:[]};teams.set(t.id,t);return{status:201,value:t};}
  if(route.startsWith('/api/teams/')){const t=teams.get(route.split('/')[3]);t.members.push({membership_id:body.membership_id});return{status:200,value:structuredClone(t)};}
  if(route.endsWith('/lifecycle/status')){const m=parents.get(route.split('/')[3]);assert.equal(body.expected_updated_at,m.updated_at);m.status='disposed';m.updated_at=stamp();m.lifecycle_version++;return{status:200,value:structuredClone(m)};}
  if(route.endsWith('/tasks')&&method==='POST'){
   const m=parents.get(route.split('/')[3]);
   assert.equal(body.expected_lifecycle_version,m.lifecycle_version);
   assert.ok(['todo','in_progress','blocked','completed'].includes(body.status),'QP_TASK_CREATE_WIRE_STATUS');
   const t={id:id(serial++),matter_id:m.id,...body,created_at:stamp(),updated_at:stamp()};
   tasks.push(t);
   return{status:200,value:structuredClone(t)};
  }
  if(route==='/api/account/deletion-requests')return{status:200,value:{request:null}};
  if(route==='/api/matter-work-queue'){
   const ownership=url.searchParams.get('ownership'),dates=url.searchParams.get('dates'),peer=id(20),cursor=url.searchParams.get('cursor');
   const list=tasks.filter(t=>{const m=parents.get(t.matter_id);return m.company_id===id(1)&&['intake','active','on_hold'].includes(m.status)&&t.status!=='completed'&&
    (ownership==='mine'?t.owner_membership_id===id(2):ownership==='team'?t.owner_membership_id===peer:t.owner_membership_id===null)&&
    (dates==='all'||(dates==='dated')===(t.due_on!==null));}).sort((a,b)=>Number(a.due_on===null)-Number(b.due_on===null)||(a.due_on||'').localeCompare(b.due_on||'')||a.created_at.localeCompare(b.created_at)||a.id.localeCompare(b.id));
   const offset=cursor?25:0,items=list.slice(offset,offset+25).map(t=>{const m=parents.get(t.matter_id);return{...t,matter:{id:m.id,title:m.title,matter_code:m.matter_code,status:m.status,is_active:true,lifecycle_version:m.lifecycle_version}};});
   return{status:200,value:{scope:'matter_tasks',ownership,dates,due_from:null,due_to:null,sort:'due_on_created_at_id',limit:25,items,next_cursor:list.length>offset+25?'synthetic-opaque-next':null}};
  }throw Error('UNEXPECTED_SYNTHETIC_ROUTE '+raw);
 };
 const io={request:async(...args)=>({...await request(...args),releaseSha:plan.sourceSha}),persist:e=>events.push(e),claim:key=>{assert.equal(claims.includes(key),false);claims.push(key);},now:()=>1000,
  persistPrivate:(file,value)=>{const r=writePrivatePeer(file,value);privateFiles.push(r);return r;},
  admit:async(_p,{boundary,charge})=>{for(let i=0;i<(boundary==='before'?10:2);i++)charge({method:boundary==='before'&&i>=2?'POST':'GET'});return{beforeMemberRead:true,sourceSha:plan.sourceSha,apiSourceSha:plan.sourceSha,webSourceSha:plan.sourceSha,...Object.fromEntries(['buildReceipt','dockerReceipt','installedEvidence','codeClosure','baseActorEvidence','admissionEvidence'].map(k=>[k,plan[k]]))};}};
 return{plan,io,calls,events,privateFiles,claims,run:()=>produceQueuePrivacy(plan,io),close:()=>fs.rmSync(dir,{recursive:true})};
}
async function admissionDouble(){
 const p=producerDouble(),dataset=await p.run(),q={...pendingQPRequest(),readyForLive:true,preparedOnly:false,platform:'ios',repoRoot:ROOT,expectedSourceSha:'a'.repeat(40),expectedSourceFingerprint:'b'.repeat(64),expectedInputFileCount:151,expectedBinaryHash:'c'.repeat(64),expectedHarnessFingerprint:'d'.repeat(64)};
 const map=new Map(),r=(key,value)=>{const ref={path:'/synthetic/'+key,sha256:'e'.repeat(64)};map.set(ref.path,value);return ref;};
 const source={sourceSha:q.expectedSourceSha,sourceFingerprint:q.expectedSourceFingerprint,inputFileCount:151,sourceDirty:false};
 const isolation={backendSha:source.sourceSha,webSha:source.sourceSha,environment:'docker-integration',syntheticDataOnly:true,project:'owned',gatewayRunId:dataset.runId,gatewayUrl:'https://127.0.0.1:8443',webGatewayUrl:'https://127.0.0.1:3443',backendRevision:'api',webRevision:'web',publicCA:'/synthetic/ca',
  apiOrigin:'https://127.0.0.1:8443',webOrigin:'https://127.0.0.1:3443',webIdentity:{service:'web',release_sha:source.sourceSha,revision:'web'},
  webAcceptanceMarkerBuild:true,productionAccessed:false,metroLaunched:false,tlsProof:{strictDefaultTLS:true,verificationDisabled:false},
  containers:['api','web','postgres'].map(service=>({name:'/owned-'+service+'-1',project:'owned',image:'sha256:'+'c'.repeat(64),networks:['owned']}))};
 q.dockerReceipt=r('receipt',isolation);q.producerEvidence=r('producer',dataset);
 const writeEvidence=(file,value)=>{const bytes=Buffer.from(JSON.stringify(value));fs.writeFileSync(file,bytes,{flag:'wx',mode:0o600});const reference={path:file,sha256:hash(bytes)};map.set(file,value);return reference;};
 const publicRoot=path.dirname(p.plan.privatePeerFiles[0]);
 const signingEvidence=writeEvidence(path.join(publicRoot,'signing-evidence.json'),{kind:'synthetic-unit-signing-evidence'});
 const installed={udid:id(80),appId:'ai.caseops.mobile.dev.simulatoracceptance',binaryHash:q.expectedBinaryHash,deviceTypeIdentifier:'com.apple.CoreSimulator.SimDeviceType.iPhone-17',appDataPath:'/synthetic/container'};
 const applicationIdentifier='CASEOPSUNIT.'+installed.appId;
 q.buildReceipt=writeEvidence(path.join(publicRoot,'build-evidence.json'),{...source,binaryHash:q.expectedBinaryHash,artifact:'/synthetic/CaseOps.app',
  platform:'ios',profile:'ios-simulator-acceptance',appId:installed.appId,automatedTest:true,devEnabled:false,apiOrigin:isolation.apiOrigin,webOrigin:isolation.webOrigin,
  iosSigning:{kind:'ios-simulator-ad-hoc-signing',appId:installed.appId,strictVerified:true,signingIdentity:'-',distributionSigning:false,
   nativeExecution:'not-run-by-signing-verifier',artifactSha256:q.expectedBinaryHash,entitlementsLocation:'Mach-O __TEXT,__entitlements',applicationIdentifier,
   keychainAccessGroups:[applicationIdentifier],slices:[{architecture:'arm64',applicationIdentifier,keychainAccessGroups:[applicationIdentifier]}],evidence:[signingEvidence]}});
 q.installedEvidence=r('installed',{...installed,buildReceipt:q.buildReceipt});q.deviceEvidence=r('device',{...installed,observed:true,platform:'ios',buildReceipt:q.buildReceipt});
 const fixture=(i)=>({environment:'docker-integration',syntheticDataOnly:true,binarySourceSha:source.sourceSha,binarySourceFingerprint:source.sourceFingerprint,backendSha:source.sourceSha,webSha:source.sourceSha,
  appId:installed.appId,appPath:'/synthetic/CaseOps.app',udid:installed.udid,deviceName:'Synthetic iPhone',platformVersion:'26.5',
  membershipId:i?id(40):id(2),companyId:i?id(41):id(1),principalLabel:'Synthetic '+i,workspaceLabel:'Synthetic firm '+i,
  buildReceipt:q.buildReceipt,isolationEvidence:q.dockerReceipt,backendRevision:isolation.backendRevision,webRevision:isolation.webRevision,
  gatewayRunId:isolation.gatewayRunId,gatewayUrl:isolation.gatewayUrl,webGatewayUrl:isolation.webGatewayUrl,apiOrigin:isolation.apiOrigin,browserApiMarkerVerified:true,
  auth:{webOrigin:isolation.webOrigin,mfaRequired:true,mode:'web-context',iosConsent:false,mfaStage:'consent',companySlug:'synthetic-'+i,emailEnv:'CASEOPS_MOBILE_QP_EMAIL_'+i,passwordEnv:'CASEOPS_MOBILE_QP_PASSWORD_'+i,totpSecretEnv:'CASEOPS_MOBILE_QP_TOTP_'+i},
  publicCa:{path:isolation.publicCA,sha256:'e'.repeat(64)}});
 const first=fixture(0),second=fixture(1),selectors={observed:true,udid:installed.udid,buildReceipt:q.buildReceipt};first.qp={inventoryId:QP.inventoryId,dataset,nativeSelectors:selectors};q.fixtureEvidence=r('fixture',first);
 const credentials=[];q.members=[first,second].map((f,i)=>{const credentialEvidence={path:'/synthetic/private'+i,sha256:'e'.repeat(64),uid:process.getuid()};const bytes=Buffer.from('synthetic private');const value={full_name:f.principalLabel,company_slug:f.auth.companySlug,email:'synthetic-'+i+'@example.invalid',password:'SYNTHETIC_ONLY',totp_secret:'JBSWY3DPEHPK3PXP'};credentials.push({path:credentialEvidence.path,bytes,value});
  const auth={observed:true,nativePrincipalVerified:true,nativeWorkspaceVerified:true,pkceUnchanged:true,logoutAcknowledged:true,sessionCleanup:'passed',udid:f.udid,bundleId:f.appId,membershipId:f.membershipId,binaryHash:q.expectedBinaryHash,importedSource:source,buildReceipt:q.buildReceipt,dockerReceipt:q.dockerReceipt,mfaStage:f.auth.mfaStage,iosConsent:f.auth.iosConsent};
  return{fixtureEvidence:r('member'+i,f),credentialEvidence,authObservation:r('auth'+i,auth)};});
 const authorityEvidence={path:'/synthetic/authority',sha256:'e'.repeat(64),uid:process.getuid()};
 const registration={kind:'registered-queue-privacy-controls',schemaVersion:1,observed:true,readyForLive:true,preparedOnly:false,sourceSha:source.sourceSha,runId:isolation.gatewayRunId,authorityEvidence,ownerRecipes:ownerRecipes(dataset),profile:QP.profile,implementationSha256:'e'.repeat(64),baseImplementationSha256:QP.baseSha256,caseControlLimits:QP.caseControls,syntheticIds:[...new Set([...dataset.tasks.flatMap(t=>[t.id,t.matter.id]),dataset.memberUserId,dataset.secondUserId,first.membershipId,first.companyId,second.membershipId,second.companyId])],
  actors:{member:{userId:dataset.memberUserId,membershipId:first.membershipId,companyId:first.companyId,credentialEvidence:q.members[0].credentialEvidence},'second-company':{userId:dataset.secondUserId,membershipId:second.membershipId,companyId:second.companyId,credentialEvidence:q.members[1].credentialEvidence}}};
 const code=['module','gatewayImplementationEvidence','baseImplementationEvidence'].map((name,i)=>({path:path.join(ROOT,'scripts/mobile',i===0?'queue-privacy-controls.mjs':i===1?'local-queue-privacy-controls.py':'local-v1-controls.py'),sha256:i===2?QP.baseSha256:'e'.repeat(64)}));
 const controls={observed:true,binaryHash:q.expectedBinaryHash,authorityEvidence,registrationSha256:'e'.repeat(64),protocol:V1_CONTROL_PROTOCOL,kind:'registered-queue-privacy-controls',profile:QP.profile,capabilities:QP.capabilities,caseControlLimits:QP.caseControls,sourceSha:source.sourceSha,runId:isolation.gatewayRunId,module:code[0],gatewayImplementationEvidence:code[1],baseImplementationEvidence:code[2],registrationEvidence:r('registration',registration)};
 registration.actors.owner={...dataset.actors.owner,credentialEvidence:{path:'/synthetic/owner',sha256:'e'.repeat(64),uid:process.getuid()}};
 controls.actorCredentialMappings={};const privateRefs=[authorityEvidence];
 for(const[name,actor]of Object.entries(registration.actors)){const host=actor.credentialEvidence,runtime={...host,path:'/fixture-state/'+path.basename(host.path),uid:0};controls.actorCredentialMappings[name]={hostEvidence:host,runtimeEvidence:runtime};privateRefs.push(host);actor.credentialEvidence=runtime;}
 registration.authorityEvidence={...authorityEvidence,path:'/fixture-state/authority',uid:0};
 registration.syntheticIds=[...new Set([...registration.syntheticIds,...Object.values(registration.actors).flatMap(a=>[a.companyId,a.membershipId,a.userId])])];
 controls.credentialMountEvidence=r('mount',{kind:'actual-native-client-cache-mount-metadata',observed:true,project:isolation.project,runId:isolation.gatewayRunId,hostRoot:'/synthetic',containerRoot:'/fixture-state',containerEffectiveUid:0,files:privateRefs.map(hostEvidence=>({hostEvidence,containerUid:0}))});
 q.controlsEvidence=r('controls',controls);q.codeClosure=r('closure',{code});const calls=[];
 const io={read:x=>{calls.push('read:'+x.path);assert.ok(map.has(x.path));return map.get(x.path);},bytes:x=>calls.push('code:'+x.path),snapshot:()=>source,inputs:()=>code.map(x=>path.relative(ROOT,x.path)).sort(),harness:()=>q.expectedHarnessFingerprint,
  installed:()=>installed,artifactHash:()=>q.expectedBinaryHash,environment:{NODE_EXTRA_CA_CERTS:isolation.publicCA},
  getJson:async url=>{calls.push('endpoint:'+url);if(url.endsWith('/api/build'))return{release_sha:source.sourceSha,revision:'api'};if(url.endsWith('/api/release-identity'))return{release_sha:source.sourceSha,revision:'web'};return{runId:isolation.gatewayRunId,v1ControlsEnabled:true,v1ControlProfile:QP.profile,v1ControlsImplementationSha256:'e'.repeat(64),v1RegistrationSha256:controls.registrationEvidence.sha256};},
  reader:file=>{calls.push('PRIVATE:'+file);const c=credentials.find(x=>x.path===file);return{bytes:c.bytes,value:c.value,sha256:'e'.repeat(64),uid:process.getuid()};}};
 return{q,io,map,source,first,second,dataset,controls,registration,credentials,calls,writeEvidence,publicRoot,run:()=>admitQPBeforeMembers(q,io),close:p.close};
}
test('Queue normal authentication permits refresh without admitting formal business writes',()=>{
 assert.equal(Object.isFrozen(QP_AUTH_AND_NATIVE_BASE_ROUTES),true);
 assert.deepEqual(QP_AUTH_AND_NATIVE_BASE_ROUTES,[
  'GET /api/account/deletion-requests','GET /api/auth/me','GET /api/auth/native/compatibility',
  'GET /api/auth/native/sessions','GET /api/build','GET /api/matter-work-queue','GET /api/me/today',
  'POST /api/auth/native/logout','POST /api/auth/native/refresh','POST /api/auth/native/token',
 ]);
 assert.equal(new Set(QP_AUTH_AND_NATIVE_BASE_ROUTES).size,10);
 assert.deepEqual(QP_AUTH_AND_NATIVE_BASE_ROUTES.filter(route=>!route.startsWith('GET ')),[
  'POST /api/auth/native/logout','POST /api/auth/native/refresh','POST /api/auth/native/token',
 ]);
 assert.equal(QP_AUTH_AND_NATIVE_BASE_ROUTES.some(route=>/billing|provider|\*|\{|notes/.test(route)),false);
});
test('literal independent two-case inventory and original17 budgets remain separate',()=>{for(const platform of['android','ios']){const c=collectQueuePrivacy(platform);assert.deepEqual(c.intended,[platform+':QUEUE-01',platform+':PRIVACY-01']);assert.equal(c.expectedPhases,6);assert.equal(c.expectedSessions,2);}assert.equal(QP.totalControls,49);assert.equal(Object.values(QP_CALL_INVENTORY['QUEUE-01']).reduce((a,b)=>a+b),18);assert.equal(Object.values(QP_CALL_INVENTORY['PRIVACY-01']).reduce((a,b)=>a+b),17);const old=fs.readFileSync(path.join(ROOT,'apps/mobile/e2e/v1-workflows-inventory.mjs'),'utf8');assert.match(old,/expectedPhases: 51/);assert.match(old,/264/);});
test('actual producer creates35tasks and complete74HTTP53POST1PATCH inventory with private peers first',async()=>{const x=producerDouble();try{const d=await x.run();assert.equal(x.calls.length,62);assert.equal(d.requests,74);assert.equal(d.posts,53);assert.equal(d.patches,1);assert.equal(d.admissions,12);assert.equal(d.tasks.length,35);assert.equal(d.pages.length,10);assert.equal(d.tasks.filter(x=>x.role==='excluded').length,4);assert.equal(x.privateFiles.length,2);assert.equal(x.claims.length,1);assert.equal(JSON.stringify(x.events).includes('Aa1!'),false);assert.equal(QP_PRODUCER.requests,74);}finally{x.close();}});
test('completed task uses the Matter task write status and stays out of every queue page',async()=>{
 const x=producerDouble();
 try{
  const dataset=await x.run();
  const writes=x.calls.filter(call=>call.method==='POST'&&call.route===`/api/matters/${dataset.matter.id}/tasks`&&call.body.status==='completed');
  assert.equal(writes.length,1);
  assert.equal(writes[0].body.owner_membership_id,x.plan.membershipId);
  const completed=dataset.tasks.filter(task=>task.status==='completed');
  assert.equal(completed.length,1);
  assert.equal(completed[0].role,'excluded');
  assert.equal(completed[0].owner_membership_id,x.plan.membershipId);
  assert.equal(completed[0].matter.id,dataset.matter.id);
  assert.ok(dataset.pages.every(page=>page.value.items.every(item=>item.id!==completed[0].id)));
 }finally{x.close();}
});
function hostProducerDouble(){
 const x=producerDouble(),root=path.dirname(x.plan.privatePeerFiles[0]),effects=[],source={sourceSha:x.plan.sourceSha,sourceFingerprint:'b'.repeat(64),inputFileCount:226,sourceDirty:false};
 const actors=Object.fromEntries([['owner',id(1),id(3),id(7)],['member',id(1),id(2),id(5)],['second-company',id(41),id(40),id(6)],['foreign-owner',id(41),id(4),id(8)]].map(([name,companyId,membershipId,userId])=>[name,{companyId,membershipId,userId,credentialEvidence:{path:'/synthetic/'+name+'.json',sha256:'e'.repeat(64),uid:process.getuid()}}]));
 const admission={repoRoot:ROOT,platform:'ios',source,...Object.fromEntries(['buildReceipt','dockerReceipt','installedEvidence','codeClosure'].map(k=>[k,x.plan[k]])),publicCa:{path:'/synthetic/ca',sha256:'d'.repeat(64)}};
 const q={...pendingQueuePrivacyHost(),readyForLive:true,preparedOnly:false,platform:'ios',outputRoot:root,plan:x.plan,admission,actors};
 const publics={source,installed:{binaryHash:'c'.repeat(64)},build:{binaryHash:'c'.repeat(64),apiOrigin:'https://127.0.0.1:8643',webOrigin:'https://127.0.0.1:3643'},docker:{platform:'ios',apiOrigin:'https://127.0.0.1:8643',webOrigin:'https://127.0.0.1:3643',gatewayUrl:'https://127.0.0.1:8643',webGatewayUrl:'https://127.0.0.1:3643',gatewayRunId:x.plan.runId,backendRevision:'api',webRevision:'web'}};
 const io={environment:{CASEOPS_NATIVE_QUEUE_PRIVACY_PRODUCER_GO:'EXPLICIT_OWNED_SYNTHETIC_PRODUCER'},now:()=>1000,
  read:ref=>ref===x.plan.baseActorEvidence?{sourceSha:x.plan.sourceSha,runId:x.plan.runId,actors}:{sourceSha:x.plan.sourceSha,runId:x.plan.runId,admission},
  admitPublic:async()=>{effects.push('public-native');return structuredClone(publics);},store:createProducerStore,
  http:options=>{assert.equal(options.deadlineMs,181000);assert.equal(options.apiOrigin,publics.docker.gatewayUrl);assert.equal(options.webOrigin,publics.docker.webGatewayUrl);effects.push('http-created');return{clear:()=>effects.push('cleared'),
   login:async(actor,ref,opts)=>{assert.equal(opts.includeIdentity,false);assert.deepEqual(ref,actors[actor].credentialEvidence);assert.equal(effects.at(-1),'public-native');effects.push('private-login:'+actor);opts.charge({method:'POST'});opts.charge({method:'POST'});return{user:{id:actors[actor].userId,is_active:true},membership:{id:actors[actor].membershipId,is_active:true,role:actor.includes('owner')?'owner':'member'},company:{id:actors[actor].companyId,is_active:true},capabilities:['company:manage_users','teams:manage','matters:create','matters:write','matters:archive']};},
   request:async({actor,method,route,body,web,...requestOptions})=>{if(route==='/api/build'||route==='/api/release-identity'){effects.push('live-'+(web?'web':'api'));return{status:200,value:{release_sha:x.plan.sourceSha,revision:web?'web':'api'}};}effects.push('business:'+method);return x.io.request(actor,method,route,body,requestOptions);}};},
  produce:(plan,callbacks)=>produceQueuePrivacy(plan,{...callbacks,persistPrivate:x.io.persistPrivate})};
 return{...x,q,io,effects,root,publics,run:()=>runQueuePrivacyProducer(q,io)};
}
test('runnable QP host dispatches the actual74-call recipe and retains exclusive claim, acknowledgements and dataset',async()=>{
 const x=hostProducerDouble();try{const result=await x.run(),dataset=JSON.parse(fs.readFileSync(result.datasetEvidence.path));
  assert.equal(dataset.requests,74);assert.equal(dataset.admissions,12);assert.equal(dataset.posts,53);assert.equal(dataset.patches,1);assert.equal(dataset.actors.owner.userId,id(7));assert.equal(x.calls.length,62);assert.equal(x.effects.filter(v=>v.startsWith('private-login:')).length,4);assert.equal(x.effects.filter(v=>v==='live-api').length,2);assert.equal(x.effects.filter(v=>v==='live-web').length,2);assert.equal(x.effects.at(-1),'cleared');
  assert.equal(fs.statSync(result.datasetEvidence.path).mode&0o777,0o600);assert.equal(fs.readdirSync(x.root).filter(v=>v.endsWith('.claim.json')).length,1);assert.equal(result.actualNativeAcceptance,false);
  const publicFiles=fs.readdirSync(x.root).filter(n=>!n.startsWith('peer-')).map(n=>fs.readFileSync(path.join(x.root,n),'utf8')).join('');assert.equal(publicFiles.includes('Aa1!'),false);
  const calls=x.calls.length;await assert.rejects(x.run());assert.equal(x.calls.length,calls);
 }finally{x.close();}
 const emulator=hostProducerDouble();try{emulator.q.platform=emulator.q.admission.platform='android';Object.assign(emulator.publics.build,{apiOrigin:'https://10.0.2.2:8743',webOrigin:'https://10.0.2.2:3743'});Object.assign(emulator.publics.docker,{platform:'android',androidTransportMode:'emulator',apiOrigin:emulator.publics.build.apiOrigin,webOrigin:emulator.publics.build.webOrigin,gatewayUrl:'https://127.0.0.1:8743',webGatewayUrl:'https://127.0.0.1:3743'});const result=await emulator.run();assert.equal(JSON.parse(fs.readFileSync(result.datasetEvidence.path)).requests,74);assert.equal(emulator.publics.build.apiOrigin,'https://10.0.2.2:8743');assert.equal(emulator.effects.filter(v=>v==='http-created').length,1);}finally{emulator.close();}
 const mismatch=hostProducerDouble();try{mismatch.publics.docker.gatewayUrl='https://127.0.0.1:9999';await assert.rejects(mismatch.run(),/QP_HOST_MOBILE_PORT_MAPPING_REQUIRED/);assert.equal(mismatch.effects.includes('http-created'),false);assert.equal(mismatch.calls.length,0);}finally{mismatch.close();}
});
test('QP host pending admission is zero-effect and unknown normal POST retains one claim without dataset or replay',async()=>{
 let effects=0;await assert.rejects(runQueuePrivacyProducer(pendingQueuePrivacyHost(),{read:()=>effects++,admitPublic:()=>effects++,store:()=>effects++,http:()=>effects++}));assert.equal(effects,0);
 const cli=path.join(ROOT,'scripts/mobile/produce-queue-privacy-fixture.mjs'),pending=spawnSync(process.execPath,[cli,'--pending'],{encoding:'utf8',timeout:10000,maxBuffer:65536});assert.equal(pending.status,0,pending.stderr);assert.equal(JSON.parse(pending.stdout).readyForLive,false);
 const dir=fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'qp-cli-refusal-'));try{const file=path.join(dir,'pending.json'),bytes=Buffer.from(pending.stdout);fs.writeFileSync(file,bytes,{mode:0o600,flag:'wx'});const refused=spawnSync(process.execPath,[cli,'--request',file,hash(bytes)],{encoding:'utf8',timeout:10000,maxBuffer:65536});assert.equal(refused.status,1);assert.equal(refused.stdout,'');assert.match(refused.stderr,/QUEUE_PRIVACY_PRODUCER_REFUSED_OR_UNKNOWN_NO_REPLAY/);assert.deepEqual(fs.readdirSync(dir),['pending.json']);}finally{fs.rmSync(dir,{recursive:true,force:true});}
 const x=hostProducerDouble();try{
  let posts=0;const original=x.io.produce;x.io.produce=(plan,callbacks)=>original(plan,{...callbacks,request:async(...args)=>{if(args[1]==='POST'){posts++;throw Error('SYNTHETIC_POST_ACK_LOST');}return callbacks.request(...args);}});
  await assert.rejects(x.run(),/SYNTHETIC_POST_ACK_LOST/);assert.equal(posts,1);assert.equal(fs.readdirSync(x.root).filter(n=>n.endsWith('.claim.json')).length,1);assert.equal(fs.readdirSync(x.root).some(n=>n.endsWith('.dataset.json')),false);assert.equal(x.effects.at(-1),'cleared');await assert.rejects(x.run());assert.equal(posts,1);
 }finally{x.close();}
 const expired=hostProducerDouble();try{let clock=1000,observations=0;expired.io.now=()=>clock;const admit=expired.io.admitPublic;expired.io.admitPublic=async(...args)=>{const result=await admit(...args);if(++observations===3)clock=181000;return result;};await assert.rejects(expired.run(),/PRODUCER_DEADLINE_EXPIRED/);assert.equal(expired.effects.some(v=>v.startsWith('private-login:')),false);assert.equal(expired.effects.at(-1),'cleared');assert.equal(fs.readdirSync(expired.root).some(n=>n.endsWith('.dataset.json')),false);}finally{expired.close();}
 const publicExpired=hostProducerDouble();try{let clock=1000,observations=0,charges=0;publicExpired.io.now=()=>clock;const admit=publicExpired.io.admitPublic;publicExpired.io.admitPublic=async(...args)=>{const result=await admit(...args);if(++observations===2)clock=181000;return result;};publicExpired.io.produce=async(plan,callbacks)=>{callbacks.claim('offline-expired-admission');await callbacks.admit(plan,{boundary:'before',charge:()=>charges++});};await assert.rejects(publicExpired.run(),/PRODUCER_DEADLINE_EXPIRED/);assert.equal(charges,0);assert.equal(publicExpired.effects.some(v=>v.startsWith('live-')||v.startsWith('private-login:')),false);assert.equal(publicExpired.calls.length,0);assert.equal(publicExpired.effects.at(-1),'cleared');}finally{publicExpired.close();}
 for(const missing of['role','capability']){const denied=hostProducerDouble();try{const make=denied.io.http;denied.io.http=options=>{const client=make(options),login=client.login;client.login=async(...args)=>{const value=await login(...args);if(missing==='role')value.membership.role='member';else value.capabilities=[];return value;};return client;};await assert.rejects(denied.run(),/QP_CURRENT_OWNER_(ROLE|CAPABILITY)_REQUIRED/);assert.equal(denied.calls.length,0);assert.equal(denied.effects.at(-1),'cleared');assert.equal(fs.readdirSync(denied.root).some(n=>n.endsWith('.dataset.json')),false);}finally{denied.close();}}
});
test('public QP registration projects observed actor IDs and exact mount ownership into the actual Python validator',async()=>{
 const x=await admissionDouble();try{Object.assign(x.map.get(x.q.dockerReceipt.path),{productionAccessed:false});
  const q={kind:'compose-queue-privacy-registration',preparedOnly:true,datasetEvidence:x.q.producerEvidence,dockerReceipt:x.q.dockerReceipt,buildReceipt:x.q.buildReceipt,codeClosure:x.q.codeClosure,credentialMountEvidence:x.controls.credentialMountEvidence,authorityEvidence:x.controls.authorityEvidence,expiresAt:1200,
   actors:Object.fromEntries(['owner','member','second-company'].map(name=>[name,{...x.dataset.actors[name],credentialEvidence:x.controls.actorCredentialMappings[name].hostEvidence}]))};
  const io={read:x.io.read,bytes:x.io.bytes,snapshot:x.io.snapshot,now:()=>1000},r=composeQPRegistration(q,io);assert.equal(r.privateReads,0);assert.equal(r.registration.actors.member.credentialEvidence.path,'/fixture-state/private0');assert.equal(r.registration.actors.member.credentialEvidence.uid,0);assert.equal(r.descriptor.actorCredentialMappings.member.hostEvidence.uid,process.getuid());assert.equal(r.registration.ownerExactRoutes.length,3);
  const script="import json,sys;from types import ModuleType;from pathlib import Path;p=ModuleType('qp');exec(compile(Path(sys.argv[1]).read_bytes(),sys.argv[1],'exec'),p.__dict__);v=json.load(sys.stdin);p.validate_registration(v,source=v['sourceSha'],run=v['runId'],now=1000)";
  const deadline=performance.now()+10000,python=fixturePython(deadline);
  const native=spawnSync(python,['-c',script,path.join(ROOT,'scripts/mobile/local-queue-privacy-controls.py')],{input:JSON.stringify(r.registration),encoding:'utf8',timeout:producerTimeout(deadline-performance.now()),maxBuffer:65536,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});pythonCompleted(native,'actual-queue-registration-validator');assert.equal(x.calls.some(v=>v.startsWith('PRIVATE:')),false);
  for(const mutate of[v=>v.actors.owner.userId=id(99),v=>v.expiresAt=2000,v=>v.credentialMountEvidence=x.q.buildReceipt]){const bad=structuredClone(q);mutate(bad);assert.throws(()=>composeQPRegistration(bad,io));}
  const mount=x.map.get(q.credentialMountEvidence.path);mount.files.push(structuredClone(mount.files[0]));assert.throws(()=>composeQPRegistration(q,io));
 }finally{x.close();}
});
test('pending producer has zero claim private write transport or admission calls',async()=>{let calls=0;const f=()=>{calls++;};await assert.rejects(produceQueuePrivacy(pendingProducer(),{request:f,admit:f,persist:f,claim:f,persistPrivate:f}));assert.equal(calls,0);});
test('unknown API acknowledgement consumes one claim and never replays or continues',async()=>{const x=producerDouble();try{let calls=0;x.io.request=async()=>{calls++;throw Error('SYNTHETIC_UNKNOWN');};await assert.rejects(x.run(),/SYNTHETIC_UNKNOWN/);assert.equal(calls,1);assert.equal(x.claims.length,1);assert.equal(x.events.filter(e=>e.type==='qp_fixture_completed').length,0);await assert.rejects(x.run());assert.equal(calls,1);}finally{x.close();}});
test('malformed or wrong-tenant page cannot become a complete fixture',async()=>{const x=producerDouble();try{const old=x.io.request;x.io.request=async(...args)=>{const r=await old(...args);if(args[2].startsWith('/api/matter-work-queue'))r.value.scope='all_company_tasks';return r;};await assert.rejects(x.run());assert.equal(x.events.some(e=>e.type==='qp_fixture_completed'),false);}finally{x.close();}});
test('private peer creation is0600underumask0 and refuses symlink and existing files',()=>{const dir=fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'qp-private-'));const original=process.umask(0);try{const file=path.join(dir,'private.json'),value={password:'SYNTHETIC_ONLY'};const r=writePrivatePeer(file,value);assert.equal(fs.statSync(file).mode&0o777,0o600);assert.equal(r.createdBeforeFirstPost,true);assert.throws(()=>writePrivatePeer(file,value));const link=path.join(dir,'link');fs.symlinkSync(file,link);assert.throws(()=>writePrivatePeer(link,value));assert.deepEqual(JSON.parse(fs.readFileSync(file)),value);}finally{process.umask(original);fs.rmSync(dir,{recursive:true});}});
test('independent order retains microseconds and exact IDs instead of millisecond or insertion order',()=>{const row=(n,stamp)=>({id:id(n),role:'mine',owner_membership_id:id(1),due_on:'2027-01-01',created_at:stamp});const a=row(9,'2026-10-27T00:00:00.100001Z'),b=row(1,'2026-10-27T00:00:00.1+00:00');assert.deepEqual(expectedQueue([a,b],'mine','all',id(1),id(2)).map(x=>x.id),[b.id,a.id]);});
test('real profile owner recipes contain only exact anchor normal APIs and current version selectors',async()=>{const x=producerDouble();try{const d=await x.run(),r=ownerRecipes(d);assert.equal(r.length,2);assert.deepEqual(r.map(x=>x.id),['change','restore']);for(const recipe of r){assert.deepEqual(recipe.requests.map(x=>x.method),['GET','GET','PATCH']);assert.deepEqual(Object.keys(recipe.requests[2].body).sort(),['due_on','expected_lifecycle_version','expected_updated_at']);assert.ok(recipe.requests.every(x=>!x.route.includes('/account/')));}}finally{x.close();}});
test('public source installed API ANDweb precede EACH actual protected-reader callback and buffers clear',async()=>{const x=await admissionDouble();try{const r=await x.run();assert.equal(r.members.length,2);assert.equal(x.calls.filter(x=>x.startsWith('PRIVATE:')).length,2);for(let i=0;i<x.calls.length;i++)if(x.calls[i].startsWith('PRIVATE:')){assert.match(x.calls[i-3],/api\/build$/);assert.match(x.calls[i-2],/api\/release-identity$/);assert.match(x.calls[i-1],/__caseops_e2e\/status$/);}assert.ok(x.credentials.every(c=>c.bytes.every(b=>b===0)));}finally{x.close();}});
test('QP admits freshly owned actors without Core-only records while Core still refuses', async () => {
 const x=await admissionDouble();
 try {
  for(const f of [x.first,x.second]) for(const key of ['coreInventory','seedEvidence','matter','today','work','calendar','foreignMatter','lifecycleMatter','accessMatter']) assert.equal(f[key],undefined);
  const secondAuth=x.map.get(x.q.members[1].authObservation.path);
  secondAuth.appId=secondAuth.bundleId;delete secondAuth.bundleId;
  const result=await x.run(); assert.equal(result.members.length,2);
  assert.deepEqual(result.members.map(member=>member.fixture.membershipId),[x.dataset.membershipId,x.dataset.actors['second-company'].membershipId]);
  const f=x.first, value=x.credentials[0].value;
  const environment={ [f.auth.emailEnv]:value.email,[f.auth.passwordEnv]:value.password,[f.auth.totpSecretEnv]:value.totp_secret };
  assert.throws(()=>validateCoreFixture(f,environment),/DATED_CORE_FIXTURE_REQUIRED/);
  assert.throws(()=>validateBuildReceipt(f,'ios',x.q.expectedBinaryHash),/DATED_CORE_FIXTURE_REQUIRED/);
  const docker=x.writeEvidence(path.join(x.publicRoot,'core-isolation.json'),x.map.get(x.q.dockerReceipt.path));
  const core={...f,coreInventory:'native-core-2026-10-25',isolationEvidence:docker};
  assert.throws(()=>validateCoreFixture(core,environment),/SEEDED_MATTER_ID_REQUIRED/);
  core.matter={id:id(70),identityLabel:'SYNTHETIC',title:'Synthetic matter',searches:[
   {kind:'matter_code',value:'SYNTHETIC'},{kind:'case_number',value:'SYNTHETIC-CASE'},{kind:'filing_number',value:'SYNTHETIC-FILE'},
   {kind:'cnr_number',value:'SYNTHETIC-CNR'},{kind:'temporary_e_case_number',value:'SYNTHETIC-E'},
  ]};
  assert.throws(()=>validateCoreFixture(core,environment),/SEEDED_WORK_ID_REQUIRED/);
 } finally {x.close();}
});
test('QP Android attestation verifies installed bytes without admitting a Core fixture or reinstalling', () => {
 const fixture={environment:'docker-integration',syntheticDataOnly:true,udid:'CASEOPSUNITUSB01',
  appId:'ai.caseops.mobile.dev.localacceptance',appPath:'/synthetic/CaseOps.apk'};
 const expected='c'.repeat(64),apk='/data/app/owned/base.apk',calls=[];
 const command=(program,args,options)=>{
  assert.equal(program,'adb');assert.equal(options.shell,false);assert.deepEqual(args.slice(0,2),['-s',fixture.udid]);
  const route=args.slice(2);calls.push(route);
  if(route[1]==='pm'&&route[2]==='list')return 'package:'+fixture.appId+'\n';
  if(route[1]==='pm'&&route[2]==='path')return 'package:'+apk+'\n';
  assert.deepEqual(route,['shell','sha256sum',apk]);return expected+'  '+apk+'\n';
 };
 assert.throws(()=>attestAndroidBinary(fixture,expected,{command}),/DATED_CORE_FIXTURE_REQUIRED/);
 assert.throws(()=>attestLocalQAAndroidBinary({...fixture,appId:'ai.caseops.mobile.dev'},expected,{command}),/DEDICATED_LOCAL_QA_APP_REQUIRED/);
 assert.equal(calls.length,0);
 const receipt=attestLocalQAAndroidBinary(fixture,expected,{command});
 assert.equal(receipt.installedApkSha256,expected);assert.equal(receipt.explicitReplaceInstall,false);
 assert.throws(()=>attestLocalQAAndroidBinary(fixture,'d'.repeat(64),{command}),/INSTALLED_ANDROID_APK_HASH_MISMATCH/);
 assert.deepEqual(calls.map(args=>args[0]),Array(6).fill('shell'));
});
test('QP public actor auth identity device and TLS failures refuse before either credential read', async () => {
 const cases=[
  [(x,auth)=>{delete x.second.auth.mfaStage;},/EXPLICIT_MFA_STAGE_REQUIRED/],
  [(x,auth)=>{delete x.second.auth.companySlug;},/FIXTURE_WORKSPACE_SLUG_REQUIRED/],
  [(x,auth)=>{x.second.auth.mode='native-firefox';},/FIREFOX_RECIPE_INCOMPLETE/],
  [(x,auth)=>{delete x.second.workspaceLabel;},/QP_ACTUAL_ACTOR_AND_DEVICE_LABELS_REQUIRED/],
  [(x,auth)=>{x.second.membershipId=x.first.membershipId;},/QP_ACTOR_MEMBERSHIP_CHANGED/],
  [(x,auth)=>{x.second.browserApiMarkerVerified=false;},/BROWSER_API_MARKER_RECEIPT_REQUIRED/],
  [(x,auth)=>{auth.nativePrincipalVerified=false;},/QP_ACTUAL_BROWSER_AUTH_OBSERVATION_REQUIRED/],
  [(x,auth)=>{auth.appId=x.second.appId;auth.bundleId='wrong';},/QP_AUTH_APP_ID_CHANGED/],
  [(x,auth)=>{x.second.auth.webOrigin='http://127.0.0.1:3443';},/QP_ACTOR_BROWSER_ORIGIN_CHANGED/],
  [(x,auth)=>{x.map.get(x.q.dockerReceipt.path).tlsProof.verificationDisabled=true;},/QP_STRICT_GATEWAY_TLS_REQUIRED/],
 ];
 for(const [mutate,pattern] of cases){
  const x=await admissionDouble();
  try {mutate(x,x.map.get(x.q.members[1].authObservation.path));await assert.rejects(x.run(),pattern);
   assert.equal(x.calls.some(call=>call.startsWith('PRIVATE:')),false);}
  finally{x.close();}
 }
});
test('QP still validates protected MFA and clears both actor values on a failed check', async () => {
 const x=await admissionDouble();
 try {
  x.credentials[1].value.totp_secret='INVALID';
  await assert.rejects(x.run(),/SYNTHETIC_TOTP_SECRET_REQUIRED/);
  assert.equal(x.calls.filter(call=>call.startsWith('PRIVATE:')).length,2);
  assert.ok(x.credentials.every(c=>c.bytes.every(byte=>byte===0)&&Object.values(c.value).every(value=>value===undefined)));
 } finally{x.close();}
});
test('pending old-source or wrong public installed admission refuses before any reader',async()=>{const x=await admissionDouble();try{for(const change of[q=>q.readyForLive=false,q=>q.expectedSourceSha='f'.repeat(40),q=>q.expectedInputFileCount=120]){const q=structuredClone(x.q);change(q);const calls=x.calls.length;await assert.rejects(admitQPBeforeMembers(q,x.io));assert.equal(x.calls.slice(calls).some(x=>x.startsWith('PRIVATE:')),false);}}finally{x.close();}});
test('serving API ORweb drift and wrong active controlprofile are zero-reader refusals',async()=>{for(const target of['api','web','profile']){const x=await admissionDouble();try{const old=x.io.getJson;x.io.getJson=async url=>{const r=await old(url);if(target==='api'&&url.endsWith('/api/build'))r.revision='wrong';if(target==='web'&&url.endsWith('/api/release-identity'))r.release_sha='f'.repeat(40);if(target==='profile'&&url.endsWith('/status'))r.v1ControlProfile='source-work-v3';return r;};await assert.rejects(x.run());assert.equal(x.calls.some(x=>x.startsWith('PRIVATE:')),false);}finally{x.close();}}});
test('second reader refusal purges already loaded first member and never creates native session',async()=>{const x=await admissionDouble();try{const old=x.io.reader;x.io.reader=file=>{if(file.endsWith('1'))throw Error('SYNTHETIC_PRIVATE_REFUSAL');return old(file);};await assert.rejects(x.run(),/SYNTHETIC_PRIVATE_REFUSAL/);assert.equal(x.credentials[0].value.password,undefined);assert.ok(x.credentials[0].bytes.every(b=>b===0));}finally{x.close();}});
test('actor environment is restored exactly on success and original failure',async()=>{const name='CASEOPS_MOBILE_QP_UNIT_EMAIL';const old=process.env[name];process.env[name]='prior';try{const member={fixture:{auth:{emailEnv:name,passwordEnv:'CASEOPS_MOBILE_QP_UNIT_PASS',totpSecretEnv:'CASEOPS_MOBILE_QP_UNIT_TOTP'}},value:{email:'new',password:'SYNTHETIC_ONLY',totp_secret:'SYNTHETIC_ONLY'}};await assert.rejects(withQPActor(member,async()=>{assert.equal(process.env[name],'new');throw Error('original');}),/original/);assert.equal(process.env[name],'prior');assert.equal(process.env.CASEOPS_MOBILE_QP_UNIT_PASS,undefined);}finally{if(old===undefined)delete process.env[name];else process.env[name]=old;}});
test('receipt validation requires exact operation and received false-completion UTC contract',()=>{const r={id:id(1),operation_id:id(2),request_type:'account_deletion',status:'received',requested_at:'2026-10-27T12:00:00.123456Z',deletion_completed:false};assert.deepEqual(decodeAccountDeletionReceipt(r),r);for(const change of[v=>v.deletion_completed=true,v=>v.status='completed',v=>v.requested_at='2026-10-27T12:00:00']){const v={...r};change(v);assert.throws(()=>decodeAccountDeletionReceipt(v));}});
test('native scenarios dispatch through original-ID raw helper without element.click or generic case filters',()=>{const text=fs.readFileSync(new URL('./queue-privacy.mjs',import.meta.url),'utf8'),runner=fs.readFileSync(path.join(ROOT,'scripts/mobile/run-queue-privacy.mjs'),'utf8');assert.equal(queuePrivacyScenarios.length,2);assert.match(text,/dispatchNativeClick/);assert.doesNotMatch(text,/\.click\(/);assert.doesNotMatch(runner,/--case|--grep/);assert.match(runner,/connectionRetryCount:0/);assert.match(text,/attempt<4/);assert.match(text,/upstreamStatus,202/);});
test('measured Android Compose queue labels resolve one contained radio parent and dispatch its raw ID once', async () => {
  // Sanitized Appium Android 16 readback on the 1080x2424 QA device. Each row
  // contains label, checked/clickable flags, parent frame and text frame.
  const captured = JSON.parse(`{
    "queue":[53,692,975,1467],
    "segments":[
      ["Mine","true","false",[53,836,327,126],[211,878,79,43]],
      ["Team","false","true",[380,836,321,126],[495,878,91,43]],
      ["Unassigned","false","true",[701,836,327,126],[770,878,189,43]],
      ["All dates","true","false",[53,1075,327,126],[181,1117,140,43]],
      ["Dated","false","true",[380,1075,321,126],[493,1117,95,43]],
      ["Undated","false","true",[701,1075,327,126],[798,1117,134,43]]
    ]
  }`);
  const appId = 'ai.caseops.mobile.dev.localacceptance';
  const rect = ([x, y, width, height]) => ({ x, y, width, height });
  const node = (elementId, attrs = {}, enabled = true) => ({ elementId, isDisplayed: async () => true,
    isEnabled: async () => enabled, getAttribute: async (name) => attrs[name],
    click: async () => { throw new Error('RAW_CLICK_REQUIRED'); } });
  const frames = new Map([['queue', rect(captured.queue)]]);
  const queries = new Map([['id=screen-work', [node('work')]], ['id=matter-task-queue', [node('queue')]]]);
  const selectors = { 'Task ownership': {}, 'Task dates': {} };
  for (const [index, [label, checked, clickable, parentFrame, labelFrame]] of captured.segments.entries()) {
    const group = index < 3 ? 'Task ownership' : 'Task dates';
    const query = `//*[@class='android.widget.TextView' and @text='${label}']`;
    frames.set(`radio-${index}`, rect(parentFrame));
    frames.set(`label-${index}`, rect(labelFrame));
    queries.set(query, [node(`label-${index}`)]);
    queries.set(`${query}/parent::*`, [node(`radio-${index}`, { package: appId, checkable: 'true', checked, clickable })]);
    selectors[group][label] = { kind: 'android-compose-parent', group, label, selectedAtObservation: checked === 'true' };
  }
  const dispatches = [];
  const driver = { $$: async (query) => queries.get(query) ?? [], getElementRect: async (id) => frames.get(id),
    elementClick: async (id) => dispatches.push(id) };
  const udid = 'captured-android-emulator';
  const buildReceipt = { path: '/synthetic/build', sha256: 'a'.repeat(64) };
  const c = { platform: 'android', driver, nativeOperations: 0, fixture: { appId, udid, buildReceipt,
    qp: { nativeSelectors: { observed: true, udid, buildReceipt, segments: selectors } } } };
  for (const [group, options] of Object.entries(selectors)) {
    for (const [label, recipe] of Object.entries(options)) {
      const { selected } = await resolveAndroidComposeQueueSegment(c, group, label);
      assert.equal(selected, recipe.selectedAtObservation);
    }
  }
  assert.deepEqual(dispatches, []);
  assert.equal(c.nativeOperations, 0);
  await selectQueueSegment(c, 'Task ownership', 'Team');
  assert.deepEqual(dispatches, ['radio-1']);
  assert.equal(c.nativeOperations, 1);
  await assert.rejects(selectQueueSegment(c, 'Task ownership', 'Mine'), /QP_ANDROID_QUEUE_TRANSITION_ALREADY_SELECTED/);
  await assert.rejects(resolveAndroidComposeQueueSegment(c, 'Task dates', 'Team'), /QP_ANDROID_QUEUE_LABEL_REQUIRED/);
  const parentQuery = "//*[@class='android.widget.TextView' and @text='Team']/parent::*";
  const parents = queries.get(parentQuery);
  queries.set(parentQuery, [...parents, node('second-parent')]);
  await assert.rejects(selectQueueSegment(c, 'Task ownership', 'Team'), /QP_ANDROID_EXACT_QUEUE_PARENT_REQUIRED/);
  queries.set(parentQuery, [node('radio-1', {}, false)]);
  await assert.rejects(selectQueueSegment(c, 'Task ownership', 'Team'), /QP_ANDROID_QUEUE_PARENT_DISABLED/);
  queries.set(parentQuery, parents);
  frames.set('radio-1', { ...frames.get('radio-1'), y: 300 });
  await assert.rejects(selectQueueSegment(c, 'Task ownership', 'Team'), /QP_ANDROID_QUEUE_PARENT_OUTSIDE_SCOPE/);
  assert.deepEqual(dispatches, ['radio-1']);
  frames.set('radio-1', rect(captured.segments[1][3]));
  const lost = new Error('original native acknowledgement lost');
  driver.elementClick = async (id) => { dispatches.push(id); throw lost; };
  await assert.rejects(selectQueueSegment(c, 'Task ownership', 'Team'), (error) => error === lost);
  assert.deepEqual(dispatches, ['radio-1', 'radio-1']);
  assert.equal(c.nativeOperations, 2);
});

test('iOS observed queue segment keeps its native exact-label locator and original dispatch identity', async () => {
  const query = '-ios predicate string:label == "Team"';
  const group = 'Task ownership';
  const label = 'Team';
  const udid = 'synthetic-ios';
  const buildReceipt = { path: '/synthetic/ios-build', sha256: 'b'.repeat(64) };
  const selectors = { observed: true, udid, buildReceipt,
    segments: { [group]: { [label]: { group, label, query, labelAttribute: 'label' } } } };
  const lookups = [], dispatches = [];
  const driver = {
    $$: async (wanted) => { lookups.push(wanted); return [{ elementId: 'ios-original', isDisplayed: async () => true,
      getAttribute: async (attribute) => { assert.equal(attribute, 'label'); return label; } }]; },
    elementClick: async (id) => dispatches.push(id),
  };
  await selectQueueSegment({ platform: 'ios', driver, nativeOperations: 0,
    fixture: { udid, buildReceipt, qp: { nativeSelectors: selectors } } }, group, label);
  assert.deepEqual(lookups, [query]);
  assert.deepEqual(dispatches, ['ios-original']);
});

test('control client single receipt read has no hidden20poll and enforces case+cleanup bounds',async()=>{const previous=process.env.NODE_EXTRA_CA_CERTS;process.env.NODE_EXTRA_CA_CERTS='/synthetic/ca';try{let calls=0,reads=0;const fixture={binarySourceSha:'a'.repeat(40),gatewayRunId:'qp-run',gatewayUrl:'https://127.0.0.1:8443',publicCa:{path:'/synthetic/ca'}},descriptor={profile:QP.profile,kind:'registered-queue-privacy-controls',observed:true,sourceSha:fixture.binarySourceSha,runId:fixture.gatewayRunId,binaryHash:'b'.repeat(64),capabilities:QP.capabilities,protocol:V1_CONTROL_PROTOCOL,origin:'https://127.0.0.1:8443',authorityEvidence:{path:'/synthetic/private',sha256:'c'.repeat(64),uid:process.getuid()},registrationSha256:'d'.repeat(64)};
 const controls=createControls({fixture,descriptor,admission:{beforeMemberRead:true,source:{sourceSha:fixture.binarySourceSha},installed:{binaryHash:descriptor.binaryHash}}},{member:()=>({bytes:Buffer.from('synthetic'),sha256:'c'.repeat(64),uid:process.getuid(),value:{control_secret:'e'.repeat(64)}}),fetch:async(_url,options)=>{calls++;const q=JSON.parse(options.body);if(q.capability==='readControlReceipt')reads++;return new Response(JSON.stringify({...q,observed:true,sourceSha:fixture.binarySourceSha,noPaidMarker:'no-paid-providers',directDatabaseWrites:false,nativeMutationsForwardedByControls:false}),{status:200});}});
 await controls.readControlReceipt({caseId:'PRIVACY-01',id:'synthetic'});assert.equal(reads,1);for(let i=0;i<23;i++)await controls.readNativeRequest({caseId:'PRIVACY-01'});await assert.rejects(controls.readNativeRequest({caseId:'PRIVACY-01'}));await controls.closeRunControls({caseId:'PRIVACY-01'});assert.equal(calls,25);assert.equal(controls.publicState().finalCleanup,1);controls.dispose();
 }finally{if(previous===undefined)delete process.env.NODE_EXTRA_CA_CERTS;else process.env.NODE_EXTRA_CA_CERTS=previous;}});

// Executes the actual scenario functions against a finite in-memory native
// protocol/ledger model. This is workflow-unit evidence, never Appium acceptance.
async function workflowDouble(caseId,{duplicateRow=false,wrongReceipt=false,delayedReadEvidence=false}={}){
 const producer=producerDouble(),dataset=await producer.run(),tasks=structuredClone(dataset.tasks),events=[],clicks=[],records=[];
 const state={page:0,ownership:'mine',dates:'all',screen:'work',selected:null,changed:false,actor:'member',privacy:'null',confirmation:false,receipt:null,armed:false};
 const fixture={appId:'ai.caseops.mobile.dev.localacceptance',udid:'synthetic-device',buildReceipt:{path:'/synthetic/build',sha256:'a'.repeat(64)},membershipId:dataset.membershipId,gatewayRunId:'synthetic-qp',gatewayUrl:'https://127.0.0.1:18443',qp:{dataset,nativeSelectors:{observed:true,udid:'synthetic-device',buildReceipt:{path:'/synthetic/build',sha256:'a'.repeat(64)},segments:{}}}};
 for(const[group,labels]of[['Task ownership',['Mine','Team','Unassigned']],['Task dates',['All dates','Dated','Undated']]])fixture.qp.nativeSelectors.segments[group]=Object.fromEntries(labels.map(label=>[label,{group,label,query:'android='+label,labelAttribute:'text'}]));
 let cursorSerial=0,deliveredCursor=null;
 const add=(method,route,status=200,extra={})=>{
  let observation={};
  if(method==='GET'&&route==='/api/matter-work-queue'){
   observation.queryObservation={ownership:state.ownership,dates:state.dates,cursorSha256:state.page&&deliveredCursor?hash(Buffer.from(deliveredCursor)):null};
   if(status===200){const value=page(state.ownership,state.dates,state.page?'next':null);
    observation.responseObservation={nextCursorSha256:value.next_cursor?hash(Buffer.from(value.next_cursor)):null,
     anchorIdSha256:value.items.length?hash(Buffer.from(value.items.at(-1).id)):null};
    if(!state.page)deliveredCursor=value.next_cursor;
   }
  }
  const r={sequence:records.length+1,method,route,status,nativeMarker:true,...observation,...extra};records.push(r);return r;
 };
 const page=(ownership=state.ownership,dates=state.dates,cursor=null)=>{const list=expectedQueue(tasks,ownership,dates,dataset.membershipId,dataset.teamPeerId);return{scope:'matter_tasks',ownership,dates,due_from:null,due_to:null,sort:'due_on_created_at_id',limit:25,items:structuredClone(list.slice(cursor?25:0,cursor?50:25)),next_cursor:!cursor&&list.length>25?'synthetic-next-'+tasks.find(t=>t.id===dataset.anchor.id).updated_at+'-'+(++cursorSerial):null};};
 const current=()=>page(state.ownership,state.dates,state.page?'next':null);
 const receipt={id:id(900),operation_id:id(901),request_type:'account_deletion',status:'received',requested_at:'2026-10-27T12:00:00.123456Z',deletion_completed:false};
 const values=()=>{
  const v={'tab-work':'Work','account-open':'Account'};
  if(state.screen==='work'){
   v['screen-work']='Work';v['matter-task-queue']='Queue';
   if(state.stale){v['queue-stale']='Work or access changed. Reload the work queue.';v['queue-first']='First page';}
   else if(state.selected){const t=state.selected;Object.assign(v,{'queue-task-detail':'Task','queue-task-title':t.title,'queue-task-id':t.id,'queue-task-matter':t.matter.matter_code+' · '+t.matter.title,'queue-task-status':t.status.replaceAll('_',' '),'queue-task-priority':t.priority,'queue-task-due':'No due date recorded','queue-task-assignment':'Assigned to you','queue-task-created':t.created_at,'queue-task-updated':t.updated_at,'queue-task-lifecycle':String(t.matter.lifecycle_version),'queue-back':'Back','queue-open-matter':'Open Matter'});}
   else{for(const t of current().items)v['queue-task-'+t.id]=t.title;if(current().next_cursor)v['queue-next']='Next';v['queue-first']='First page';v['queue-ownership-meaning']='Your own and unassigned tasks are excluded';}
  }else if(state.screen==='matter'){v['matter-detail']='Matter';v['matter-code']=dataset.matter.matter_code;}
  else if(state.screen==='account'){
   v['account-screen']='Account';v.back='Back';v['privacy-request-state']=state.privacy==='unknown'?'Acknowledgement unconfirmed':state.privacy==='received'?'Request received':'No received request is recorded';
   if(state.confirmation){v['privacy-request-confirmation']='Confirm request';v['privacy-request-confirm']='Confirm';v['privacy-request-cancel']='Cancel';}
   else if(state.privacy==='null')v['privacy-request-start']='Request';
   if(state.privacy==='unknown')v['privacy-request-reload']='Reload';
   if(state.privacy==='received')Object.assign(v,{'privacy-request-receipt':'Receipt','privacy-request-id':wrongReceipt?id(999):receipt.id,'privacy-request-operation':receipt.operation_id,'privacy-request-requested-at':receipt.requested_at,'privacy-request-status':'Received','privacy-request-not-completed':'Not completed'});
  }return v;
 };
 const element=(key,text)=>({elementId:key,isDisplayed:async()=>true,isEnabled:async()=>true,getText:async()=>text,getAttribute:async attribute=>attribute==='resource-id'?key:attribute==='text'?text:attribute==='package'?fixture.appId:
  attribute==='class'&&['account-screen','work-scroll'].includes(key)?'android.widget.ScrollView':attribute==='class'&&key.startsWith('queue-task-')?'android.widget.Button':attribute==='clickable'&&key.startsWith('queue-task-')?'true':null,click:async()=>{throw Error('ELEMENT_CLICK_FORBIDDEN');}});
 let settings={waitForIdleTimeout:500};
 const driver={getSettings:async()=>({...settings}),updateSettings:async value=>{settings={...settings,...value};},
  findElements:async(using,query)=>{assert.equal(using,'xpath');assert.equal(query,"//*[starts-with(@resource-id, 'queue-task-')]");const rows=current().items;return (duplicateRow?[...rows,rows[0]]:rows).map((t,index)=>({'element-6066-11e4-a52e-4f735466cecf':id(3000+index),ELEMENT:id(3000+index),displayed:'true','attribute/resource-id':'queue-task-'+t.id,'attribute/package':fixture.appId}));},waitUntil:async fn=>assert.equal(await fn(),true,'SYNTHETIC_STATE_NOT_REACHED'),
  getElementRect:async()=>({x:4,y:20,width:900,height:1900}),getWindowRect:async()=>({x:0,y:0,width:1080,height:2400}),
  execute:async(command,opts)=>{assert.equal(command,'mobile: scrollGesture');
   assert.equal(opts.elementId,state.screen==='account'?'account-screen':'work-scroll');
   assert.ok(['down','up'].includes(opts.direction));return false;},
  $$:async query=>{
   if(query.includes("/ancestor::*[@class='android.widget.ScrollView']"))return state.screen==='work'?[element('work-scroll','')]:[];
   if(query===`android=new UiSelector().text("No matching tasks")`)return state.screen==='work'&&!current().items.length?[element(query,'No matching tasks')]:[];
   if(query.startsWith('//*[starts-with(')){const rows=Object.entries(values()).filter(([k])=>/^queue-task-[a-f0-9-]{36}$/.test(k)).map(([k,v])=>element(k,v));return duplicateRow?[...rows,rows[0]]:rows;}
   if(query.startsWith('android='))return[element(query,query.slice(8))];const key=query.replace(/^id=/,'');const v=values();return Object.hasOwn(v,key)?[element(key,v[key])]:[];
  },elementClick:async key=>{assert.equal(settings.waitForIdleTimeout,500,'QP_ACTION_REQUIRES_NORMAL_IDLE_BARRIER');clicks.push(key);
   if(key.startsWith('android=')){const label=key.slice(8);if(['Mine','Team','Unassigned'].includes(label))state.ownership={Mine:'mine',Team:'team',Unassigned:'unassigned'}[label];else state.dates={'All dates':'all',Dated:'dated',Undated:'undated'}[label];state.page=0;add('GET','/api/matter-work-queue');}
   else if(key==='tab-work'){state.screen='work';state.selected=null;state.page=0;state.stale=false;add('GET','/api/matter-work-queue');}
   else if(key==='queue-next'){if(state.changed){state.stale=true;add('GET','/api/matter-work-queue',409,{queryObservation:{ownership:state.ownership,dates:state.dates,cursorSha256:hash(Buffer.from(deliveredCursor))}});}else{state.page=1;add('GET','/api/matter-work-queue');}}
   else if(key==='queue-first'){state.stale=false;state.page=0;add('GET','/api/matter-work-queue');}
   else if(/^queue-task-[a-f0-9-]{36}$/.test(key))state.selected=current().items.find(t=>t.id===key.slice(11));
   else if(key==='queue-back')state.selected=null;else if(key==='queue-open-matter')state.screen='matter';
   else if(key==='account-open'){state.screen='account';state.privacy=state.actor==='member'&&state.receipt?'received':'null';add('GET','/api/account/deletion-requests');}
   else if(key==='privacy-request-start')state.confirmation=true;
   else if(key==='privacy-request-cancel')state.confirmation=false;
   else if(key==='privacy-request-confirm'){assert.equal(state.armed,true);assert.equal(state.receipt,null);state.receipt=receipt;state.confirmation=false;state.privacy='unknown';add('POST','/api/account/deletion-requests',202,{bodyObservation:{keys:['confirmation','operation_id']},responseObservation:receipt});}
   else if(key==='privacy-request-reload'){state.privacy='received';add('GET','/api/account/deletion-requests');}
   else if(key==='back')state.screen='home';else throw Error('UNEXPECTED_SYNTHETIC_TAP '+key);
  }};
 const applyClick=driver.elementClick,scroll=driver.execute;
 driver.elementClick=async key=>{assert.ok(!/^queue-task-[a-f0-9-]{36}$/.test(key),'ANDROID_TASK_LEGACY_CLICK_FORBIDDEN');return applyClick(key);};
 driver.execute=async(command,args)=>command==='mobile: clickGesture'?applyClick(args.elementId):scroll(command,args);
 const calls=[],readAttempts=new Map();const controls={readQueue:async args=>{calls.push('readQueue');return{status:200,value:page(args.ownership,args.dates,args.cursor)};},
  changeAnchor:async({action})=>{calls.push('changeAnchor');const t=tasks.find(t=>t.id===dataset.anchor.id);t.due_on=action==='change'?dataset.anchor.changedDueOn:dataset.anchor.due_on;t.updated_at=action==='change'?'2026-10-27T13:00:00.000001Z':'2026-10-27T13:00:00.000002Z';state.changed=action==='change';return{acknowledged:true,id:t.id,updatedAt:t.updated_at};},
  readNativeRequest:async args=>{calls.push('readNativeRequest');if(delayedReadEvidence&&args.method==='GET'){const n=(readAttempts.get(args.afterSequence)||0)+1;readAttempts.set(args.afterSequence,n);if(n<4)return{requests:[]};}return{requests:records.filter(r=>r.sequence>args.afterSequence&&r.method===args.method&&r.route===args.route)};},
  readOwnPrivacy:async({actor='member'})=>{calls.push('readOwnPrivacy');return{status:200,value:{request:actor==='member'?state.receipt:null}};},
  armPrivacyAckLoss:async()=>{calls.push('armPrivacyAckLoss');state.armed=true;return{id:'synthetic-arm'};},
  readControlReceipt:async()=>{calls.push('readControlReceipt');return{requestsForwarded:1,upstreamAcknowledged:true,upstreamStatus:202,responseObservation:state.receipt};}};
 const context={platform:'android',fixture,driver,caseId,controls,controlCalls:0,nativeOperations:0,authoritativeReads:0,record:e=>events.push(e),switchActor:async()=>{state.actor='second-company';state.screen='home';state.privacy='null';}};
 const originalFetch=globalThis.fetch;globalThis.fetch=async()=>new Response(JSON.stringify({runId:fixture.gatewayRunId,overflow:false,markerRejected:0,routeRejected:0,lastSequence:records.length,requests:structuredClone(records)}));
 return{context,calls,clicks,events,records,run:()=>queuePrivacyScenarios.find(c=>c.id===caseId).run(context),close(){globalThis.fetch=originalFetch;producer.close();}};
}
test('Queue Matter navigation binds the actual native accessibility contract',()=>{
 const screen=fs.readFileSync(path.join(ROOT,'apps/mobile/src/application/screens/MatterScreen.tsx'),'utf8');
 assert.match(screen,/<ScrollView\b[^>]*\btestID="matter-detail"/s);
 assert.doesNotMatch(screen,/testID="screen-matter"/);
});
test('actual Queue scenario executes every view, nullable detail, stale409 and fresh restoration in a protocol double',async()=>{const x=await workflowDouble('QUEUE-01');try{await x.run();assert.equal(x.calls.filter(v=>v==='readQueue').length,13);assert.equal(x.calls.filter(v=>v==='changeAnchor').length,2);assert.equal(x.context.controlCalls,17);assert.equal(x.events.at(-1).boundary,'queue-complete');assert.equal(x.records.some(r=>r.status===409),true);assert.equal(x.records.some(r=>r.method==='POST'),false);}finally{x.close();}});
test('actual Queue task gesture preserves a lost acknowledgement without a legacy click or second dispatch',async()=>{
 const x=await workflowDouble('QUEUE-01'),original=x.context.driver.execute,unknown=Error('synthetic lost native gesture ACK');let gestures=0;
 x.context.driver.execute=async(command,args)=>{if(command==='mobile: clickGesture'){gestures++;throw unknown;}return original(command,args);};
 try {
  const run=x.run();await assert.rejects(run,error=>error===unknown);
  assert.equal(gestures,1);assert.equal(x.clicks.some(key=>/^queue-task-[a-f0-9-]{36}$/.test(key)),false);
  assert.equal((await x.context.driver.getSettings()).waitForIdleTimeout,500);
 }finally{x.close();}
});
test('actual Privacy scenario retains one202 Unknown then GET reload/revisit and other-user absence in a protocol double',async()=>{const x=await workflowDouble('PRIVACY-01');try{await x.run();assert.equal(x.calls.filter(v=>v==='readControlReceipt').length,1);assert.equal(x.calls.filter(v=>v==='readOwnPrivacy').length,4);assert.equal(x.records.filter(r=>r.method==='POST').length,1);assert.equal(x.clicks.filter(v=>v==='privacy-request-confirm').length,1);assert.equal(x.events.at(-1).boundary,'privacy-complete');}finally{x.close();}});
test('actual Queue scenario refuses duplicate bound native rows before its Next dispatch',async()=>{const x=await workflowDouble('QUEUE-01',{duplicateRow:true});try{await assert.rejects(x.run(),/QP_DUPLICATE_NATIVE_ROW/);assert.equal(x.clicks.includes('queue-next'),false);}finally{x.close();}});
test('actual Privacy scenario refuses a wrong rendered receipt after one POST without another confirmation',async()=>{const x=await workflowDouble('PRIVACY-01',{wrongReceipt:true});try{await assert.rejects(x.run());assert.equal(x.clicks.filter(v=>v==='privacy-request-confirm').length,1);assert.equal(x.records.filter(r=>r.method==='POST').length,1);assert.equal(x.events.some(v=>v.boundary==='privacy-complete'),false);}finally{x.close();}});
test('both four-read privacy boundaries execute within the fixed17 RPC allocation including cleanup',async()=>{const x=await workflowDouble('PRIVACY-01',{delayedReadEvidence:true});try{await x.run();assert.equal(x.context.controlCalls,16);assert.equal(x.calls.filter(v=>v==='readNativeRequest').length,10);assert.equal(x.context.controlCalls+1,QP_CALL_INVENTORY['PRIVACY-01'].readOwnPrivacy+QP_CALL_INVENTORY['PRIVACY-01'].armPrivacyAckLoss+QP_CALL_INVENTORY['PRIVACY-01'].readControlReceipt+QP_CALL_INVENTORY['PRIVACY-01'].readNativeRequest+QP_CALL_INVENTORY['PRIVACY-01'].closeCaseControls);assert.equal(x.records.filter(v=>v.method==='POST').length,1);}finally{x.close();}});
test('private UID metadata is required before the QP reader and retained descriptor UID must match',async()=>{for(const edit of[ref=>delete ref.uid,ref=>ref.uid=true]){const x=await admissionDouble();try{edit(x.q.members[0].credentialEvidence);await assert.rejects(x.run());assert.equal(x.calls.some(v=>v.startsWith('PRIVATE:')),false);}finally{x.close();}}const x=await admissionDouble();try{x.io.reader=file=>{x.calls.push('PRIVATE:'+file);return{bytes:x.credentials[0].bytes,value:x.credentials[0].value,sha256:'e'.repeat(64),uid:process.getuid()+1};};await assert.rejects(x.run());assert.equal(x.calls.filter(v=>v.startsWith('PRIVATE:')).length,1);assert.ok(x.credentials[0].bytes.every(v=>v===0));}finally{x.close();}});
test('public fixture projection binds normal producer, exact recipes, current source and descriptor hash without private reads',async()=>{const x=await admissionDouble();try{const q={...x.q,baseFixtureEvidence:x.q.fixtureEvidence,registrationEvidence:x.controls.registrationEvidence,nativeSelectorEvidence:{path:'/synthetic/selectors',sha256:'e'.repeat(64)}};x.map.set(q.nativeSelectorEvidence.path,x.first.qp.nativeSelectors);const result=composeQPFixture(q,{read:x.io.read,snapshot:x.io.snapshot});assert.equal(result.actualNativeAcceptance,false);assert.deepEqual(result.fixture.qp.dataset,x.dataset);assert.equal(x.calls.some(v=>v.startsWith('PRIVATE:')),false);x.registration.ownerRecipes[0].requests[2].body.due_on='2099-01-01';assert.throws(()=>composeQPFixture(q,{read:x.io.read,snapshot:x.io.snapshot}));assert.equal(x.calls.some(v=>v.startsWith('PRIVATE:')),false);}finally{x.close();}});
test('stale registration, unobserved control descriptor and mismatched protocol refuse before private member admission',async()=>{for(const mutate of[x=>x.registration.sourceSha='f'.repeat(40),x=>x.controls.observed=false,x=>x.controls.registrationSha256='f'.repeat(64),x=>x.controls.protocol={...V1_CONTROL_PROTOCOL,statusReads:20},x=>x.controls.binaryHash='f'.repeat(64),x=>delete x.controls.actorCredentialMappings,x=>delete x.registration.actors.owner,x=>delete x.dataset.actors,x=>x.map.get(x.controls.credentialMountEvidence.path).runId='old-epoch']){const x=await admissionDouble();try{mutate(x);await assert.rejects(x.run());assert.equal(x.calls.some(v=>v.startsWith('PRIVATE:')),false);}finally{x.close();}}});

function physicalLayoutRecord(binaryHash, pageSizeBytes = 4096) {
 const physicalIdentity={access:'run-as',deviceKind:'physical',transportMode:'usb-reverse',shellUid:2000,packageUid:10087,runAsUid:10087,usbDevPath:'usb:1-2.5',apiLevel:36,abi:'arm64-v8a',qemuOff:true};
 const record={platform:'android',udid:'CASEOPSUNITUSB01',appId:'ai.caseops.mobile.dev.localacceptance',binaryHash,bootId:'11111111-2222-4333-8444-555555555555',pageSizeBytes,...physicalIdentity,physicalWorkflowOnly:true,sixteenKEmulatorAcceptance:false};
 record.androidLayout={schemaVersion:1,kind:'android-physical-layout-observation',observed:true,platform:'android',udid:record.udid,appId:record.appId,binaryHash,bootId:record.bootId,deviceKind:'physical',transportMode:'usb-reverse',pageSizeBytes,physicalIdentity,observationCommand:['shell','getconf','PAGESIZE'],returnedOutputBytes:{beforeBoot:37,pageSize:pageSizeBytes===4096?5:6,afterBoot:37},acceptanceScope:'physical-workflow-only',sixteenKEmulatorAcceptance:false};
 return record;
}
function bindPhysicalPacket(x, values, current, pageSize=4096) {
 const actual={...physicalLayoutRecord(x.q.expectedBinaryHash,pageSize),...(current.appDataPath?{appDataPath:current.appDataPath}:{})}; x.q.platform='android'; const oldUdid=current.udid,oldAppId=current.appId;
 const seen=new Set();function update(v){if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);for(const[k,c]of Object.entries(v)){if(c===oldUdid)v[k]=actual.udid;else if(c===oldAppId)v[k]=actual.appId;else if(k==='platform'&&c==='ios')v[k]='android';else if(k==='inventoryId'&&typeof c==='string')v[k]=c.replace('client-extension-ios','client-extension-android');else update(c);}}
 for(const v of values.values())update(v);
 x.q.inventoryId=x.q.inventoryId?.replace('client-extension-ios','client-extension-android');
 for(const r of[x.q.deviceEvidence,x.q.installedEvidence]){const v=values.get(r.path);delete v.deviceTypeIdentifier;delete v.runtime;Object.assign(v,structuredClone(actual));}
 for(const r of[x.q.fixtureEvidence,...x.q.members.map(m=>m.fixtureEvidence)]){const f=values.get(r.path);f.androidTransport={adbPort:5042,appiumUrl:'http://127.0.0.1:4729',systemPort:8206,transportMode:'usb-reverse'};if(f.cx)f.cx.workflowDomain='physical';f.apiOrigin='https://127.0.0.1:8443';f.auth.webOrigin='https://127.0.0.1:3443';}
 const build=values.get(x.q.buildReceipt.path);Object.assign(build,{apiOrigin:'https://127.0.0.1:8443',webOrigin:'https://127.0.0.1:3443'});
 for(const r of[x.q.fixtureEvidence,...x.q.members.map(m=>m.fixtureEvidence)])validateAndroidTransport(values.get(r.path),'android',build);
 // This packet model exercises native layout admission. Its signed Android
 // evidence is covered separately by the build receipt tests.
 x.io.buildCheck=(f,platform,binary)=>{assert.equal(platform,'android');assert.equal(binary,actual.binaryHash);assert.equal(f.appId,actual.appId);};
 x.io.installed=()=>structuredClone(actual);return actual;
}

test('complete Queue/Privacy admission binds physical4K layout and rejects changed retained page or boot before readers',async()=>{
 const good=await admissionDouble();try{const current=good.io.installed();bindPhysicalPacket(good,good.map,current);const result=await good.run();assert.equal(result.actual.pageSizeBytes,4096);assert.equal(result.actual.androidLayout.sixteenKEmulatorAcceptance,false);}finally{good.close();}
 for(const mutate of[x=>x.map.get(x.q.deviceEvidence.path).pageSizeBytes=16384,x=>x.map.get(x.q.installedEvidence.path).androidLayout=undefined,x=>x.map.get(x.q.deviceEvidence.path).bootId='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee']){const x=await admissionDouble();try{bindPhysicalPacket(x,x.map,x.io.installed());mutate(x);await assert.rejects(x.run());assert.equal(x.calls.some(v=>v.startsWith('PRIVATE:')),false);}finally{x.close();}}
});


test('Queue/Privacy complete admission binds signed observer UID and rejects substitution before private reads',async()=>{
 for(const wrong of[false,true]){const x=await admissionDouble(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'caseops-qp-observer-'));try{const actual=bindPhysicalPacket(x,x.map,x.io.installed());const ref=bindObserverTestIdentity(actual,dir,x.q.expectedSourceSha);for(const r of[x.q.fixtureEvidence,...x.q.members.map(m=>m.fixtureEvidence)])x.map.get(r.path).privacyObserverEvidence=ref;for(const r of[x.q.deviceEvidence,x.q.installedEvidence]){delete x.map.get(r.path).runAsUid;Object.assign(x.map.get(r.path),structuredClone(actual));}x.io.installed=()=>structuredClone(actual);if(wrong)x.map.get(x.q.installedEvidence.path).observerUid++;if(wrong){await assert.rejects(x.run());assert.equal(x.calls.some(v=>v.startsWith('PRIVATE:')),false);}else{const r=await x.run();assert.equal(r.actual.access,'qa-observer-service');assert.equal(r.actual.sixteenKEmulatorAcceptance,false);}}finally{x.close();fs.rmSync(dir,{recursive:true,force:true});}}
});

const androidViewportRanks = [
  [1, 2], [2, 3, 4, 5, 6], [5, 6, 7, 8, 9], [8, 9, 10, 11, 12],
  [11, 12, 13, 14, 15], [14, 15, 16, 17, 18], [18, 19, 20, 21],
  [21, 22, 23, 24, 25], [23, 24, 25],
];

function androidViewportDouble({ rankPages = androidViewportRanks, next = true, footer = true, status,
  initial = 0, scopePackage = 'ai.caseops.mobile.dev.localacceptance', hiddenPrivacyAt } = {}) {
  const appId = 'ai.caseops.mobile.dev.localacceptance';
  const scope = {
    elementId: 'owned-scroll',
    isDisplayed: async () => true,
    getAttribute: async key => ({ class: 'android.widget.ScrollView', package: scopePackage }[key]),
  };
  const element = (attributes = {}, getText = async () => '') => ({
    isDisplayed: async () => true,
    getAttribute: async key => ({ package: appId, ...attributes }[key]),
    getText,
  });
  const view = { x: 2, y: 40, width: 1010, height: 2010 }, window = { x: 0, y: 0, width: 1080, height: 2400 };
  const gestures = [];
  let position = initial, settings={waitForIdleTimeout:500};
  const driver = {
    getSettings:async()=>({...settings}),
    updateSettings:async value=>{settings={...settings,...value};},
    async findElements(using, query) {
      assert.equal(using,'xpath');assert.equal(query,"//*[starts-with(@resource-id, 'queue-task-')]");
      return rankPages[position].map((rank,index)=>({'element-6066-11e4-a52e-4f735466cecf':id(3000+index),ELEMENT:id(3000+index),
        displayed:'true','attribute/resource-id':'queue-task-'+id(rank),'attribute/package':appId}));
    },
    async $$(query) {
      if (query === 'id=account-screen' || query.includes("/ancestor::*[@class='android.widget.ScrollView']")) return [scope];
      if (query === 'id=screen-work') return position === 0 ? [element()] : [];
      if (query === 'id=matter-task-queue') return [element()];
      if (query === 'id=privacy-request-start') return position === hiddenPrivacyAt ? [element()] : [];
      if (query === 'id=privacy-request-state') return status && position >= 2 ? [element({}, status)] : [];
      if (query === 'id=queue-first') return footer && position === rankPages.length - 1 ? [element()] : [];
      if (query === 'id=queue-next') return next && position === rankPages.length - 1 ? [element()] : [];
      if (query === "//*[starts-with(@resource-id, 'queue-task-')]") {
        return rankPages[position].map(rank => element({ 'resource-id': 'queue-task-' + id(rank) }));
      }
      throw Error('Unexpected diagnostic query ' + query);
    },
    getElementRect: async target => { assert.equal(target, scope.elementId); return view; },
    getWindowRect: async () => window,
    async execute(command, args) {
      assert.equal(command, 'mobile: scrollGesture');
      assert.deepEqual(args, { elementId: scope.elementId, direction: args.direction, percent: 0.65 });
      gestures.push(args.direction);
      if (args.direction === 'up') {
        position = Math.max(0, position - 1);
        return position > 0;
      }
      assert.equal(args.direction, 'down');
      position = Math.min(rankPages.length - 1, position + 1);
      return position < rankPages.length - 1;
    },
  };
  const tasks = Array.from({ length: 26 }, (_, n) => ({ id: id(n + 1), role: n === 25 ? 'excluded' : 'mine' }));
  return { c: { platform: 'android', driver, nativeOperations: 0, fixture: { appId, qp: { dataset: { tasks } } } },
    page: { items: tasks.slice(0, 25), next_cursor: 'owned cursor' }, gestures };
}

function nativeQueueBatchDouble(edit=()=>{}){
 const c=androidViewportDouble(),calls=[];
 const rows=c.page.items.slice(0,2).map((item,index)=>({'element-6066-11e4-a52e-4f735466cecf':id(3000+index),ELEMENT:id(3000+index),
  displayed:'true','attribute/resource-id':'queue-task-'+item.id,'attribute/package':c.c.fixture.appId}));
 edit(rows);c.c.driver.findElements=async(using,value)=>{calls.push({using,value});return rows;};return{...c,rows,calls};
}
test('Android Queue batch reads the same complete row identity, package and visibility facts in one native command',async()=>{
 const x=nativeQueueBatchDouble();assert.equal(typeof queueEvidence.readQPAndroidQueueRows,'function');
 const actual=await queueEvidence.readQPAndroidQueueRows(x.c);assert.deepEqual(actual,x.page.items.slice(0,2).map(item=>item.id));
 assert.deepEqual(x.calls,[{using:'xpath',value:"//*[starts-with(@resource-id, 'queue-task-')]"}]);
});
test('Android Queue batch refuses missing, hidden, foreign, duplicate, unknown and overbound native row evidence',async()=>{
 for(const edit of [rows=>delete rows[0].displayed,rows=>rows[0].displayed='false',rows=>rows[0]['attribute/package']='foreign.package',
  rows=>rows[0]['element-6066-11e4-a52e-4f735466cecf']='unbound',rows=>rows[0].ELEMENT=id(4000),
  rows=>rows[1]['attribute/resource-id']=rows[0]['attribute/resource-id'],rows=>rows[0]['attribute/resource-id']='queue-task-'+id(26),
  rows=>rows[0].text='PRIVATE_VALUE_MUST_NOT_BE_REQUESTED',rows=>{while(rows.length<=64)rows.push({...rows[0]});}]){
  const x=nativeQueueBatchDouble(edit);const refused=queueEvidence.readQPAndroidQueueRows(x.c);await assert.rejects(refused);assert.equal(x.calls.length,1);
 }
});
test('Android Queue batch settings are verified and restore the original selector and idle controls',async()=>{
 assert.equal(typeof queueEvidence.configureQPAndroidQueueRows,'function');
 const before={shouldUseCompactResponses:true,elementResponseAttributes:'name,text',waitForIdleTimeout:500,disableIdLocatorAutocompletion:true};let state={...before};const writes=[],events=[];
 const driver={getSettings:async()=>({...state}),updateSettings:async value=>{writes.push(value);state={...state,...value};}};
 const restore=await queueEvidence.configureQPAndroidQueueRows(driver,e=>events.push(e));
 assert.equal(state.shouldUseCompactResponses,false);assert.equal(state.elementResponseAttributes,'displayed,attribute/resource-id,attribute/package');
 assert.equal(state.waitForIdleTimeout,500);assert.equal(state.disableIdLocatorAutocompletion,true);
 await restore();assert.deepEqual(state,before);const replay=restore();await assert.rejects(replay);assert.equal(writes.length,2);assert.deepEqual(events.map(e=>e.state),['configured','restored']);
});
test('Android Queue batch refuses ignored settings and never replays an uncertain restoration',async()=>{
 const before={shouldUseCompactResponses:true,elementResponseAttributes:'name,text',waitForIdleTimeout:500};let writes=0;
 const ignored={getSettings:async()=>({...before}),updateSettings:async()=>{writes++;}};
 const setup=queueEvidence.configureQPAndroidQueueRows(ignored,()=>{});await assert.rejects(setup,/QP_ANDROID_BATCH_SETTINGS_REQUIRED/);assert.equal(writes,2);
 let state={...before};writes=0;
 const lost={getSettings:async()=>({...state}),updateSettings:async value=>{writes++;if(writes===2)throw Error('synthetic unknown settings ACK');state={...state,...value};}};
 const restore=await queueEvidence.configureQPAndroidQueueRows(lost,()=>{});const first=restore();await assert.rejects(first,/unknown settings ACK/);
 const replay=restore();await assert.rejects(replay,/QP_ANDROID_BATCH_RESTORATION_REPLAY_REFUSED/);assert.equal(writes,2);
});
test('Android Queue scope preserves a failed body and an uncertain settings cleanup, then forbids later native setup',async()=>{
 let settings={shouldUseCompactResponses:true,elementResponseAttributes:'name,text',waitForIdleTimeout:500},writes=0;
 const c={platform:'android',record:()=>{},driver:{getSettings:async()=>({...settings}),updateSettings:async value=>{writes++;if(writes===2)throw Error('synthetic lost restoration ACK');settings={...settings,...value};}}};
 const body=Error('synthetic original Queue failure');const run=queueEvidence.withQPAndroidQueueRows(c,async()=>{throw body;});
 await assert.rejects(run,error=>error instanceof AggregateError&&error.errors[0]===body&&error.code==='QP_ANDROID_QUEUE_SETTINGS_CLEANUP_UNCERTAIN');
 assert.equal(c.nativeSettingsCleanupUncertain,true);assert.equal(writes,2);assert.equal(QP.serialMs,480000);
 const runner=fs.readFileSync(path.join(ROOT,'scripts/mobile/run-queue-privacy.mjs'),'utf8');
 assert.match(runner,/let clean=c\?\.nativeSettingsCleanupUncertain!==true/);assert.match(runner,/cleanupUncertain\|\|=!clean/);
});
test('Android Queue restores the normal input idle barrier before the next action, including a failed page read',async()=>{
 const writes=[];let settings={waitForIdleTimeout:500};
 const c={platform:'android',driver:{getSettings:async()=>({...settings}),updateSettings:async value=>{writes.push(value);settings={...settings,...value};}}};
 const result=await queueEvidence.withQPAndroidQueuePageIdle(c,async()=>{assert.equal(settings.waitForIdleTimeout,0);return 'complete-page';});
 assert.equal(result,'complete-page');assert.equal(settings.waitForIdleTimeout,500);
 const failed=Error('synthetic exact page failure');
 const run=queueEvidence.withQPAndroidQueuePageIdle(c,async()=>{throw failed;});
 await assert.rejects(run,error=>error===failed);assert.equal(settings.waitForIdleTimeout,500);
 assert.deepEqual(writes,[{waitForIdleTimeout:0},{waitForIdleTimeout:500},{waitForIdleTimeout:0},{waitForIdleTimeout:500}]);
});
test('Android Queue page refuses an ignored idle setting before row reads and restores only once',async()=>{
 let calls=0;const writes=[];
 const c={platform:'android',driver:{getSettings:async()=>({waitForIdleTimeout:500}),updateSettings:async value=>{writes.push(value);}}};
 const run=queueEvidence.withQPAndroidQueuePageIdle(c,async()=>{calls++;});
 await assert.rejects(run,/QP_ANDROID_PAGE_IDLE_SETTING_REQUIRED/);assert.equal(calls,0);
 assert.deepEqual(writes,[{waitForIdleTimeout:0},{waitForIdleTimeout:500}]);
});
test('Android Queue outer response cleanup never retries a lost page idle restoration',async()=>{
 let settings={shouldUseCompactResponses:true,elementResponseAttributes:'name,text',waitForIdleTimeout:500};
 const writes=[],body=Error('synthetic body failure');
 const c={platform:'android',driver:{getSettings:async()=>({...settings}),updateSettings:async value=>{
  writes.push(value);if(Object.keys(value).length===1&&value.waitForIdleTimeout===500)throw Error('synthetic lost idle restoration ACK');
  settings={...settings,...value};
 }}};
 const run=queueEvidence.withQPAndroidQueueRows(c,()=>queueEvidence.withQPAndroidQueuePageIdle(c,async()=>{throw body;}));
 await assert.rejects(run,error=>error instanceof AggregateError&&error.errors[0]===body&&error.code==='QP_ANDROID_QUEUE_SETTINGS_CLEANUP_UNCERTAIN');
 assert.equal(c.nativeSettingsCleanupUncertain,true);assert.equal(settings.shouldUseCompactResponses,true);assert.equal(settings.elementResponseAttributes,'name,text');
 assert.equal(writes.filter(x=>Object.hasOwn(x,'waitForIdleTimeout')).length,2);assert.equal(writes.length,4);
});
test('Android queue reaches the exact page through all measured overlapping visible ranges and its real footer', async () => {
  const current = androidViewportDouble();
  await androidQueuePage(current.c, current.page);
  assert.equal((await current.c.driver.getSettings()).waitForIdleTimeout,500);
  assert.deepEqual(current.gestures, Array(8).fill('down'));
  assert.equal(current.c.nativeOperations, 8);
  // Page replacement can leave the viewport at the old footer. Verify again
  // from the actual top, even when the header is absent from the first lookup.
  await androidQueuePage(current.c, current.page);
  assert.deepEqual(current.gestures.slice(8), [...Array(8).fill('up'), ...Array(8).fill('down')]);
});

test('opted-in Queue viewport diagnostics retain ordered ranks without extra native reads or raw identities', async () => {
  const current = androidViewportDouble(), events = [];
  current.c.queueViewportDiagnostics = true;
  current.c.record = row => events.push(row);
  await androidQueuePage(current.c, current.page);
  const samples = events.filter(row => row.type === 'qp_android_queue_viewport');
  assert.equal(samples.length, androidViewportRanks.length);
  assert.deepEqual(samples.map(row => row.sampleRanks), androidViewportRanks.map(ids => ids.map(n => n - 1)));
  assert.ok(samples.every(row => /^[a-f0-9]{64}$/.test(row.expectedPageSha256) && row.expectedCount === 25));
  assert.equal(JSON.stringify(events).includes(id(1)), false);
  assert.deepEqual(current.gestures, Array(8).fill('down'));
  const silent = androidViewportDouble();
  silent.c.record = () => { throw Error('Unarmed diagnostics must stay inactive'); };
  await androidQueuePage(silent.c, silent.page);
});

test('Android queue rejects skipped, reordered, duplicate, excluded and unbound rows, or an incorrect footer', async () => {
  for (const [sample, reason] of [
    [[3, 4, 5, 6], /QP_EXACT_NATIVE_PAGE_IDENTITIES/],
    [[2, 4, 3, 5, 6], /QP_EXACT_NATIVE_PAGE_IDENTITIES/],
    [[2, 3, 3, 4, 5], /QP_DUPLICATE_NATIVE_ROW/],
    [[2, 3, 26], /QP_UNAUTHORIZED_OR_UNBOUND_NATIVE_ROW/],
    [[2, 3, 27], /QP_UNAUTHORIZED_OR_UNBOUND_NATIVE_ROW/],
  ]) {
    const current = androidViewportDouble({ rankPages: [[1, 2], sample, ...androidViewportRanks.slice(2)] });
    await assert.rejects(androidQueuePage(current.c, current.page), reason);
    assert.deepEqual(current.gestures, ['down']);
  }
  for (const [settings, reason] of [[{ next: false }, /QP_ANDROID_QUEUE_NEXT_MISMATCH/],
    [{ footer: false }, /QP_ANDROID_QUEUE_FOOTER_NOT_REACHED/],
    [{ scopePackage: 'other.app' }, /QP_ANDROID_WRONG_SCROLL_PACKAGE/]]) {
    const current = androidViewportDouble(settings);
    await assert.rejects(androidQueuePage(current.c, current.page), reason);
  }
});

test('Android account locates the exact public status after the measured two scoped downward gestures', async () => {
  const text = 'No received request is recorded';
  let reads = 0;
  const current = androidViewportDouble({ status: async () => ++reads === 1 ? 'Loading your own request' : text });
  await waitForQPPrivacyControl(current.c, 'privacy-request-state', text);
  assert.deepEqual(current.gestures, ['up', 'down', 'down']);
  assert.equal(reads, 2, 'visible transient state must settle without another gesture');
  const foreign = androidViewportDouble({ scopePackage: 'other.app' });
  await assert.rejects(waitForQPPrivacyControl(foreign.c, 'privacy-request-state', text), /QP_ANDROID_WRONG_SCROLL_PACKAGE/);
  assert.deepEqual(foreign.gestures, []);
});


test('Android privacy absence rejects a stale control below the status viewport', async () => {
  const current = androidViewportDouble({ initial: 2, hiddenPrivacyAt: 5, status: async () => 'Request received' });
  await assert.rejects(assertQPPrivacyControlsAbsent(current.c, ['privacy-request-start']), /QP_PRIVATE_OLD_CONTROL_REMAINS/);
  assert.deepEqual(current.gestures, ['up', 'up', 'down', 'down', 'down', 'down', 'down']);
  const clean = androidViewportDouble({ initial: 2, status: async () => 'Request received' });
  await assertQPPrivacyControlsAbsent(clean.c, ['privacy-request-start']);
  assert.deepEqual(clean.gestures, ['up', 'up', ...Array(8).fill('down')]);
});

async function scrolledPrivacyLogout({wrongPrincipal=false,logoutStatus=204}={}) {
 const originalFetch=globalThis.fetch,clicks=[],swipes=[];let page=5,signedOut=false,reads=0;
 const element=id=>({elementId:id,isDisplayed:async()=>true,getText:async()=>id==='account-principal'?(wrongPrincipal?'Other synthetic member':'Synthetic member'):id});
 const driver={
  $$:async query=>{const id=query.replace(/^id=/,'');
   if(id==='account-principal'&&!signedOut&&page===0)return[element(id)];
   if(id==='sign-out'&&!signedOut&&page===5)return[element(id)];
   if(id==='signed-out'&&signedOut)return[element(id)];return[];},
  waitUntil:async(condition,{timeoutMsg}={})=>{if(!await condition())throw Error(timeoutMsg||'condition not met');},
  getWindowRect:async()=>({width:400,height:800}),
  performActions:async actions=>{const moves=actions[0].actions.filter(x=>x.type==='pointerMove');const up=moves[1].y>moves[0].y;swipes.push(up?'up':'down');page=Math.max(0,Math.min(5,page+(up?-1:1)));},
  releaseActions:async()=>{},
  elementClick:async id=>{clicks.push(id);assert.equal(id,'sign-out');assert.equal(page,5);signedOut=true;},
 };
 globalThis.fetch=async(_url,options)=>{assert.equal(options.method,'GET');assert.equal(options.headers['X-CaseOps-Automated-Test'],'no-paid-providers');reads++;
  return new Response(JSON.stringify(reads===1?{lastSequence:0,requests:[]}:{lastSequence:1,requests:[{method:'POST',route:'/api/auth/native/logout',status:logoutStatus}]}),{status:200});};
 try {await logoutQPAccount({platform:'android',driver,fixture:{principalLabel:'Synthetic member',gatewayUrl:'https://127.0.0.1:9743'}});}
 finally {globalThis.fetch=originalFetch;if(wrongPrincipal){assert.deepEqual(clicks,[]);assert.equal(reads,0);}else{assert.deepEqual(clicks,['sign-out']);assert.equal(reads,2);}}
 return {clicks,swipes,reads,signedOut};
}
test('Queue privacy logout restores the header from the receipt before one acknowledged sign-out',async()=>{
 const result=await scrolledPrivacyLogout();assert.deepEqual(result.clicks,['sign-out']);assert.equal(result.signedOut,true);assert.equal(result.reads,2);assert.ok(result.swipes.includes('up'));assert.ok(result.swipes.includes('down'));
});
test('Queue privacy logout still refuses another principal and an unacknowledged sign-out',async()=>{
 await assert.rejects(scrolledPrivacyLogout({wrongPrincipal:true}));await assert.rejects(scrolledPrivacyLogout({logoutStatus:500}));
});
