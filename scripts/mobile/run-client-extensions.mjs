import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { sourceSnapshot } from './source-snapshot.mjs';
import { observeInstalled } from './run-v1-workflows.mjs';
import { createClientExtensionControls } from './client-extension-controls.mjs';
import { readClientPublicInput } from './client-extension-public-input.mjs';
import { admitClientServerAsync, clientHarnessFingerprint, captureClientFile, captureClientTreeCommitmentAsync, assertClientRuntimeInventory, selectedClientExecutable } from './client-extension-runtime.mjs';
import { clientExtensionCodeClosure } from './prepare-client-extensions.mjs';
import { CX_BUDGETS } from '../../apps/mobile/e2e/client-extensions-inventory.mjs';
import { collectNativeClientExtensions, clientExtensionScenarios } from '../../apps/mobile/e2e/client-extensions-20261028.mjs';
import { requireClientExtensionRequest, validateClientExtensionFixture } from '../../apps/mobile/e2e/client-extensions-contract.mjs';
import { ClientExtensionUnavailable, account, signOut, cameraPrivacy } from '../../apps/mobile/e2e/client-extensions-ui.mjs';
import { readV1Member } from '../../apps/mobile/e2e/v1-workflows-credentials.mjs';
import { validateBuildReceipt, validateCoreFixture } from '../../apps/mobile/e2e/fixture-contract.mjs';
import { binaryHash, localJson, Journal, reconcileResults } from '../../apps/mobile/e2e/support.mjs';
import { configureNativeDriver, appiumSessionEvent } from '../../apps/mobile/e2e/run-state.mjs';
import { authenticate } from '../../apps/mobile/e2e/browser-handoff.mjs';
import { home } from '../../apps/mobile/e2e/native-ui.mjs';
import { openMatter } from '../../apps/mobile/e2e/journeys.mjs';
import { observedSegment } from '../../apps/mobile/e2e/client-extensions-ui.mjs';
import { androidSessionTransport, verifyAndroidSessionTransport } from '../../apps/mobile/e2e/local-run.mjs';

const ROOT=path.resolve(fileURLToPath(new URL('../../',import.meta.url)));
const read=ref=>readClientPublicInput(ref.path,{expectedSha256:ref.sha256}).value;
const PUBLIC_FAILURES=new Set(['CX_EARLIER_OUTCOME_UNSAFE','CX_REQUIRED_PRIOR_CASE_UNVERIFIED','CX_CASE_DEADLINE',
 'CX_NATIVE_CLEANUP_RESERVE','CX_VERIFIED_DOMAIN_AND_SIGNED_PROFILE_PENDING','CX_CAPTURE_EXCEEDS_FIXED_GATEWAY_POSITIVE_BOUND',
 'CX_ACTUAL_OS_RECIPE_REQUIRED','CX_OBSERVED_OS_BIOMETRIC_SIMULATION_REQUIRED','CX_ACTUAL_VERIFIED_HTTPS_ARTIFACT_REQUIRED',
 'CX_OPERATOR_OUTCOME_UNVERIFIED_NO_REPLAY','CX_OPERATOR_COMPLETION_DEADLINE','CX_SESSION_CREATE_OUTCOME_UNKNOWN','CX_INDEPENDENT_CLEANUP_UNVERIFIED','CX_OWNER_OUTCOME_UNKNOWN_NO_REPLAY']);
export const clientFailure=(error,fallback)=>PUBLIC_FAILURES.has(error?.message)?error.message:fallback;

