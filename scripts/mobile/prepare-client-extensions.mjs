import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { clientExtensionInventory } from '../../apps/mobile/e2e/client-extensions-inventory.mjs';
import { validateClientExtensionFixture, version } from '../../apps/mobile/e2e/client-extensions-contract.mjs';
import { CX_PROTOCOL, CX_REMOTE_CAPABILITIES } from './client-extension-controls.mjs';
import { readClientPublicInput, writeClientProjection } from './client-extension-public-input.mjs';
import { captureClientFile, clientHarnessFingerprint, captureClientTreeInventory, captureClientTreeInventoryAsync, assertClientRuntimeInventory } from './client-extension-runtime.mjs';
import { sourceSnapshot } from './source-snapshot.mjs';

const ROOT=path.resolve(fileURLToPath(new URL('../../',import.meta.url)));
const read=ref=>readClientPublicInput(ref.path,{expectedSha256:ref.sha256}).value;
const sha=b=>createHash('sha256').update(b).digest('hex');
export function pendingClientExtensionRequest(platform){return{
 schemaVersion:1,platform,inventoryId:clientExtensionInventory(platform).inventoryId,readyForLive:false,preparedOnly:true,
 caseIds:clientExtensionInventory(platform).cases.map(x=>x.id),repoRoot:ROOT,automaticRetry:false,nativeWindowOwned:false,
 expectedSourceSha:null,expectedSourceFingerprint:null,expectedInputFileCount:null,expectedBinaryHash:null,expectedHarnessFingerprint:null,
 fixtureEvidence:null,producerEvidence:null,retainedRowsEvidence:null,artifactVersionEvidence:null,
 buildReceipt:null,dockerReceipt:null,deviceEvidence:null,installedEvidence:null,codeClosure:null,controlsEvidence:null,
 appiumServerEvidence:null,appiumInventoryEvidence:null,acceptedToolEvidence:null,clientRuntimeInventoryEvidence:null,appiumUrl:null,wdaPort:null,
 members:[],claimRoot:null,report:null,leaseDeadlineMs:null,
 physicalHardwareAcceptance:'unverified',verifiedDomainAssociation:'unverified'};}

export function pendingClientExtensionProducers(platform) {
 assert.ok(['ios','android'].includes(platform));const common={schemaVersion:1,readyForLive:false,preparedOnly:true,platform,noPaidMarker:'no-paid-providers',productionAccessed:false,automaticRetry:false,sourceSha:null,backendRevision:null,webRevision:null,expiresAt:null,companyId:null,companySlug:null,membershipId:null,userId:null,credentialEvidence:null};
 return{normal:{...common,kind:'native-client-normal-api-producer',datasetId:null,cameraMatterId:null,byteSourceId:null,byteSourceSha256:null,byteSourceText:null,hearingDate:null,actualBinaryVersion:null,floorVersion:null,workflowDomain:null,secondMatterEvidence:null,scannerConfigurationEvidence:null,retainedRows:[{id:null,kind:'oversize'},{id:null,kind:'legacy-json'}]},retained:{...common,kind:'native-client-retained-row-producer',matterId:null,validSiblingId:null,validSiblingEvidence:null,expectedLifecycleVersion:null,databaseIdentity:null,rows:[{id:null,kind:'oversize'},{id:null,kind:'legacy-json'}]}};
}

/** Filesystem evidence only. The full v2 manifest is audit-only; neither it nor
 * this public producer acknowledges a native server, device or private actor. */
