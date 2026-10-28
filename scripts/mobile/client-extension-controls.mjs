import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { CX_BUDGETS, clientExtensionInventory } from '../../apps/mobile/e2e/client-extensions-inventory.mjs';
import { readReference } from '../../apps/mobile/e2e/client-extensions-contract.mjs';
import { readV1Member } from '../../apps/mobile/e2e/v1-workflows-credentials.mjs';
import { snapshotIosCameraPrivacy } from './ios-files-privacy.mjs';
import { snapshotAndroidCameraPrivacy } from './android-files-privacy.mjs';
import { localJson } from '../../apps/mobile/e2e/support.mjs';
import { observeInstalled } from './run-v1-workflows.mjs';
import { readClientPublicInput } from './client-extension-public-input.mjs';

export const CX_PROTOCOL=Object.freeze({schemaVersion:1,profile:'native-client-extensions-v1',pathname:'/__caseops_e2e/v1-control',
 perReadMs:15000,responseBytes:1048576,argumentBytes:16384,mutationRetries:0});
export const CX_REMOTE_CAPABILITIES=Object.freeze(['readAttachments','readAttachmentBytes','readNativeSessionIdentity','readCompatibility','readClientMetadata','policyAvailabilityCheckpoint',
 'beginColdPromptObservation','readPromptObservation','readReadthrough','readthroughAccessCheckpoint','closeCase','closeRun']);
