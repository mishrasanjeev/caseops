import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { produceQueuePrivacy, pendingProducer, QP_PRODUCER } from '../../apps/mobile/e2e/queue-privacy-fixture.mjs';
import { QP, identity } from '../../apps/mobile/e2e/queue-privacy-contract.mjs';
import { v1PrivateReference } from '../../apps/mobile/e2e/v1-workflows-contract.mjs';
import { readProducerReference, createProducerStore, createProducerHttp, producerTimeout } from './native-producer-host.mjs';
import { admitProducerPublic } from './native-producer-admission.mjs';

const ROOT=path.resolve(fileURLToPath(new URL('../../',import.meta.url)));
export const QP_PRODUCER_INPUTS=Object.freeze(['scripts/mobile/produce-queue-privacy-fixture.mjs','scripts/mobile/queue-privacy-registration.mjs','scripts/mobile/prepare-queue-privacy-fixture.mjs','scripts/mobile/run-queue-privacy.mjs','scripts/mobile/queue-privacy-controls.mjs','scripts/mobile/client-extension-public-input.mjs','scripts/mobile/local-queue-privacy-controls.py','scripts/mobile/local-v1-controls.py','scripts/mobile/local-gateway.py','compose.mobile-local.yml']);
export function pendingQueuePrivacyHost(){return{schemaVersion:1,kind:'produce-queue-privacy-fixture',readyForLive:false,preparedOnly:true,repoRoot:ROOT,platform:null,outputRoot:null,admission:null,actors:null,plan:pendingProducer(),automaticRetry:false};}
function hostOrigins({build,docker},platform){
 assert.equal(docker.platform,platform);if(platform==='ios')assert.equal(Object.hasOwn(docker,'androidTransportMode'),false);const mode=platform==='android'?(docker.androidTransportMode??'emulator'):null;
 assert.ok(mode===null||['emulator','usb-reverse'].includes(mode));const mobileHost=platform==='android'&&mode==='emulator'?'10.0.2.2':'127.0.0.1';
 for(const[mobileKey,hostKey]of[['apiOrigin','gatewayUrl'],['webOrigin','webGatewayUrl']]){
  assert.equal(build[mobileKey],docker[mobileKey],'QP_BUILD_RECEIPT_ORIGIN_MISMATCH');const mobile=new URL(build[mobileKey]),host=new URL(docker[hostKey]);
  for(const[url,value]of[[mobile,build[mobileKey]],[host,docker[hostKey]]])assert.ok(url.origin===value&&url.protocol==='https:'&&!url.username&&!url.password&&!url.search&&!url.hash);
  assert.equal(mobile.hostname,mobileHost,'QP_MOBILE_TRANSPORT_ORIGIN_MISMATCH');assert.equal(host.hostname,'127.0.0.1','QP_HOST_LOOPBACK_REQUIRED');
  assert.ok(Number.isInteger(Number(host.port))&&Number(host.port)>=1024&&Number(host.port)<=65535);assert.equal(host.port,mobile.port,'QP_HOST_MOBILE_PORT_MAPPING_REQUIRED');
 }
 assert.notEqual(docker.gatewayUrl,docker.webGatewayUrl);
 return{apiOrigin:docker.gatewayUrl,webOrigin:docker.webGatewayUrl};
}

/** The callbacks are the real finite producer's host, not a second recipe.
 * The public actor/admission manifests are inputs; current API acknowledgements
 * alone establish their identities. No native session or gateway reset runs. */