export async function admitClientExtensions(q,dependencies={}) {
  requireClientExtensionRequest(q);
  const io={read,bytes:ref=>readClientPublicInput(ref.path,{expectedSha256:ref.sha256,json:false}).bytes,snapshot:sourceSnapshot,harness:clientHarnessFingerprint,installed:observeInstalled,
    artifactHash:binaryHash,getJson:localJson,server:admitClientServerAsync,tool:captureClientFile,selectedExecutable:selectedClientExecutable,reader:readV1Member,
    buildCheck:validateBuildReceipt,coreCheck:validateCoreFixture,closure:clientExtensionCodeClosure,tree:captureClientTreeCommitmentAsync,environment:process.env,now:Date.now,...dependencies};
  assert.equal(q.repoRoot,ROOT);assert.equal(q.automaticRetry,false);assert.equal(q.nativeWindowOwned,true);
  assert.equal(io.environment.CASEOPS_NATIVE_CLIENT_EXTENSIONS_GO,'EXPLICIT_OWNED_NATIVE_WINDOW');
  assert.ok(Number.isSafeInteger(q.leaseDeadlineMs)&&q.leaseDeadlineMs-io.now()>=CX_BUDGETS.serialMs+120000,'CX_FULL_INVENTORY_LEASE_REQUIRED');
  const tools=io.read(q.acceptedToolEvidence);assert.equal(tools.observed,true);assert.equal(tools.platform,q.platform);
  if(q.platform==='ios')assert.equal(io.environment.DEVELOPER_DIR,tools.developerDir);
  assert.ok(Array.isArray(tools.executables)&&tools.executables.length>=2&&tools.executables.length<=12);
  assert.equal(new Set(tools.executables.map(t=>t.role)).size,tools.executables.length);
  assert.equal(tools.executables.find(t=>t.role==='node').file.path,process.execPath);
  assert.equal(tools.executables.find(t=>t.role==='git').file.path,io.selectedExecutable('git',io.environment));
  for(const tool of tools.executables)assert.deepEqual(io.tool(tool.file.path),tool.file,'CX_ACCEPTED_EXECUTABLE_CHANGED');
  const source={sourceSha:q.expectedSourceSha,sourceFingerprint:q.expectedSourceFingerprint,sourceDirty:false,inputFileCount:q.expectedInputFileCount};
  assert.deepEqual(io.snapshot(ROOT),source);assert.equal(io.harness(ROOT),q.expectedHarnessFingerprint);
  const fixture=io.read(q.fixtureEvidence);validateClientExtensionFixture(fixture,q.platform);
  for(const observed of [fixture.cx.osRecipes,fixture.cx.nativeSelectors]){assert.equal(observed.observed,true);assert.equal(observed.platform,q.platform);assert.equal(observed.udid,fixture.udid);assert.equal(observed.binaryHash,q.expectedBinaryHash);assert.deepEqual(observed.appiumInventoryEvidence,q.appiumInventoryEvidence);}
  if(fixture.cx.biometricSimulation?.observed){assert.equal(fixture.cx.biometricSimulation.udid,fixture.udid);assert.equal(fixture.cx.biometricSimulation.binaryHash,q.expectedBinaryHash);}

  const build=io.read(q.buildReceipt),isolation=io.read(q.dockerReceipt),device=io.read(q.deviceEvidence),expectedInstalled=io.read(q.installedEvidence);
  assert.deepEqual(fixture.buildReceipt,q.buildReceipt);assert.deepEqual(fixture.isolationEvidence,q.dockerReceipt);
  for(const k of ['binarySourceSha','backendSha','webSha'])assert.equal(fixture[k],source.sourceSha);
  assert.equal(build.sourceSha,source.sourceSha);assert.equal(build.sourceFingerprint,source.sourceFingerprint);assert.equal(build.sourceDirty,false);assert.equal(build.inputFileCount,source.inputFileCount);
  assert.equal(io.artifactHash(build.artifact),q.expectedBinaryHash);io.buildCheck(fixture,q.platform,q.expectedBinaryHash);
  const versionProof=io.read(q.artifactVersionEvidence);assert.equal(versionProof.kind,'actual-native-artifact-version');assert.equal(versionProof.observed,true);
  assert.deepEqual(versionProof.buildReceipt,q.buildReceipt);assert.equal(versionProof.binaryHash,q.expectedBinaryHash);assert.equal(versionProof.platform,q.platform);
  assert.equal(versionProof.version,fixture.cx.version.actual);assert.equal(versionProof.reader,q.platform==='ios'?'PlistBuddy-CFBundleShortVersionString':'aapt2-dump-badging');
  assert.equal(isolation.backendSha,source.sourceSha);assert.equal(isolation.webSha,source.sourceSha);assert.equal(isolation.productionAccessed,false);assert.equal(isolation.noPaidProviderKeysInAPIOrWeb,true);assert.equal(isolation.apiWebPostgresScannerNetworkInternal,true);assert.equal(isolation.tlsProof.strictDefaultTLS,true);assert.equal(isolation.tlsProof.verificationDisabled,false);
  assert.equal(device.observed,true);assert.equal(device.platform,q.platform);assert.equal(device.udid,fixture.udid);assert.equal(device.appId,fixture.appId);assert.deepEqual(device.buildReceipt,q.buildReceipt);
  const closure=io.read(q.codeClosure);assert.equal(closure.harnessFingerprint,q.expectedHarnessFingerprint);
  assert.deepEqual(closure,io.closure(ROOT),'CX_COMPLETE_EXECUTABLE_SOURCE_CLOSURE_REQUIRED');
  assert.ok(Array.isArray(closure.code)&&closure.code.length>0);
  const gatewayCode=closure.code.find(x=>x.path===path.join(ROOT,'scripts/mobile/local-gateway.py'));assert.ok(gatewayCode);assert.equal(isolation.gatewayImplementationSha256,gatewayCode.sha256);
  for(const ref of closure.code){assert.ok(ref.path.startsWith(ROOT+path.sep));io.bytes(ref);}
  const producer=io.read(q.producerEvidence);assert.equal(producer.kind,'actual-normal-api-native-client-extension-fixture');
  for(const [key,value]of Object.entries({observed:true,sourceSha:source.sourceSha,noPaidMarker:'no-paid-providers',directDatabaseWrites:false,automaticRetry:false,mutationUncertain:false}))assert.equal(producer[key],value);
  assert.deepEqual(fixture.cx.provenance.normalApiDataset,q.producerEvidence);assert.equal(producer.companyId,fixture.companyId);assert.equal(producer.membershipId,fixture.membershipId);
  const retained=io.read(q.retainedRowsEvidence);assert.equal(retained.complete,true);assert.equal(retained.normalApiReadback,true);assert.equal(retained.companyId,fixture.companyId);assert.equal(retained.sourceSha,source.sourceSha);
  assert.deepEqual(fixture.cx.provenance.retainedRows,q.retainedRowsEvidence);
  const controls=io.read(q.controlsEvidence);assert.equal(controls.profile,'native-client-extensions-v1');assert.equal(controls.sourceSha,source.sourceSha);assert.equal(controls.binaryHash,q.expectedBinaryHash);
  assert.deepEqual(controls.moduleEvidence,closure.controlsModuleEvidence);assert.equal(controls.moduleEvidence.path,path.join(ROOT,'scripts/mobile/client-extension-controls.mjs'));
  const registration=io.read(controls.registrationEvidence);assert.equal(registration.clientVersion,versionProof.version);assert.equal(registration.runId,isolation.gatewayRunId);
  assert.equal(registration.companyId,fixture.companyId);assert.equal(registration.implementationSha256,controls.gatewayImplementationEvidence.sha256);
  const installed=io.installed(fixture,q.platform,q.expectedBinaryHash,io.environment);assert.equal(installed.udid,fixture.udid);assert.equal(installed.appId,fixture.appId);assert.equal(installed.binaryHash,q.expectedBinaryHash);
  assert.equal(expectedInstalled.binaryHash??expectedInstalled.installedApkSha256,q.expectedBinaryHash);assert.equal(expectedInstalled.udid,fixture.udid);
  if(q.platform==='android'){assert.equal(installed.bootId,device.bootId);assert.equal(device.pageSizeBytes,16384);}else{assert.equal(installed.deviceTypeIdentifier,device.deviceTypeIdentifier);assert.equal(installed.runtime,device.runtime);}
  const server=await io.server(q);assert.deepEqual(fixture.cx.osRecipes.appiumInventoryEvidence,q.appiumInventoryEvidence);
  const clientRuntime=io.read(q.clientRuntimeInventoryEvidence);assertClientRuntimeInventory(clientRuntime,'webdriver',q.platform);assert.equal(clientRuntime.root,io.environment.CASEOPS_MOBILE_TOOLING_HOME);
  assert.deepEqual(await io.tree(clientRuntime.root),clientRuntime.tree,'CX_COMPLETE_WEBDRIVER_RUNTIME_CHANGED');
  assert.notEqual(io.environment.NODE_TLS_REJECT_UNAUTHORIZED,'0');assert.equal(io.environment.NODE_EXTRA_CA_CERTS,isolation.publicCA);assert.equal(fixture.publicCa.path,isolation.publicCA);io.bytes(fixture.publicCa);
  for(const [origin,route,revision]of [[isolation.gatewayUrl,'/api/build',isolation.backendRevision],[isolation.webGatewayUrl,'/api/release-identity',isolation.webRevision]]){
    const value=await io.getJson(origin+route);assert.equal(value.release_sha,source.sourceSha);assert.equal(value.revision,revision);
  }
  const status=await io.getJson(isolation.gatewayUrl+'/__caseops_e2e/status');assert.equal(status.runId,isolation.gatewayRunId);assert.equal(status.implementationSha256,gatewayCode.sha256);assert.equal(status.overflow,false);
  assert.equal(status.v1ControlProfile,controls.profile);assert.equal(status.v1ControlsEnabled,true);assert.equal(status.v1RegistrationSha256,controls.registrationEvidence.sha256);assert.equal(status.v1ControlsImplementationSha256,controls.gatewayImplementationEvidence.sha256);
  assert.deepEqual(io.snapshot(ROOT),source);assert.deepEqual(io.installed(fixture,q.platform,q.expectedBinaryHash,io.environment),installed);
  const publicMembers=q.members.map((entry,index)=>{
    const f=io.read(entry.fixtureEvidence),auth=io.read(entry.authObservation),name=index?'second-company':'member';
    assert.equal(f.udid,fixture.udid);assert.deepEqual(f.buildReceipt,q.buildReceipt);assert.deepEqual(f.isolationEvidence,q.dockerReceipt);
    for(const key of ['binarySourceSha','backendSha','webSha'])assert.equal(f[key],source.sourceSha);
    assert.equal(auth.observed,true);assert.equal(auth.udid,fixture.udid);assert.equal(auth.membershipId,f.membershipId);assert.equal(auth.binaryHash,q.expectedBinaryHash);
    assert.equal(f.auth.mfaRequired,true);assert.deepEqual(auth.importedSource,source);assert.equal(auth.appId??auth.bundleId,f.appId);assert.equal(auth.nativePrincipalVerified,true);assert.equal(auth.nativeWorkspaceVerified,true);assert.equal(auth.pkceUnchanged,true);assert.equal(auth.logoutAcknowledged,true);assert.equal(auth.sessionCleanup,'passed');
    assert.deepEqual(auth.buildReceipt,q.buildReceipt);assert.deepEqual(auth.dockerReceipt,q.dockerReceipt);
    const mapping=controls.actorCredentialMappings[name];assert.deepEqual(entry.credentialEvidence,mapping.hostEvidence);assert.deepEqual(registration.actors[name].credentialEvidence,mapping.runtimeEvidence);assert.equal(mapping.runtimeEvidence.path,'/fixture-state/'+path.basename(entry.credentialEvidence.path));assert.equal(mapping.runtimeEvidence.sha256,entry.credentialEvidence.sha256);const mount=io.read(controls.credentialMountEvidence);assert.equal(mount.observed,true);assert.equal(mount.runId,isolation.gatewayRunId);assert.equal(mount.project,isolation.project);assert.equal(mount.hostRoot,path.dirname(q.dockerReceipt.path));assert.equal(mapping.runtimeEvidence.uid,mount.containerEffectiveUid);assert.ok(mount.files.some(x=>x.containerUid===mapping.runtimeEvidence.uid&&JSON.stringify(x.hostEvidence)===JSON.stringify(entry.credentialEvidence)));assert.equal(f.companyId,registration.actors[name].companyId);assert.equal(f.membershipId,registration.actors[name].membershipId);
    return{entry,fixture:f};
  });
  const envNames=publicMembers.flatMap(x=>['emailEnv','passwordEnv','totpSecretEnv'].map(k=>x.fixture.auth[k]));assert.equal(new Set(envNames).size,6);for(const name of envNames)assert.match(name,/^CASEOPS_MOBILE_[A-Z0-9_]+$/);
  assert.equal(publicMembers.length,2);assert.equal(publicMembers[0].fixture.membershipId,fixture.membershipId);assert.notEqual(publicMembers[0].fixture.companyId,publicMembers[1].fixture.companyId);
  // Every public and current-runtime check above precedes either protected reader.
  const currentGuard=async()=>{
    assert.deepEqual(io.snapshot(ROOT),source);assert.deepEqual(io.installed(fixture,q.platform,q.expectedBinaryHash,io.environment),installed);await io.server(q);
    const api=await io.getJson(isolation.gatewayUrl+'/api/build'),web=await io.getJson(isolation.webGatewayUrl+'/api/release-identity');
    assert.equal(api.release_sha,source.sourceSha);assert.equal(api.revision,isolation.backendRevision);assert.equal(web.release_sha,source.sourceSha);assert.equal(web.revision,isolation.webRevision);
    const status=await io.getJson(isolation.gatewayUrl+'/__caseops_e2e/status');assert.equal(status.runId,isolation.gatewayRunId);assert.equal(status.implementationSha256,gatewayCode.sha256);assert.equal(status.v1RegistrationSha256,controls.registrationEvidence.sha256);
  };
  const members=[];
  try {for(const {entry,fixture:f}of publicMembers){await currentGuard();const loaded=io.reader(entry.credentialEvidence.path);let transferred=false;try{
    assert.equal(loaded.sha256,entry.credentialEvidence.sha256);assert.equal(loaded.uid,entry.credentialEvidence.uid);
    const env={...io.environment};assert.equal(loaded.value.full_name,f.principalLabel);assert.equal(loaded.value.company_slug,f.auth.companySlug);
    for(const [key,field]of [['emailEnv','email'],['passwordEnv','password'],['totpSecretEnv','totp_secret']]){assert.match(f.auth[key],/^CASEOPS_MOBILE_[A-Z0-9_]+$/);assert.ok(typeof loaded.value[field]==='string'&&loaded.value[field]);env[f.auth[key]]=loaded.value[field];}
    try{io.coreCheck(f,env);}finally{for(const key of ['emailEnv','passwordEnv','totpSecretEnv'])delete env[f.auth[key]];}members.push({fixture:f,value:loaded.value});transferred=true;
  }finally{try{loaded.bytes.fill(0);}finally{if(!transferred&&loaded.value)for(const key of Object.keys(loaded.value))loaded.value[key]=undefined;}}}}catch(error){members.forEach(m=>{if(m.value)for(const key of Object.keys(m.value))m.value[key]=undefined;m.value=undefined;});throw error;}
  return{fixture,build,isolation,source,installed,members,controls,server,currentGuard,platform:q.platform,beforeMemberRead:true};
}

