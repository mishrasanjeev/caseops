import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { existsSync, lstatSync, openSync, closeSync, fstatSync, readSync, constants, realpathSync } from 'node:fs';
import { createV1FixtureAggregate, validateV1FixtureAggregate } from '../../apps/mobile/e2e/v1-workflows-contract.mjs';
import { produceV1Dataset, produceV1Inbox } from '../../apps/mobile/e2e/v1-workflows-fixture.mjs';
import { produceV1Viewer } from '../../apps/mobile/e2e/v1-workflows-viewer.mjs';
import { createProducerHttp, createProducerStore, producerHash, readProducerReference, producerTimeout } from './native-producer-host.mjs';
import { admitProducerPublic } from './native-producer-admission.mjs';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';

const ROOT = path.resolve(fileURLToPath(new URL('../../',import.meta.url)));
export const V1_PRODUCER_INPUTS = Object.freeze(['scripts/mobile/produce-v1-fixture.mjs','scripts/mobile/native-producer-private.py',
  'scripts/mobile/local-fixture.py','scripts/mobile/local-transport.py','scripts/mobile/local-v1-inbox.py','scripts/mobile/local-v1-controls.py']);
/** References resolve only to earlier acknowledged outputs; no code or future
 * receipt is accepted. The resolved plan itself is retained before its stage. */