export function prepareClientRuntimeInventory(q,dependencies={}) {
 const io={snapshot:sourceSnapshot,capture:captureClientTreeInventory,...dependencies};
 assert.equal(q.kind,'prepare-native-client-runtime-inventory');assert.equal(q.preparedOnly,true);
 assert.ok(['webdriver','appium'].includes(q.purpose)&&['ios','android'].includes(q.platform));
 assert.ok(path.isAbsolute(q.root)&&path.resolve(q.root)===q.root);
 for(const file of [q.output,q.manifestOutput]) {
  assert.ok(path.isAbsolute(file)&&path.resolve(file)===file);
  assert.ok(file!==ROOT&&!file.startsWith(ROOT+path.sep),'CX_RUNTIME_OUTPUT_OUTSIDE_SOURCE_REQUIRED');
  assert.ok(file!==q.root&&!file.startsWith(q.root+path.sep),'CX_AUDIT_OUTPUT_OUTSIDE_RUNTIME_REQUIRED');
 }
 assert.notEqual(q.output,q.manifestOutput);
 if(q.purpose==='appium')assert.ok(path.isAbsolute(q.appiumEntry)&&path.resolve(q.appiumEntry)===q.appiumEntry&&q.appiumEntry.startsWith(q.root+path.sep),'CX_CANONICAL_CAPTURED_RUNTIME_FILE_REQUIRED');
 const source=io.snapshot(ROOT);assert.equal(source.sourceDirty,false);
 const captured=io.capture(q.root,q.manifestOutput,undefined,q.purpose==='appium'?q.appiumEntry:undefined);
 const inventory={schemaVersion:2,kind:'native-client-'+q.purpose+'-inventory',complete:true,platform:q.platform,...captured,...(q.purpose==='appium'?{appiumEntry:q.appiumEntry}:{})};
 assertClientRuntimeInventory(inventory,q.purpose,q.platform);assert.deepEqual(io.snapshot(ROOT),source);
 return {inventory,source,preparedOnly:true,publicProjectionOnly:true,nativeActions:0,privateReads:0,actualNativeAcceptance:false};
}

export async function prepareClientRuntimeInventoryAsync(q,dependencies={}) {
 const io={snapshot:sourceSnapshot,capture:captureClientTreeInventoryAsync,...dependencies};
 assert.equal(q.kind,'prepare-native-client-runtime-inventory');assert.equal(q.preparedOnly,true);
 assert.ok(['webdriver','appium'].includes(q.purpose)&&['ios','android'].includes(q.platform));
 assert.ok(path.isAbsolute(q.root)&&path.resolve(q.root)===q.root);
 for(const file of [q.output,q.manifestOutput]) {
  assert.ok(path.isAbsolute(file)&&path.resolve(file)===file);
  assert.ok(file!==ROOT&&!file.startsWith(ROOT+path.sep),'CX_RUNTIME_OUTPUT_OUTSIDE_SOURCE_REQUIRED');
  assert.ok(file!==q.root&&!file.startsWith(q.root+path.sep),'CX_AUDIT_OUTPUT_OUTSIDE_RUNTIME_REQUIRED');
 }
 assert.notEqual(q.output,q.manifestOutput);
 if(q.purpose==='appium')assert.ok(path.isAbsolute(q.appiumEntry)&&path.resolve(q.appiumEntry)===q.appiumEntry&&q.appiumEntry.startsWith(q.root+path.sep),'CX_CANONICAL_CAPTURED_RUNTIME_FILE_REQUIRED');
 const source=io.snapshot(ROOT);assert.equal(source.sourceDirty,false);
 const captured=await io.capture(q.root,q.manifestOutput,undefined,q.purpose==='appium'?q.appiumEntry:undefined);
 const inventory={schemaVersion:2,kind:'native-client-'+q.purpose+'-inventory',complete:true,platform:q.platform,...captured,...(q.purpose==='appium'?{appiumEntry:q.appiumEntry}:{})};
 assertClientRuntimeInventory(inventory,q.purpose,q.platform);assert.deepEqual(io.snapshot(ROOT),source);
 return {inventory,source,preparedOnly:true,publicProjectionOnly:true,nativeActions:0,privateReads:0,actualNativeAcceptance:false};
}