/** Serial phase accounting; known unsupported prerequisites remain unverified. */
export async function executeClientExtensionInventory({platform,scenarios=clientExtensionScenarios,setup,teardown,write,now=Date.now}) {
  const collection=collectNativeClientExtensions(platform),passed=new Set();let unsafe=false;
  assert.deepEqual(scenarios.map(x=>x.id),clientExtensionScenarios.map(x=>x.id),'CX_COMPLETE_EXECUTABLE_INVENTORY_REQUIRED');
  const started=now();
  for(const scenario of scenarios){const id=platform+':'+scenario.id;let context,setupPassed=false,callPassed=false;
    write({type:'phase_started',id,phase:'setup'});
    try{if(unsafe)throw new ClientExtensionUnavailable('CX_EARLIER_OUTCOME_UNSAFE');assert.ok(now()-started<CX_BUDGETS.serialMs);if(!(scenario.requires||[]).every(x=>passed.has(x)))throw new ClientExtensionUnavailable('CX_REQUIRED_PRIOR_CASE_UNVERIFIED');context=await setup(scenario);setupPassed=true;write({type:'phase_result',id,phase:'setup',status:'passed'});}
    catch(error){const unavailable=error instanceof ClientExtensionUnavailable;unsafe ||= !unavailable;write({type:'phase_result',id,phase:'setup',status:unavailable?'blocked':'failed',reason:clientFailure(error,'CX_SETUP_FAILED')});}
    write({type:'phase_started',id,phase:'call'});
    if(setupPassed)try{await scenario.run(context);assert.ok(now()-context.startedAt<=CX_BUDGETS.perCaseMs,'CX_CASE_DEADLINE');callPassed=true;passed.add(scenario.id);write({type:'phase_result',id,phase:'call',status:'passed'});}
    catch(error){unsafe ||= !(error instanceof ClientExtensionUnavailable);write({type:'phase_result',id,phase:'call',status:'failed',reason:clientFailure(error,'CX_CALL_FAILED'),...(error instanceof ClientExtensionUnavailable?{unverified:true}:{})});}
    else write({type:'phase_result',id,phase:'call',status:'not-run',reason:'CX_SETUP_REQUIRED'});
    write({type:'phase_started',id,phase:'teardown'});
    try{await teardown({scenario,context,setupPassed,callPassed,unsafe});write({type:'phase_result',id,phase:'teardown',status:'passed'});}
    catch(error){unsafe=true;write({type:'phase_result',id,phase:'teardown',status:'failed',reason:clientFailure(error,'CX_CLEANUP_UNVERIFIED')});}
  }return {unsafe,passed:[...passed],collection};
}