export function resolveProducedReferences(value, produced) {
  if (Array.isArray(value)) return value.map(x=>resolveProducedReferences(x,produced));
  if (!value || typeof value !== 'object') return value;
  if (Object.keys(value).length === 1 && Object.hasOwn(value,'$produced')) {
    assert.match(value.$produced,/^(base|viewer|inbox)(?:\.(?:[A-Za-z][A-Za-z0-9_]*|0|[1-9][0-9]*))+$/);
    let result=produced;
    for (const key of value.$produced.split('.')) { assert.ok(!['constructor','prototype','__proto__'].includes(key) && result && Object.hasOwn(result,key),'EARLIER_ACKNOWLEDGED_PRODUCER_OUTPUT_REQUIRED');result=result[key]; }
    return structuredClone(result);
  }
  return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,resolveProducedReferences(v,produced)]));
}
function generated(file,max=65536) {
  assert.equal(realpathSync(file),file); const fd=openSync(file,constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
  try { const first=fstatSync(fd,{bigint:true}), fields=['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'];
    const named=lstatSync(file,{bigint:true});assert.ok(first.isFile()&&!named.isSymbolicLink()&&first.uid===BigInt(process.getuid())&&first.nlink===1n&&(first.mode&0o077n)===0n&&first.size>0n&&first.size<=BigInt(max));
    assert.ok(fields.every(k=>first[k]===named[k])); const bytes=Buffer.alloc(Number(first.size)+1);let offset=0;
    while(offset<bytes.length){const n=readSync(fd,bytes,offset,bytes.length-offset,null);if(!n)break;offset+=n;}
    assert.equal(offset,Number(first.size));assert.ok(fields.every(k=>first[k]===fstatSync(fd,{bigint:true})[k]&&first[k]===lstatSync(file,{bigint:true})[k]));assert.equal(realpathSync(file),file);
    return {bytes:bytes.subarray(0,offset),evidence:{path:file,sha256:producerHash(bytes.subarray(0,offset))}};
  } finally {closeSync(fd);}
}
export function createV1PrivateWriter({root,python,canonicalWriter,adapter,remaining=()=>10000},command=execFileSync) {
  assert.equal(canonicalWriter.path,path.join(ROOT,'scripts/mobile/local-fixture.py'));
  assert.equal(adapter.path,path.join(ROOT,'scripts/mobile/native-producer-private.py'));
  const program=verifiedFile(adapter.path,adapter.sha256,65536).toString('utf8');verifiedFile(canonicalWriter.path,canonicalWriter.sha256,131072);verifiedFile(python.path,python.sha256,33554432);
  let latest, stopped=false;
  return async (value,options) => {
    assert.equal(stopped,false,'PRODUCER_PRIVATE_OUTCOME_UNCERTAIN_NO_REPLAY');
    assert.equal(options.kind,'canonical-local-fixture-private-json');assert.equal(options.mode,0o600);
    if(options.createExclusive){assert.equal(latest,undefined,'PRODUCER_PRIVATE_CREATE_REPLAY_REFUSED');}
    else {assert.equal(options.sameOwnedDescriptor,true);assert.deepEqual(options.expectedEvidence,latest?.evidence);}
    const name=latest?path.basename(latest.evidence.path):'core-credentials-'+producerHash(Buffer.from(value.email)).slice(0,12)+'.json';
    const input=JSON.stringify({value,expected:latest?{identity:latest.frame,sha256:latest.evidence.sha256}:null});assert.ok(Buffer.byteLength(input)<=16384);
    let output;stopped=true;
    try {output=command(python.path,['-I','-c',program,canonicalWriter.path,canonicalWriter.sha256,root,name],{input,encoding:'utf8',timeout:producerTimeout(remaining()),maxBuffer:16384,env:{PATH:process.env.PATH},stdio:['pipe','pipe','pipe']});}
    catch {throw new Error('PRODUCER_PRIVATE_WRITE_INCOMPLETE_NO_REPLAY');}
    latest=JSON.parse(output);assert.equal(latest.canonicalWriter,'local-fixture.py');assert.equal(latest.evidence.path,path.join(root,name));
    verifiedFile(latest.evidence.path,latest.evidence.sha256,16384);stopped=false;return structuredClone(latest);
  };
}
export function createV1Worker({docker,dockerReceipt,cache,sourceSha,store},command=execFileSync) {
  verifiedFile(docker.path,docker.sha256,134217728);
  const candidates=dockerReceipt.containers.filter(x=>/-api-\d+$/.test(x.name));assert.equal(candidates.length,1);const api=candidates[0];
  let workerRequest;
  return {
    persistWorkerRequest:async value=>{assert.equal(workerRequest,undefined,'PRODUCER_WORKER_REQUEST_REPLAY_REFUSED');assert.equal(value.sourceSha,sourceSha);
      const cacheStore=createProducerStore(cache);workerRequest=cacheStore.write('v1-inbox-worker-request-'+value.runId+'.json',value);return workerRequest;},
    executeWorker:async ({requestEvidence,sourceEvidence,timeoutMs,automaticRetry,onObserverStatement})=>{
      assert.equal(automaticRetry,false);assert.deepEqual(requestEvidence,workerRequest);assert.equal(sourceEvidence.path,path.join(ROOT,'scripts/mobile/local-v1-inbox.py'));
      producerTimeout(timeoutMs,90000);const end=Date.now()+timeoutMs,workerProgram=verifiedFile(sourceEvidence.path,sourceEvidence.sha256,65536).toString('utf8'),request=readProducerReference(requestEvidence);
      const run=(args,maxBuffer=65536)=>command(docker.path,args,{encoding:'utf8',timeout:producerTimeout(end-Date.now(),90000),maxBuffer,stdio:['pipe','pipe','pipe']});
      const keys=['CASEOPS_ENV','CASEOPS_RELEASE_SHA','K_REVISION','K_SERVICE','CLOUD_RUN_JOB','GAE_ENV','FUNCTION_TARGET'];
      const conditions=keys.map(x=>'(eq $key "'+x+'")').join(' ');
      const format='{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"mounts":{{json .Mounts}},"environment":[{{$sep := ""}}{{range .Config.Env}}{{$key := index (split . "=") 0}}{{if or '+conditions+'}}{{$sep}}{{json .}}{{$sep = ","}}{{end}}{{end}}]}';
      const observed=JSON.parse(run(['inspect','--format',format,api.id]));assert.equal(observed.id,api.id);assert.equal(observed.image,api.image);assert.equal(observed.project,dockerReceipt.project);assert.equal(observed.running,true);
      assert.ok(Array.isArray(observed.environment)&&observed.environment.length<=keys.length);const environment={};
      for(const item of observed.environment){assert.equal(typeof item,'string');const index=item.indexOf('='),name=item.slice(0,index);assert.ok(index>0&&keys.includes(name)&&!Object.hasOwn(environment,name));environment[name]=item.slice(index+1);}
      assert.equal(environment.CASEOPS_ENV,'local','PRODUCER_WORKER_NONLOCAL_REFUSED');assert.equal(environment.CASEOPS_RELEASE_SHA,sourceSha);
      assert.equal(environment.K_REVISION,dockerReceipt.backendRevision,'PRODUCER_WORKER_REVISION_CHANGED');
      for(const name of ['K_SERVICE','CLOUD_RUN_JOB','GAE_ENV','FUNCTION_TARGET'])assert.ok(!environment[name],'PRODUCER_WORKER_CLOUD_REFUSED');
      assert.equal(observed.mounts.filter(x=>x.Source===cache&&x.Destination==='/fixture-state'&&x.RW===true).length,1);
      assert.equal(observed.mounts.filter(x=>x.Source===path.join(ROOT,'scripts/mobile')&&x.Destination==='/mobile-fixture'&&x.RW===false).length,1);
      const output=path.join(cache,'v1-inbox-worker-'+request.runId+'.json'),journal=path.join(cache,'v1-inbox-worker-'+request.runId+'.jsonl');assert.equal(existsSync(output)||existsSync(journal),false);
      store.claim('canonical-inbox-dispatch:'+request.runId);
      try {run(['exec','-e','CASEOPS_MOBILE_V1_INBOX_FIXTURE=1','-e','K_REVISION=',api.id,'python','-c','__file__ = "/mobile-fixture/local-v1-inbox.py"\n'+workerProgram,
        '/fixture-state/'+path.basename(requestEvidence.path),requestEvidence.sha256,'/fixture-state/'+path.basename(output)]);}
      catch {throw new Error('PRODUCER_CANONICAL_WORKER_INCOMPLETE_NO_REPLAY');}
      const held=generated(journal);for(const line of held.bytes.toString('utf8').trim().split('\n')){const event=JSON.parse(line);if(event.type==='v1_inbox_observer_charged')onObserverStatement(event.sequence);}
      store.write('inbox-worker-journal-evidence.json',{evidence:held.evidence});const receipt=generated(output);return JSON.parse(receipt.bytes.toString('utf8'));
    },
  };
}
export async function runV1FixtureProducer(q,{admitPublic=admitProducerPublic,now=Date.now,command=execFileSync}={}) {
  const noSecrets=value=>{if(value&&typeof value==='object')for(const[k,v]of Object.entries(value)){assert.ok(!/^(password|access_token|refresh_token|totp_secret|code_verifier|cookies?|authorization|private_key)$/i.test(k),'PRODUCER_PUBLIC_SECRET_REFUSED');noSecrets(v);}};noSecrets(q);
  assert.equal(q.schemaVersion,1);assert.equal(q.kind,'produce-v1-fixture');assert.equal(q.readyForLive,true);assert.equal(q.preparedOnly,false);
  assert.equal(process.versions.node,'24.15.0');assert.equal(q.repoRoot,ROOT);assert.equal(q.admission.repoRoot,ROOT);
  for(const name of ['outputRoot','privateRoot','workerCache'])assert.ok(path.isAbsolute(q[name])&&q[name]!==ROOT&&!q[name].startsWith(ROOT+path.sep),'PRODUCER_OUTPUT_OUTSIDE_REPOSITORY_REQUIRED');
  assert.deepEqual(Object.keys(q.plans),['base','viewer','inbox','readthrough']);
  const store=createProducerStore(q.outputRoot);store.claim('v1-producer:'+q.runId);store.write('request.json',q);
  const initial=await admitPublic(q.admission,{requiredInputs:V1_PRODUCER_INPUTS});
  const host=createProducerHttp({apiOrigin:initial.docker.gatewayUrl,webOrigin:initial.docker.webGatewayUrl,sourceSha:initial.source.sourceSha,
    publicCa:q.admission.publicCa,deadlineMs:now()+510000,persist:store.persist,now});
  const aggregate=createV1FixtureAggregate({runId:q.runId,sourceSha:initial.source.sourceSha,claim:store.claim,persist:store.persist,now});
  const produced={};let stage,actor,actorSpec,admitted;
  const identity=(me,spec)=>{assert.equal(me.company.id,spec.companyId);assert.equal(me.membership.id,spec.membershipId);assert.equal(me.membership.is_active,true);assert.equal(me.user.is_active,true);return me;};
  const admit=async(plan,{boundary,charge,remaining})=>{
    const actual=await admitPublic(q.admission,{requiredInputs:V1_PRODUCER_INPUTS});
    const check=async(key,route,web)=>{const budget=remaining();const timeoutMs=producerTimeout(budget);charge({key,method:'GET',route});const r=await host.request({actor,method:'GET',route,web,timeoutMs,deadlineMs:now()+budget});assert.equal(r.status,200);assert.equal(r.value.release_sha,initial.source.sourceSha);assert.equal(r.value.revision,web?actual.docker.webRevision:actual.docker.backendRevision);};
    await check('api-'+boundary,'/api/build',false);await check('web-'+boundary,'/api/release-identity',true);
    if(boundary==='before'){
      const me=identity(await host.login(actor,actorSpec.credentialEvidence,{charge,remaining}),actorSpec);
      assert.equal(me.membership.role,stage==='inbox'?'member':'owner');
      admitted={beforeMemberRead:true,sourceSha:actual.source.sourceSha,apiSourceSha:actual.source.sourceSha,webSourceSha:actual.source.sourceSha,
        companyId:me.company.id,membershipId:me.membership.id,role:me.membership.role,capabilities:me.capabilities,credentialEvidence:actorSpec.credentialEvidence,
        buildReceipt:q.admission.buildReceipt,dockerReceipt:q.admission.dockerReceipt,installedEvidence:q.admission.installedEvidence,binaryHash:actual.build.binaryHash};
    }
    return admitted;
  };
  try {
    for(stage of ['base','viewer','inbox','readthrough']){
      const plan=resolveProducedReferences(q.plans[stage],produced);assert.equal(plan.sourceSha,initial.source.sourceSha);assert.equal(plan.runId,q.runId);
      actor=stage==='inbox'?'member':'owner';actorSpec=stage==='viewer'?produced.base.receipt.secondaryOwner:q.actors[actor];
      assert.equal(plan.companyId,actorSpec.companyId);assert.equal(stage==='inbox'?plan.membershipId:plan.ownerMembershipId,actorSpec.membershipId);
      if(stage==='viewer')for(const key of ['buildReceipt','dockerReceipt','installedEvidence'])assert.deepEqual(plan[key],q.admission[key]);
      const planEvidence=store.write(stage+'-plan.json',plan),privateWriter=createV1PrivateWriter({root:q.privateRoot,python:q.python,canonicalWriter:q.canonicalWriter,adapter:q.privateAdapter,remaining:()=>aggregate.remaining(stage)},command);
      const dependencies={aggregate,planEvidence,admit,request:input=>host.request({actor,...input,deadlineMs:now()+aggregate.remaining(stage)}),persist:store.persist,claim:store.claim,now,persistPrivate:privateWriter};
      let result;
      if(stage==='viewer')result={receipt:await produceV1Viewer(plan,dependencies)};
      else if(stage==='inbox')result={receipt:await produceV1Inbox(plan,{...dependencies,...createV1Worker({docker:q.docker,dockerReceipt:initial.docker,cache:q.workerCache,sourceSha:initial.source.sourceSha,store},command)})};
      else result=await produceV1Dataset(plan,{...dependencies,catalogue:readProducerReference(plan.catalogueEvidence)});
      const receiptEvidence=store.write(stage+'-receipt.json',result.receipt),fixtureEvidence=result.fixture?store.write(stage+'-dataset.json',result.fixture):undefined;
      produced[stage]={...result,receiptEvidence,...(fixtureEvidence?{fixtureEvidence}:{})};aggregate.complete(stage,receiptEvidence);
    }
    const result=aggregate.finish();validateV1FixtureAggregate(result,initial.source.sourceSha);
    const aggregateEvidence=store.write('aggregate.json',result);
    return {aggregateEvidence,producerEvidence:produced.readthrough.receiptEvidence,datasetEvidence:produced.readthrough.fixtureEvidence,
      viewerEvidence:produced.viewer.receiptEvidence,inboxEvidence:produced.inbox.receiptEvidence,nativeExecution:'not-run'};
  } catch {store.persist({type:'v1_producer_orchestration_stopped',stage,automaticRetry:false,observed:false,completionUnverified:true});throw new Error('V1_PRODUCER_INCOMPLETE_NO_REPLAY');}
  finally {host.clear();}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try{assert.equal(process.env.CASEOPS_NATIVE_V1_PRODUCER_GO,'EXPLICIT_OWNED_SYNTHETIC_PRODUCER');assert.equal(process.argv.length,4);
    console.log(JSON.stringify(await runV1FixtureProducer(readProducerReference({path:process.argv[2],sha256:process.argv[3]}))));}
  catch{console.error('V1_PRODUCER_REFUSED_OR_INCOMPLETE');process.exitCode=1;}
}