/** Public-only composition; the separate writer/normal HTTP receipts stay distinct. */
export function composeClientExtensionFixture(q,dependencies={}){
 const io={read,snapshot:sourceSnapshot,harness:clientHarnessFingerprint,...dependencies};
 assert.equal(q.kind,'compose-native-client-extension-fixture');assert.equal(q.preparedOnly,true);
 const source=io.snapshot(ROOT);assert.equal(source.sourceDirty,false);
 const base=io.read(q.baseFixtureEvidence),dataset=io.read(q.datasetEvidence),build=io.read(q.buildReceipt),receipt=io.read(q.dockerReceipt);
 assert.equal(dataset.kind,'actual-normal-api-native-client-extension-fixture');assert.equal(dataset.observed,true);
 assert.equal(dataset.sourceSha,source.sourceSha);assert.equal(dataset.noPaidMarker,'no-paid-providers');assert.equal(dataset.directDatabaseWrites,false);assert.equal(dataset.automaticRetry,false);assert.equal(dataset.mutationUncertain,false);
 assert.equal(dataset.companyId,base.companyId);assert.equal(dataset.membershipId,base.membershipId);
 assert.deepEqual(base.buildReceipt,q.buildReceipt);assert.deepEqual(base.isolationEvidence,q.dockerReceipt);
 assert.equal(build.sourceSha,source.sourceSha);assert.equal(build.sourceFingerprint,source.sourceFingerprint);assert.equal(build.inputFileCount,source.inputFileCount);assert.equal(build.sourceDirty,false);
 assert.equal(receipt.backendSha,source.sourceSha);assert.equal(receipt.webSha,source.sourceSha);
 const retained=io.read(q.retainedRowsEvidence),committed=io.read(retained.committedEvidence);
 assert.equal(retained.kind,'actual-retained-native-client-extension-readback');assert.equal(retained.complete,true);assert.equal(retained.normalApiReadback,true);
 for(const value of [retained,committed]){assert.equal(value.sourceSha,source.sourceSha);assert.equal(value.companyId,base.companyId);assert.equal(value.matterId,dataset.cx.readthrough.matterId);assert.equal(value.noPaidMarker,'no-paid-providers');}
 assert.equal(committed.historicalWriter,true);assert.equal(committed.directDatabaseWrites,true);assert.equal(committed.consumerDatabaseAuthorityAdded,false);assert.equal(committed.committed,true);assert.deepEqual(committed.before,committed.after);
 const unsupported=retained.readbacks.find(x=>x.id===dataset.cx.readthrough.unsupportedRecommendationId);
 assert.ok(unsupported);assert.equal(unsupported.read_state,'unsupported_size');assert.equal(unsupported.record,null);
 const fixture={...structuredClone(base),cx:{...structuredClone(dataset.cx),inventoryId:clientExtensionInventory(q.platform).inventoryId,
  provenance:{normalApiDataset:q.datasetEvidence,retainedRows:q.retainedRowsEvidence,baseFixture:q.baseFixtureEvidence}}};
 fixture.cx.readthrough.recommendationIds=retained.recommendationPage.items.map(x=>x.id);
 fixture.cx.readthrough.expectedReadbacks=dataset.normalReadbacks;
 fixture.cx.osRecipes=io.read(q.osRecipeEvidence);fixture.cx.nativeSelectors=io.read(q.nativeSelectorEvidence);
 validateClientExtensionFixture(fixture,q.platform);
 return{fixture,request:{...pendingClientExtensionRequest(q.platform),...source,expectedSourceSha:source.sourceSha,expectedSourceFingerprint:source.sourceFingerprint,expectedInputFileCount:source.inputFileCount,expectedBinaryHash:build.binaryHash,expectedHarnessFingerprint:io.harness(ROOT),buildReceipt:q.buildReceipt,dockerReceipt:q.dockerReceipt,producerEvidence:q.datasetEvidence,retainedRowsEvidence:q.retainedRowsEvidence},publicProjectionOnly:true,privateReads:0,nativeActions:0};
}

/** Host paths and actual /fixture-state paths are separate projections of the
 * same admitted bytes, never an invented host path inside a container. */
