import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createHash,randomUUID } from 'node:crypto';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { QP,requireRequest,validateDataset,collectQP,readReference,readBytes,reference ,ownerRecipes } from '../../apps/mobile/e2e/queue-privacy-contract.mjs';
import { queuePrivacyScenarios } from '../../apps/mobile/e2e/queue-privacy.mjs';
import { readV1Member } from '../../apps/mobile/e2e/v1-workflows-credentials.mjs';
import { observeInstalled } from './run-v1-workflows.mjs';
import { sourceSnapshot } from './source-snapshot.mjs';
import { authenticate } from '../../apps/mobile/e2e/browser-handoff.mjs';
import { find,visible,selector,dispatchNativeClick } from '../../apps/mobile/e2e/native-ui.mjs';
import { validateBuildReceipt,validateCoreFixture } from '../../apps/mobile/e2e/fixture-contract.mjs';
import { Journal,binaryHash,localJson,reconcileResults,safeFailure } from '../../apps/mobile/e2e/support.mjs';
import { gatewayBaseline,validateTraffic } from '../../apps/mobile/e2e/traffic.mjs';
import { appiumSessionEvent,configureNativeDriver } from '../../apps/mobile/e2e/run-state.mjs';
import { androidSessionTransport,verifyAndroidSessionTransport } from '../../apps/mobile/e2e/local-run.mjs';
import { createControls,V1_CONTROL_PROTOCOL } from './queue-privacy-controls.mjs';
import { v1PrivateReference } from '../../apps/mobile/e2e/v1-workflows-contract.mjs';
const ROOT=path.resolve(fileURLToPath(new URL('../../',import.meta.url)));
export function qpInputPaths(root=ROOT){return [...new Set([
 ...fs.readdirSync(path.join(root,'apps/mobile/e2e')).filter(n=>/\.(mjs|json)$/.test(n)).map(n=>'apps/mobile/e2e/'+n),
 'scripts/mobile/run-queue-privacy.mjs','scripts/mobile/prepare-queue-privacy-fixture.mjs','scripts/mobile/queue-privacy-controls.mjs',
 'scripts/mobile/run-v1-workflows.mjs','scripts/mobile/source-snapshot.mjs','scripts/mobile/android-files-privacy.mjs',
 'scripts/mobile/local-gateway.py','scripts/mobile/local-v1-controls.py','scripts/mobile/local-queue-privacy-controls.py','compose.mobile-local.yml'])].sort();}
export function qpHarnessFingerprint(root=ROOT){const h=createHash('sha256');for(const name of qpInputPaths(root))h.update(name+'\0').update(fs.readFileSync(path.join(root,name))).update('\0');return h.digest('hex');}
export function pendingQPRequest(){return{schemaVersion:1,inventoryId:QP.inventoryId,profile:QP.profile,readyForLive:false,preparedOnly:true,platform:'PENDING',repoRoot:ROOT,
 expectedSourceSha:null,expectedSourceFingerprint:null,expectedInputFileCount:null,expectedBinaryHash:null,expectedHarnessFingerprint:null,
 fixtureEvidence:null,buildReceipt:null,dockerReceipt:null,deviceEvidence:null,installedEvidence:null,producerEvidence:null,controlsEvidence:null,codeClosure:null,
 members:[{fixtureEvidence:null,credentialEvidence:null,authObservation:null},{fixtureEvidence:null,credentialEvidence:null,authObservation:null}],reportRoot:null};}
