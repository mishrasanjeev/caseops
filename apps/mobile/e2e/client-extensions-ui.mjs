import { withObserverAppiumWitness } from '../../../scripts/mobile/android-qa-observer.mjs';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { find, findQuery, visible, selector, dispatchNativeClick, restart, input, backgroundAndResume } from './native-ui.mjs';
import { CX_BUDGETS } from './client-extensions-inventory.mjs';

export class ClientExtensionUnavailable extends Error { constructor(code) { super(code); this.name='ClientExtensionUnavailable'; } }
const operation=c=>{c.checkBudget?.(CX_BUDGETS.nativeReadMs);assert.ok(++c.nativeOperations<=CX_BUDGETS.nativeControls,'CX_NATIVE_OPERATION_BOUND');};
export const record=(c,boundary,facts={})=>c.record({type:'client_extension_assertion',boundary,...facts});
export async function tap(c,id,{scroll=true}={}) { operation(c); const e=await find(c,'id',id,{scroll}); assert.equal(await e.isEnabled(),true,'CX_CONTROL_DISABLED'); await dispatchNativeClick(c,e,'id',id);return e; }
export async function textTap(c,label){operation(c);const e=await find(c,'text',label,{scroll:true});assert.equal(await e.isEnabled(),true);await dispatchNativeClick(c,e);}
export async function waitId(c,id,value,{timeout=CX_BUDGETS.transitionMs}={}) {
 let terminal;
 await c.driver.waitUntil(async()=>{try{const e=await visible(c.driver,selector(c.platform,'id',id));return!!e&&(value===undefined||await e.getText()===value);}catch(error){terminal=error;return true;}},
 {timeout,interval:CX_BUDGETS.pollMs,timeoutMsg:'CX_NATIVE_STATE_REQUIRED'});if(terminal)throw terminal;
}
export async function fact(c,id){operation(c);return(await find(c,'id',id,{scroll:true})).getText();}
export async function text(c,value){operation(c);const e=await find(c,'text',value,{scroll:true});assert.equal(await e.getText(),value,'CX_LITERAL_VISIBLE_VALUE_REQUIRED');}
export async function absent(c,id){operation(c);assert.equal(await visible(c.driver,selector(c.platform,'id',id)),undefined,'CX_PRIVATE_OR_STALE_SURFACE_REMAINS');}
export async function privateAbsent(c){for(const id of ['account-principal','matter-code','files-selection','screen-readthrough','recommendation-options','hearing-pack-items'])await absent(c,id);}
export async function readonly(c,action){const before=await c.controls.traffic();await action();const after=await c.controls.traffic();assert.equal(after.runId,before.runId,'CX_UNEXPECTED_LEDGER_EPOCH_CHANGE');assert.deepEqual(after.requests.slice(0,before.requests.length),before.requests,'CX_LEDGER_PREFIX_CHANGED');const changes=after.requests.slice(before.requests.length);assert.ok(changes.every(x=>['GET','OPTIONS'].includes(x.method)),'CX_READONLY_FLOW_MUTATED');return changes;}
export async function owner(c,name,args={}){c.checkBudget?.(['policyCheckpoint','policyAvailabilityCheckpoint','operatorBoundary'].includes(name)?CX_BUDGETS.operatorCompletionMs:name==='cameraPrivacy'?30000:CX_BUDGETS.httpMs);assert.ok(++c.ownerOperations<=CX_BUDGETS.ownerOperations,'CX_OWNER_OPERATION_BOUND');assert.equal(typeof c.controls[name],'function','CX_REAL_OWNER_CAPABILITY_REQUIRED');return c.controls[name]({caseId:c.caseId,...args});}
export async function authoritative(c,name,args={}){assert.ok(++c.authoritativeReads<=CX_BUDGETS.authoritativeReads,'CX_AUTHORITATIVE_READ_BOUND');return owner(c,name,args);}
export async function files(c){await c.openMatter(c.fixture.cx.matter);await c.segment('Matter view','Files');await waitId(c,'matter-files');assert.equal(await fact(c,'files-matter-code'),c.fixture.cx.matter.code);}
export async function account(c){await tap(c,'account-open',{scroll:false});await waitId(c,'account-screen');assert.equal(await fact(c,'account-principal'),c.fixture.principalLabel);assert.equal(await fact(c,'account-workspace'),c.fixture.workspaceLabel);}
export async function signOut(c,control='sign-out') {
 const before=await c.controls.traffic();await tap(c,control);await waitId(c,'signed-out');await privateAbsent(c);
 const after=await c.controls.traffic();assert.equal(after.runId,before.runId);const rows=after.requests.slice(before.requests.length).filter(x=>x.method==='POST'&&x.route==='/api/auth/native/logout');assert.equal(rows.length,1,'CX_LOGOUT_NOT_ONCE');assert.ok([200,204].includes(rows[0].status));
 c.state.activeActor=null;
}
export async function cameraPrivacy(c,{empty=true}={}) {const witnessed=c.platform==='android'&&c.fixture.privacyObserverEvidence?await withObserverAppiumWitness(c.driver,()=>authoritative(c,'cameraPrivacy')):{value:await authoritative(c,'cameraPrivacy')};const r=witnessed.value;if(witnessed.appiumWitness){assert.equal(r.access,'qa-observer-service');assert.equal(r.observationEpoch?.fullPackageForceStoppedStateCertified,false);c.record?.({type:'qa-observer-appium-coexistence',evidence:witnessed.appiumWitness,observationEpoch:r.observationEpoch});}assert.equal(r.observed,true);assert.equal(r.complete,true);assert.equal(r.udid,c.fixture.udid);assert.equal(r.appId,c.fixture.appId);assert.equal(r.binaryHash,c.binaryHash);assert.equal(r.providerOriginalsRead,false);assert.equal(r.filesDeleted,false);assert.equal(r.legacyKnownFixtureCountsIncluded,false);if(empty)assert.equal(r.counts.copies,0,'CX_CAMERA_SDK_COPY_REMAINS');return r;}
export async function runOsRecipe(c,name) {
 const envelope=c.fixture.cx.osRecipes;
 assert.equal(envelope.observed,true);assert.equal(envelope.platform,c.platform);assert.equal(envelope.udid,c.fixture.udid);assert.equal(envelope.binaryHash,c.binaryHash);assert.deepEqual(envelope.appiumInventoryEvidence,c.appiumInventoryEvidence);
 const recipe=envelope.recipes[name];if(!recipe)throw new ClientExtensionUnavailable('CX_ACTUAL_OS_RECIPE_REQUIRED');
 assert.ok(Array.isArray(recipe)&&recipe.length>0&&recipe.length<=12,'CX_OS_RECIPE_BOUND');
 for(const step of recipe){operation(c);
  if(step.kind==='activate') {assert.ok(envelope.allowedApplications.includes(step.appId),'CX_OWNED_OS_APPLICATION_REQUIRED');await c.driver.activateApp(step.appId);}
  else if(step.kind==='wait') {assert.ok(['id','text','label'].includes(step.locator.kind));await find(c,step.locator.kind,step.locator.value);}
  else if(step.kind==='click') {assert.ok(['id','text','label'].includes(step.locator.kind));const e=await find(c,step.locator.kind,step.locator.value);assert.equal(await e.isEnabled(),true);assert.equal(await e.getAttribute(step.labelAttribute),step.expectedLabel);await dispatchNativeClick(c,e);}
  else throw new ClientExtensionUnavailable('CX_UNREVIEWED_OS_OPERATION');
 }
 record(c,'normal-os-recipe-complete',{recipe:name,steps:recipe.length,workflowDomain:c.workflowDomain,physicalHardwareProven:false});
}
/** A current-device observed value locator scoped to the exact rendered record.
 * Equal generic "Not recorded" labels elsewhere never satisfy this assertion. */
