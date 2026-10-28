import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {collectNativeClientExtensions,clientExtensionScenarios} from '../../apps/mobile/e2e/client-extensions-20261028.mjs';
import {collectClientExtensions} from '../../apps/mobile/e2e/client-extensions-inventory.mjs';
import {parseClientCompatibility,requireClientExtensionRequest,decodeReadPage,decodeRecommendation} from '../../apps/mobile/e2e/client-extensions-contract.mjs';
import {ClientExtensionUnavailable} from '../../apps/mobile/e2e/client-extensions-ui.mjs';
import {readClientPublicInput} from './client-extension-public-input.mjs';
import {captureClientTree,captureClientFile} from './client-extension-runtime.mjs';
import {admitClientExtensions,executeClientExtensionInventory,runClientExtensions} from './run-client-extensions.mjs';
import {waitForClientOperator} from './client-extension-controls.mjs';
import {fileURLToPath} from 'node:url';
import {Journal} from '../../apps/mobile/e2e/support.mjs';

const sha=b=>createHash('sha256').update(b).digest('hex');
const temp=()=>fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'caseops-client-extension-'));
const ids=clientExtensionScenarios.map(x=>x.id);

for(const platform of ['ios','android'])test(`${platform} independent executable collection has24 cases/72 phases and no inherited acceptance`,()=>{
 const c=collectNativeClientExtensions(platform);assert.equal(c.expectedCases,24);assert.equal(c.expectedPhases,72);assert.equal(c.expectedSessions,24);
 assert.deepEqual(c.intended,ids.map(id=>platform+':'+id));assert.equal(c.nativeExecution,'not-run');assert.equal(c.core23Claimed,false);assert.equal(c.files17Claimed,false);assert.equal(c.v1Claimed,false);
});
test('filtered, duplicated or non-executable scenario inventory refuses',()=>{
 assert.throws(()=>collectClientExtensions('ios',clientExtensionScenarios.slice(1)));
 assert.throws(()=>collectClientExtensions('android',[clientExtensionScenarios[0],...clientExtensionScenarios.slice(0,23)]));
 assert.throws(()=>collectClientExtensions('ios',clientExtensionScenarios.map(x=>({...x,run:null}))));
});
test('pending request refuses before any native or credential entry',()=>{
 assert.throws(()=>requireClientExtensionRequest({schemaVersion:1,readyForLive:false,preparedOnly:true}),/CX_PENDING_PUBLIC_BINDINGS/);
});
test('exact correlated policy versions use ASCII components and cannot assert a false status',()=>{
 const policy={protocol_version:1,platform:'ios',client_version:'1.2.3',minimum_supported_version:'1.2.4',status:'update_required'};
 assert.equal(parseClientCompatibility(policy,{platform:'ios',version:'1.2.3'}),policy);
 for(const change of [{status:'supported'},{platform:'android'},{client_version:'01.2.3'},{client_version:'1.2.3 ',minimum_supported_version:null},{extra:'value'}])
  assert.throws(()=>parseClientCompatibility({...policy,...change},{platform:'ios',version:'1.2.3'}));
});
test('readthrough oracle rejects company/parent/cursor mismatch and arrays masquerading as JSON objects',()=>{
 const scope={company_id:'company',matter_id:'matter',matter_status:'active',matter_is_active:true,matter_lifecycle_version:0};
 const page={scope,parent_id:null,kind:'recommendations',order:'created_at_desc_id_desc',limit:25,items:[],next_cursor:null};
 assert.equal(decodeReadPage(page,'company','matter',null,page.kind,page.order,null,()=>{}),page);
 assert.throws(()=>decodeReadPage({...page,scope:{...scope,company_id:'foreign'}},'company','matter',null,page.kind,page.order,null,()=>{}));
 assert.throws(()=>decodeReadPage({...page,parent_id:'foreign'},'company','matter',null,page.kind,page.order,null,()=>{}));
 assert.throws(()=>decodeReadPage({...page,next_cursor:'same'},'company','matter',null,page.kind,page.order,'same',()=>{}));
 const detail={scope,id:'rec',read_state:'available',created_at:'2026-10-28T00:00:00Z',updated_at:'2026-10-28T00:00:00Z',record:{type:'strategy',title:'Synthetic',confidence:'recorded',status:'draft',review_required:true,rationale:'R',primary_option_index:0,assumptions:[],missing_facts:[],retrieved_authorities:[],next_action:null,strategy_payload:[],analysis:null}};
 assert.throws(()=>decodeRecommendation(detail,'company','matter','rec'));
});
test('held public FD returns exact bytes and closes on hash refusal',()=>{
 const root=temp(),file=path.join(root,'input.json'),data=Buffer.from('{"synthetic":true}');fs.writeFileSync(file,data,{mode:0o600});let descriptor;
 try{assert.equal(readClientPublicInput(file,{expectedSha256:sha(data)}).value.synthetic,true);
  assert.throws(()=>readClientPublicInput(file,{expectedSha256:'0'.repeat(64),afterOpen:fd=>{descriptor=fd;}}));
  assert.throws(()=>fs.fstatSync(descriptor),{code:'EBADF'});
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('actual growing public file reads at most maximum+1 and closes its FD',()=>{
 const root=temp(),file=path.join(root,'input.json');fs.writeFileSync(file,'{}');let fd;
 try{assert.throws(()=>readClientPublicInput(file,{maxBytes:32,afterOpen:value=>{fd=value;fs.appendFileSync(file,' '.repeat(100000));}}),/CX_PUBLIC_INPUT_BOUND/);assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});}
 finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('late parent symlink to the same held leaf is refused without reflecting its bytes',()=>{
 const root=temp(),dir=path.join(root,'owned'),moved=path.join(root,'moved');fs.mkdirSync(dir);const file=path.join(dir,'input.json');fs.writeFileSync(file,'{}');let fd;
 try{assert.throws(()=>readClientPublicInput(file,{afterOpen:value=>{fd=value;fs.renameSync(dir,moved);fs.symlinkSync(moved,dir);}}),/CX_CANONICAL_PUBLIC_PATH_REQUIRED/);assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});}
 finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('complete Appium tree includes hidden inputs and rejects a changed file or outside symlink',()=>{
 const root=temp();fs.mkdirSync(path.join(root,'.hidden'));fs.writeFileSync(path.join(root,'.hidden','driver.js'),'synthetic');
 try{const first=captureClientTree(root);assert.ok(first.entries.some(x=>x.path==='.hidden/driver.js'));fs.appendFileSync(path.join(root,'.hidden','driver.js'),'change');assert.notDeepEqual(captureClientTree(root),first);
  assert.equal(captureClientFile(path.join(root,'.hidden','driver.js')).extent,15);fs.symlinkSync('/etc/hosts',path.join(root,'outside'));assert.throws(()=>captureClientTree(root),/CX_EXTERNAL_TOOL_SYMLINK/);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
for(const platform of ['ios','android'])test(`${platform} all24 serial callbacks produce exactly72 ordered phases`,async()=>{
 const events=[],setups=[],teardowns=[];const scenarios=ids.map(id=>({id,run:async c=>{c.called=true;}}));
 const r=await executeClientExtensionInventory({platform,scenarios,now:()=>0,write:e=>events.push(e),setup:async s=>{setups.push(s.id);return{startedAt:0};},teardown:async({scenario,context})=>{assert.equal(context.called,true);teardowns.push(scenario.id);}});
 assert.equal(r.unsafe,false);assert.deepEqual(r.passed,ids);assert.deepEqual(setups,ids);assert.deepEqual(teardowns,ids);
 assert.deepEqual(events.filter(x=>x.type==='phase_result').map(x=>[x.id,x.phase,x.status]),ids.flatMap(id=>['setup','call','teardown'].map(p=>[platform+':'+id,p,'passed'])));
});
test('unknown first call stops all later native setups but retains every phase and independent teardown',async()=>{
 const events=[],setups=[];let closed=0;
 await executeClientExtensionInventory({platform:'ios',scenarios:ids.map(id=>({id,run:async()=>{throw Error('CX_CLICK_ACK_UNKNOWN');}})),now:()=>0,write:e=>events.push(e),setup:async s=>{setups.push(s.id);return{startedAt:0};},teardown:async()=>{closed++;}});
 assert.deepEqual(setups,[ids[0]]);assert.equal(closed,24);assert.equal(events.filter(x=>x.type==='phase_result').length,72);assert.equal(events.filter(x=>x.phase==='call'&&x.status==='not-run').length,23);
});
test('known unavailable prerequisite is scoped unverified and permits independent later cases',async()=>{
 const events=[];
 const r=await executeClientExtensionInventory({platform:'android',scenarios:ids.map(id=>({id,run:async()=>{}})),now:()=>0,write:e=>events.push(e),setup:async s=>{if(s.id===ids[0])throw new ClientExtensionUnavailable('CX_VERIFIED_ASSOCIATION_PENDING');return{startedAt:0};},teardown:async()=>{}});
 assert.equal(r.unsafe,false);assert.equal(r.passed.length,23);assert.equal(events.find(x=>x.type==='phase_result').status,'blocked');
});
test('failed teardown cannot be hidden by passing call or admit another setup',async()=>{
 const events=[];let setups=0,teardowns=0;
 await executeClientExtensionInventory({platform:'ios',scenarios:ids.map(id=>({id,run:async()=>{}})),now:()=>0,write:e=>events.push(e),setup:async()=>{setups++;return{startedAt:0};},teardown:async()=>{if(++teardowns===1)throw Error('CX_DELETE_ACK_UNKNOWN');}});
 assert.equal(setups,1);assert.equal(teardowns,24);assert.equal(events.find(x=>x.phase==='teardown'&&x.type==='phase_result').status,'failed');
});
test('bounded owner ACK consumes exact request and terminal unknown is never replayed',async()=>{
 const root=temp(),binding={sourceSha:'a'.repeat(40),binaryHash:'b'.repeat(64),udid:'owned',runId:'epoch'};let sleeps=0;
 try{const result=await waitForClientOperator({root,operation:'policyCheckpoint',caseId:'CX28-VERSION-02',args:{phase:'floor'},binding},{now:()=>0,sleep:async()=>{
   sleeps++;const file=fs.readdirSync(root).find(x=>x.endsWith('.request.json'));const bytes=fs.readFileSync(path.join(root,file)),q=JSON.parse(bytes);
   fs.writeFileSync(path.join(root,file.replace('.request.','.result.')),JSON.stringify({kind:'native-client-extension-owner-ack',requestEvidence:{path:path.join(root,file),sha256:sha(bytes)},operation:q.operation,caseId:q.caseId,binding:q.binding,observed:true,acknowledged:true,noPaidMarker:'no-paid-providers',mutationUncertain:false,replayed:false,value:{actual:true}}),{mode:0o600,flag:'wx'});
  }});assert.deepEqual(result,{actual:true});assert.equal(sleeps,1);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('owner completion timeout is finite and leaves one request for reconciliation',async()=>{
 const root=temp();let clock=0,reads=0;
 try{await assert.rejects(waitForClientOperator({root,operation:'operatorBoundary',caseId:'CX28-LOCK-01',args:{operation:'biometric-match'},binding:{}},{now:()=>clock,sleep:async ms=>{clock+=ms;reads++;}}),/CX_OPERATOR_OUTCOME_UNVERIFIED_NO_REPLAY/);assert.equal(reads,12);assert.equal(clock,180000);assert.equal(fs.readdirSync(root).length,1);}
 finally{fs.rmSync(root,{recursive:true,force:true});}
});

test('registration uses observed host/runtime UID mappings and actual retained siblings; Python consumes the identical profile',async()=>{
 const {composeClientExtensionRegistration}=await import('./prepare-client-extensions.mjs');
 const {spawnSync}=await import('node:child_process');const {fileURLToPath}=await import('node:url');
 const root=fileURLToPath(new URL('../../',import.meta.url)),base='/synthetic/owned-cache',id=n=>'00000000-0000-4000-8000-'+n.toString(16).padStart(12,'0');
 const ref=name=>({path:base+'/'+name+'.json',sha256:'a'.repeat(64)}),privateRef=name=>({...ref(name),uid:501});
 const actors={owner:{userId:id(1),companyId:id(2),membershipId:id(3),credentialEvidence:privateRef('owner')},member:{userId:id(4),companyId:id(2),membershipId:id(5),credentialEvidence:privateRef('member')},'second-company':{userId:id(6),companyId:id(7),membershipId:id(8),credentialEvidence:privateRef('second')}};
 const dataset={kind:'actual-normal-api-native-client-extension-fixture',observed:true,sourceSha:'b'.repeat(40),companyId:id(2),membershipId:id(5),cx:{identity:{userId:id(4)},matter:{id:id(10)},version:{actual:'1.0.0',byteSource:{id:id(11)}},scannerConfigurationEvidence:ref('scanner'),links:{secondMatter:{id:id(12)}},readthrough:{matterId:id(20),emptyMatter:{id:id(21)},revocableMatter:{id:id(22)},revocableRecommendationId:id(23),recommendationIds:[id(24)],packStates:[{matter:{id:id(20)},hearingId:id(25),packId:id(26)},{matter:{id:id(20)},hearingId:id(27)}]}}};
 const receipt={backendSha:dataset.sourceSha,webSha:dataset.sourceSha,productionAccessed:false,project:'owned',gatewayRunId:'owned-epoch',gatewayUrl:'https://127.0.0.1:9443',backendRevision:'owned-api',webRevision:'owned-web'};
 const source={sourceSha:dataset.sourceSha,sourceFingerprint:'c'.repeat(64),sourceDirty:false,inputFileCount:140},build={...source,binaryHash:'d'.repeat(64)};
 const authority=privateRef('authority'),mount={kind:'actual-native-client-cache-mount-metadata',observed:true,project:'owned',runId:'owned-epoch',hostRoot:base,containerRoot:'/fixture-state',containerEffectiveUid:0,files:[...Object.values(actors).map(x=>x.credentialEvidence),authority].map(hostEvidence=>({hostEvidence,containerUid:0}))};
 const baseFile=fs.readFileSync(path.join(root,'scripts/mobile/local-v1-controls.py'));const closure={controlsModuleEvidence:{path:path.join(root,'scripts/mobile/client-extension-controls.mjs'),sha256:'1'.repeat(64)},code:[{path:path.join(root,'scripts/mobile/local-client-extension-controls.py'),sha256:'2'.repeat(64)},{path:path.join(root,'scripts/mobile/local-v1-controls.py'),sha256:sha(baseFile)}]};
 const retained={complete:true,normalApiReadback:true,companyId:id(2),sourceSha:source.sourceSha,recommendationPage:{items:[{id:id(24)},{id:id(28)},{id:id(29)}]}};
 const q={kind:'compose-native-client-extension-registration',preparedOnly:true,platform:'ios',registrationId:'owned-registration',expiresAt:1100,datasetEvidence:ref('dataset'),dockerReceipt:ref('receipt'),buildReceipt:ref('build'),credentialMountEvidence:ref('mount'),retainedRowsEvidence:ref('retained'),actors,authorityEvidence:authority,cameraContainersEvidence:ref('camera'),servingEvidence:ref('serving')};
 const values=new Map([[q.datasetEvidence.path,dataset],[q.dockerReceipt.path,receipt],[q.buildReceipt.path,build],[q.credentialMountEvidence.path,mount],[q.retainedRowsEvidence.path,retained]]);
 const io={read:r=>values.get(r.path),snapshot:()=>source,code:()=>closure,now:()=>1000};
 const result=composeClientExtensionRegistration(q,io);assert.equal(result.privateReads,0);assert.equal(result.registration.actors.member.credentialEvidence.path,'/fixture-state/member.json');assert.equal(result.registration.actors.member.credentialEvidence.uid,0);assert.equal(result.descriptor.actorCredentialMappings.member.hostEvidence.uid,501);
 assert.ok(result.registration.exactRoutes.includes('GET /api/matter-readthrough/'+id(20)+'/recommendations/'+id(28)));
 assert.ok(result.registration.exactRoutes.includes('GET /api/matters/'+id(12)+'/workspace'));
 const code="from pathlib import Path\nimport json,sys\nn={}\nexec(compile(Path(sys.argv[1]).read_bytes(),sys.argv[1],'exec'),n)\nv=json.loads(sys.stdin.read())\nn['validate_registration'](v,source='b'*40,run='owned-epoch',now=1000)\nprint('exact-profile-accepted')\n";
 const child=spawnSync('python3',['-c',code,path.join(root,'scripts/mobile/local-client-extension-controls.py')],{input:JSON.stringify(result.registration),encoding:'utf8',timeout:10000,maxBuffer:65536,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
 assert.equal(child.status,0,child.stderr);assert.equal(child.stdout.trim(),'exact-profile-accepted');
 for(const bad of [{...mount,hostRoot:'/foreign'},{...mount,containerEffectiveUid:501},{...mount,files:mount.files.slice(1)}]){values.set(q.credentialMountEvidence.path,bad);assert.throws(()=>composeClientExtensionRegistration(q,io));}values.set(q.credentialMountEvidence.path,mount);
 const altered=structuredClone(dataset);altered.membershipId=id(99);values.set(q.datasetEvidence.path,altered);assert.throws(()=>composeClientExtensionRegistration(q,io));
});

test('all four immutable policy checkpoints require actual current GET readbacks and retained old epoch',async()=>{
 const {verifyClientPolicyCheckpoint}=await import('./client-policy-checkpoint.mjs');
 for(const phase of ['floor','rollback','exit-floor','final-rollback']){
  const ref=n=>({path:'/synthetic/'+n+'.json',sha256:sha(n)}),source='a'.repeat(40),binary='b'.repeat(64),floor=phase==='floor'||phase==='exit-floor',old='previous',next='next-'+phase;
  const q={kind:'complete-native-client-policy-checkpoint',readyForLive:true,preparedOnly:false,requestEvidence:ref('request'),previousServingEvidence:ref('prior'),servingEvidence:ref('serving'),controlsEvidence:ref('controls'),configurationEvidence:ref('config'),receiptEvidence:ref('receipt'),previousReceiptEvidence:ref('old-receipt'),floorVersion:'1.0.1'};
  const request={kind:'native-client-extension-owner-checkpoint',operation:'policyCheckpoint',noReplay:true,caseId:phase==='floor'?'CX28-VERSION-02':phase==='rollback'?'CX28-VERSION-03':'CX28-VERSION-04',args:{phase,priorNativeIdentityEvidence:ref('native')},binding:{sourceSha:source,binaryHash:binary,runId:old}};
  const serving={kind:'actual-client-policy-configuration-transition',observed:true,complete:true,productionAccessed:false,noPaidMarker:'no-paid-providers',databaseAndSecurityIdentityPreserved:true,previousServingEvidence:q.previousServingEvidence,protectedIdentityEvidence:ref('protected'),backendSha:source,webSha:source,gatewayRunId:next,receiptEvidence:q.receiptEvidence,previousLedgerEvidence:ref('ledger'),currentContainerIdentities:['api','gateway','migrate','postgres','scanner','valkey','web'].map(role=>({role,id:role})),configurationEvidence:q.configurationEvidence,publicCA:'/synthetic/ca',gatewayUrl:'https://127.0.0.1:9443',webGatewayUrl:'https://127.0.0.1:4443',backendRevision:'api',webRevision:'web'};
  const registration={runId:next,platform:'ios',clientVersion:'1.0.0',priorNativeIdentityEvidence:ref('native'),priorNativeIdentity:{sessionId:'actual-opaque-id'}};
  const controls={profile:'native-client-extensions-v1',sourceSha:source,binaryHash:binary,runId:next,servingEvidence:q.servingEvidence,registrationEvidence:ref('registration')};
  const map=new Map([[q.requestEvidence.path,request],[q.previousServingEvidence.path,{protectedIdentityEvidence:ref('protected'),receiptEvidence:q.previousReceiptEvidence,gatewayLedgerEvidence:ref('ledger')}],[q.servingEvidence.path,serving],[q.controlsEvidence.path,controls],[q.receiptEvidence.path,{gatewayRunId:next,backendSha:source,webSha:source,productionAccessed:false}],[q.previousReceiptEvidence.path,{gatewayRunId:old,backendSha:source,webSha:source,productionAccessed:false}],[ref('ledger').path,{runId:old,overflow:false,requests:[]}],[ref('protected').path,{observed:true,before:{privateMetadata:'same'},after:{privateMetadata:'same'},scope:'owned-postgres-mount-and-private-metadata-identities'}],[ref('registration').path,registration],[ref('native').path,{kind:'actual-native-session-identity',observed:true,sourceSha:source,binaryHash:binary,runId:old,identity:registration.priorNativeIdentity}],[q.configurationEvidence.path,{CASEOPS_NATIVE_MINIMUM_IOS_VERSION:floor?'1.0.1':null}]]);
  let reads=0;const io={read:r=>map.get(r.path),environment:{NODE_EXTRA_CA_CERTS:'/synthetic/ca'},getJson:async url=>{reads++;return url.endsWith('/api/build')?{release_sha:source,revision:'api'}:url.endsWith('/api/release-identity')?{release_sha:source,revision:'web'}:url.includes('/compatibility?')?{protocol_version:1,platform:'ios',client_version:'1.0.0',minimum_supported_version:floor?'1.0.1':null,status:floor?'update_required':'supported'}:{runId:next,v1ControlProfile:controls.profile,v1RegistrationSha256:controls.registrationEvidence.sha256,overflow:false};}};
  const result=await verifyClientPolicyCheckpoint(q,io);assert.equal(reads,4);assert.equal(result.value.operation,phase);assert.equal(result.acknowledged,true);
  reads=0;const changed={...serving,previousLedgerEvidence:ref('foreign')};map.set(q.servingEvidence.path,changed);await assert.rejects(verifyClientPolicyCheckpoint(q,io));assert.equal(reads,0);
  map.set(q.servingEvidence.path,serving);await assert.rejects(verifyClientPolicyCheckpoint(q,{...io,getJson:async()=>({release_sha:'foreign',revision:'api'})}));
 }
});

function clientAdmissionPacket(){
 const root=fileURLToPath(new URL('../../',import.meta.url)).replace(/\/$/,''),id=n=>'00000000-0000-4000-8000-'+n.toString(16).padStart(12,'0'),ref=n=>({path:'/synthetic/cache/'+n+'.json',sha256:sha(n)}),S='a'.repeat(40),H='b'.repeat(64),F='c'.repeat(64),HF='d'.repeat(64);
 function packet(){
  let secretReads=0;const loadedValues=[];const source={sourceSha:S,sourceFingerprint:F,sourceDirty:false,inputFileCount:140},q={schemaVersion:1,readyForLive:true,preparedOnly:false,platform:'ios',inventoryId:'native-client-extension-ios-2026-10-28',caseIds:ids,repoRoot:root,automaticRetry:false,nativeWindowOwned:true,leaseDeadlineMs:4000000,expectedSourceSha:S,expectedSourceFingerprint:F,expectedInputFileCount:140,expectedBinaryHash:H,expectedHarnessFingerprint:HF,fixtureEvidence:ref('fixture'),buildReceipt:ref('build'),dockerReceipt:ref('receipt'),deviceEvidence:ref('device'),installedEvidence:ref('installed'),artifactVersionEvidence:ref('version'),codeClosure:ref('closure'),producerEvidence:ref('producer'),retainedRowsEvidence:ref('retained'),controlsEvidence:ref('controls'),appiumServerEvidence:ref('server'),appiumInventoryEvidence:ref('appium'),acceptedToolEvidence:ref('tools'),clientRuntimeInventoryEvidence:ref('runtime')};
  const fixture={environment:'docker-integration',syntheticDataOnly:true,companyId:id(1),membershipId:id(2),udid:'owned-current',appId:'synthetic.app',buildReceipt:q.buildReceipt,isolationEvidence:q.dockerReceipt,binarySourceSha:S,backendSha:S,webSha:S,principalLabel:'Synthetic Member',workspaceLabel:'Synthetic Company',publicCa:{path:'/synthetic/ca'},auth:{mfaRequired:true,mfaStage:'totp',iosConsent:'observed',companySlug:'test-mobile-primary',emailEnv:'CASEOPS_MOBILE_CX_PRIMARY_EMAIL',passwordEnv:'CASEOPS_MOBILE_CX_PRIMARY_PASSWORD',totpSecretEnv:'CASEOPS_MOBILE_CX_PRIMARY_TOTP'},cx:{inventoryId:q.inventoryId,noPaidMarker:'no-paid-providers',automaticRetry:false,directDatabaseWrites:false,nativeMutationsForwardedByControls:false,identity:{userId:id(3),companyId:id(1),membershipId:id(2)},matter:{id:id(4),code:'SYNTHETIC'},camera:{filename:'capture.jpg',filenames:['capture.jpg','capture.jpeg','capture.png'],deniedMessage:'Camera access was not granted. You can still use Choose file, or enable camera access in device settings.',privacyDisclosure:'Take a photo, then choose whether to upload it. Photos may include details such as capture location. Those details are kept when you upload. Camera access is optional; Choose file remains available.',maxAcceptanceBytes:900000},version:{actual:'1.0.0',floor:'1.0.1',byteSource:{id:id(5),matterId:id(4),text:'synthetic',sha256:H}},workflowDomain:'simulator',osRecipes:{observed:true,udid:'owned-current',platform:'ios',binaryHash:H,allowedApplications:['synthetic.app'],appiumInventoryEvidence:q.appiumInventoryEvidence},links:{invalid:['one','two','three','four'],own:'caseops://own',secondOwn:'caseops://second',foreign:'caseops://foreign',foreignMessage:'Sign in to the matching workspace, then open this link again.'},readthrough:{matterId:id(6),matter:{id:id(6)},packStates:[{},{}]},provenance:{normalApiDataset:q.producerEvidence,retainedRows:q.retainedRowsEvidence}}};
  fixture.cx.nativeSelectors={observed:true,platform:'ios',udid:fixture.udid,binaryHash:H,appiumInventoryEvidence:q.appiumInventoryEvidence};
  const second=structuredClone(fixture);second.companyId=id(10);second.membershipId=id(11);second.principalLabel='Synthetic Second';second.auth={...fixture.auth,companySlug:'test-mobile-second',emailEnv:'CASEOPS_MOBILE_CX_SECOND_EMAIL',passwordEnv:'CASEOPS_MOBILE_CX_SECOND_PASSWORD',totpSecretEnv:'CASEOPS_MOBILE_CX_SECOND_TOTP'};
  q.members=[fixture,second].map((f,i)=>({fixtureEvidence:ref('member-fixture-'+i),authObservation:ref('auth-'+i),credentialEvidence:{...ref('credential-'+i),uid:501}}));
  const module={path:root+'/scripts/mobile/client-extension-controls.mjs',sha256:H},closure={harnessFingerprint:HF,controlsModuleEvidence:module,code:[module,{path:root+'/scripts/mobile/local-gateway.py',sha256:H}]},registration={clientVersion:'1.0.0',runId:'epoch',companyId:fixture.companyId,implementationSha256:H,actors:{}};
  const controls={profile:'native-client-extensions-v1',sourceSha:S,binaryHash:H,moduleEvidence:module,gatewayImplementationEvidence:{path:root+'/scripts/mobile/local-client-extension-controls.py',sha256:H},registrationEvidence:ref('registration'),credentialMountEvidence:ref('mount'),actorCredentialMappings:{}};
  const mount={observed:true,runId:'epoch',project:'owned',hostRoot:'/synthetic/cache',containerEffectiveUid:0,files:[]};
  for(const [i,name]of['member','second-company'].entries()){const f=i?second:fixture,m=q.members[i],runtime={...m.credentialEvidence,path:'/fixture-state/credential-'+i+'.json',uid:0};registration.actors[name]={companyId:f.companyId,membershipId:f.membershipId,credentialEvidence:runtime};controls.actorCredentialMappings[name]={hostEvidence:m.credentialEvidence,runtimeEvidence:runtime};mount.files.push({hostEvidence:m.credentialEvidence,containerUid:0});}
  const installed={udid:fixture.udid,appId:fixture.appId,binaryHash:H,deviceTypeIdentifier:'iPhone17',runtime:'iOS26.5'},receipt={backendSha:S,webSha:S,productionAccessed:false,noPaidProviderKeysInAPIOrWeb:true,apiWebPostgresScannerNetworkInternal:true,tlsProof:{strictDefaultTLS:true,verificationDisabled:false},publicCA:fixture.publicCa.path,gatewayUrl:'https://127.0.0.1:9443',webGatewayUrl:'https://127.0.0.1:4443',backendRevision:'api',webRevision:'web',gatewayRunId:'epoch',project:'owned',gatewayImplementationSha256:H};
  const tools={observed:true,platform:'ios',developerDir:'/synthetic/Xcode',executables:[{role:'node',file:{path:process.execPath}},{role:'git',file:{path:'/synthetic/git'}}]},producer={kind:'actual-normal-api-native-client-extension-fixture',observed:true,sourceSha:S,noPaidMarker:'no-paid-providers',directDatabaseWrites:false,automaticRetry:false,mutationUncertain:false,companyId:fixture.companyId,membershipId:fixture.membershipId};
  const values=new Map([[q.fixtureEvidence.path,fixture],[q.buildReceipt.path,{...source,artifact:'/synthetic/app',binaryHash:H}],[q.dockerReceipt.path,receipt],[q.deviceEvidence.path,{...installed,observed:true,platform:'ios',buildReceipt:q.buildReceipt}],[q.installedEvidence.path,installed],[q.artifactVersionEvidence.path,{kind:'actual-native-artifact-version',observed:true,buildReceipt:q.buildReceipt,binaryHash:H,platform:'ios',version:'1.0.0',reader:'PlistBuddy-CFBundleShortVersionString'}],[q.codeClosure.path,closure],[q.producerEvidence.path,producer],[q.retainedRowsEvidence.path,{complete:true,normalApiReadback:true,companyId:fixture.companyId,sourceSha:S}],[q.controlsEvidence.path,controls],[controls.registrationEvidence.path,registration],[controls.credentialMountEvidence.path,mount],[q.acceptedToolEvidence.path,tools],[q.clientRuntimeInventoryEvidence.path,{complete:true,root:'/synthetic/runtime',tree:{}}]]);
  q.members.forEach((m,i)=>{const f=i?second:fixture;values.set(m.fixtureEvidence.path,f);values.set(m.authObservation.path,{observed:true,udid:f.udid,appId:f.appId,membershipId:f.membershipId,binaryHash:H,nativePrincipalVerified:true,nativeWorkspaceVerified:true,pkceUnchanged:true,logoutAcknowledged:true,sessionCleanup:'passed',importedSource:source,buildReceipt:q.buildReceipt,dockerReceipt:q.dockerReceipt,mfaStage:f.auth.mfaStage,iosConsent:f.auth.iosConsent});});
  const io={read:r=>values.get(r.path),bytes:()=>Buffer.from('synthetic public'),snapshot:()=>source,harness:()=>HF,installed:()=>installed,artifactHash:()=>H,buildCheck:()=>{},coreCheck:()=>{},closure:()=>closure,tree:()=>({}),server:()=>({}),tool:file=>tools.executables.find(x=>x.file.path===file).file,selectedExecutable:()=>'/synthetic/git',now:()=>0,environment:{CASEOPS_NATIVE_CLIENT_EXTENSIONS_GO:'EXPLICIT_OWNED_NATIVE_WINDOW',CASEOPS_MOBILE_TOOLING_HOME:'/synthetic/runtime',DEVELOPER_DIR:tools.developerDir,NODE_EXTRA_CA_CERTS:receipt.publicCA},getJson:async url=>url.endsWith('/api/build')?{release_sha:S,revision:'api'}:url.endsWith('/api/release-identity')?{release_sha:S,revision:'web'}:{runId:'epoch',implementationSha256:H,overflow:false,v1ControlProfile:controls.profile,v1ControlsEnabled:true,v1RegistrationSha256:controls.registrationEvidence.sha256,v1ControlsImplementationSha256:H},reader:file=>{secretReads++;const i=q.members.findIndex(m=>m.credentialEvidence.path===file),f=i?second:fixture,value={full_name:f.principalLabel,company_slug:f.auth.companySlug,email:'synthetic@example.invalid',password:'not-a-live-credential',totp_secret:'synthetic-no-live-factor'};loadedValues.push(value);return{sha256:q.members[i].credentialEvidence.sha256,uid:501,value,bytes:Buffer.alloc(16)};}};
  return{q,io,values,reads:()=>secretReads,loadedValues};
 }
 return packet();
}
test('actual admission composition proves every public/current fence before either protected member reader',async()=>{
 const packet=clientAdmissionPacket;
 const positive=packet(),result=await admitClientExtensions(positive.q,positive.io);assert.equal(result.beforeMemberRead,true);assert.equal(positive.reads(),2);assert.ok(result.members.every((m,i)=>m.value===positive.loadedValues[i]&&typeof m.value.password==='string'));
 for(const alter of [x=>{x.io.snapshot=()=>({sourceSha:'f'.repeat(40)});},x=>{x.io.installed=()=>({binaryHash:'foreign'});},x=>{x.io.server=()=>{throw Error('changed owned server');};},x=>{x.io.getJson=async()=>({release_sha:'foreign'});},x=>{x.q.readyForLive=false;},x=>{x.values.get(x.q.fixtureEvidence.path).cx.osRecipes.binaryHash='f'.repeat(64);},x=>{x.values.get(x.q.fixtureEvidence.path).cx.nativeSelectors.udid='old-device';}]){const x=packet();alter(x);await assert.rejects(admitClientExtensions(x.q,x.io));assert.equal(x.reads(),0);}
 const between=packet(),read=between.io.getJson;between.io.getJson=async url=>between.reads()===1&&url.endsWith('/api/release-identity')?{release_sha:'foreign',revision:'web'}:read(url);await assert.rejects(admitClientExtensions(between.q,between.io));assert.equal(between.reads(),1);assert.ok(Object.values(between.loadedValues[0]).every(v=>v===undefined));
});

test('owned Appium listener parser binds one exact PID, finite FD set and loopback port',async()=>{
 const {clientListenerIdentity}=await import('./client-extension-runtime.mjs');
 assert.deepEqual(clientListenerIdentity('p29000\nf14\nn127.0.0.1:4727\n',29000,4727),{pid:29000,port:4727,descriptors:[14]});
 assert.deepEqual(clientListenerIdentity('p29000\nf14\nn127.0.0.1:4727\nf15\nn[::1]:4727\n',29000,4727).descriptors,[14,15]);
 for(const value of ['p29001\nf14\nn127.0.0.1:4727\n','p29000\nf14\nn*:4727\n','p29000\nf14\nn127.0.0.1:4728\n','p29000\nf14\n','p29000\nf14\nn127.0.0.1:4727\np29000\n','error: no such process','p29000\nn127.0.0.1:4727\n'])assert.throws(()=>clientListenerIdentity(value,29000,4727));
});

test('policy preparation retains original config and produces exact canonical API/gateway-only invocation',async()=>{
 const {prepareClientPolicyTransition}=await import('./prepare-client-extensions.mjs');
 const ref=name=>({path:'/synthetic/cache/'+name+'.json',sha256:sha(name)}),S='a'.repeat(40),source={sourceSha:S,sourceDirty:false},original={CASEOPS_MOBILE_API_SHA:S,CASEOPS_MOBILE_WEB_SHA:S,CASEOPS_MOBILE_GATEWAY_RUN_ID:'old',CASEOPS_MOBILE_CACHE:'/synthetic/cache',CASEOPS_MOBILE_PLATFORM:'ios',CASEOPS_MOBILE_PROJECT:'owned',CASEOPS_MOBILE_API_IMAGE:'sha256:actual-api',CASEOPS_MOBILE_WEB_IMAGE:'sha256:actual-web'},saved=structuredClone(original);
 for(const [phase,caseId]of [['floor','CX28-VERSION-02'],['rollback','CX28-VERSION-03'],['exit-floor','CX28-VERSION-04'],['final-rollback','CX28-VERSION-04']]){
  const q={kind:'prepare-native-client-policy-transition',preparedOnly:true,requestEvidence:ref('request'),configurationEvidence:ref('configuration'),registrationEvidence:ref('registration-'+phase),configurationOutput:'/synthetic/cache/new-'+phase+'.json',overrideOutput:'/synthetic/cache/override-'+phase+'.json',floorVersion:'1.0.1'};
  const request={operation:'policyCheckpoint',noReplay:true,caseId,args:{phase,priorNativeIdentityEvidence:ref('native')},binding:{sourceSha:S,runId:'old'}},registration={sourceSha:S,runId:'new-'+phase,profile:'native-client-extensions-v1',platform:'ios',priorNativeIdentityEvidence:request.args.priorNativeIdentityEvidence,implementationSha256:'b'.repeat(64)};
  const map=new Map([[q.requestEvidence.path,request],[q.configurationEvidence.path,original],[q.registrationEvidence.path,registration]]),result=prepareClientPolicyTransition(q,{read:r=>map.get(r.path),snapshot:()=>source});
  assert.deepEqual(original,saved);assert.equal(result.mutations,0);assert.equal(result.privateReads,0);assert.deepEqual(result.canonicalOperator.argvSuffix,['up','-d','--no-build','--no-deps','--force-recreate','--wait','--wait-timeout','60','api','gateway']);assert.equal(result.canonicalOperator.automaticRetry,false);assert.deepEqual(result.canonicalOperator.requiresFreshDockerCapacity,{bytes:68719476736,inodes:100000});
  for(const key of Object.keys(saved))if(key!=='CASEOPS_MOBILE_GATEWAY_RUN_ID')assert.deepEqual(result.configuration[key],saved[key]);assert.equal(result.configuration.CASEOPS_MOBILE_GATEWAY_RUN_ID,registration.runId);assert.equal(result.override.services.api.environment.CASEOPS_NATIVE_MINIMUM_IOS_VERSION,['floor','exit-floor'].includes(phase)?'1.0.1':undefined);
  const bad={...q,floorVersion:'01.0.1'};if(['floor','exit-floor'].includes(phase))assert.throws(()=>prepareClientPolicyTransition(bad,{read:r=>map.get(r.path),snapshot:()=>source}));
 }
});

function admittedCleanupFixture(t){
 const root=temp();fs.chmodSync(root,0o700);t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const claim=path.join(root,'retained-one-attempt.claim'),claimBytes=Buffer.from('SYNTHETIC_ALREADY_CONSUMED_ATTEMPT');fs.writeFileSync(claim,claimBytes,{mode:0o600,flag:'wx'});
 const values=[{email:'synthetic-one@contract.invalid',password:'SYNTHETIC_ONE'},{email:'synthetic-two@contract.invalid',password:'SYNTHETIC_TWO'}];
 const members=values.map(value=>({value}));let controls=0,sessions=0,journal;
 const q={platform:'ios',claimRoot:root,report:path.join(root,'report'),expectedHarnessFingerprint:'a'.repeat(64)};
 const admitted={members,source:{},currentGuard:async()=>{throw Error('SYNTHETIC_PUBLIC_PREFLIGHT_REFUSAL');}};
 const dependencies={admit:async()=>admitted,controls:async()=>{controls++;throw Error('MUST_NOT_DISPATCH_CONTROL');},remote:async()=>{sessions++;throw Error('MUST_NOT_DISPATCH_SESSION');},
  journal:file=>(journal=new Journal(file))};
 const verify=()=>{assert.deepEqual(members.map(m=>m.value),[undefined,undefined]);assert.ok(values.every(value=>Object.values(value).every(v=>v===undefined)));assert.deepEqual(fs.readFileSync(claim),claimBytes);assert.equal(controls,0);assert.equal(sessions,0);if(journal)assert.throws(()=>fs.fstatSync(journal.fd),{code:'EBADF'});};
 return{q,admitted,dependencies,verify,getJournal:()=>journal};
}
test('post-admission report refusal clears both retained members and preserves the consumed claim',async t=>{
 const f=admittedCleanupFixture(t);f.dependencies.admit=async()=>{fs.mkdirSync(f.q.report,{mode:0o700});return f.admitted;};
 await assert.rejects(runClientExtensions(f.q,f.dependencies),/CX_FRESH_REPORT_REQUIRED/);f.verify();
});
test('real post-admission mkdir failure clears members without a control or native dispatch',async t=>{
 const f=admittedCleanupFixture(t);f.dependencies.mkdir=(file,options)=>{fs.writeFileSync(file,'synthetic-occupied',{mode:0o600,flag:'wx'});return fs.mkdirSync(file,options);};
 await assert.rejects(runClientExtensions(f.q,f.dependencies),{code:'EEXIST'});f.verify();
});
test('actual exclusive Journal open failure clears members and leaves its existing bytes intact',async t=>{
 const f=admittedCleanupFixture(t),bytes=Buffer.from('SYNTHETIC_EXISTING_JOURNAL');f.dependencies.journal=file=>{fs.writeFileSync(file,bytes,{mode:0o600,flag:'wx'});return new Journal(file);};
 await assert.rejects(runClientExtensions(f.q,f.dependencies),{code:'EEXIST'});assert.deepEqual(fs.readFileSync(path.join(f.q.report,'events.jsonl')),bytes);f.verify();
});
test('actual run_started FD write failure preserves original EBADF and separately records failed close',async t=>{
 const f=admittedCleanupFixture(t),open=f.dependencies.journal;f.dependencies.journal=file=>{const journal=open(file);fs.closeSync(journal.fd);return journal;};
 let failure;try{await runClientExtensions(f.q,f.dependencies);}catch(error){failure=error;}
 assert.equal(failure.code,'EBADF');assert.equal(failure.journalCleanupIncomplete,true);f.verify();
});
test('composed public preflight refusal closes real journal and retains all72 unrun phase results',async t=>{
 const f=admittedCleanupFixture(t);const summary=await runClientExtensions(f.q,f.dependencies);
 assert.notEqual(summary.status,'passed');assert.equal(summary.nativeExecution,'not-run');
 const events=fs.readFileSync(path.join(f.q.report,'events.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
 const phases=events.filter(e=>e.type==='phase_result');assert.equal(phases.length,72);assert.equal(phases.filter(e=>e.phase==='setup'&&e.status==='blocked').length,24);assert.equal(phases.filter(e=>e.phase==='call'&&e.status==='not-run').length,24);f.verify();
});

test('current decoded member is cleared on hash UID label or canonical core refusal before transfer',async()=>{
 for(const stage of ['hash','uid','label','core']){
  const f=clientAdmissionPacket(),held=[],reader=f.io.reader;
  f.io.reader=file=>{const value=reader(file);held.push(value);if(stage==='hash')value.sha256='f'.repeat(64);if(stage==='uid')value.uid=999;if(stage==='label')value.value.full_name='Synthetic wrong label';return value;};
  if(stage==='core')f.io.coreCheck=()=>{throw Error('SYNTHETIC_CORE_REFUSAL');};
  await assert.rejects(admitClientExtensions(f.q,f.io));assert.equal(f.reads(),1);assert.equal(held.length,1);assert.ok(held[0].bytes.every(v=>v===0));assert.ok(Object.values(held[0].value).every(v=>v===undefined));
 }
});
test('second member core refusal clears the earlier transferred member and current decoded result',async()=>{
 const f=clientAdmissionPacket(),held=[],reader=f.io.reader;let checked=0;
 f.io.reader=file=>{const value=reader(file);held.push(value);return value;};f.io.coreCheck=()=>{if(++checked===2)throw Error('SYNTHETIC_SECOND_CORE_REFUSAL');};
 await assert.rejects(admitClientExtensions(f.q,f.io),/SYNTHETIC_SECOND_CORE_REFUSAL/);assert.equal(f.reads(),2);assert.equal(checked,2);
 assert.ok(held.every(value=>value.bytes.every(b=>b===0)&&Object.values(value.value).every(v=>v===undefined)));
});