export async function runQueuePrivacyProducer(q,dependencies={}) {
 const io={read:readProducerReference,store:createProducerStore,http:createProducerHttp,admitPublic:admitProducerPublic,produce:produceQueuePrivacy,now:Date.now,environment:process.env,...dependencies};
 assert.equal(q.kind,'produce-queue-privacy-fixture');assert.equal(q.schemaVersion,1);assert.equal(q.readyForLive,true,'QP_HOST_PENDING');assert.equal(q.preparedOnly,false,'QP_HOST_PENDING');assert.equal(q.automaticRetry,false);
 assert.equal(io.environment.CASEOPS_NATIVE_QUEUE_PRIVACY_PRODUCER_GO,'EXPLICIT_OWNED_SYNTHETIC_PRODUCER');
 for(const key of['K_SERVICE','CLOUD_RUN_JOB','GAE_ENV','FUNCTION_TARGET'])assert.ok(!io.environment[key]);
 assert.equal(q.repoRoot,ROOT);assert.ok(['android','ios'].includes(q.platform));assert.equal(q.admission.repoRoot,ROOT);assert.equal(q.admission.platform,q.platform);
 const plan=q.plan;assert.equal(plan.readyForLive,true);assert.equal(plan.preparedOnly,false);assert.equal(plan.inventoryId,QP.inventoryId);assert.equal(plan.sourceSha,q.admission.source.sourceSha);
 for(const key of['buildReceipt','dockerReceipt','installedEvidence','codeClosure'])assert.deepEqual(plan[key],q.admission[key]);
 assert.ok(path.isAbsolute(q.outputRoot)&&path.resolve(q.outputRoot)===q.outputRoot&&q.outputRoot!==ROOT&&!q.outputRoot.startsWith(ROOT+path.sep));
 assert.ok(Array.isArray(plan.privatePeerFiles)&&plan.privatePeerFiles.length===2);for(const file of plan.privatePeerFiles)assert.equal(path.dirname(file),q.outputRoot);
 assert.deepEqual(Object.keys(q.actors).sort(),['foreign-owner','member','owner','second-company']);
 for(const actor of Object.values(q.actors)){for(const key of['userId','membershipId','companyId'])identity(actor[key]);v1PrivateReference(actor.credentialEvidence);}
 assert.equal(q.actors.member.companyId,plan.companyId);assert.equal(q.actors.member.membershipId,plan.membershipId);assert.equal(q.actors.member.userId,plan.memberUserId);assert.equal(q.actors.owner.companyId,plan.companyId);assert.equal(q.actors.owner.membershipId,plan.ownerMembershipId);assert.equal(q.actors['second-company'].userId,plan.secondUserId);assert.equal(q.actors['foreign-owner'].membershipId,plan.foreignOwnerMembershipId);assert.equal(q.actors['foreign-owner'].companyId,q.actors['second-company'].companyId);assert.notEqual(q.actors['second-company'].companyId,plan.companyId);
 const actorInput=io.read(plan.baseActorEvidence,16384),admissionInput=io.read(plan.admissionEvidence,16384);
 assert.equal(actorInput.sourceSha,plan.sourceSha);assert.equal(actorInput.runId,plan.runId);assert.deepEqual(actorInput.actors,q.actors);
 assert.equal(admissionInput.sourceSha,plan.sourceSha);assert.equal(admissionInput.runId,plan.runId);assert.deepEqual(admissionInput.admission,q.admission);
 const deadline=io.now()+QP_PRODUCER.milliseconds,publicBefore=await io.admitPublic(q.admission,{requiredInputs:QP_PRODUCER_INPUTS});
 producerTimeout(deadline-io.now());
 assert.deepEqual(publicBefore.source,q.admission.source);assert.equal(publicBefore.docker.gatewayRunId,plan.runId);assert.equal(publicBefore.build.binaryHash,publicBefore.installed.binaryHash);
 const origins=hostOrigins(publicBefore,q.platform),store=io.store(q.outputRoot),http=io.http({...origins,sourceSha:plan.sourceSha,publicCa:q.admission.publicCa,deadlineMs:deadline,persist:store.persist,now:io.now});
 let claimed=false;
 const claim=key=>{assert.equal(claimed,false);store.write('queue-privacy-'+plan.runId+'.claim.json',{planSha256:key,sourceSha:plan.sourceSha,runId:plan.runId,noReplay:true});claimed=true;};
 const checkIdentity=(value,actor)=>{
  for(const[key,field]of[['user','userId'],['membership','membershipId'],['company','companyId']]){assert.equal(value[key]?.id,q.actors[actor][field],'QP_CURRENT_ACTOR_IDENTITY_REQUIRED');assert.equal(value[key].is_active,true,'QP_ACTIVE_ACTOR_REQUIRED');}
  assert.ok(Array.isArray(value.capabilities));
  if(['owner','foreign-owner'].includes(actor)){
   assert.ok(['owner','admin'].includes(value.membership.role),'QP_CURRENT_OWNER_ROLE_REQUIRED');
   for(const capability of(actor==='owner'?['company:manage_users','teams:manage','matters:create','matters:write','matters:archive']:['matters:create','matters:write']))assert.ok(value.capabilities.includes(capability),'QP_CURRENT_OWNER_CAPABILITY_REQUIRED');
  }
 };
 const admit=async(_plan,{boundary,charge})=>{
  assert.equal(_plan,plan);assert.ok(['before','after'].includes(boundary));assert.ok(io.now()<deadline);
  const current=await io.admitPublic(q.admission,{requiredInputs:QP_PRODUCER_INPUTS});assert.deepEqual(current.source,publicBefore.source);assert.deepEqual(current.installed,publicBefore.installed);assert.deepEqual(current.docker,publicBefore.docker);
  for(const[web,route,revision]of[[false,'/api/build',current.docker.backendRevision],[true,'/api/release-identity',current.docker.webRevision]]){
   const timeoutMs=producerTimeout(deadline-io.now());charge({method:'GET'});const response=await http.request({actor:'public',method:'GET',route,web,timeoutMs,deadlineMs:deadline});assert.equal(response.status,200);assert.equal(response.value.release_sha,plan.sourceSha);assert.equal(response.value.revision,revision);
  }
  if(boundary==='before')for(const actor of['owner','member','second-company','foreign-owner']){
   // Public native/source identity is freshly observed before each private read.
   const fresh=await io.admitPublic(q.admission,{requiredInputs:QP_PRODUCER_INPUTS});assert.deepEqual(fresh.source,publicBefore.source);assert.deepEqual(fresh.installed,publicBefore.installed);
   producerTimeout(deadline-io.now());
   const value=await http.login(actor,q.actors[actor].credentialEvidence,{charge,remaining:()=>deadline-io.now(),includeIdentity:false});checkIdentity(value,actor);
  }
  return{beforeMemberRead:true,sourceSha:plan.sourceSha,apiSourceSha:plan.sourceSha,webSourceSha:plan.sourceSha,...Object.fromEntries(['baseActorEvidence','admissionEvidence','buildReceipt','dockerReceipt','installedEvidence','codeClosure'].map(key=>[key,plan[key]]))};
 };
 try{
  const dataset=await io.produce(plan,{claim,persist:store.persist,admit,now:io.now,request:(actor,method,route,body,options)=>http.request({actor,method,route,body,...options})});
  assert.equal(claimed,true);assert.ok(io.now()<=deadline,'QP_HOST_TOTAL_DEADLINE');
  const datasetEvidence=store.write('queue-privacy-'+plan.runId+'.dataset.json',dataset);
  return{datasetEvidence,registrationActors:Object.fromEntries(['owner','member','second-company'].map(name=>[name,{...dataset.actors[name],credentialEvidence:q.actors[name].credentialEvidence}])),automaticRetry:false,actualNativeAcceptance:false,privateCredentialsPublished:false};
 }finally{http.clear();}
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))try{
 const[mode,file,digest]=process.argv.slice(2);
 if(mode==='--pending'){assert.equal(process.argv.length,3);console.log(JSON.stringify(pendingQueuePrivacyHost(),null,2));}
 else{assert.equal(mode,'--request');assert.equal(process.argv.length,5);console.log(JSON.stringify(await runQueuePrivacyProducer(readProducerReference({path:file,sha256:digest},65536))));}
}catch{console.error('QUEUE_PRIVACY_PRODUCER_REFUSED_OR_UNKNOWN_NO_REPLAY');process.exitCode=1;}
