import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { QP, validateDataset, ownerRecipes, identity, hash } from '../../apps/mobile/e2e/queue-privacy-contract.mjs';
import { v1PrivateReference } from '../../apps/mobile/e2e/v1-workflows-contract.mjs';
import { readClientPublicInput } from './client-extension-public-input.mjs';
import { sourceSnapshot } from './source-snapshot.mjs';
import { V1_CONTROL_PROTOCOL } from './queue-privacy-controls.mjs';

const ROOT=path.resolve(fileURLToPath(new URL('../../',import.meta.url)));
const read=ref=>readClientPublicInput(ref.path,{expectedSha256:ref.sha256}).value;

/** Public metadata binds the same private bytes in the host and owned mount.
 * This composer never opens credentials or enables/restarts a gateway. */
export function composeQPRegistration(q,dependencies={}) {
 const io={read,bytes:ref=>readClientPublicInput(ref.path,{expectedSha256:ref.sha256,json:false}),snapshot:sourceSnapshot,now:()=>Date.now()/1000,...dependencies};
 assert.equal(q.kind,'compose-queue-privacy-registration');assert.equal(q.preparedOnly,true);
 const source=io.snapshot(ROOT),dataset=validateDataset(io.read(q.datasetEvidence)),receipt=io.read(q.dockerReceipt),build=io.read(q.buildReceipt),closure=io.read(q.codeClosure);
 assert.equal(source.sourceDirty,false);assert.equal(dataset.sourceSha,source.sourceSha);assert.equal(dataset.runId,receipt.gatewayRunId);
 assert.equal(receipt.backendSha,source.sourceSha);assert.equal(receipt.webSha,source.sourceSha);assert.equal(receipt.productionAccessed,false);
 assert.equal(receipt.environment,'docker-integration');assert.equal(receipt.syntheticDataOnly,true);
 for(const key of['sourceSha','sourceFingerprint','inputFileCount','sourceDirty'])assert.equal(build[key],source[key]);
 assert.match(build.binaryHash,/^[a-f0-9]{64}$/);
 const cache=path.dirname(q.dockerReceipt.path);assert.ok(path.isAbsolute(cache)&&cache!==ROOT&&!cache.startsWith(ROOT+path.sep));
 const mount=io.read(q.credentialMountEvidence);assert.equal(mount.kind,'actual-native-client-cache-mount-metadata');assert.equal(mount.observed,true);assert.equal(mount.project,receipt.project);assert.equal(mount.runId,receipt.gatewayRunId);assert.equal(mount.hostRoot,cache);assert.equal(mount.containerRoot,'/fixture-state');assert.ok(Number.isSafeInteger(mount.containerEffectiveUid)&&mount.containerEffectiveUid>=0);
 const mounted=ref=>{
  v1PrivateReference(ref);assert.equal(path.dirname(ref.path),cache);
  const matches=mount.files.filter(row=>row.hostEvidence.path===ref.path);assert.equal(matches.length,1,'QP_UNIQUE_MOUNT_METADATA_REQUIRED');
  const actual=matches[0];assert.deepEqual(actual.hostEvidence,ref);assert.equal(actual.containerUid,mount.containerEffectiveUid);
  return{...ref,path:'/fixture-state/'+path.basename(ref.path),uid:actual.containerUid};
 };
 assert.deepEqual(Object.keys(q.actors).sort(),['member','owner','second-company']);
 const actors={},mappings={};
 for(const[name,actor]of Object.entries(q.actors)){
  const actual=dataset.actors?.[name];assert.ok(actual,'QP_ACTUAL_AUTH_CONTEXT_REQUIRED');
  for(const key of['userId','membershipId','companyId']){identity(actor[key]);assert.equal(actor[key],actual[key]);}
  const runtime=mounted(actor.credentialEvidence);actors[name]={...actual,credentialEvidence:runtime};mappings[name]={hostEvidence:actor.credentialEvidence,runtimeEvidence:runtime};
 }
 assert.equal(actors.owner.companyId,dataset.companyId);assert.equal(actors.member.companyId,dataset.companyId);assert.equal(actors.member.membershipId,dataset.membershipId);assert.equal(actors.member.userId,dataset.memberUserId);assert.equal(actors['second-company'].userId,dataset.secondUserId);assert.notEqual(actors['second-company'].companyId,dataset.companyId);
 assert.equal(new Set(Object.values(actors).map(x=>x.userId)).size,3);assert.equal(new Set(Object.values(actors).map(x=>x.membershipId)).size,3);
 const code=(file)=>{const matches=closure.code.filter(r=>r.path===path.join(ROOT,'scripts/mobile',file));assert.equal(matches.length,1);assert.match(matches[0].sha256,/^[a-f0-9]{64}$/);io.bytes(matches[0]);return matches[0];};
 const implementation=code('local-queue-privacy-controls.py'),base=code('local-v1-controls.py'),module=code('queue-privacy-controls.mjs');assert.equal(base.sha256,QP.baseSha256);
 const ids=new Set();for(const actor of Object.values(actors))for(const key of['userId','membershipId','companyId'])ids.add(actor[key]);
 for(const t of dataset.tasks)for(const value of[t.id,t.matter.id,t.owner_membership_id])if(value!==null&&value!==undefined){identity(value);ids.add(value);}
 for(const p of dataset.peers)for(const key of['membershipId','userId']){identity(p[key]);ids.add(p[key]);}
 assert.ok(ids.size>0&&ids.size<=92);assert.ok(Number.isFinite(q.expiresAt)&&q.expiresAt>io.now()&&q.expiresAt-io.now()<=480);
 const recipes=ownerRecipes(dataset),anchor=dataset.anchor;
 const registration={schemaVersion:1,kind:'registered-queue-privacy-controls',profile:QP.profile,inventoryId:QP.inventoryId,observed:true,readyForLive:true,preparedOnly:false,environment:'docker-integration',syntheticDataOnly:true,noPaidMarker:'no-paid-providers',directDatabaseWrites:false,nativeMutationsForwardedByControls:false,
  sourceSha:source.sourceSha,runId:receipt.gatewayRunId,registrationId:hash(Buffer.from([source.sourceSha,receipt.gatewayRunId,dataset.membershipId].join('\0'))).slice(0,32),expiresAt:q.expiresAt,companyId:dataset.companyId,backendRevision:receipt.backendRevision,webRevision:receipt.webRevision,
  implementationSha256:implementation.sha256,baseImplementationSha256:QP.baseSha256,caseControlLimits:QP.caseControls,capabilities:QP.capabilities,syntheticIds:[...ids].sort(),actors,anchor,
  exactRoutes:['GET /api/matter-work-queue','GET /api/account/deletion-requests','POST /api/account/deletion-requests','GET /api/matters/'+anchor.matterId+'/workspace'],
  ownerExactRoutes:recipes[0].requests.map(r=>r.method+' '+r.route),ownerRecipes:recipes,authorityEvidence:mounted(q.authorityEvidence)};
 assert.deepEqual(io.snapshot(ROOT),source,'QP_REGISTRATION_SOURCE_CHANGED');
 return{registration,descriptor:{kind:registration.kind,profile:QP.profile,observed:true,sourceSha:source.sourceSha,runId:receipt.gatewayRunId,binaryHash:build.binaryHash,origin:receipt.gatewayUrl,authorityEvidence:q.authorityEvidence,credentialMountEvidence:q.credentialMountEvidence,actorCredentialMappings:mappings,capabilities:QP.capabilities,caseControlLimits:QP.caseControls,protocol:V1_CONTROL_PROTOCOL,module,gatewayImplementationEvidence:implementation,baseImplementationEvidence:base},publicProjectionOnly:true,privateReads:0,nativeActions:0,actualNativeAcceptance:false};
}
