import assert from 'node:assert/strict';
import { clientExtensionInventory } from './client-extensions-inventory.mjs';
export { readV1Reference as readReference, readV1Bytes as readBytes, v1Reference as reference } from './v1-workflows-contract.mjs';
const SHA=/^[a-f0-9]{64}$/,COMMIT=/^[a-f0-9]{40}$/;
const ID=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
export const CX_CAPABILITIES=Object.freeze(['readAttachments','readAttachmentBytes','cameraPrivacy','readNativeSessionIdentity','readCompatibility','readClientMetadata',
 'beginColdPromptObservation','readPromptObservation','readReadthrough','policyCheckpoint','policyAvailabilityCheckpoint','operatorBoundary','readthroughAccessCheckpoint','closeCase','closeRun']);
const row=v=>{assert.ok(v&&typeof v==='object'&&!Array.isArray(v),'CX_OBJECT_REQUIRED');return v;};
const string=(v,max=65536)=>{assert.ok(typeof v==='string'&&v.length<=max,'CX_STRING_REQUIRED');return v;};
const id=v=>{string(v,200);assert.ok(v.trim()&&!/[\x00-\x1f\x7f]/.test(v));return v;};
const integer=v=>{assert.ok(Number.isSafeInteger(v));return v;};
const bool=v=>{assert.equal(typeof v,'boolean');return v;};
const nullable=(v,fn)=>v===null?null:fn(v);
const strings=v=>{assert.ok(Array.isArray(v)&&v.length<=8192);return v.map(x=>string(x));};
function timestamp(v){string(v,64);assert.match(v,/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/);assert.ok(Number.isFinite(Date.parse(v)));return v;}
function scope(v,company,matter){row(v);assert.equal(v.company_id,company);assert.equal(v.matter_id,matter);string(v.matter_status,64);bool(v.matter_is_active);assert.ok(integer(v.matter_lifecycle_version)>=0);return v;}
function retained(v,decode){row(v);id(v.id);if(v.read_state==='available')decode(row(v.record));else{assert.ok(['unsupported_size','unsupported_legacy'].includes(v.read_state));assert.equal(v.record,null);}return v;}
function metadata(v){for(const key of ['type','title','confidence','status'])string(v[key]);bool(v.review_required);}
export function decodeRecommendationSummary(v){retained(v,metadata);timestamp(v.created_at);timestamp(v.updated_at);return v;}
export function decodeRecommendation(v,company,matter,expected){retained(v,x=>{metadata(x);string(x.rationale);integer(x.primary_option_index);for(const key of ['assumptions','missing_facts','retrieved_authorities'])strings(x[key]);nullable(x.next_action,string);if(x.strategy_payload!==null)row(x.strategy_payload);if(x.analysis!==null)row(x.analysis);});assert.equal(v.id,expected);scope(v.scope,company,matter);timestamp(v.created_at);timestamp(v.updated_at);return v;}
export function decodeRecommendationOption(v){retained(v,x=>{for(const key of ['label','rationale','confidence'])string(x[key]);strings(x.supporting_citations);nullable(x.risk_notes,string);});integer(v.rank);return v;}
export function decodeRecommendationDecision(v){retained(v,x=>{nullable(x.actor_membership_id,id);string(x.decision);nullable(x.selected_option_index,integer);nullable(x.notes,string);});timestamp(v.created_at);return v;}
export function decodeHearingPack(v,company,matter,expected){retained(v,x=>{for(const k of ['generated_by_membership_id','reviewed_by_membership_id','model_run_id'])nullable(x[k],id);string(x.status);string(x.summary);bool(x.review_required);});scope(v.scope,company,matter);nullable(v.hearing_id,id);if(expected.packId!==undefined)assert.equal(v.id,expected.packId);if(expected.hearingId!==undefined)assert.equal(v.hearing_id,expected.hearingId);timestamp(v.generated_at);nullable(v.reviewed_at,timestamp);return v;}
export function decodeHearingPackItem(v){retained(v,x=>{for(const k of ['item_type','title','body'])string(x[k]);nullable(x.source_ref,string);});integer(v.rank);timestamp(v.created_at);return v;}
export function decodeReadPage(v,company,matter,parent,kind,order,cursor,decode){row(v);scope(v.scope,company,matter);assert.equal(v.parent_id,parent);assert.equal(v.kind,kind);assert.equal(v.order,order);assert.equal(v.limit,25);assert.ok(Array.isArray(v.items)&&v.items.length<=25);v.items.forEach(decode);assert.equal(new Set(v.items.map(x=>x.id)).size,v.items.length);if(v.next_cursor!==null){string(v.next_cursor,4000);assert.ok(v.next_cursor.trim()&&v.next_cursor!==cursor&&v.items.length>0);}return v;}
export function version(v){assert.ok(typeof v==='string'&&v.length<=29&&/^(?:0|[1-9]\d{0,8})\.(?:0|[1-9]\d{0,8})\.(?:0|[1-9]\d{0,8})$/.test(v),'CX_VERSION_REQUIRED');return v.split('.').map(Number);}
export function parseClientCompatibility(v,client){row(v);assert.deepEqual(Object.keys(v).sort(),['client_version','minimum_supported_version','platform','protocol_version','status']);assert.equal(v.protocol_version,1);assert.equal(v.platform,client.platform);assert.equal(v.client_version,client.version);const actual=version(v.client_version);let update=false;if(v.minimum_supported_version!==null){const floor=version(v.minimum_supported_version);for(let i=0;i<3;i++){if(actual[i]!==floor[i]){update=actual[i]<floor[i];break;}}}assert.equal(v.status,update?'update_required':'supported');return v;}
export function requireClientExtensionRequest(q){row(q);assert.equal(q.schemaVersion,1);assert.equal(q.readyForLive,true,'CX_PENDING_PUBLIC_BINDINGS');assert.equal(q.preparedOnly,false,'CX_PENDING_PUBLIC_BINDINGS');const inventory=clientExtensionInventory(q.platform);assert.equal(q.inventoryId,inventory.inventoryId);assert.match(q.expectedSourceSha||'',COMMIT);for(const k of ['expectedSourceFingerprint','expectedBinaryHash','expectedHarnessFingerprint'])assert.match(q[k]||'',SHA);assert.ok(Number.isSafeInteger(q.expectedInputFileCount)&&q.expectedInputFileCount>0);assert.deepEqual(q.caseIds,inventory.cases.map(x=>x.id),'CX_NO_FILTERED_NATIVE_INVENTORY');return q;}
export function validateClientExtensionFixture(f,platform){
 row(f);assert.equal(f.environment,'docker-integration');assert.equal(f.syntheticDataOnly,true);const c=row(f.cx);
 assert.equal(c.inventoryId,clientExtensionInventory(platform).inventoryId);assert.equal(c.noPaidMarker,'no-paid-providers');assert.equal(c.automaticRetry,false);assert.equal(c.directDatabaseWrites,false);assert.equal(c.nativeMutationsForwardedByControls,false);
 for(const k of ['userId','companyId','membershipId']){assert.match(c.identity[k]||'',ID);if(k!=='userId')assert.equal(c.identity[k],f[k]);}
 assert.match(c.matter.id||'',ID);string(c.matter.code,200);for(const k of ['filename','deniedMessage','privacyDisclosure'])string(c.camera[k],2000);
 assert.deepEqual(c.camera.filenames,['capture.jpg','capture.jpeg','capture.png']);assert.equal(c.camera.deniedMessage,'Camera access was not granted. You can still use Choose file, or enable camera access in device settings.');
 assert.equal(c.camera.privacyDisclosure,'Take a photo, then choose whether to upload it. Photos may include details such as capture location. Those details are kept when you upload. Camera access is optional; Choose file remains available.');
 const actual=version(c.version.actual),floor=version(c.version.floor);assert.ok(actual.some((x,i)=>x!==floor[i])&&actual.find((x,i)=>x!==floor[i])<floor[actual.findIndex((x,i)=>x!==floor[i])],'CX_FLOOR_MUST_EXCEED_ACTUAL_VERSION');assert.ok(Number.isSafeInteger(c.camera.maxAcceptanceBytes)&&c.camera.maxAcceptanceBytes>0&&c.camera.maxAcceptanceBytes<=900000);assert.match(c.version.byteSource.id||'',ID);assert.equal(c.version.byteSource.matterId,c.matter.id);string(c.version.byteSource.text,100000);assert.match(c.version.byteSource.sha256||'',SHA);assert.ok(['simulator','emulator','physical'].includes(c.workflowDomain));if(platform==='ios')assert.notEqual(c.workflowDomain,'emulator');else assert.notEqual(c.workflowDomain,'simulator');
 assert.equal(c.osRecipes.observed,true);assert.equal(c.osRecipes.udid,f.udid);assert.equal(c.osRecipes.platform,platform);assert.match(c.osRecipes.binaryHash||'',SHA);
 assert.ok(Array.isArray(c.osRecipes.allowedApplications)&&c.osRecipes.allowedApplications.length<=6&&c.osRecipes.allowedApplications.includes(f.appId));
 assert.ok(Array.isArray(c.links.invalid)&&c.links.invalid.length>=4&&c.links.invalid.length<=8);for(const key of ['own','secondOwn','foreign'])string(c.links[key],512);
 assert.equal(c.links.foreignMessage,'Sign in to the matching workspace, then open this link again.');assert.match(c.readthrough.matterId||'',ID);assert.equal(c.readthrough.matter.id,c.readthrough.matterId);
 assert.ok(Array.isArray(c.readthrough.packStates)&&c.readthrough.packStates.length>=2&&c.readthrough.packStates.length<=4);
 return f;
}