export function composeClientExtensionRegistration(q,dependencies={}) {
 const io={read,snapshot:sourceSnapshot,code:clientExtensionCodeClosure,now:()=>Date.now()/1000,...dependencies};
 assert.equal(q.kind,'compose-native-client-extension-registration');assert.equal(q.preparedOnly,true);
 const source=io.snapshot(ROOT),dataset=io.read(q.datasetEvidence),receipt=io.read(q.dockerReceipt),build=io.read(q.buildReceipt);
 assert.equal(source.sourceDirty,false);assert.equal(dataset.observed,true);assert.equal(dataset.sourceSha,source.sourceSha);
 assert.equal(receipt.backendSha,source.sourceSha);assert.equal(receipt.webSha,source.sourceSha);assert.equal(receipt.productionAccessed,false);
 assert.equal(build.sourceSha,source.sourceSha);assert.equal(build.sourceFingerprint,source.sourceFingerprint);assert.equal(build.sourceDirty,false);
 const cache=path.dirname(q.dockerReceipt.path);assert.ok(path.isAbsolute(cache)&&cache!==ROOT&&!cache.startsWith(ROOT+path.sep));
 const mount=io.read(q.credentialMountEvidence);assert.equal(mount.kind,'actual-native-client-cache-mount-metadata');assert.equal(mount.observed,true);assert.equal(mount.project,receipt.project);assert.equal(mount.hostRoot,cache);assert.equal(mount.containerRoot,'/fixture-state');assert.ok(Number.isSafeInteger(mount.containerEffectiveUid)&&mount.containerEffectiveUid>=0);assert.equal(mount.runId,receipt.gatewayRunId);
 const mounted=ref=>{assert.equal(path.dirname(ref.path),cache);assert.match(ref.sha256,/^[a-f0-9]{64}$/);assert.ok(Number.isSafeInteger(ref.uid)&&ref.uid>=0);const observed=mount.files.find(x=>x.hostEvidence.path===ref.path);assert.ok(observed);assert.deepEqual(observed.hostEvidence,ref);assert.equal(observed.containerUid,mount.containerEffectiveUid);return{...ref,path:'/fixture-state/'+path.basename(ref.path),uid:observed.containerUid};};
 assert.ok(q.actors&&Object.keys(q.actors).sort().join(',')==='member,owner,second-company');
 const mappings={},actors={};
 for(const [name,value]of Object.entries(q.actors)){const runtime=mounted(value.credentialEvidence);mappings[name]={hostEvidence:value.credentialEvidence,runtimeEvidence:runtime};actors[name]={...value,credentialEvidence:runtime};}
 assert.equal(actors.member.companyId,dataset.companyId);assert.equal(actors.member.membershipId,dataset.membershipId);assert.equal(actors.member.userId,dataset.cx.identity.userId);
 assert.equal(actors.owner.companyId,dataset.companyId);assert.notEqual(actors['second-company'].companyId,dataset.companyId);
 const closure=io.code(ROOT),implementation=closure.code.find(x=>x.path===path.join(ROOT,'scripts/mobile/local-client-extension-controls.py')),base=closure.code.find(x=>x.path===path.join(ROOT,'scripts/mobile/local-v1-controls.py'));
 const retained=io.read(q.retainedRowsEvidence);assert.equal(retained.complete,true);assert.equal(retained.normalApiReadback,true);assert.equal(retained.companyId,dataset.companyId);assert.equal(retained.sourceSha,source.sourceSha);const r={...dataset.cx.readthrough,recommendationIds:retained.recommendationPage.items.map(x=>x.id)},targets=[];
 for(const id of r.recommendationIds)for(const kind of ['recommendation','options','decisions'])targets.push({kind,matterId:r.matterId,id});
 targets.push({kind:'recommendation',matterId:r.revocableMatter.id,id:r.revocableRecommendationId});
 for(const state of r.packStates){targets.push({kind:'latestPack',matterId:state.matter.id,id:state.hearingId});if(state.packId)for(const kind of ['pack','packItems'])targets.push({kind,matterId:state.matter.id,id:state.packId});}
 const matters=[...new Set([r.matterId,r.emptyMatter.id,r.revocableMatter.id])],routes=new Set(['GET /api/auth/native/compatibility','GET /api/auth/native/sessions',`GET /api/matters/${dataset.cx.matter.id}/workspace`,`GET /api/matters/${dataset.cx.matter.id}/attachments/${dataset.cx.version.byteSource.id}/download`,`POST /api/matters/${dataset.cx.matter.id}/attachments`]);
 for(const id of matters)routes.add(`GET /api/matter-readthrough/${id}/recommendations`);
 const navigable=[...new Set([dataset.cx.matter.id,...matters,dataset.cx.links.secondMatter.id])];for(const id of navigable)for(const suffix of ['', '/workspace'])routes.add(`GET /api/matters/${id}${suffix}`);
 for(const t of targets){const prefix=`GET /api/matter-readthrough/${t.matterId}`;routes.add(prefix+(t.kind==='latestPack'?`/hearings/${t.id}/pack`:['recommendation','options','decisions'].includes(t.kind)?`/recommendations/${t.id}`+(t.kind==='recommendation'?'':`/${t.kind}`):`/hearing-packs/${t.id}`+(t.kind==='packItems'?'/items':'')));}
 const identities=new Set([dataset.cx.matter.id,dataset.cx.version.byteSource.id,...matters,...targets.map(x=>x.id),...navigable]);for(const a of Object.values(actors))for(const k of ['companyId','membershipId','userId'])identities.add(a[k]);
 assert.ok(identities.size<=128);assert.ok(Number.isFinite(q.expiresAt)&&q.expiresAt>io.now()&&q.expiresAt-io.now()<=3600);
 const registration={schemaVersion:1,kind:'registered-native-client-extension-controls',profile:'native-client-extensions-v1',observed:true,readyForLive:true,preparedOnly:false,environment:'docker-integration',syntheticDataOnly:true,noPaidMarker:'no-paid-providers',directDatabaseWrites:false,nativeMutationsForwardedByControls:false,sourceSha:source.sourceSha,runId:receipt.gatewayRunId,registrationId:sha(Buffer.from([source.sourceSha,receipt.gatewayRunId,dataset.membershipId].join('\0'))).slice(0,32),expiresAt:q.expiresAt,companyId:dataset.companyId,implementationSha256:implementation.sha256,baseImplementationSha256:base.sha256,platform:q.platform,clientVersion:dataset.cx.version.actual,backendRevision:receipt.backendRevision,webRevision:receipt.webRevision,capabilities:CX_REMOTE_CAPABILITIES,caseIds:clientExtensionInventory(q.platform).cases.map(x=>x.id),caseControlLimits:Object.fromEntries(clientExtensionInventory(q.platform).cases.map(x=>[x.id,12])),syntheticIds:[...identities].sort(),actors,cameraMatterId:dataset.cx.matter.id,byteSourceId:dataset.cx.version.byteSource.id,readthroughMatterId:r.matterId,readthroughMatterIds:matters,readthroughTargets:targets,navigableMatterIds:navigable,revocableMatterId:r.revocableMatter.id,exactRoutes:[...routes].sort(),ownerRecipes:[],ownerExactRoutes:[],scannerConfigurationEvidence:dataset.cx.scannerConfigurationEvidence,authorityEvidence:mounted(q.authorityEvidence)};
 return{registration,descriptor:{kind:'registered-native-client-extension-controls',profile:registration.profile,observed:true,sourceSha:source.sourceSha,binaryHash:build.binaryHash,origin:receipt.gatewayUrl,runId:receipt.gatewayRunId,authorityEvidence:q.authorityEvidence,credentialMountEvidence:q.credentialMountEvidence,actorCredentialMappings:mappings,capabilities:CX_REMOTE_CAPABILITIES,protocol:CX_PROTOCOL,moduleEvidence:closure.controlsModuleEvidence,gatewayImplementationEvidence:implementation,cameraContainersEvidence:q.cameraContainersEvidence,servingEvidence:q.servingEvidence},publicProjectionOnly:true,privateReads:0,nativeActions:0};
}