async function withMember(member,action){const old=new Map();try{for(const[k,v]of [['emailEnv','email'],['passwordEnv','password'],['totpSecretEnv','totp_secret']]){const name=member.fixture.auth[k];old.set(name,process.env[name]);process.env[name]=member.value[v];}return await action();}finally{for(const[k,v]of old)if(v===undefined)delete process.env[k];else process.env[k]=v;}}

export function admitClientOutputRoot(q) {
 assert.ok(path.isAbsolute(q.claimRoot||'')&&fs.realpathSync(q.claimRoot)===q.claimRoot);assert.ok(q.claimRoot!==ROOT&&!q.claimRoot.startsWith(ROOT+path.sep));
 const value=fs.lstatSync(q.claimRoot);assert.ok(value.isDirectory()&&!value.isSymbolicLink());if(process.getuid)assert.equal(value.uid,process.getuid());assert.equal(value.mode&0o077,0);
 assert.equal(path.dirname(q.report),q.claimRoot);assert.ok(!fs.existsSync(q.report),'CX_FRESH_REPORT_REQUIRED');
}

export async function runClientExtensions(q,dependencies={}) {
  const io={admit:admitClientExtensions,controls:createClientExtensionControls,server:admitClientServerAsync,snapshot:sourceSnapshot,harness:clientHarnessFingerprint,installed:observeInstalled,now:Date.now,mkdir:(file,options)=>fs.mkdirSync(file,options),journal:file=>new Journal(file),...dependencies};
  admitClientOutputRoot(q);const admitted=await io.admit(q);
  // Private admission has completed. Every later public/output/journal failure
  // must still clear both retained members; test-only dependencies are code,
  // never fields accepted from an execution request.
  let journal,journalCloseAttempted=false,originalError;
  const closeJournal=()=>{if(journal&&!journalCloseAttempted){journalCloseAttempted=true;journal.close();}};
  try{
  const collection=collectNativeClientExtensions(q.platform);
  admitClientOutputRoot(q);io.mkdir(q.report,{mode:0o700});journal=io.journal(path.join(q.report,'events.jsonl'));
  const write=event=>journal.write(event),state={mutationUncertain:false};let controls,preflightPassed=false,finalPassed=false,active,sessionUnknown=false,runtimeRefusal;const sessions=[];
  write({type:'run_started',...collection,harnessFingerprint:q.expectedHarnessFingerprint,source:admitted.source,binaryHash:q.expectedBinaryHash,physicalHardwareAcceptance:'unverified'});
  const live=async()=>{
    if(runtimeRefusal)throw runtimeRefusal;
    try{assert.ok(io.now()<q.leaseDeadlineMs-120000);assert.equal(io.harness(ROOT),q.expectedHarnessFingerprint);assert.deepEqual(io.snapshot(ROOT),admitted.source);assert.deepEqual(io.installed(admitted.fixture,q.platform,q.expectedBinaryHash,process.env),admitted.installed);await io.server(q);}
    catch(error){if(error.captureRequiresProcessExit)runtimeRefusal=error;throw error;}
  };
  try{
    await admitted.currentGuard();controls=await io.controls({fixture:admitted.fixture,descriptor:admitted.controls,admission:admitted,report:q.report});
    write({type:'preflight_result',status:'passed'});preflightPassed=true;
    const remote=dependencies.remote||createRequire(path.join(process.env.CASEOPS_MOBILE_TOOLING_HOME||path.join(os.homedir(),'.cache/caseops-mobile/tooling'),'package.json'))('webdriverio').remote;
    await executeClientExtensionInventory({platform:q.platform,now:io.now,write,setup:async scenario=>{
      await live();const f=admitted.fixture,transport=androidSessionTransport(f,q.platform),url=new URL(q.appiumUrl);
      if(q.platform==='android')assert.equal(url.href,transport.appiumUrl.href,'CX_ANDROID_TRANSPORT_BINDING_REQUIRED');
      const capabilities={platformName:q.platform==='ios'?'iOS':'Android','appium:automationName':q.platform==='ios'?'XCUITest':'UiAutomator2','appium:udid':f.udid,'appium:deviceName':f.deviceName,'appium:platformVersion':f.platformVersion,'appium:noReset':true,'appium:autoLaunch':false,'appium:newCommandTimeout':60,...transport.capabilities,
        ...(q.platform==='ios'?{'appium:bundleId':f.appId,'appium:wdaLocalPort':q.wdaPort,'appium:includeSafariInWebviews':true,'appium:webviewConnectTimeout':20000}:{'appium:appPackage':f.appId,'appium:dontStopAppOnReset':true,'appium:ensureWebviewsHavePages':true,'appium:enableWebviewDetailsCollection':true})};
      sessionUnknown=true;const driver=await remote({hostname:url.hostname,port:Number(url.port),protocol:url.protocol.slice(0,-1),path:url.pathname,capabilities,logLevel:'silent',connectionRetryCount:0,connectionRetryTimeout:10000});sessionUnknown=false;
      active=driver;sessions.push(driver.sessionId);write({...appiumSessionEvent(driver.sessionId,'created'),id:q.platform+':'+scenario.id});
      if(q.platform==='android')verifyAndroidSessionTransport(f,q.platform,driver.capabilities);
      await configureNativeDriver(driver,q.platform);await driver.switchContext('NATIVE_APP');
      const actor=state.activeActor==='second-company'?admitted.members[1].fixture:f;
      const context={fixture:{...actor,cx:f.cx},platform:q.platform,driver,controls,state,caseId:scenario.id,binaryHash:q.expectedBinaryHash,workflowDomain:f.cx.workflowDomain,appiumInventoryEvidence:q.appiumInventoryEvidence,startedAt:io.now(),nativeOperations:0,ownerOperations:0,authoritativeReads:0,record:row=>write({...row,id:q.platform+':'+scenario.id})};
      context.checkBudget=needed=>{assert.ok(io.now()+needed<=context.startedAt+CX_BUDGETS.perCaseMs,'CX_CASE_DEADLINE');assert.ok(io.now()+needed<=q.leaseDeadlineMs-120000,'CX_NATIVE_CLEANUP_RESERVE');};
      context.home=tab=>home(context,tab);context.segment=(group,label)=>observedSegment(context,group,label);
      context.openMatter=matter=>openMatter(context,matter);
      context.ensureAuthenticated=async(actor='member')=>{assert.ok(['member','second-company'].includes(actor));const member=admitted.members[actor==='member'?0:1];
        if(state.activeActor&&state.activeActor!==actor){await account(context);await signOut(context);}
        context.fixture={...member.fixture,cx:f.cx};await withMember(member,()=>authenticate(context,{fresh:false}));state.activeActor=actor;};
      if(scenario.id==='CX28-CAM-01')await context.ensureAuthenticated();
      return context;
    },teardown:async({scenario,context,unsafe})=>{
      const failures=[];
      if(controls&&context)try{const clean=await controls.closeCase({caseId:scenario.id});assert.equal(clean.allOwnedControlsClosed,true);}catch{failures.push('owner');}
      if(context&&scenario.id==='CX28-VERSION-04'&&!unsafe)try{assert.equal(state.finalSignedOut,true);await cameraPrivacy(context);}catch{failures.push('signed-out');}
      if(active){const driver=active;active=undefined;try{const id=driver.sessionId;await driver.deleteSession();write({...appiumSessionEvent(id,'deleted'),id:q.platform+':'+scenario.id});}catch{failures.push('session');}}
      assert.equal(sessionUnknown,false,'CX_OPERATOR_OUTCOME_UNVERIFIED_NO_REPLAY','CX_OPERATOR_COMPLETION_DEADLINE','CX_SESSION_CREATE_OUTCOME_UNKNOWN');assert.equal(failures.length,0,'CX_INDEPENDENT_CLEANUP_UNVERIFIED');
    }});
    await live();assert.equal(state.mutationUncertain,false);assert.equal(state.finalSignedOut,true);assert.equal(sessions.length,24);finalPassed=true;
  }catch(error){if(error.captureRequiresProcessExit)runtimeRefusal=error;write({type:'extension_boundary_failed',reason:clientFailure(error,'CX_RUN_INCOMPLETE')});if(!preflightPassed){write({type:'preflight_result',status:'failed'});for(const id of collection.intended)for(const phase of ['setup','call','teardown']){write({type:'phase_started',id,phase});write({type:'phase_result',id,phase,status:phase==='setup'?'blocked':phase==='call'?'not-run':'passed',reason:'CX_NO_NATIVE_SESSION_PREFLIGHT_REQUIRED'});}}}
  finally{
    const failures=[];
    if(active)try{const id=active.sessionId;await active.deleteSession();write(appiumSessionEvent(id,'deleted'));}catch{failures.push('session');}
    if(controls)try{const closed=await controls.closeRun({caseId:'CX28-VERSION-04'});assert.equal(closed.allOwnedControlsClosed,true);assert.equal(closed.authorityCleared,true);}catch{failures.push('owner');}
    controls?.dispose();finalPassed &&= failures.length===0;
  }
  if(preflightPassed)write({type:'postflight_result',status:finalPassed?'passed':'failed'});write({type:'run_completed',platform:q.platform,intendedCount:24});
  const result=reconcileResults(journal.events,collection.intended);closeJournal();
  const summary={...collection,...result,report:q.report,actualNativeExecution:sessions.length>0,nativeExecution:sessions.length?'observed':'not-run',physicalHardwareAcceptance:'unverified',core23Claimed:false,files17Claimed:false,v1Claimed:false,...(runtimeRefusal?{captureCleanupUncertain:true,captureRequiresProcessExit:true}:{})};
  fs.writeFileSync(path.join(q.report,'summary.json'),JSON.stringify(summary,null,2)+'\n',{flag:'wx',mode:0o600});return summary;
  }catch(error){originalError=error;throw error;}
  finally{
    try{admitted.members.forEach(m=>{if(m.value)for(const key of Object.keys(m.value))m.value[key]=undefined;m.value=undefined;});}
    finally{try{closeJournal();}catch(error){if(originalError)originalError.journalCleanupIncomplete=true;else throw error;}}
  }
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))try{
  const[platform,mode,file,digest]=process.argv.slice(2);
  if(mode==='--collect'){assert.equal(process.argv.length,4);console.log(JSON.stringify(collectNativeClientExtensions(platform)));}
  else{assert.equal(mode,'--request');assert.equal(process.argv.length,6);const q=readClientPublicInput(file,{maxBytes:16384,expectedSha256:digest}).value;assert.equal(q.platform,platform);requireClientExtensionRequest(q);
    assert.equal(process.env.CASEOPS_NATIVE_CLIENT_EXTENSIONS_GO,'EXPLICIT_OWNED_NATIVE_WINDOW');
    admitClientOutputRoot(q);assert.match(digest,/^[a-f0-9]{64}$/);
    fs.writeFileSync(path.join(q.claimRoot,digest+'.claim.json'),JSON.stringify({request:{path:file,sha256:digest},noReplay:true})+'\n',{flag:'wx',mode:0o600});
    const result=await runClientExtensions(q);console.log(JSON.stringify(result));if(result.status!=='passed')process.exitCode=1;}
}catch{console.error('NATIVE_CLIENT_EXTENSIONS_REFUSED_OR_INCOMPLETE');process.exitCode=1;}
