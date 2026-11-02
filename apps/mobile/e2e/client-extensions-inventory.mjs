import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
// Independently literal per-platform inventories. No core/Files/V1 case is
// appended, filtered or relabelled by this runner.
export const iosClientExtensions = Object.freeze({
  inventoryId: 'native-client-extension-ios-2026-10-28', platform: 'ios',
  cases: Object.freeze([
    {"id":"CX28-CAM-01","title":"Explicit capture permission denial retains Choose file fallback; no upload","physicalVerificationPending":false},
    {"id":"CX28-CAM-02","title":"Cancel real OS camera intent; empty selection and no owned private SDK copy","physicalVerificationPending":true},
    {"id":"CX28-CAM-03","title":"Explicit real photo -> inspect disclosure -> one upload -> scanner -> exact source/hash/reload","physicalVerificationPending":true},
    {"id":"CX28-CAM-04","title":"Normal OS Settings permission recovery then one explicit capture; no automatic request/replay","physicalVerificationPending":true},
    {"id":"CX28-CAM-05","title":"Rapid retained native upload/clear clicks while camera is opening produce no extra POST; distinguish stale rejection from acknowledged click and prove SDK cleanup","physicalVerificationPending":true},
    {"id":"CX28-CAM-06","title":"Background and logout retire capture; SDK copies absent in separate camera scope","physicalVerificationPending":true},
    {"id":"CX28-LOCK-01","title":"Opt in through actual strong biometric authenticated marker read-back; no server step-up substitution","physicalVerificationPending":true},
    {"id":"CX28-LOCK-02","title":"Background covers/unmounts private UI; real biometric unlock then server revalidation","physicalVerificationPending":true},
    {"id":"CX28-LOCK-03","title":"Cold opted-in restore stays covered without refresh/profile until native prompt succeeds; same admitted server identity returns","physicalVerificationPending":true},
    {"id":"CX28-LOCK-04","title":"Cancel/unavailable sensor/read error stays locked; explicit sign-out remains available","physicalVerificationPending":true},
    {"id":"CX28-LOCK-05","title":"Real enrollment change returns missing-or-invalidated marker without asserting its precise cause; normal sign-in fallback","physicalVerificationPending":true},
    {"id":"CX28-LINK-01","title":"Cold custom record link held in memory until exact own-workspace identity/unlock/policy readiness","physicalVerificationPending":false},
    {"id":"CX28-LINK-02","title":"Warm source link uses actual leave guard; Stay retains draft; explicit Leave performs authorized GET only","physicalVerificationPending":false},
    {"id":"CX28-LINK-03","title":"Locked pending intent cannot cross logout/new principal; a fresh OS link still works","physicalVerificationPending":false},
    {"id":"CX28-LINK-04","title":"Forged/foreign/malformed/query/token/callback links do not navigate or grant authority","physicalVerificationPending":false},
    {"id":"CX28-LINK-05","title":"Actual verified HTTPS association opens installed signed app cold/warm using owned domain metadata","physicalVerificationPending":true},
    {"id":"CX28-READ-01","title":"Populated current recommendation revision/body/citations and option/decision pages remain read-only after reload","physicalVerificationPending":false},
    {"id":"CX28-READ-02","title":"Missing nullable facts, empty response and revoked access clear stale recommendation content honestly","physicalVerificationPending":false},
    {"id":"CX28-READ-03","title":"Existing stored hearing pack and items retain exact parent, content, opaque source reference and return position; no generation or source-ref URL resolution","physicalVerificationPending":false},
    {"id":"CX28-READ-04","title":"Recorded pack states remain distinct and discard earlier positive content; no generation claim","physicalVerificationPending":false},
    {"id":"CX28-VERSION-01","title":"Actual binary version matches policy request and all JSON/multipart/byte headers; supported UI enters normally","physicalVerificationPending":false},
    {"id":"CX28-VERSION-02","title":"Fresh immutable floor-above-actual-binary backend blocks private business UI, preserves session and explicit security exits","physicalVerificationPending":false},
    {"id":"CX28-VERSION-03","title":"Separate immutable rollback configuration plus explicit retry resumes same server session family after revalidation","physicalVerificationPending":false},
    {"id":"CX28-VERSION-04","title":"Unavailable policy, explicit recovery and separately receipted underfloor logout/rollback; no auth replay","physicalVerificationPending":false},
  ].map(Object.freeze)),
});
export const androidClientExtensions = Object.freeze({
  inventoryId: 'native-client-extension-android-2026-10-28', platform: 'android',
  cases: Object.freeze([
    {"id":"CX28-CAM-01","title":"Explicit capture permission denial retains Choose file fallback; no upload","physicalVerificationPending":false},
    {"id":"CX28-CAM-02","title":"Cancel real OS camera intent; empty selection and no owned private SDK copy","physicalVerificationPending":true},
    {"id":"CX28-CAM-03","title":"Explicit real photo -> inspect disclosure -> one upload -> scanner -> exact source/hash/reload","physicalVerificationPending":true},
    {"id":"CX28-CAM-04","title":"Normal OS Settings permission recovery then one explicit capture; no automatic request/replay","physicalVerificationPending":true},
    {"id":"CX28-CAM-05","title":"Rapid retained native upload/clear clicks while camera is opening produce no extra POST; distinguish stale rejection from acknowledged click and prove SDK cleanup","physicalVerificationPending":true},
    {"id":"CX28-CAM-06","title":"Background and logout retire capture; SDK copies absent in separate camera scope","physicalVerificationPending":true},
    {"id":"CX28-LOCK-01","title":"Opt in through actual strong biometric authenticated marker read-back; no server step-up substitution","physicalVerificationPending":true},
    {"id":"CX28-LOCK-02","title":"Background covers/unmounts private UI; real biometric unlock then server revalidation","physicalVerificationPending":true},
    {"id":"CX28-LOCK-03","title":"Cold opted-in restore stays covered without refresh/profile until native prompt succeeds; same admitted server identity returns","physicalVerificationPending":true},
    {"id":"CX28-LOCK-04","title":"Cancel/unavailable sensor/read error stays locked; explicit sign-out remains available","physicalVerificationPending":true},
    {"id":"CX28-LOCK-05","title":"Real enrollment change returns missing-or-invalidated marker without asserting its precise cause; normal sign-in fallback","physicalVerificationPending":true},
    {"id":"CX28-LINK-01","title":"Cold custom record link held in memory until exact own-workspace identity/unlock/policy readiness","physicalVerificationPending":false},
    {"id":"CX28-LINK-02","title":"Warm source link uses actual leave guard; Stay retains draft; explicit Leave performs authorized GET only","physicalVerificationPending":false},
    {"id":"CX28-LINK-03","title":"Locked pending intent cannot cross logout/new principal; a fresh OS link still works","physicalVerificationPending":false},
    {"id":"CX28-LINK-04","title":"Forged/foreign/malformed/query/token/callback links do not navigate or grant authority","physicalVerificationPending":false},
    {"id":"CX28-LINK-05","title":"Actual verified HTTPS association opens installed signed app cold/warm using owned domain metadata","physicalVerificationPending":true},
    {"id":"CX28-READ-01","title":"Populated current recommendation revision/body/citations and option/decision pages remain read-only after reload","physicalVerificationPending":false},
    {"id":"CX28-READ-02","title":"Missing nullable facts, empty response and revoked access clear stale recommendation content honestly","physicalVerificationPending":false},
    {"id":"CX28-READ-03","title":"Existing stored hearing pack and items retain exact parent, content, opaque source reference and return position; no generation or source-ref URL resolution","physicalVerificationPending":false},
    {"id":"CX28-READ-04","title":"Recorded pack states remain distinct and discard earlier positive content; no generation claim","physicalVerificationPending":false},
    {"id":"CX28-VERSION-01","title":"Actual binary version matches policy request and all JSON/multipart/byte headers; supported UI enters normally","physicalVerificationPending":false},
    {"id":"CX28-VERSION-02","title":"Fresh immutable floor-above-actual-binary backend blocks private business UI, preserves session and explicit security exits","physicalVerificationPending":false},
    {"id":"CX28-VERSION-03","title":"Separate immutable rollback configuration plus explicit retry resumes same server session family after revalidation","physicalVerificationPending":false},
    {"id":"CX28-VERSION-04","title":"Unavailable policy, explicit recovery and separately receipted underfloor logout/rollback; no auth replay","physicalVerificationPending":false},
  ].map(Object.freeze)),
});
export const CX_BUDGETS = Object.freeze({ serialMs: 3600000, finalCleanupMs: 90000,
  perCaseMs: 300000, nativeReadMs: 10000, transitionMs: 20000,
  physicalPromptMs: 60000, operatorCompletionMs: 180000, operatorReads: 13,
  pollMs: 200, maxScrolls: 9, nativeControls: 200, authoritativeReads: 32,
  httpMs: 15000, httpBytes: 1048576, ownerOperations: 11, cameraCopies: 128 });