export async function admitQPBeforeMembers(q,dependencies={}){
 requireRequest(q);assert.equal(q.profile,QP.profile);assert.equal(q.repoRoot,ROOT);
 const io={read:readReference,bytes:readBytes,snapshot:sourceSnapshot,installed:observeInstalled,getJson:localJson,reader:readV1Member,
 artifactHash:binaryHash,buildCheck:validateBuildReceipt,coreCheck:validateCoreFixture,environment:process.env,harness:qpHarnessFingerprint,inputs:qpInputPaths,...dependencies};
 for(const key of['fixtureEvidence','buildReceipt','dockerReceipt','deviceEvidence','installedEvidence','producerEvidence','controlsEvidence','codeClosure'])reference(q[key]);
 assert.equal(q.members.length,2);for(const m of q.members)v1PrivateReference(m.credentialEvidence);for(const m of q.members)for(const key of['fixtureEvidence','credentialEvidence','authObservation'])reference(m[key]);
 const fixture=io.read(q.fixtureEvidence),build=io.read(q.buildReceipt),isolation=io.read(q.dockerReceipt),device=io.read(q.deviceEvidence),installed=io.read(q.installedEvidence),dataset=io.read(q.producerEvidence),controls=io.read(q.controlsEvidence);
 validateDataset(dataset);assert.deepEqual(fixture.qp.dataset,dataset);assert.equal(fixture.qp.inventoryId,QP.inventoryId);assert.equal(dataset.sourceSha,q.expectedSourceSha);
 assert.equal(dataset.companyId,fixture.companyId);assert.equal(dataset.membershipId,fixture.membershipId);
 const source=io.snapshot(ROOT);assert.deepEqual(source,{sourceSha:q.expectedSourceSha,sourceFingerprint:q.expectedSourceFingerprint,inputFileCount:q.expectedInputFileCount,sourceDirty:false});
 assert.equal(build.sourceSha,source.sourceSha);assert.equal(build.sourceFingerprint,source.sourceFingerprint);assert.equal(build.inputFileCount,source.inputFileCount);assert.equal(build.sourceDirty,false);
 assert.equal(io.artifactHash(build.artifact),q.expectedBinaryHash);io.buildCheck(fixture,q.platform,q.expectedBinaryHash);
 for(const key of['backendSha','webSha','binarySourceSha'])assert.equal(fixture[key],source.sourceSha);assert.equal(fixture.binarySourceFingerprint,source.sourceFingerprint);
 assert.deepEqual(fixture.buildReceipt,q.buildReceipt);assert.deepEqual(fixture.isolationEvidence,q.dockerReceipt);
 for(const key of['backendSha','webSha'])assert.equal(isolation[key],source.sourceSha);assert.equal(isolation.syntheticDataOnly,true);assert.equal(isolation.environment,'docker-integration');
 assert.equal(fixture.qp.nativeSelectors.observed,true);assert.equal(fixture.qp.nativeSelectors.udid,fixture.udid);assert.deepEqual(fixture.qp.nativeSelectors.buildReceipt,q.buildReceipt);
 const closure=io.read(q.codeClosure),expected=io.inputs(ROOT).map(p=>path.join(ROOT,p));assert.deepEqual(closure.code.map(r=>r.path).sort(),expected);
 for(const r of closure.code)io.bytes(r);assert.equal(io.harness(),q.expectedHarnessFingerprint);
 assert.equal(controls.observed,true);assert.equal(controls.binaryHash,q.expectedBinaryHash);assert.equal(controls.kind,'registered-queue-privacy-controls');assert.equal(controls.profile,QP.profile);assert.deepEqual(controls.capabilities,QP.capabilities);assert.deepEqual(controls.caseControlLimits,QP.caseControls);
 assert.equal(controls.sourceSha,source.sourceSha);assert.equal(controls.runId,isolation.gatewayRunId);assert.equal(controls.baseImplementationEvidence.sha256,QP.baseSha256);
 for(const[name,file]of[['module','queue-privacy-controls.mjs'],['gatewayImplementationEvidence','local-queue-privacy-controls.py'],['baseImplementationEvidence','local-v1-controls.py']]){
  assert.equal(controls[name].path,path.join(ROOT,'scripts/mobile',file));io.bytes(controls[name]);assert.ok(closure.code.some(r=>r.path===controls[name].path&&r.sha256===controls[name].sha256));}
 assert.equal(controls.registrationSha256,controls.registrationEvidence.sha256);assert.deepEqual(controls.protocol,V1_CONTROL_PROTOCOL);
 const registration=io.read(controls.registrationEvidence);assert.equal(registration.kind,'registered-queue-privacy-controls');assert.equal(registration.schemaVersion,1);assert.equal(registration.observed,true);assert.equal(registration.readyForLive,true);assert.equal(registration.preparedOnly,false);assert.equal(registration.sourceSha,source.sourceSha);assert.equal(registration.runId,isolation.gatewayRunId);
 assert.deepEqual(registration.authorityEvidence,controls.authorityEvidence);v1PrivateReference(controls.authorityEvidence);for(const actor of Object.values(registration.actors))v1PrivateReference(actor.credentialEvidence);
 assert.deepEqual(registration.ownerRecipes,ownerRecipes(dataset));assert.equal(registration.profile,QP.profile);assert.equal(registration.implementationSha256,controls.gatewayImplementationEvidence.sha256);assert.equal(registration.baseImplementationSha256,QP.baseSha256);
 assert.deepEqual(registration.caseControlLimits,QP.caseControls);assert.ok(registration.syntheticIds.length<=92);assert.equal(new Set(registration.syntheticIds).size,registration.syntheticIds.length);
 for(const actor of Object.values(registration.actors))for(const key of ['userId','membershipId','companyId'])assert.ok(registration.syntheticIds.includes(actor[key]),'QP_COMPLETE_ACTOR_CONTROL_IDENTITIES_REQUIRED');
 for(const t of dataset.tasks)assert.ok(registration.syntheticIds.includes(t.id)&&registration.syntheticIds.includes(t.matter.id));
 assert.equal(registration.actors.member.userId,dataset.memberUserId);assert.equal(registration.actors['second-company'].userId,dataset.secondUserId);
 assert.notEqual(io.environment.NODE_TLS_REJECT_UNAUTHORIZED,'0');assert.equal(io.environment.NODE_EXTRA_CA_CERTS,isolation.publicCA);
 assert.equal(device.observed,true);assert.equal(device.udid,fixture.udid);assert.equal(device.platform,q.platform);assert.deepEqual(device.buildReceipt,q.buildReceipt);
 const actual=io.installed(fixture,q.platform,q.expectedBinaryHash,io.environment);assert.equal(actual.udid,fixture.udid);assert.equal(actual.appId,fixture.appId);assert.equal(actual.binaryHash,q.expectedBinaryHash);
 assert.equal(installed.udid,actual.udid);assert.equal(installed.binaryHash??installed.installedApkSha256,actual.binaryHash);assert.deepEqual(installed.buildReceipt,q.buildReceipt);
 if(q.platform==='android'){assert.equal(actual.bootId,device.bootId);assert.equal(device.pageSizeBytes,16384);}else assert.equal(actual.deviceTypeIdentifier,device.deviceTypeIdentifier);
 if(installed.appDataPath)assert.equal(actual.appDataPath,installed.appDataPath);
 const publics=q.members.map((m,i)=>{
  const f=io.read(m.fixtureEvidence),auth=io.read(m.authObservation),actor=registration.actors[i?'second-company':'member'];
  for(const key of['backendSha','webSha','binarySourceSha'])assert.equal(f[key],source.sourceSha);
  assert.equal(f.binarySourceFingerprint,source.sourceFingerprint);assert.equal(f.udid,fixture.udid);assert.equal(f.appId,fixture.appId);assert.equal(f.auth.mfaRequired,true);
  assert.deepEqual(f.buildReceipt,q.buildReceipt);assert.deepEqual(f.isolationEvidence,q.dockerReceipt);assert.equal(f.membershipId,actor.membershipId);assert.equal(f.companyId,actor.companyId);assert.deepEqual(m.credentialEvidence,actor.credentialEvidence);
  for(const key of['observed','nativePrincipalVerified','nativeWorkspaceVerified','pkceUnchanged','logoutAcknowledged'])assert.equal(auth[key],true);
  assert.equal(auth.sessionCleanup,'passed');assert.equal(auth.udid,f.udid);assert.equal(auth.bundleId,f.appId);assert.equal(auth.membershipId,f.membershipId);assert.equal(auth.binaryHash,q.expectedBinaryHash);
  assert.deepEqual(auth.importedSource,source);assert.deepEqual(auth.buildReceipt,q.buildReceipt);assert.deepEqual(auth.dockerReceipt,q.dockerReceipt);assert.equal(auth.mfaStage,f.auth.mfaStage);assert.equal(auth.iosConsent,f.auth.iosConsent);
  return{entry:m,fixture:f};});
 assert.notEqual(publics[0].fixture.companyId,publics[1].fixture.companyId);assert.equal(publics[0].fixture.membershipId,fixture.membershipId);
 const names=publics.flatMap(x=>['emailEnv','passwordEnv','totpSecretEnv'].map(k=>x.fixture.auth[k]));assert.equal(new Set(names).size,6);for(const name of names)assert.match(name,/^CASEOPS_MOBILE_[A-Z0-9_]+$/);
 const members=[];
 try{for(const p of publics){
  // Repeat source/installed AND both current serving identities immediately
  // before EACH protected member reader, not merely an immutable old receipt.
  assert.deepEqual(io.snapshot(ROOT),source);assert.deepEqual(io.installed(fixture,q.platform,q.expectedBinaryHash,io.environment),actual);
  const api=await io.getJson(isolation.gatewayUrl+'/api/build'),web=await io.getJson(isolation.webGatewayUrl+'/api/release-identity');assert.equal(api.release_sha,source.sourceSha);assert.equal(api.revision,isolation.backendRevision);assert.equal(web.release_sha,source.sourceSha);assert.equal(web.revision,isolation.webRevision);
  const status=await io.getJson(isolation.gatewayUrl+'/__caseops_e2e/status');assert.equal(status.runId,isolation.gatewayRunId);assert.equal(status.v1ControlsEnabled,true);assert.equal(status.v1ControlProfile,QP.profile);
  assert.equal(status.v1ControlsImplementationSha256,controls.gatewayImplementationEvidence.sha256);assert.equal(status.v1RegistrationSha256,controls.registrationEvidence.sha256);
  const loaded=io.reader(p.entry.credentialEvidence.path);let value;try{
   assert.equal(loaded.sha256,p.entry.credentialEvidence.sha256);assert.equal(loaded.uid,p.entry.credentialEvidence.uid);value=loaded.value;assert.equal(value.full_name,p.fixture.principalLabel);assert.equal(value.company_slug,p.fixture.auth.companySlug);
   const environment={...io.environment};for(const[key,field]of[['emailEnv','email'],['passwordEnv','password'],['totpSecretEnv','totp_secret']]){assert.ok(typeof value[field]==='string'&&value[field]);environment[p.fixture.auth[key]]=value[field];}
   try{io.coreCheck(p.fixture,environment);}finally{for(const key of['emailEnv','passwordEnv','totpSecretEnv'])delete environment[p.fixture.auth[key]];}
   members.push({fixture:p.fixture,value});
  }finally{loaded.bytes.fill(0);}
 }}catch(error){for(const m of members){for(const key of Object.keys(m.value||{}))m.value[key]=undefined;m.value=undefined;}throw error;}
 return{fixture,isolation,source,actual,members,controls,publicAdmission:{source,installed:actual,beforeMemberRead:true}};
}
export async function withQPActor(member,action){const prior=new Map();try{for(const[key,field]of[['emailEnv','email'],['passwordEnv','password'],['totpSecretEnv','totp_secret']]){const name=member.fixture.auth[key];prior.set(name,process.env[name]);process.env[name]=member.value[field];}return await action();}finally{for(const[name,value]of prior){if(value===undefined)delete process.env[name];else process.env[name]=value;}}}
async function logout(c){
 const open=await visible(c.driver,selector(c.platform,'id','account-open'));if(open)await dispatchNativeClick(c,open,'id','account-open');
 assert.equal(await(await find(c,'id','account-principal')).getText(),c.fixture.principalLabel);const before=await localJson(c.fixture.gatewayUrl+'/__caseops_e2e/status');
 await dispatchNativeClick(c,await find(c,'id','sign-out',{scroll:true}),'id','sign-out');await c.driver.waitUntil(async()=>!!await visible(c.driver,selector(c.platform,'id','signed-out'))&&!await visible(c.driver,selector(c.platform,'id','session-loading')),{timeout:20000,interval:200});
 const after=await localJson(c.fixture.gatewayUrl+'/__caseops_e2e/status');assert.equal(after.requests.slice(before.lastSequence).filter(r=>r.method==='POST'&&r.route==='/api/auth/native/logout'&&r.status===204).length,1);
 assert.equal((await c.driver.$$(selector(c.platform,'id','privacy-request-receipt'))).length,0);assert.equal((await c.driver.$$(selector(c.platform,'id','queue-task-detail'))).length,0);
}
export async function runQueuePrivacy(q){
 const a=await admitQPBeforeMembers(q),collection=collectQP(q.platform,queuePrivacyScenarios),report=path.join(q.reportRoot,new Date().toISOString().replace(/[:.]/g,'-')+'-'+q.platform+'-qp-'+randomUUID().slice(0,8));
 fs.mkdirSync(report,{mode:0o700});const journal=new Journal(path.join(report,'events.jsonl'));journal.write({type:'run_started',...collection,source:a.source,harnessFingerprint:q.expectedHarnessFingerprint});
 const timer=setTimeout(()=>{journal.write({type:'run_interrupted',reason:'QP_EIGHT_MINUTE_BOUND'});journal.close();process.exit(124);},480000);timer.unref();let controls,cleanupUncertain=false,preflight=false,postflight;const state={actor:null};
 try{
  controls=createControls({fixture:a.fixture,descriptor:a.controls,admission:a.publicAdmission});const baseline=gatewayBaseline(await localJson(a.isolation.gatewayUrl+'/__caseops_e2e/status'),a.isolation);
  const remote=createRequire(path.join(process.env.CASEOPS_MOBILE_TOOLING_HOME||path.join(os.homedir(),'.cache/caseops-mobile/tooling'),'package.json'))('webdriverio').remote;
  const transport=androidSessionTransport(a.fixture,q.platform),url=transport.appiumUrl;
  journal.write({type:'preflight_result',status:'passed',source:a.source,installed:a.actual});preflight=true;
  for(const scenario of queuePrivacyScenarios){const id=q.platform+':'+scenario.id;let driver,c,setup=false,requested=false;let sessionId;
   journal.write({type:'phase_started',id,phase:'setup'});
   try{
    assert.equal(cleanupUncertain,false);assert.deepEqual(sourceSnapshot(ROOT),a.source);assert.equal(qpHarnessFingerprint(),q.expectedHarnessFingerprint);assert.deepEqual(observeInstalled(a.fixture,q.platform,q.expectedBinaryHash,process.env),a.actual);
    const f=a.members[0].fixture;requested=true;driver=await remote({hostname:url.hostname,port:Number(url.port)||4723,protocol:url.protocol.slice(0,-1),path:url.pathname,logLevel:'silent',connectionRetryCount:0,connectionRetryTimeout:60000,
     capabilities:{platformName:q.platform==='ios'?'iOS':'Android','appium:automationName':q.platform==='ios'?'XCUITest':'UiAutomator2','appium:udid':f.udid,'appium:deviceName':f.deviceName,'appium:platformVersion':f.platformVersion,'appium:noReset':true,'appium:newCommandTimeout':60,...transport.capabilities,
      ...(q.platform==='ios'?{'appium:bundleId':f.appId,'appium:includeSafariInWebviews':true,'appium:webviewConnectTimeout':20000}:{'appium:appPackage':f.appId,'appium:dontStopAppOnReset':true,'appium:ensureWebviewsHavePages':true,'appium:enableWebviewDetailsCollection':true})}});
    sessionId=driver.sessionId;journal.write({...appiumSessionEvent(sessionId,'created'),id});if(q.platform==='android')verifyAndroidSessionTransport(f,q.platform,driver.capabilities);await configureNativeDriver(driver,q.platform);await driver.switchContext('NATIVE_APP');
    c={fixture:{...f,qp:a.fixture.qp},platform:q.platform,driver,caseId:scenario.id,controls,gatewayBaseline:baseline,nativeOperations:0,controlCalls:0,authoritativeReads:0,record:e=>journal.write({...e,id})};
    c.switchActor=async actor=>{await logout(c);const member=a.members[actor==='second-company'?1:0];c.fixture={...member.fixture,qp:a.fixture.qp};await withQPActor(member,()=>authenticate(c,{fresh:true}));state.actor=member;};
    await withQPActor(a.members[0],()=>authenticate(c,{fresh:true}));state.actor=a.members[0];setup=true;journal.write({type:'phase_result',id,phase:'setup',status:'passed'});
   }catch(e){cleanupUncertain=true;journal.write({type:'phase_result',id,phase:'setup',status:'failed',reason:safeFailure(e,'QP_SETUP_FAILED')});}
   journal.write({type:'phase_started',id,phase:'call'});if(setup)try{await scenario.run(c);journal.write({type:'phase_result',id,phase:'call',status:'passed'});}catch(e){journal.write({type:'phase_result',id,phase:'call',status:'failed',reason:safeFailure(e,'QP_CALL_FAILED')});}else journal.write({type:'phase_result',id,phase:'call',status:'not-run',reason:'SETUP_FAILED'});
   journal.write({type:'phase_started',id,phase:'teardown'});let clean=true;
   try{const r=await controls.closeCaseControls({caseId:scenario.id});assert.equal(r.allOwnedControlsClosed,true);}catch{clean=false;}
   if(driver){try{if(setup)await logout(c);}catch{clean=false;}try{await driver.deleteSession();journal.write({...appiumSessionEvent(sessionId,'deleted'),id});}catch{clean=false;}}
   else if(requested)clean=false;
   cleanupUncertain||=!clean;journal.write({type:'qp_case_budget',id,nativeControls:c?.nativeOperations,logicalControlCalls:c?.controlCalls,actualTransport:controls.publicState()});journal.write({type:'phase_result',id,phase:'teardown',status:clean?'passed':'failed'});
  }
  assert.equal(cleanupUncertain,false);assert.deepEqual(sourceSnapshot(ROOT),a.source);assert.equal(qpHarnessFingerprint(),q.expectedHarnessFingerprint);assert.deepEqual(observeInstalled(a.fixture,q.platform,q.expectedBinaryHash,process.env),a.actual);
  const after=await localJson(a.isolation.gatewayUrl+'/__caseops_e2e/status');validateTraffic(after,baseline);fs.writeFileSync(path.join(report,'gateway-after.json'),JSON.stringify(after,null,2)+'\n',{flag:'wx',mode:0o600});
  for(const[url,revision]of[[a.isolation.gatewayUrl+'/api/build',a.isolation.backendRevision],[a.isolation.webGatewayUrl+'/api/release-identity',a.isolation.webRevision]]){const value=await localJson(url);assert.equal(value.release_sha,a.source.sourceSha);assert.equal(value.revision,revision);}
  postflight={type:'postflight_result',status:'passed'};
 }catch(e){if(preflight)postflight={type:'postflight_result',status:'failed',reason:safeFailure(e,'QP_RUN_INCOMPLETE')};else{journal.write({type:'preflight_result',status:'failed',reason:safeFailure(e,'QP_PREFLIGHT_INCOMPLETE')});for(const id of collection.intended)for(const phase of['setup','call','teardown']){journal.write({type:'phase_started',id,phase});journal.write({type:'phase_result',id,phase,status:phase==='setup'?'blocked':phase==='call'?'not-run':'passed',reason:'NO_NATIVE_SESSION_PREFLIGHT_FAILED'});}}}
 finally{
  try{if(controls){const r=await controls.closeRunControls({caseId:'PRIVACY-01'});assert.equal(r.allOwnedControlsClosed,true);assert.equal(r.authorityCleared,true);assert.equal(r.journalClosed,true);const s=await localJson(a.isolation.gatewayUrl+'/__caseops_e2e/status');assert.equal(s.v1ControlsEnabled,false);}}
  catch{if(preflight)postflight={type:'postflight_result',status:'failed',reason:'QP_CONTROL_CLEANUP_UNVERIFIED'};}
  finally{controls?.dispose();for(const m of a.members)m.value=undefined;clearTimeout(timer);}
 }
 const sessions=journal.events.filter(e=>e.type==='appium_session'),created=sessions.filter(e=>e.state==='created'),deleted=sessions.filter(e=>e.state==='deleted');
 const paired=created.length===2&&deleted.length===2&&new Set(created.map(e=>e.sessionId)).size===2&&created.every(e=>deleted.some(z=>z.id===e.id&&z.sessionId===e.sessionId));
 if(preflight&&!paired)postflight={type:'postflight_result',status:'failed',reason:'QP_EXACT_TWO_SESSION_LIFECYCLE_REQUIRED'};if(postflight)journal.write(postflight);
 journal.write({type:'run_completed',...collection,intendedCount:2});const result=reconcileResults(journal.events,collection.intended);journal.close();const summary={...collection,...result,pairedSessions:paired,nativeExecution:created.length?'actual':'not-run',report,core23PassedByThisRun:false,files17PassedByThisRun:false,v1SeventeenPassedByThisRun:false};
 fs.writeFileSync(path.join(report,'summary.json'),JSON.stringify(summary,null,2)+'\n',{flag:'wx',mode:0o600});return summary;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{const[platform,mode,file,digest]=process.argv.slice(2);if(mode==='--collect'){assert.equal(process.argv.length,4);console.log(JSON.stringify(collectQP(platform,queuePrivacyScenarios),null,2));}
 else{assert.equal(mode,'--request');assert.equal(process.argv.length,6);assert.equal(process.env.CASEOPS_NATIVE_QUEUE_PRIVACY_GO,'FINAL_SOURCE_MATCHING_WINDOW_RELEASED');const q=readReference({path:file,sha256:digest},16384);requireRequest(q);assert.equal(q.platform,platform);assert.ok(path.isAbsolute(q.reportRoot)&&!path.resolve(q.reportRoot).startsWith(ROOT+path.sep));fs.mkdirSync(q.reportRoot,{recursive:true,mode:0o700});fs.writeFileSync(path.join(q.reportRoot,digest+'.claim.json'),JSON.stringify({request:{path:file,sha256:digest},noReplay:true})+'\n',{flag:'wx',mode:0o600});const r=await runQueuePrivacy(q);console.log(JSON.stringify(r));if(r.status!=='passed')process.exitCode=1;}}
 catch{console.error('QUEUE_PRIVACY_NATIVE_REFUSED_OR_INCOMPLETE_NO_REPLAY');process.exitCode=1;}
}