/** A distinct immutable Compose override; omitted floors are never empty strings. */
export function clientPolicyOverride(platform,floor){
 assert.ok(['ios','android'].includes(platform));if(floor!==null)version(floor);
 return{services:{api:{environment:floor===null?{}:{['CASEOPS_NATIVE_MINIMUM_'+platform.toUpperCase()+'_VERSION']:floor}}}};
}

/** Produce the exact override and argv suffix for the separately admitted
 * canonical Compose operator. This function never restarts a service, reads a
 * secret or publishes a transition ACK. Existing immutable config stays intact. */
export function prepareClientPolicyTransition(q,dependencies={}) {
 const io={read,snapshot:sourceSnapshot,...dependencies};assert.equal(q.kind,'prepare-native-client-policy-transition');assert.equal(q.preparedOnly,true);
 const request=io.read(q.requestEvidence),prior=io.read(q.configurationEvidence),registration=io.read(q.registrationEvidence),source=io.snapshot(ROOT);
 assert.equal(source.sourceDirty,false);assert.equal(request.binding.sourceSha,source.sourceSha);assert.equal(request.operation,'policyCheckpoint');assert.equal(request.noReplay,true);
 const phase=request.args.phase;assert.ok(['floor','rollback','exit-floor','final-rollback'].includes(phase));
 assert.equal(request.caseId,({floor:'CX28-VERSION-02',rollback:'CX28-VERSION-03','exit-floor':'CX28-VERSION-04','final-rollback':'CX28-VERSION-04'})[phase]);
 assert.equal(prior.CASEOPS_MOBILE_API_SHA,source.sourceSha);assert.equal(prior.CASEOPS_MOBILE_WEB_SHA,source.sourceSha);
 assert.equal(prior.CASEOPS_MOBILE_GATEWAY_RUN_ID,request.binding.runId);assert.equal(registration.sourceSha,source.sourceSha);assert.notEqual(registration.runId,request.binding.runId);
 assert.equal(registration.profile,'native-client-extensions-v1');assert.equal(registration.platform,prior.CASEOPS_MOBILE_PLATFORM);
 assert.deepEqual(registration.priorNativeIdentityEvidence,request.args.priorNativeIdentityEvidence);
 const cache=prior.CASEOPS_MOBILE_CACHE;assert.ok(path.isAbsolute(cache)&&cache!==ROOT&&!cache.startsWith(ROOT+path.sep));assert.equal(path.dirname(q.configurationOutput),cache);assert.equal(path.dirname(q.overrideOutput),cache);assert.notEqual(q.configurationOutput,q.overrideOutput);assert.equal(path.dirname(q.registrationEvidence.path),cache);
 const minimum=['floor','exit-floor'].includes(phase)?q.floorVersion:null,override=clientPolicyOverride(registration.platform,minimum);
 const config={...structuredClone(prior),CASEOPS_MOBILE_GATEWAY_RUN_ID:registration.runId,CASEOPS_MOBILE_V1_CONTROLS:'1',CASEOPS_MOBILE_V1_PROFILE:registration.profile,CASEOPS_MOBILE_V1_IMPLEMENTATION_SHA256:registration.implementationSha256,CASEOPS_MOBILE_V1_REGISTRATION:'/fixture-state/'+path.basename(q.registrationEvidence.path),CASEOPS_MOBILE_V1_REGISTRATION_SHA256:q.registrationEvidence.sha256};
 return{kind:'native-client-policy-transition-plan',preparedOnly:true,mutations:0,privateReads:0,source,requestEvidence:q.requestEvidence,originalConfigurationEvidence:q.configurationEvidence,configuration:config,override,configurationSnapshot:{['CASEOPS_NATIVE_MINIMUM_'+registration.platform.toUpperCase()+'_VERSION']:minimum},
  canonicalOperator:{entry:path.join(ROOT,'scripts/mobile/local-bootstrap.py'),function:'compose(cache, configuration)',additionalComposeFiles:[q.overrideOutput],argvSuffix:['up','-d','--no-build','--no-deps','--force-recreate','--wait','--wait-timeout','60','api','gateway'],timeoutSeconds:90,automaticRetry:false,requiresFreshDockerCapacity:{bytes:68719476736,inodes:100000},postcondition:'exact new seven-service/current API+web/TLS/config/epoch/protected-identity observation; then client-policy-checkpoint.mjs actual GET admission'},
  claims:{oldConfigOverwritten:false,oldGatewayEvidenceReset:false,postgresRecreated:false,migrateReplayed:false,apiImageRebuilt:false,nativeCredentialOrHeaderChanged:false}};
}