export function clientExtensionInventory(platform) {
  assert.ok(['ios','android'].includes(platform), 'CX_PLATFORM_REQUIRED');
  return platform === 'ios' ? iosClientExtensions : androidClientExtensions;
}
export function collectClientExtensions(platform, scenarios) {
  const inventory = clientExtensionInventory(platform);
  assert.equal(inventory.cases.length,24); assert.equal(new Set(inventory.cases.map(x=>x.id)).size,24);
  assert.ok(Array.isArray(scenarios) && scenarios.every(x=>typeof x.run==='function'), 'CX_EXECUTABLE_SCENARIOS_REQUIRED');
  assert.deepEqual(scenarios.map(x=>x.id),inventory.cases.map(x=>x.id),'CX_COMPLETE_LITERAL_INVENTORY_REQUIRED');
  const intended=inventory.cases.map(x=>platform+':'+x.id);
  return { platform,inventoryId:inventory.inventoryId,intended,discovered:[...intended],
    expectedCases:24,expectedPhases:72,expectedSessions:24,nativeExecution:'not-run',
    phases:intended.flatMap(id=>['setup','call','teardown'].map(phase=>({id,phase}))),
    callbacks:scenarios.map(x=>({id:platform+':'+x.id,sourceSha256:createHash('sha256').update(x.run.toString()).digest('hex'),executable:true})),
    core23Claimed:false,files17Claimed:false,v1Claimed:false };
}
