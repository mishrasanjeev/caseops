import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { QP,requireRequest,validateDataset,readReference,reference,ownerRecipes } from '../../apps/mobile/e2e/queue-privacy-contract.mjs';
import { pendingProducer } from '../../apps/mobile/e2e/queue-privacy-fixture.mjs';
import { sourceSnapshot } from './source-snapshot.mjs';
import { pendingQPRequest } from './run-queue-privacy.mjs';
import { V1_CONTROL_PROTOCOL } from './queue-privacy-controls.mjs';
import { composeQPRegistration } from './queue-privacy-registration.mjs';
import { writeClientProjection } from './client-extension-public-input.mjs';
export { composeQPRegistration } from './queue-privacy-registration.mjs';
const ROOT=path.resolve(fileURLToPath(new URL('../../',import.meta.url)));
export { writePrivatePeer } from '../../apps/mobile/e2e/queue-privacy-fixture.mjs';

export { ownerRecipes } from '../../apps/mobile/e2e/queue-privacy-contract.mjs';
export function pendingRegistration(){return{schemaVersion:1,kind:'registered-queue-privacy-controls',profile:QP.profile,inventoryId:QP.inventoryId,observed:false,readyForLive:false,preparedOnly:true,
 environment:'docker-integration',syntheticDataOnly:true,noPaidMarker:'no-paid-providers',directDatabaseWrites:false,nativeMutationsForwardedByControls:false,
 sourceSha:null,runId:null,expiresAt:null,registrationId:null,companyId:null,implementationSha256:null,baseImplementationSha256:QP.baseSha256,
 backendRevision:null,webRevision:null,caseControlLimits:QP.caseControls,capabilities:QP.capabilities,syntheticIds:[],actors:null,anchor:null,exactRoutes:[],ownerExactRoutes:[],ownerRecipes:[],authorityEvidence:null};}
export function composeQPFixture(q,{read=readReference,snapshot=sourceSnapshot}={}){
 requireRequest(q);assert.equal(q.repoRoot,ROOT);for(const name of['baseFixtureEvidence','producerEvidence','buildReceipt','dockerReceipt','nativeSelectorEvidence','registrationEvidence','controlsEvidence'])reference(q[name]);
 const f=structuredClone(read(q.baseFixtureEvidence)),d=validateDataset(read(q.producerEvidence)),b=read(q.buildReceipt),i=read(q.dockerReceipt),s=snapshot(ROOT),r=read(q.registrationEvidence),controls=read(q.controlsEvidence),selectors=read(q.nativeSelectorEvidence);
 assert.equal(s.sourceDirty,false);assert.equal(s.sourceSha,q.expectedSourceSha);assert.equal(s.sourceFingerprint,q.expectedSourceFingerprint);assert.equal(s.inputFileCount,q.expectedInputFileCount);
 assert.equal(b.sourceSha,s.sourceSha);assert.equal(b.sourceFingerprint,s.sourceFingerprint);assert.equal(b.inputFileCount,s.inputFileCount);assert.equal(b.binaryHash,q.expectedBinaryHash);assert.equal(b.sourceDirty,false);
 assert.equal(d.sourceSha,s.sourceSha);assert.equal(d.companyId,f.companyId);assert.equal(d.membershipId,f.membershipId);assert.equal(d.runId,i.gatewayRunId);
 assert.equal(i.backendSha,s.sourceSha);assert.equal(i.webSha,s.sourceSha);assert.deepEqual(f.buildReceipt,q.buildReceipt);assert.deepEqual(f.isolationEvidence,q.dockerReceipt);
 assert.equal(selectors.observed,true);assert.equal(selectors.udid,f.udid);assert.deepEqual(selectors.buildReceipt,q.buildReceipt);
 assert.equal(r.profile,QP.profile);assert.equal(r.sourceSha,s.sourceSha);assert.equal(r.runId,i.gatewayRunId);assert.deepEqual(r.caseControlLimits,QP.caseControls);assert.deepEqual(r.ownerRecipes,ownerRecipes(d));
 assert.equal(r.actors.member.userId,d.memberUserId);assert.equal(r.actors['second-company'].userId,d.secondUserId);assert.equal(r.baseImplementationSha256,QP.baseSha256);
 assert.deepEqual(controls.registrationEvidence,q.registrationEvidence);assert.deepEqual(controls.capabilities,QP.capabilities);assert.deepEqual(controls.protocol,V1_CONTROL_PROTOCOL);assert.equal(controls.registrationSha256,q.registrationEvidence.sha256);
 f.qp={inventoryId:QP.inventoryId,dataset:d,nativeSelectors:selectors,producerEvidence:q.producerEvidence};return{fixture:f,actualNativeAcceptance:false,producerReplayed:false};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{const[mode,file,digest,output]=process.argv.slice(2);
 if(mode==='--pending'){assert.equal(process.argv.length,3);console.log(JSON.stringify({request:pendingQPRequest(),producer:pendingProducer(),registration:pendingRegistration()},null,2));}
 else if(mode==='--registration'){
  assert.equal(process.argv.length,5);const q=readReference({path:file,sha256:digest},16384),r=composeQPRegistration(q),cache=path.dirname(q.dockerReceipt.path);
  assert.equal(path.dirname(q.registrationOutput),cache);assert.equal(path.dirname(q.descriptorOutput),cache);assert.notEqual(q.registrationOutput,q.descriptorOutput);
  const registration=Buffer.from(JSON.stringify(r.registration,null,2)+'\n'),registrationEvidence=writeClientProjection(q.registrationOutput,registration);
  const descriptor=Buffer.from(JSON.stringify({...r.descriptor,registrationEvidence,registrationSha256:registrationEvidence.sha256},null,2)+'\n'),controlsEvidence=writeClientProjection(q.descriptorOutput,descriptor);
  console.log(JSON.stringify({registrationEvidence,controlsEvidence,actualNativeAcceptance:false,privateReads:0,nativeActions:0}));
 }
 else{assert.equal(mode,'--from-producer');assert.equal(process.argv.length,6);assert.ok(path.isAbsolute(output)&&!path.resolve(output).startsWith(ROOT+path.sep));
  const q=readReference({path:file,sha256:digest},16384),r=composeQPFixture(q);const bytes=Buffer.from(JSON.stringify(r.fixture,null,2)+'\n');const fixtureEvidence=writeClientProjection(output,bytes);console.log(JSON.stringify({fixtureEvidence,actualNativeAcceptance:false,producerReplayed:false}));}}
 catch{console.error('QUEUE_PRIVACY_FIXTURE_REFUSED_NO_REPLAY');process.exitCode=1;}
}