export async function observedFact(c,recordId,label,value) {
 const envelope=c.fixture.cx.nativeSelectors;assert.equal(envelope.observed,true);assert.equal(envelope.udid,c.fixture.udid);assert.equal(envelope.binaryHash,c.binaryHash);assert.deepEqual(envelope.appiumInventoryEvidence,c.appiumInventoryEvidence);
 const recipe=envelope.facts?.[recordId+':'+label];assert.ok(recipe&&recipe.recordId===recordId&&recipe.label===label,'CX_OBSERVED_FACT_VALUE_SCOPE_REQUIRED');
 assert.ok(typeof recipe.query==='string'&&recipe.query.length<=4000);operation(c);
 const e=await findQuery(c,recipe.query,{scroll:true});assert.equal(await e.getText(),value===null?'Not recorded':String(value),'CX_LITERAL_RENDERED_FACT_REQUIRED');
}
export async function background(c) {operation(c);await backgroundAndResume(c);}
export async function observedSegment(c,group,label){
 const observed=c.fixture.cx.nativeSelectors;
 assert.equal(observed.observed,true);assert.equal(observed.udid,c.fixture.udid);assert.equal(observed.binaryHash,c.binaryHash);
 assert.deepEqual(observed.appiumInventoryEvidence,c.appiumInventoryEvidence);
 const recipe=observed.segments[group]?.[label];assert.ok(recipe&&recipe.group===group&&recipe.label===label,'CX_OBSERVED_SEGMENT_REQUIRED');
 assert.ok(recipe.query.startsWith(c.platform==='ios'?'-ios predicate string:':'android='));
 const scope=recipe.scopeQuery?await findQuery(c,recipe.scopeQuery,{scroll:true}):c.driver;
 const element=await visible(scope,recipe.query);assert.ok(element);assert.ok(['text','name','label'].includes(recipe.labelAttribute));
 assert.equal(await element.getAttribute(recipe.labelAttribute),label);operation(c);await dispatchNativeClick(c,element);
}
export async function cold(c) {operation(c);await restart(c);}
export async function biometric(c,mode) {
 assert.ok(['match','cancel','enrollment-change'].includes(mode));
 if(c.workflowDomain==='physical') {await owner(c,'operatorBoundary',{operation:'biometric-'+mode});return;}
 const b=c.fixture.cx.biometricSimulation;
 if(!b?.observed||b.udid!==c.fixture.udid||b.binaryHash!==c.binaryHash)throw new ClientExtensionUnavailable('CX_OBSERVED_OS_BIOMETRIC_SIMULATION_REQUIRED');
 operation(c);
 if(mode==='cancel'){await runOsRecipe(c,'biometricCancel');return;}
 if(mode==='match')await runOsRecipe(c,'biometricPromptVisible');
 if(c.platform==='ios') {
  assert.equal(c.workflowDomain,'simulator');assert.ok(['faceId','touchId'].includes(b.type));
  if(mode==='enrollment-change'){await c.driver.execute('mobile: enrollBiometric',{isEnabled:false});await c.driver.execute('mobile: enrollBiometric',{isEnabled:true});}
  else await c.driver.execute('mobile: sendBiometricMatch',{type:b.type,match:true});
 }else {
  assert.equal(c.workflowDomain,'emulator');
  if(mode==='enrollment-change')await runOsRecipe(c,'biometricEnrollmentChange');
  else {assert.ok(Number.isInteger(b.fingerprintId)&&b.fingerprintId>0&&b.fingerprintId<1000);await c.driver.execute('mobile: fingerprint',{fingerprintId:b.fingerprintId});}
 }
 record(c,'native-os-simulation',{operation:mode,workflowDomain:c.workflowDomain,physicalHardwareProven:false});
}
export async function recordLink(c,url,{verifiedHttps=false}={}) {
 assert.ok(typeof url==='string'&&url.length<=512&&!/[\x00-\x20\x7f]/.test(url));
 if(verifiedHttps){const p=c.fixture.cx.links.verifiedAssociation;if(!p?.observed||p.binaryHash!==c.binaryHash||p.udid!==c.fixture.udid||p.mode!=='production'||!url.startsWith(p.origin+'/native/open/'))throw new ClientExtensionUnavailable('CX_ACTUAL_VERIFIED_HTTPS_ARTIFACT_REQUIRED');}
 operation(c);await c.driver.execute('mobile: deepLink',c.platform==='ios'?{url,bundleId:c.fixture.appId}:{url,package:c.fixture.appId,waitForLaunch:true});
 record(c,'os-record-link-dispatched-once',{urlSha256:createHash('sha256').update(url).digest('hex'),verifiedHttps,physicalAssociationProven:verifiedHttps&&c.workflowDomain==='physical'});
}
export async function openPending(c){await waitId(c,'record-link-open');await tap(c,'record-link-open');}
export async function locked(c){await waitId(c,'local-lock');await privateAbsent(c);}
export async function unlock(c){await locked(c);await tap(c,'local-unlock');await biometric(c,'match');await waitId(c,'account-open',undefined,{timeout:CX_BUDGETS.physicalPromptMs});await absent(c,'local-lock');}
export async function enableLock(c){await account(c);await tap(c,'local-lock-enable');await biometric(c,'match');await text(c,'Enabled for this sign-in on this installation. Sign out to turn it off.');await absent(c,'local-lock-enable');await tap(c,'back');}
export async function inputNote(c,value){operation(c);await input(c,'id','note-input',value);}