export function clientExtensionCodeClosure(root=ROOT){
 const files=['scripts/mobile/client-extension-controls.mjs','scripts/mobile/client-extension-public-input.mjs','scripts/mobile/client-extension-runtime.mjs',
  'scripts/mobile/run-client-extensions.mjs','scripts/mobile/prepare-client-extensions.mjs','scripts/mobile/local-client-extension-controls.py','scripts/mobile/local-client-extension-fixture.py',
  'scripts/mobile/local-v1-controls.py','scripts/mobile/local-gateway.py','scripts/mobile/local-fixture.py','compose.mobile-local.yml'];
 for(const dir of ['apps/mobile/e2e','scripts/mobile'])for(const name of fs.readdirSync(path.join(root,dir)))if(/\.(mjs|py|json)$/.test(name))files.push(dir+'/'+name);
 const code=[...new Set(files)].sort().map(file=>{const value=captureClientFile(path.join(root,file),1048576);return{path:value.path,sha256:value.sha256};});
 return{kind:'native-client-extension-code-closure',harnessFingerprint:clientHarnessFingerprint(root),code,
 controlsModuleEvidence:code.find(x=>x.path===path.join(root,'scripts/mobile/client-extension-controls.mjs'))};
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))try{
 const[mode,arg,digest]=process.argv.slice(2);
 if(mode==='--pending'){assert.equal(process.argv.length,4);console.log(JSON.stringify({request:pendingClientExtensionRequest(arg),producers:pendingClientExtensionProducers(arg)},null,2));}
 else if(mode==='--runtime-inventory'){
  assert.equal(process.argv.length,5);const q=readClientPublicInput(arg,{maxBytes:16384,expectedSha256:digest}).value,result=await prepareClientRuntimeInventoryAsync(q);
  const bytes=Buffer.from(JSON.stringify(result.inventory,null,2)+'\n');writeClientProjection(q.output,bytes);
  console.log(JSON.stringify({inventoryEvidence:{path:q.output,sha256:sha(bytes)},auditManifest:result.inventory.auditManifest,preparedOnly:true,actualNativeAcceptance:false,publicProjectionOnly:true,nativeActions:0,privateReads:0}));
 }
 else if(mode==='--policy-plan'){
  assert.equal(process.argv.length,5);const q=readClientPublicInput(arg,{maxBytes:16384,expectedSha256:digest}).value,result=prepareClientPolicyTransition(q);
  const outputs=[[q.configurationOutput,result.configuration],[q.overrideOutput,result.override]].map(([file,value])=>({path:file,bytes:Buffer.from(JSON.stringify(value,null,2)+'\n')}));
  for(const output of outputs){assert.equal(fs.realpathSync(path.dirname(output.path)),path.dirname(output.path));writeClientProjection(output.path,output.bytes);}
  console.log(JSON.stringify({...result,configurationEvidence:{path:outputs[0].path,sha256:sha(outputs[0].bytes)},overrideEvidence:{path:outputs[1].path,sha256:sha(outputs[1].bytes)}}));
 }
 else if(mode==='--register'){
  assert.equal(process.argv.length,5);const q=readClientPublicInput(arg,{maxBytes:16384,expectedSha256:digest}).value,result=composeClientExtensionRegistration(q);
  const cache=path.dirname(q.dockerReceipt.path);assert.equal(path.dirname(q.registrationOutput),cache);assert.equal(path.dirname(q.descriptorOutput),cache);assert.notEqual(q.registrationOutput,q.descriptorOutput);
  const registration=Buffer.from(JSON.stringify(result.registration,null,2)+'\n');assert.ok(registration.length<=1048576);writeClientProjection(q.registrationOutput,registration);
  const registrationEvidence={path:q.registrationOutput,sha256:sha(registration)};
  const descriptor=Buffer.from(JSON.stringify({...result.descriptor,registrationEvidence},null,2)+'\n');assert.ok(descriptor.length<=1048576);writeClientProjection(q.descriptorOutput,descriptor);
  console.log(JSON.stringify({registrationEvidence,controlsEvidence:{path:q.descriptorOutput,sha256:sha(descriptor)},actualNativeAcceptance:false,publicProjectionOnly:true}));
 }
 else{assert.equal(mode,'--compose');assert.equal(process.argv.length,5);const q=readClientPublicInput(arg,{maxBytes:16384,expectedSha256:digest}).value,result=composeClientExtensionFixture(q);
  assert.equal(path.resolve(q.output),q.output);assert.ok(!q.output.startsWith(ROOT+path.sep));const data=Buffer.from(JSON.stringify(result.fixture,null,2)+'\n');assert.ok(data.length<=1048576);
  writeClientProjection(q.output,data);console.log(JSON.stringify({fixtureEvidence:{path:q.output,sha256:sha(data)},request:{...result.request,fixtureEvidence:{path:q.output,sha256:sha(data)}}}));}
}catch{console.error('NATIVE_CLIENT_EXTENSION_PUBLIC_COMPOSITION_REFUSED');process.exitCode=1;}