const sha=b=>createHash('sha256').update(b).digest('hex');
const noSecrets=value=>{if(Array.isArray(value)){value.forEach(noSecrets);return;}if(value&&typeof value==='object')for(const[key,item]of Object.entries(value)){assert.ok(!/(password|secret|token|authorization|cookie)/i.test(key),'CX_PUBLIC_CONTROL_ARGUMENTS_REQUIRED');noSecrets(item);}};
async function body(response,limit){const reader=response.body?.getReader();assert.ok(reader);const chunks=[];let count=0;try{for(;;){const value=await reader.read();if(value.done)break;count+=value.value.length;assert.ok(count<=limit,'CX_CONTROL_RESPONSE_BOUND');chunks.push(value.value);}}finally{try{await reader.cancel();}finally{reader.releaseLock();}}try{return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));}catch{throw Error('CX_CONTROL_JSON_REQUIRED');}}
function writeNew(file,value){const b=Buffer.from(JSON.stringify(value,null,2)+'\n');fs.writeFileSync(file,b,{flag:'wx',mode:0o600});return{path:file,sha256:sha(b)};}
export async function waitForClientOperator({root,operation,caseId,args,binding},dependencies={}){
 const io={now:Date.now,sleep:ms=>new Promise(r=>setTimeout(r,ms)),readPublic:readClientPublicInput,...dependencies};
 assert.ok(path.isAbsolute(root)&&fs.realpathSync(root)===root&&fs.lstatSync(root).isDirectory());
 assert.ok(['policyCheckpoint','policyAvailabilityCheckpoint','operatorBoundary'].includes(operation));noSecrets(args);
 const identity=sha(Buffer.from(JSON.stringify({operation,caseId,args,source:binding.sourceSha,runId:binding.runId})));
 const request=writeNew(path.join(root,identity+'.request.json'),{schemaVersion:1,kind:'native-client-extension-owner-checkpoint',operation,caseId,args,binding,noReplay:true});
 const result=path.join(root,identity+'.result.json'),deadline=io.now()+CX_BUDGETS.operatorCompletionMs;
 for(let attempt=0;attempt<CX_BUDGETS.operatorReads;attempt++){
  assert.ok(io.now()<=deadline,'CX_OPERATOR_COMPLETION_DEADLINE');
  if(fs.existsSync(result)){
   const {value}=io.readPublic(result,{maxBytes:1048576});
   // The authoritative operator writes one immutable ACK. A nonzero, unknown
   // or failed ACK is terminal; this request/claim is never removed or replayed.
   assert.equal(value.kind,'native-client-extension-owner-ack');assert.deepEqual(value.requestEvidence,request);assert.equal(value.operation,operation);assert.equal(value.caseId,caseId);
   assert.deepEqual(value.binding,binding);assert.equal(value.observed,true);assert.equal(value.acknowledged,true);assert.equal(value.noPaidMarker,'no-paid-providers');assert.equal(value.mutationUncertain,false);assert.equal(value.replayed,false);return value.value;
  }
  if(attempt+1<CX_BUDGETS.operatorReads)await io.sleep(Math.min(15000,Math.max(0,deadline-io.now())));
 }
 throw Error('CX_OPERATOR_OUTCOME_UNVERIFIED_NO_REPLAY');
}
export function createClientExtensionControls({fixture,descriptor,admission,report},dependencies={}){
 const io={fetch:globalThis.fetch,member:readV1Member,read:readReference,getJson:localJson,installed:observeInstalled,
  cameraIos:snapshotIosCameraPrivacy,cameraAndroid:snapshotAndroidCameraPrivacy,operator:waitForClientOperator,environment:process.env,...dependencies};
 assert.equal(admission?.beforeMemberRead,true);assert.equal(descriptor.kind,'registered-native-client-extension-controls');assert.equal(descriptor.profile,CX_PROTOCOL.profile);
 assert.equal(descriptor.observed,true);assert.equal(descriptor.sourceSha,admission.source.sourceSha);assert.equal(descriptor.binaryHash,admission.installed.binaryHash);
 assert.deepEqual(descriptor.capabilities,CX_REMOTE_CAPABILITIES);assert.deepEqual(descriptor.protocol,CX_PROTOCOL);
 const origin=new URL(descriptor.origin);assert.equal(origin.origin,new URL(fixture.gatewayUrl).origin);assert.equal(origin.protocol,'https:');assert.ok(['127.0.0.1','localhost','[::1]'].includes(origin.hostname));
 assert.notEqual(io.environment.NODE_TLS_REJECT_UNAUTHORIZED,'0');assert.equal(io.environment.NODE_EXTRA_CA_CERTS,fixture.publicCa.path);
 const registered=io.read(descriptor.registrationEvidence);assert.equal(registered.profile,CX_PROTOCOL.profile);assert.equal(descriptor.authorityEvidence.sha256,registered.authorityEvidence.sha256);
 const loaded=io.member(descriptor.authorityEvidence.path);let authority;
 try{assert.equal(loaded.sha256,descriptor.authorityEvidence.sha256);assert.equal(loaded.uid,descriptor.authorityEvidence.uid);assert.deepEqual(Object.keys(loaded.value),['control_secret']);authority=loaded.value.control_secret;assert.match(authority||'',/^[a-f0-9]{64}$/);}finally{loaded.bytes.fill(0);loaded.value.control_secret=undefined;}
 const cameraRoot=path.join(report,'camera-observations'),operatorRoot=path.join(report,'owner-checkpoints');fs.mkdirSync(cameraRoot,{mode:0o700});fs.mkdirSync(operatorRoot,{mode:0o700});
 let sequence=0,disposed=false,current={...descriptor},nativeIdentityEvidence=null;const attempted=new Set(),counts={};
 const binding=()=>({sourceSha:admission.source.sourceSha,binaryHash:admission.installed.binaryHash,udid:fixture.udid,runId:current.runId});
 async function rpc(capability,{caseId,...args}){
  assert.equal(disposed,false);assert.ok(CX_REMOTE_CAPABILITIES.includes(capability));assert.ok(clientExtensionInventory(admission.platform).cases.some(x=>x.id===caseId));noSecrets(args);
  counts[caseId]=(counts[caseId]||0)+1;assert.ok(counts[caseId]<=12,'CX_CONTROL_CASE_BOUND');
  const operationId=current.runId+':'+caseId+':'+(++sequence);assert.equal(attempted.has(operationId),false);attempted.add(operationId);
  const payload=JSON.stringify({schemaVersion:1,capability,caseId,operationId,runId:current.runId,registrationSha256:current.registrationEvidence.sha256,args});assert.ok(Buffer.byteLength(payload)<=CX_PROTOCOL.argumentBytes);
  let response;try{response=await io.fetch(new URL(CX_PROTOCOL.pathname,origin),{method:'POST',redirect:'error',signal:AbortSignal.timeout(CX_PROTOCOL.perReadMs),headers:{'Content-Type':'application/json','X-CaseOps-Automated-Test':'no-paid-providers','X-CaseOps-V1-Control':authority},body:payload});}
  catch{throw Error(capability==='readthroughAccessCheckpoint'?'CX_OWNER_OUTCOME_UNKNOWN_NO_REPLAY':'CX_OWNER_READ_FAILED');}
  assert.equal(response.status,200,'CX_CONTROL_STATUS_REQUIRED');const result=await body(response,CX_PROTOCOL.responseBytes);
  for(const[key,value]of Object.entries({observed:true,capability,caseId,operationId,runId:current.runId,sourceSha:admission.source.sourceSha,noPaidMarker:'no-paid-providers',directDatabaseWrites:false,nativeMutationsForwardedByControls:false}))assert.equal(result[key],value);
  return result.value;
 }
 const methods=Object.fromEntries(CX_REMOTE_CAPABILITIES.map(cap=>[cap,args=>rpc(cap,args)]));
 methods.readNativeSessionIdentity=async args=>{const value=await rpc('readNativeSessionIdentity',args);
   nativeIdentityEvidence=writeNew(path.join(operatorRoot,++sequence+'.native-identity.json'),{kind:'actual-native-session-identity',observed:true,sourceSha:admission.source.sourceSha,binaryHash:admission.installed.binaryHash,runId:current.runId,identity:Object.fromEntries(['userId','companyId','membershipId','sessionId'].map(k=>[k,value[k]]))});return value;};
 async function checkpoint(operation,{caseId,...args}){
  if(operation==='policyCheckpoint')assert.ok(nativeIdentityEvidence,'CX_ACTUAL_PRIOR_SESSION_REQUIRED');
  const value=await io.operator({root:operatorRoot,operation,caseId,args:{...args,...(operation==='policyCheckpoint'?{priorNativeIdentityEvidence:nativeIdentityEvidence}:{})},binding:binding()});
  if(operation==='policyCheckpoint'){
   const next=io.read(value.controlsEvidence);assert.equal(next.profile,CX_PROTOCOL.profile);assert.equal(next.sourceSha,admission.source.sourceSha);assert.equal(next.binaryHash,admission.installed.binaryHash);
   assert.notEqual(next.runId,current.runId);assert.equal(next.origin,current.origin);assert.equal(next.authorityEvidence.sha256,current.authorityEvidence.sha256);
   assert.deepEqual(next.capabilities,CX_REMOTE_CAPABILITIES);assert.deepEqual(next.protocol,CX_PROTOCOL);
   const nextRegistration=io.read(next.registrationEvidence),oldRegistration=io.read(current.registrationEvidence);
   for(const key of ['actors','capabilities','caseIds','caseControlLimits','syntheticIds','exactRoutes','ownerRecipes','ownerExactRoutes','clientVersion','platform','cameraMatterId','byteSourceId','readthroughMatterIds','navigableMatterIds','readthroughTargets','revocableMatterId','baseImplementationSha256','implementationSha256','binaryHash','sourceSha','scannerConfigurationEvidence'])assert.deepEqual(nextRegistration[key],oldRegistration[key],'CX_POLICY_CHANGED_UNRELATED_PROFILE');
   assert.equal(nextRegistration.priorNativeIdentityEvidence.sha256,nativeIdentityEvidence.sha256);
   assert.deepEqual(nextRegistration.priorNativeIdentity,io.read(nativeIdentityEvidence).identity);
   const serving=io.read(value.servingEvidence);assert.equal(serving.complete,true);assert.equal(serving.productionAccessed,false);assert.equal(serving.backendSha,admission.source.sourceSha);assert.equal(serving.webSha,admission.source.sourceSha);assert.equal(serving.gatewayRunId,next.runId);
   assert.equal(serving.kind,'actual-client-policy-configuration-transition');assert.equal(serving.observed,true);
   assert.deepEqual(serving.previousServingEvidence,current.servingEvidence);assert.deepEqual(next.servingEvidence,value.servingEvidence);
   const previous=io.read(current.servingEvidence);assert.deepEqual(serving.protectedIdentityEvidence,previous.protectedIdentityEvidence);
   assert.deepEqual([...serving.currentContainerIdentities.map(x=>x.role)].sort(),['api','gateway','migrate','postgres','scanner','valkey','web']);
   assert.equal(new Set(serving.currentContainerIdentities.map(x=>x.id)).size,7);
   const config=io.read(value.configurationEvidence);assert.equal(config['CASEOPS_NATIVE_MINIMUM_'+admission.platform.toUpperCase()+'_VERSION'],['floor','exit-floor'].includes(args.phase)?fixture.cx.version.floor:null);
   assert.equal(serving.databaseAndSecurityIdentityPreserved,true);assert.equal(serving.configurationEvidence.sha256,value.configurationEvidence.sha256);
   const api=await io.getJson(fixture.gatewayUrl+'/api/build'),web=await io.getJson(fixture.webGatewayUrl+'/api/release-identity');assert.equal(api.release_sha,admission.source.sourceSha);assert.equal(api.revision,serving.backendRevision);assert.equal(web.release_sha,admission.source.sourceSha);assert.equal(web.revision,serving.webRevision);
   const status=await io.getJson(fixture.gatewayUrl+'/__caseops_e2e/status');assert.equal(status.runId,next.runId);assert.equal(status.v1ControlProfile,CX_PROTOCOL.profile);assert.equal(status.v1RegistrationSha256,next.registrationEvidence.sha256);current=next;
  }
  return value;
 }
 return{...methods,policyCheckpoint:args=>checkpoint('policyCheckpoint',args),operatorBoundary:args=>checkpoint('operatorBoundary',args),
  async traffic(){const status=await io.getJson(fixture.gatewayUrl+'/__caseops_e2e/status');assert.equal(status.runId,current.runId);assert.equal(status.overflow,false);assert.ok(Array.isArray(status.requests)&&status.requests.length<=500);return status;},
  async cameraPrivacy(){assert.deepEqual(io.installed(fixture,admission.platform,admission.installed.binaryHash,io.environment),admission.installed);const containers=io.read(descriptor.cameraContainersEvidence);
   const output=path.join(cameraRoot,++sequence+'.json');const result=admission.platform==='ios'?io.cameraIos({containers,output}):io.cameraAndroid({containers,output,udid:fixture.udid,appId:fixture.appId,environment:io.environment});
   return{...result.observation,observed:true,binaryHash:admission.installed.binaryHash};},
  dispose(){authority=undefined;disposed=true;},publicState:()=>({attemptedOperations:attempted.size,caseCounts:{...counts},disposed,credentialValuesPrinted:false,currentRunId:current.runId})};
}
