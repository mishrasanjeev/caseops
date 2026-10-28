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
import {readClientPublicInput,writeClientProjection} from './client-extension-public-input.mjs';
import {captureClientTree,captureClientTreeAsync,captureClientTreeCommitmentAsync,captureClientTreeInventoryAsync,captureClientFile,admitClientServer,admitClientServerAsync,captureClientTreeCommitment,captureClientTreeInventory,clientTreeManifest,assertClientTreeCommitment,assertClientRuntimeInventory,writeClientTreeAuditManifest,CLIENT_TREE_AUDIT_MAX_BYTES} from './client-extension-runtime.mjs';
import {admitClientExtensions,executeClientExtensionInventory,runClientExtensions} from './run-client-extensions.mjs';
import {waitForClientOperator} from './client-extension-controls.mjs';
import {fileURLToPath} from 'node:url';
import {Journal} from '../../apps/mobile/e2e/support.mjs';

const sha=b=>createHash('sha256').update(b).digest('hex');
const temp=()=>fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'caseops-client-extension-'));
const ids=clientExtensionScenarios.map(x=>x.id);
// A unit fixture does not own unrelated entries in the system temporary root.
// Stabilize only those external ancestors' volatile directory counters/times;
// continue reading their real identity/type and every full field inside root.
// Production readClientPublicInput remains unchanged and strict at every level.
function isolatedFixtureAncestors(root,operation){
 const original=fs.lstatSync,parents=new Map();
 for(let p=path.dirname(root);;p=path.dirname(p)){parents.set(p,original(p,{bigint:true}));if(path.dirname(p)===p)break;}
 fs.lstatSync=(file,...args)=>{
  const actual=original(file,...args),saved=parents.get(file);if(!saved||args[0]?.bigint!==true)return actual;
  for(const key of ['dev','ino','uid','gid','mode'])assert.equal(actual[key],saved[key],'UNIT_EXTERNAL_PARENT_IDENTITY_CHANGED');
  assert.ok(actual.isDirectory()&&!actual.isSymbolicLink());
  return new Proxy(actual,{get(target,key){return ['nlink','size','mtimeNs','ctimeNs'].includes(key)?saved[key]:Reflect.get(target,key);}});
 };
 try{return operation();}finally{fs.lstatSync=original;}
}

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
 try{isolatedFixtureAncestors(root,()=>{assert.equal(readClientPublicInput(file,{expectedSha256:sha(data)}).value.synthetic,true);
  assert.throws(()=>readClientPublicInput(file,{expectedSha256:'0'.repeat(64),afterOpen:fd=>{descriptor=fd;}}));
  assert.throws(()=>fs.fstatSync(descriptor),{code:'EBADF'});
 });
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('unit external namespace isolation preserves the real owned-parent drift refusal and FD closure',()=>{
 const root=temp(),file=path.join(root,'input.json'),unrelated=root+'-unrelated';fs.writeFileSync(file,'{}',{mode:0o600});let descriptor;
 try{isolatedFixtureAncestors(root,()=>{
  const publicValue=readClientPublicInput(file,{afterOpen:()=>fs.mkdirSync(unrelated)});assert.deepEqual(publicValue.value,{});
  assert.throws(()=>readClientPublicInput(file,{afterOpen:fd=>{descriptor=fd;fs.mkdirSync(path.join(root,'actual-new-child'));}}));
  assert.throws(()=>fs.fstatSync(descriptor),{code:'EBADF'});
 });}finally{fs.rmSync(root,{recursive:true,force:true});fs.rmSync(unrelated,{recursive:true,force:true});}
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
  const runtimeTree={schemaVersion:3,kind:'caseops-client-tree-commitment',captureSchemaVersion:2,observations:2,complete:true,root:'/synthetic/runtime',entryCount:1,bytes:0,chargedEntries:2,chargedBytes:0,manifest:{encoding:'caseops-client-tree-v2-json-lf',sha256:H,extent:256}};
  const runtimeInventory={schemaVersion:2,kind:'native-client-webdriver-inventory',complete:true,platform:'ios',root:runtimeTree.root,tree:structuredClone(runtimeTree),auditManifest:{path:'/synthetic/cache/runtime-tree.json',sha256:H,extent:256,metadata:{dev:'0',ino:'1',uid:'501',gid:'20',mode:'33152',nlink:'1',size:'256',mtimeNs:'0',ctimeNs:'0'}}};
  const values=new Map([[q.fixtureEvidence.path,fixture],[q.buildReceipt.path,{...source,artifact:'/synthetic/app',binaryHash:H}],[q.dockerReceipt.path,receipt],[q.deviceEvidence.path,{...installed,observed:true,platform:'ios',buildReceipt:q.buildReceipt}],[q.installedEvidence.path,installed],[q.artifactVersionEvidence.path,{kind:'actual-native-artifact-version',observed:true,buildReceipt:q.buildReceipt,binaryHash:H,platform:'ios',version:'1.0.0',reader:'PlistBuddy-CFBundleShortVersionString'}],[q.codeClosure.path,closure],[q.producerEvidence.path,producer],[q.retainedRowsEvidence.path,{complete:true,normalApiReadback:true,companyId:fixture.companyId,sourceSha:S}],[q.controlsEvidence.path,controls],[controls.registrationEvidence.path,registration],[controls.credentialMountEvidence.path,mount],[q.acceptedToolEvidence.path,tools],[q.clientRuntimeInventoryEvidence.path,runtimeInventory]]);
  q.members.forEach((m,i)=>{const f=i?second:fixture;values.set(m.fixtureEvidence.path,f);values.set(m.authObservation.path,{observed:true,udid:f.udid,appId:f.appId,membershipId:f.membershipId,binaryHash:H,nativePrincipalVerified:true,nativeWorkspaceVerified:true,pkceUnchanged:true,logoutAcknowledged:true,sessionCleanup:'passed',importedSource:source,buildReceipt:q.buildReceipt,dockerReceipt:q.dockerReceipt,mfaStage:f.auth.mfaStage,iosConsent:f.auth.iosConsent});});
  const io={read:r=>values.get(r.path),bytes:()=>Buffer.from('synthetic public'),snapshot:()=>source,harness:()=>HF,installed:()=>installed,artifactHash:()=>H,buildCheck:()=>{},coreCheck:()=>{},closure:()=>closure,tree:()=>structuredClone(runtimeTree),server:()=>({}),tool:file=>tools.executables.find(x=>x.file.path===file).file,selectedExecutable:()=>'/synthetic/git',now:()=>0,environment:{CASEOPS_NATIVE_CLIENT_EXTENSIONS_GO:'EXPLICIT_OWNED_NATIVE_WINDOW',CASEOPS_MOBILE_TOOLING_HOME:'/synthetic/runtime',DEVELOPER_DIR:tools.developerDir,NODE_EXTRA_CA_CERTS:receipt.publicCA},getJson:async url=>url.endsWith('/api/build')?{release_sha:S,revision:'api'}:url.endsWith('/api/release-identity')?{release_sha:S,revision:'web'}:{runId:'epoch',implementationSha256:H,overflow:false,v1ControlProfile:controls.profile,v1ControlsEnabled:true,v1RegistrationSha256:controls.registrationEvidence.sha256,v1ControlsImplementationSha256:H},reader:file=>{secretReads++;const i=q.members.findIndex(m=>m.credentialEvidence.path===file),f=i?second:fixture,value={full_name:f.principalLabel,company_slug:f.auth.companySlug,email:'synthetic@example.invalid',password:'not-a-live-credential',totp_secret:'synthetic-no-live-factor'};loadedValues.push(value);return{sha256:q.members[i].credentialEvidence.sha256,uid:501,value,bytes:Buffer.alloc(16)};}};
  return{q,io,values,reads:()=>secretReads,loadedValues};
 }
 return packet();
}
test('actual admission composition proves every public/current fence before either protected member reader',async()=>{
 const packet=clientAdmissionPacket;
 const positive=packet(),result=await admitClientExtensions(positive.q,positive.io);assert.equal(result.beforeMemberRead,true);assert.equal(positive.reads(),2);assert.ok(result.members.every((m,i)=>m.value===positive.loadedValues[i]&&typeof m.value.password==='string'));
 for(const alter of [x=>{x.io.snapshot=()=>({sourceSha:'f'.repeat(40)});},x=>{x.io.installed=()=>({binaryHash:'foreign'});},x=>{x.io.server=()=>{throw Error('changed owned server');};},x=>{x.io.getJson=async()=>({release_sha:'foreign'});},x=>{x.q.readyForLive=false;},x=>{x.values.get(x.q.clientRuntimeInventoryEvidence.path).tree.observations=1;},x=>{x.values.get(x.q.clientRuntimeInventoryEvidence.path).tree.manifest.sha256='f'.repeat(64);x.values.get(x.q.clientRuntimeInventoryEvidence.path).auditManifest.sha256='f'.repeat(64);},x=>{x.values.get(x.q.fixtureEvidence.path).cx.osRecipes.binaryHash='f'.repeat(64);},x=>{x.values.get(x.q.fixtureEvidence.path).cx.nativeSelectors.udid='old-device';}]){const x=packet();alter(x);await assert.rejects(admitClientExtensions(x.q,x.io));assert.equal(x.reads(),0);}
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

function withInstrumentedFile(reader, { replace = false } = {}) {
 const root=temp(),file=path.join(root,'owned.json');fs.writeFileSync(file,'{"synthetic":true}',{mode:0o600});
 const original={open:fs.openSync,stat:fs.fstatSync,named:fs.lstatSync,read:fs.readSync};let fd,reads=0,replaced=false;const order=[];
 fs.openSync=(name,...args)=>{const result=original.open(name,...args);if(name===file&&fd===undefined){fd=result;order.push('open');}return result;};
 fs.fstatSync=(value,...args)=>{const result=original.stat(value,...args);if(value===fd){order.push('fstat');if(replace&&!replaced){replaced=true;fs.renameSync(file,path.join(root,'retained'));fs.writeFileSync(file,'{}',{mode:0o600});}}return result;};
 fs.lstatSync=(name,...args)=>{if(name===file)order.push('named');return original.named(name,...args);};
 fs.readSync=(value,...args)=>{if(value===fd){reads++;order.push('read');}return original.read(value,...args);};
 let error,result;try{result=reader(file);}catch(value){error=value;}finally{Object.assign(fs,{openSync:original.open,fstatSync:original.stat,lstatSync:original.named,readSync:original.read});}
 try{assert.notEqual(fd,undefined);assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});return{order,reads,error,result,replaced};}finally{fs.rmSync(root,{recursive:true,force:true});}
}
test('public reader admits opened descriptor before named leaf or body',()=>{
 const result=withInstrumentedFile(file=>readClientPublicInput(file));assert.ifError(result.error);assert.deepEqual(result.order.slice(0,3),['open','fstat','named']);assert.ok(result.reads>0);
});
test('runtime file admits opened descriptor before named leaf or body',()=>{
 const result=withInstrumentedFile(file=>captureClientFile(file));assert.ifError(result.error);assert.deepEqual(result.order.slice(0,3),['open','fstat','named']);assert.ok(result.reads>0);
});
test('public leaf replacement after fstat is refused before zero body reads and FD closes',()=>{
 const result=withInstrumentedFile(file=>readClientPublicInput(file),{replace:true});assert.ok(result.replaced&&result.error);assert.equal(result.reads,0);
});
test('runtime leaf replacement after fstat is refused before zero body reads and FD closes',()=>{
 const result=withInstrumentedFile(file=>captureClientFile(file),{replace:true});assert.ok(result.replaced&&result.error);assert.equal(result.reads,0);
});
test('tree regular file uses descriptor-first admission and replacement consumes zero bytes',()=>{
 const result=withInstrumentedFile(file=>captureClientTree(path.dirname(file)),{replace:true});assert.ok(result.replaced&&result.error);assert.equal(result.reads,0);
});
test('portable named device zero preserves inode owner and every other metadata field',async()=>{
 const {assertClientNamedDescriptor}=await import('./client-extension-public-input.mjs');
 const fd={dev:7n,ino:9n,mode:0o100600n,uid:501n,gid:20n,nlink:1n,size:2n,mtimeNs:3n,ctimeNs:4n};
 assertClientNamedDescriptor({...fd,dev:0n},fd,'win32');
 assert.throws(()=>assertClientNamedDescriptor({...fd,dev:0n},fd,'darwin'));
 for(const change of [{dev:8n},{ino:10n},{uid:999n},{nlink:2n},{size:3n},{ctimeNs:5n}])assert.throws(()=>assertClientNamedDescriptor({...fd,dev:0n,...change},fd,'win32'));
});
test('tree late nested insertion after second directory observation is refused',()=>{
 const root=temp(),nested=path.join(root,'nested'),late=path.join(nested,'late');fs.mkdirSync(nested);fs.writeFileSync(path.join(nested,'seed'),'x');
 const oldRead=fs.readdirSync,oldOpen=fs.opendirSync;let reads=0,closes=0,inserted=false;
 const insert=()=>{if(!inserted){inserted=true;fs.writeFileSync(late,'late');}};
 fs.readdirSync=(file,...args)=>{const result=oldRead(file,...args);if(file===root&&++reads===2)insert();return result;};
 fs.opendirSync=(file,...args)=>{const dir=oldOpen(file,...args);if(file===root){const close=dir.closeSync.bind(dir);dir.closeSync=()=>{close();if(++closes===2)insert();};}return dir;};
 let error;try{captureClientTree(root);}catch(value){error=value;}finally{fs.readdirSync=oldRead;fs.opendirSync=oldOpen;}
 try{assert.ok(inserted,'actual late entry was created');assert.ok(error,'late nested entry must not be certified complete');}finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('wide tree discovery uses bounded iterator before retaining entries and closes it',()=>{
 const root=temp();for(let i=0;i<100;i++)fs.writeFileSync(path.join(root,'file-'+i),'x');
 const oldRead=fs.readdirSync,oldOpen=fs.opendirSync;let yielded=0,closed=0;
 fs.readdirSync=()=>{throw Error('UNBOUNDED_READDIR_REFUSED');};
 fs.opendirSync=(...args)=>{const dir=oldOpen(...args),read=dir.readSync.bind(dir),close=dir.closeSync.bind(dir);dir.readSync=()=>{const value=read();if(value)yielded++;return value;};dir.closeSync=()=>{closed++;return close();};return dir;};
 try{assert.throws(()=>captureClientTree(root,{maxEntries:8}),/CX_COMPLETE_TREE_ENTRY_BOUND/);assert.ok(yielded<=8);assert.equal(closed,1);}finally{fs.readdirSync=oldRead;fs.opendirSync=oldOpen;fs.rmSync(root,{recursive:true,force:true});}
});
test('two complete tree inventories share the original entry and byte caps',()=>{
 const root=temp();fs.writeFileSync(path.join(root,'seed'),'x');
 try{assert.throws(()=>captureClientTree(root,{maxEntries:3}),/CX_COMPLETE_TREE_ENTRY_BOUND/);assert.throws(()=>captureClientTree(root,{maxBytes:1}),/CX_COMPLETE_TREE_BYTE_BOUND/);
  const positive=captureClientTree(root,{maxEntries:4,maxBytes:2});assert.equal(positive.complete,true);assert.equal(positive.entries[0].path,'');assert.equal(positive.bytes,1);assert.equal(positive.chargedBytes,2);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('tree deadline expires during actual enumeration and closes the iterator',()=>{
 const root=temp();fs.writeFileSync(path.join(root,'seed'),'x');const oldOpen=fs.opendirSync,oldPerformance=globalThis.performance;let now=0,readCount=0,closed=0;
 globalThis.performance={now:()=>now};
 fs.opendirSync=(...args)=>{const dir=oldOpen(...args),read=dir.readSync.bind(dir),close=dir.closeSync.bind(dir);dir.readSync=()=>{const result=read();readCount++;now=1;return result;};dir.closeSync=()=>{closed++;return close();};return dir;};
 try{assert.throws(()=>captureClientTree(root,{timeoutMs:1}),/CX_COMPLETE_TREE_DEADLINE/);assert.equal(readCount,1);assert.equal(closed,1);}finally{fs.opendirSync=oldOpen;globalThis.performance=oldPerformance;fs.rmSync(root,{recursive:true,force:true});}
});
test('internal tool symlinks remain metadata-only and included in both complete inventories',()=>{
 const root=temp();fs.writeFileSync(path.join(root,'seed'),'x');fs.symlinkSync('seed',path.join(root,'alias'));
 try{const tree=captureClientTree(root);assert.equal(tree.entries.find(row=>row.path==='alias').kind,'symlink');assert.equal(tree.bytes,1);assert.equal(tree.chargedBytes,2);}finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('late entry after the second file FD closes is caught by final every-path reconciliation',()=>{
 const root=temp(),nested=path.join(root,'nested'),file=path.join(nested,'seed');fs.mkdirSync(nested);fs.writeFileSync(file,'x');
 const oldOpen=fs.openSync,oldClose=fs.closeSync;const selected=new Set();let closed=0,inserted=false;
 fs.openSync=(name,...args)=>{const fd=oldOpen(name,...args);if(name===file)selected.add(fd);return fd;};
 fs.closeSync=fd=>{const chosen=selected.delete(fd);const result=oldClose(fd);if(chosen&&++closed===2){inserted=true;fs.writeFileSync(path.join(nested,'late'),'late');}return result;};
 let error;try{captureClientTree(root);}catch(value){error=value;}finally{fs.openSync=oldOpen;fs.closeSync=oldClose;}
 try{assert.ok(inserted,'actual second descriptor completion was reached');assert.match(error?.message??'',/CX_COMPLETE_TREE_FINAL_PATH_CHANGED/);}finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('tree aggregate growing-file consumption is capped at shared maximum plus one and all FDs close',()=>{
 const root=temp(),a=path.join(root,'a'),b=path.join(root,'b');fs.writeFileSync(a,'aaa');fs.writeFileSync(b,'bbb');
 const oldOpen=fs.openSync,oldRead=fs.readSync;const selected=new Map();let bytes=0,grown=false;
 fs.openSync=(name,...args)=>{const fd=oldOpen(name,...args);if(name===a||name===b)selected.set(fd,name);return fd;};
 fs.readSync=(fd,...args)=>{if(selected.get(fd)===b&&!grown){grown=true;fs.appendFileSync(b,'x'.repeat(100000));}const n=oldRead(fd,...args);if(selected.has(fd))bytes+=n;return n;};
 let error;try{captureClientTree(root,{maxBytes:8});}catch(value){error=value;}finally{fs.openSync=oldOpen;fs.readSync=oldRead;}
 try{assert.ok(grown&&error);assert.equal(bytes,9);for(const fd of selected.keys())assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});}finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('runtime and tree descriptor ownership admission refuses matching foreign metadata before bytes',()=>{
 const originalUid=process.getuid;if(!originalUid)process.getuid=()=>0;
 try{for(const reader of [captureClientFile,file=>captureClientTree(path.dirname(file))]){
  const root=temp(),file=path.join(root,'owned');fs.writeFileSync(file,'x');const oldOpen=fs.openSync,oldStat=fs.fstatSync,oldNamed=fs.lstatSync,oldRead=fs.readSync;let fd,reads=0;
  const foreign=s=>new Proxy(s,{get(target,key){return key==='uid'?BigInt(process.getuid()+1):Reflect.get(target,key);}});
  fs.openSync=(name,...args)=>{const opened=oldOpen(name,...args);if(name===file)fd=opened;return opened;};
  fs.fstatSync=(value,...args)=>{const s=oldStat(value,...args);return value===fd?foreign(s):s;};fs.lstatSync=(name,...args)=>{const s=oldNamed(name,...args);return name===file?foreign(s):s;};fs.readSync=(value,...args)=>{if(value===fd)reads++;return oldRead(value,...args);};
  let error;try{reader(file);}catch(value){error=value;}finally{fs.openSync=oldOpen;fs.fstatSync=oldStat;fs.lstatSync=oldNamed;fs.readSync=oldRead;}
  try{assert.ok(error);assert.equal(reads,0);assert.notEqual(fd,undefined);assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});}finally{fs.rmSync(root,{recursive:true,force:true});}
 }}finally{if(!originalUid)delete process.getuid;}
});
test('empty directory exact two-observation entry cap passes while one less refuses',()=>{
 const root=temp();try{const value=captureClientTree(root,{maxEntries:2});assert.equal(value.entries.length,1);assert.equal(value.chargedEntries,2);assert.equal(value.bytes,0);assert.equal(value.chargedBytes,0);assert.throws(()=>captureClientTree(root,{maxEntries:1}),/CX_COMPLETE_TREE_ENTRY_BOUND/);}finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('expired exact-cap EOF probe does not call next and closes both directory iterators',()=>{
 const root=temp(),oldOpen=fs.opendirSync,oldPerformance=globalThis.performance;let now=0,opened=0,next=0,closed=0;globalThis.performance={now:()=>now};
 fs.opendirSync=(...args)=>{const dir=oldOpen(...args),read=dir.readSync.bind(dir),close=dir.closeSync.bind(dir);if(++opened===2)now=1;dir.readSync=()=>{next++;return read();};dir.closeSync=()=>{closed++;return close();};return dir;};
 try{assert.throws(()=>captureClientTree(root,{maxEntries:2,timeoutMs:1}),/CX_COMPLETE_TREE_DEADLINE/);assert.equal(opened,2);assert.equal(next,1);assert.equal(closed,2);}finally{fs.opendirSync=oldOpen;globalThis.performance=oldPerformance;fs.rmSync(root,{recursive:true,force:true});}
});
test('tree root must be a real directory before nonempty or zero-size file body consumption',()=>{
 for(const contents of ['', 'synthetic']){const root=temp(),file=path.join(root,'file');fs.writeFileSync(file,contents);const oldOpen=fs.openSync,oldRead=fs.readSync;let fd,reads=0;
  fs.openSync=(name,...args)=>{const value=oldOpen(name,...args);if(name===file)fd=value;return value;};fs.readSync=(value,...args)=>{if(value===fd)reads++;return oldRead(value,...args);};
  let error;try{captureClientTree(file);}catch(value){error=value;}finally{fs.openSync=oldOpen;fs.readSync=oldRead;}
  try{assert.match(error?.message??'',/CX_TREE_ROOT_DIRECTORY_REQUIRED/);assert.equal(reads,0);assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});}finally{fs.rmSync(root,{recursive:true,force:true});}}
});
test('versioned tree receipt preserves logical bytes and refuses historical proof before server commands',()=>{
 const root=temp();fs.writeFileSync(path.join(root,'seed'),'abc');
 try{const current=captureClientTree(root);assert.equal(current.schemaVersion,2);assert.equal(current.observations,2);assert.equal(current.bytes,3);assert.equal(current.chargedBytes,6);assert.equal(current.chargedEntries,4);
  const legacy={root,entries:current.entries,bytes:3,complete:true},ref={path:'/synthetic',sha256:'a'.repeat(64)},q={platform:'ios',appiumUrl:'http://127.0.0.1:4727',appiumServerEvidence:ref,appiumInventoryEvidence:ref};let commands=0;
  const server={observed:true,owned:true,platform:'ios',pid:10,inventoryEvidence:ref,appiumUrl:q.appiumUrl},inventory={complete:true,platform:'ios',root,tree:legacy};let reads=0;
  assert.throws(()=>admitClientServer(q,{read:()=>++reads===1?server:inventory,command:()=>{commands++;throw Error('MUST_NOT_DISPATCH');}}),/CX_FRESH_TWO_OBSERVATION_TREE_REQUIRED/);assert.equal(commands,0);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('internal late alias fallback consumes metadata only at the exact two-observation byte cap',()=>{
 const root=temp(),target=path.join(root,'a-target'),alias=path.join(root,'z-alias');fs.writeFileSync(target,'abc');fs.symlinkSync('a-target',alias);
 const oldOpen=fs.openSync,oldRead=fs.readSync,oldClose=fs.closeSync,aliases=new Set();let aliasOpens=0,aliasReads=0;
 // Scoped capability model: only this owned alias uses the no-NOFOLLOW path.
 fs.openSync=(file,flags,...args)=>{const fd=oldOpen(file,file===alias?flags&~(fs.constants.O_NOFOLLOW??0):flags,...args);if(file===alias){aliasOpens++;aliases.add(fd);}return fd;};
 fs.readSync=(fd,...args)=>{if(aliases.has(fd))aliasReads++;return oldRead(fd,...args);};fs.closeSync=fd=>{aliases.delete(fd);return oldClose(fd);};
 let tree,error;try{tree=captureClientTree(root,{maxEntries:6,maxBytes:6});}catch(value){error=value;}finally{fs.openSync=oldOpen;fs.readSync=oldRead;fs.closeSync=oldClose;}
 try{assert.ifError(error);assert.equal(tree.bytes,3);assert.equal(tree.chargedBytes,6);assert.equal(tree.chargedEntries,6);assert.equal(tree.entries.find(row=>row.path==='z-alias').kind,'symlink');assert.equal(aliasOpens,2);assert.equal(aliasReads,0);assert.equal(aliases.size,0);}finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('tree external ancestor checks are shared while every file remains in both complete observations',()=>{
 const root=temp();for(let i=0;i<40;i++){const folder=path.join(root,'dir-'+i);fs.mkdirSync(folder);fs.writeFileSync(path.join(folder,'file'),'x');}
 const original=fs.lstatSync,parent=path.dirname(root);let externalReads=0;
 fs.lstatSync=(file,...args)=>{if(file===parent)externalReads++;return original(file,...args);};
 let tree;try{tree=captureClientTree(root);}finally{fs.lstatSync=original;}
 try{assert.equal(tree.entries.length,81);assert.equal(tree.chargedEntries,162);assert.equal(tree.bytes,40);assert.equal(tree.chargedBytes,80);assert.ok(externalReads>=4&&externalReads<=8,'external ancestors must not be walked per payload');}
 finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('tree external identity drift during a body or after second file close refuses the final namespace',()=>{
 for(const point of ['body','second-close']){
  const envelope=temp(),retained=envelope+'-retained',root=path.join(envelope,'root'),file=path.join(root,'file');fs.mkdirSync(root);fs.writeFileSync(file,'x');
  const oldOpen=fs.openSync,oldRead=fs.readSync,oldClose=fs.closeSync,selected=new Set();let closes=0,changed=false;
  const change=()=>{if(!changed){fs.renameSync(envelope,retained);fs.mkdirSync(envelope);fs.renameSync(path.join(retained,'root'),root);changed=true;}};
  fs.openSync=(name,...args)=>{const fd=oldOpen(name,...args);if(name===file)selected.add(fd);return fd;};
  fs.readSync=(fd,...args)=>{if(point==='body'&&selected.has(fd))change();return oldRead(fd,...args);};
  fs.closeSync=fd=>{const chosen=selected.delete(fd),result=oldClose(fd);if(point==='second-close'&&chosen&&++closes===2)change();return result;};
  let error;try{captureClientTree(root);}catch(value){error=value;}finally{fs.openSync=oldOpen;fs.readSync=oldRead;fs.closeSync=oldClose;}
  try{assert.ok(changed);assert.match(error?.message??'',/CX_COMPLETE_TREE_ROOT_NAMESPACE_CHANGED/);assert.equal(selected.size,0);}
  finally{fs.rmSync(envelope,{recursive:true,force:true});fs.rmSync(retained,{recursive:true,force:true});}
 }
});
test('tree held-file parent replacement with a same-inode symlink refuses before body and closes every FD',()=>{
 const root=temp(),parent=path.join(root,'parent'),moved=path.join(root,'retained'),file=path.join(parent,'file');fs.mkdirSync(parent);fs.writeFileSync(file,'x');
 const oldOpen=fs.openSync,oldStat=fs.fstatSync,oldRead=fs.readSync;let fd,changed=false,reads=0;
 fs.openSync=(name,...args)=>{const result=oldOpen(name,...args);if(name===file)fd=result;return result;};
 fs.fstatSync=(value,...args)=>{const result=oldStat(value,...args);if(value===fd&&!changed){changed=true;fs.renameSync(parent,moved);fs.symlinkSync(moved,parent);}return result;};
 fs.readSync=(value,...args)=>{if(value===fd)reads++;return oldRead(value,...args);};
 let error;try{captureClientTree(root);}catch(value){error=value;}finally{fs.openSync=oldOpen;fs.fstatSync=oldStat;fs.readSync=oldRead;}
 try{assert.ok(changed);assert.match(error?.message??'',/CX_CANONICAL_RUNTIME_NAMESPACE_REQUIRED/);assert.equal(reads,0);assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});}
 finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('native canonical resolver and supported fallback retain the identical version2 tree receipt',()=>{
 const root=temp();fs.writeFileSync(path.join(root,'file'),'x');const original=fs.realpathSync;
 try{const native=captureClientTree(root);fs.realpathSync=(...args)=>original(...args);assert.equal(fs.realpathSync.native,undefined);assert.deepEqual(captureClientTree(root),native);}
 finally{fs.realpathSync=original;fs.rmSync(root,{recursive:true,force:true});}
});
test('late entry after the last leaf namespace check is caught by final unique-directory reconciliation',()=>{
 const root=temp(),file=path.join(root,'file');fs.writeFileSync(file,'x');const original=fs.realpathSync;let reads=0,inserted=false;
 const resolve=(name,...args)=>{const value=(original.native??original)(name,...args);if(name===file&&++reads===5){inserted=true;fs.writeFileSync(path.join(root,'late'),'late');}return value;};
 fs.realpathSync=(...args)=>resolve(...args);if(original.native)fs.realpathSync.native=resolve;
 let error;try{captureClientTree(root);}catch(value){error=value;}finally{fs.realpathSync=original;}
 try{assert.ok(inserted);assert.match(error?.message??'',/CX_COMPLETE_TREE_FINAL_PATH_CHANGED/);}finally{fs.rmSync(root,{recursive:true,force:true});}
});

test('small complete reads include the growth sentinel without a redundant EOF syscall',()=>{
 for(const size of [0,7,65535]) {
  const root=temp(),file=path.join(root,'file');fs.writeFileSync(file,Buffer.alloc(size,0x61));
  const open=fs.openSync,read=fs.readSync,close=fs.closeSync,selected=new Set(),calls=[];let result;
  fs.openSync=(name,...args)=>{const fd=open(name,...args);if(name===file)selected.add(fd);return fd;};
  fs.readSync=(fd,buffer,offset,length,position)=>{const n=read(fd,buffer,offset,length,position);if(selected.has(fd))calls.push({length,n});return n;};
  fs.closeSync=fd=>{selected.delete(fd);return close(fd);};
  try{result=captureClientTree(root,{maxBytes:Math.max(1,size*2)});}finally{fs.openSync=open;fs.readSync=read;fs.closeSync=close;}
  try{assert.equal(result.bytes,size);assert.equal(result.chargedBytes,size*2);assert.equal(result.chargedEntries,4);assert.equal(calls.length,2);assert.ok(calls.every(x=>x.length>size&&x.n===size));assert.equal(selected.size,0);}
  finally{fs.rmSync(root,{recursive:true,force:true});}
 }
});
test('exact buffer boundaries keep the explicit growth and EOF probe in both observations',()=>{
 const root=temp(),file=path.join(root,'file');fs.writeFileSync(file,Buffer.alloc(65536,0x61));
 const open=fs.openSync,read=fs.readSync,selected=new Set(),calls=[];let result;
 fs.openSync=(name,...args)=>{const fd=open(name,...args);if(name===file)selected.add(fd);return fd;};
 fs.readSync=(fd,...args)=>{const n=read(fd,...args);if(selected.has(fd))calls.push({requested:args[2],n});return n;};
 try{result=captureClientTree(root);}finally{fs.openSync=open;fs.readSync=read;}
 try{assert.equal(result.bytes,65536);assert.equal(result.chargedBytes,131072);assert.deepEqual(calls.map(x=>x.n),[65536,0,65536,0]);assert.ok(calls.every(x=>x.requested>=1));for(const fd of selected)assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});}
 finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('partial regular-file reads continue until the complete admitted payload is hashed twice',()=>{
 const root=temp(),file=path.join(root,'file'),contents=Buffer.from('partial-read-payload');fs.writeFileSync(file,contents);
 const open=fs.openSync,read=fs.readSync,close=fs.closeSync,selected=new Set();let calls=0,result;
 fs.openSync=(name,...args)=>{const fd=open(name,...args);if(name===file)selected.add(fd);return fd;};
 fs.readSync=(fd,buffer,offset,length,position)=>{if(selected.has(fd)){calls++;return read(fd,buffer,offset,Math.min(length,3),position);}return read(fd,buffer,offset,length,position);};
 fs.closeSync=fd=>{selected.delete(fd);return close(fd);};
 try{result=captureClientTree(root);}finally{fs.openSync=open;fs.readSync=read;fs.closeSync=close;}
 try{assert.equal(result.bytes,contents.length);assert.equal(result.chargedBytes,contents.length*2);assert.equal(result.entries.find(x=>x.path==='file').sha256,sha(contents));assert.ok(calls>=Math.ceil(contents.length/3)*2);assert.equal(selected.size,0);}
 finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('initial FD and named primitive frames remain independent of mutable Stat objects',()=>{
 const root=temp(),file=path.join(root,'file');fs.writeFileSync(file,'before');
 const open=fs.openSync,stat=fs.fstatSync,named=fs.lstatSync,read=fs.readSync,frames=[];let fd,changed=false,error;
 fs.openSync=(name,...args)=>{const value=open(name,...args);if(name===file&&fd===undefined)fd=value;return value;};
 fs.fstatSync=(value,...args)=>{const s=stat(value,...args);if(value===fd&&!changed)frames.push(s);return s;};
 fs.lstatSync=(name,...args)=>{const s=named(name,...args);if(name===file&&!changed)frames.push(s);return s;};
 fs.readSync=(value,...args)=>{
  const n=read(value,...args);
  if(value===fd&&n>0&&!changed){changed=true;const writer=open(file,'r+');try{fs.writeSync(writer,Buffer.from('after!'));fs.futimesSync(writer,1700000000,1700000001);}finally{fs.closeSync(writer);}const current=stat(fd,{bigint:true});
   for(const frame of frames)for(const key of ['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'])frame[key]=current[key];
  }return n;
 };
 try{captureClientFile(file);}catch(value){error=value;}finally{fs.openSync=open;fs.fstatSync=stat;fs.lstatSync=named;fs.readSync=read;}
 try{assert.ok(changed&&frames.length>=2);assert.ok(error,'rewriting interface objects must not rewrite admitted primitive facts');assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});}
 finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('each independent final FD and named metadata field remains checked after payload consumption',()=>{
 const fields=['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'];
 for(const side of ['fd','named'])for(const field of fields) {
  const root=temp(),file=path.join(root,'file');fs.writeFileSync(file,'payload');
  const open=fs.openSync,stat=fs.fstatSync,named=fs.lstatSync,read=fs.readSync;let fd,consumed=false,error;
  const changed=s=>new Proxy(s,{get(target,key){return key===field?Reflect.get(target,key)+1n:Reflect.get(target,key);}});
  fs.openSync=(name,...args)=>{const value=open(name,...args);if(name===file)fd=value;return value;};
  fs.fstatSync=(value,...args)=>{const s=stat(value,...args);return consumed&&side==='fd'&&value===fd?changed(s):s;};
  fs.lstatSync=(name,...args)=>{const s=named(name,...args);return consumed&&side==='named'&&name===file?changed(s):s;};
  fs.readSync=(value,...args)=>{const n=read(value,...args);if(value===fd&&n>0)consumed=true;return n;};
  try{captureClientTree(root);}catch(value){error=value;}finally{fs.openSync=open;fs.fstatSync=stat;fs.lstatSync=named;fs.readSync=read;}
  try{assert.ok(consumed&&error,side+':'+field);assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});}
  finally{fs.rmSync(root,{recursive:true,force:true});}
 }
});
test('post-read internal and external parent aliases retaining the same leaf inode cannot be certified',()=>{
 for(const point of ['internal','external']) {
  const home=temp(),parent=point==='internal'?path.join(home,'root','nested'):home,root=path.join(home,'root'),retained=home+'-retained';
  fs.mkdirSync(root);if(point==='internal')fs.mkdirSync(parent);const file=path.join(point==='internal'?parent:root,'file');fs.writeFileSync(file,'payload');
  const originalInode=fs.statSync(file,{bigint:true}).ino,open=fs.openSync,read=fs.readSync;let fd,changed=false,error;
  fs.openSync=(name,...args)=>{const value=open(name,...args);if(name===file)fd=value;return value;};
  fs.readSync=(value,...args)=>{const n=read(value,...args);if(value===fd&&n>0&&!changed){changed=true;const moved=point==='internal'?path.join(home,'retained'):retained;fs.renameSync(parent,moved);fs.symlinkSync(moved,parent);}return n;};
  try{captureClientTree(root);}catch(value){error=value;}finally{fs.openSync=open;fs.readSync=read;}
  try{assert.ok(changed&&error);assert.equal(fs.statSync(file,{bigint:true}).ino,originalInode);assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});}
  finally{fs.rmSync(home,{recursive:true,force:true});fs.rmSync(retained,{recursive:true,force:true});}
 }
});
test('final root frame follows the last nested canonical directory observation',t=>{
 const root=temp(),nested=path.join(root,'nested'),file=path.join(nested,'file');fs.mkdirSync(nested);fs.writeFileSync(file,'payload');
 const open=fs.openSync,close=fs.closeSync,named=fs.lstatSync,real=fs.realpathSync,selected=new Set();let closed=0,rootChecks=0,nestedChecks=0,rootChecksAtInsert,inserted=false,error,result;
 fs.openSync=(name,...args)=>{const fd=open(name,...args);if(name===file)selected.add(fd);return fd;};
 fs.closeSync=fd=>{const chosen=selected.delete(fd),value=close(fd);if(chosen)closed++;return value;};
 fs.lstatSync=(name,...args)=>{const value=named(name,...args);if(name===root&&closed===2)rootChecks++;return value;};
 const resolve=(name,...args)=>{const value=(real.native??real)(name,...args);if(name===nested&&closed===2&&++nestedChecks===2){rootChecksAtInsert=rootChecks;fs.writeFileSync(path.join(root,'late'),'late');inserted=true;}return value;};
 fs.realpathSync=(...args)=>resolve(...args);if(real.native)fs.realpathSync.native=resolve;
 try{result=captureClientTree(root);}catch(value){error=value;}finally{fs.openSync=open;fs.closeSync=close;fs.lstatSync=named;fs.realpathSync=real;}
 try{t.diagnostic(JSON.stringify({inserted,closed,rootChecksAtInsert,rootChecks,returnedComplete:result?.complete??false,retainedRootNames:result?.entries.find(x=>x.path==='')?.names??null,actualLatePresent:fs.existsSync(path.join(root,'late'))}));assert.ok(inserted,'last nested final canonical boundary was reached');assert.equal(closed,2);assert.equal(selected.size,0);assert.match(error?.message??'',/CX_COMPLETE_TREE_FINAL_PATH_CHANGED/);assert.ok(rootChecks>rootChecksAtInsert,'root must be reconciled after the nested canonical boundary');}
 finally{fs.rmSync(root,{recursive:true,force:true});}
});

function runtimeFixture(operation){
 const home=temp(),root=path.join(home,'sdk'),audit=path.join(home,'manifest.json');fs.mkdirSync(root);fs.writeFileSync(path.join(root,'entry.mjs'),'synthetic');
 try{return operation({home,root,audit});}finally{fs.rmSync(home,{recursive:true,force:true});}
}
function runtimeEnvelope(captured,purpose='webdriver',platform='ios'){
 return {schemaVersion:2,kind:'native-client-'+purpose+'-inventory',complete:true,platform,...captured,...(purpose==='appium'?{appiumEntry:path.join(captured.root,'entry.mjs')}:{})};
}
test('canonical full manifest encoding binds every v2 field in a fixed byte order',()=>runtimeFixture(({root})=>{
 const tree=captureClientTree(root),material=clientTreeManifest(tree);assert.deepEqual(material.bytes,Buffer.from(JSON.stringify(tree)+'\n'));
 const reverse=Object.fromEntries(Object.entries(tree).reverse());reverse.entries=tree.entries.map(row=>({...row,metadata:Object.fromEntries(Object.entries(row.metadata).reverse())}));
 assert.deepEqual(clientTreeManifest(reverse),material);assert.equal(material.commitment.manifest.sha256,sha(material.bytes));assert.equal(material.commitment.manifest.extent,material.bytes.length);
 assert.equal(material.commitment.entryCount,tree.entries.length);assert.equal(material.commitment.chargedEntries,2*tree.entries.length);assert.equal(material.commitment.chargedBytes,2*tree.bytes);
 for(const change of [{extra:true},{observations:1},{complete:false},{entries:tree.entries.slice(1)},{bytes:tree.bytes+1},{chargedEntries:tree.chargedEntries+1}])assert.throws(()=>clientTreeManifest({...tree,...change}));
}));
test('required entry projection computes its stable relative key once instead of per member',async()=>asyncReadFixture(Object.fromEntries(Array.from({length:40},(_,i)=>['item-'+String(i).padStart(2,'0'),'synthetic']).concat([['zz-entry.mjs','entry']])),async state=>{
 const original=path.relative,entry=path.join(state.root,'zz-entry.mjs');let calls=0;
 path.relative=(from,to)=>{if(from===state.root&&to===entry)calls++;return original(from,to);};
 try{const sync=captureClientTreeCommitment(state.root,undefined,entry);assert.ok(calls<=8);calls=0;const async=await state.track(captureClientTreeCommitmentAsync(state.root,undefined,entry));assert.ok(calls<=8);assert.deepEqual(async,sync);assert.equal(state.live.size,0);}finally{path.relative=original;}
}));
test('codec-only widest numeric metadata is one bounded exact canonical chunk',()=>{
 const wide='-'+('9'.repeat(40)),metadata={dev:wide,ino:wide,uid:wide,gid:wide,mode:wide,nlink:wide,size:wide,mtimeNs:wide,ctimeNs:wide};
 const tree={schemaVersion:2,observations:2,root:'/codec-only',entries:[{path:'',kind:'directory',metadata,names:[]}],bytes:0,chargedBytes:0,chargedEntries:2,complete:true},expected=Buffer.from(JSON.stringify(tree)+'\n'),byteLength=Buffer.byteLength,chunks=[];let material;
 Buffer.byteLength=(value,...args)=>{if(typeof value==='string'&&value.startsWith(',"metadata":{'))chunks.push(value);return byteLength(value,...args);};
 try{material=clientTreeManifest(tree);}finally{Buffer.byteLength=byteLength;}
 assert.ok(material.bytes.equals(expected));assert.equal(material.commitment.manifest.sha256,sha(expected));assert.ok(chunks.length>0);assert.equal(new Set(chunks).size,1);assert.equal(chunks[0],',"metadata":'+JSON.stringify(metadata));assert.ok(chunks.every(value=>byteLength(value)<=512));
});
test('codec retains each validated metadata primitive and rejects first malformed getter values',()=>runtimeFixture(({root})=>{
 const tree=captureClientTree(root),expected=Buffer.from(JSON.stringify(tree)+'\n'),index=tree.entries.findIndex(row=>row.kind==='file'),fields=['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'];
 for(const field of fields){const copy=structuredClone(tree),value=copy.entries[index].metadata[field];let reads=0;Object.defineProperty(copy.entries[index].metadata,field,{enumerable:true,get:()=>++reads===1?value:'UNVERIFIED_LATER_VALUE'});const material=clientTreeManifest(copy);assert.equal(reads,1);assert.ok(material.bytes.equals(expected));}
 for(const field of fields)for(const bad of[undefined,null,17,17n,'00','-01','1.0','1e3','1'.repeat(41)]){const copy=structuredClone(tree),good=copy.entries[index].metadata[field];let reads=0;Object.defineProperty(copy.entries[index].metadata,field,{enumerable:true,get:()=>++reads===1?bad:good});assert.throws(()=>clientTreeManifest(copy),/CX_TREE_METADATA_REQUIRED/);assert.equal(reads,1);}
 for(const mutate of[metadata=>metadata.extra='0',metadata=>delete metadata.ino]){const copy=structuredClone(tree);mutate(copy.entries[index].metadata);assert.throws(()=>clientTreeManifest(copy));}
 const copy=structuredClone(tree),metadata=copy.entries[index].metadata;let references=0;Object.defineProperty(copy.entries[index],'metadata',{enumerable:true,get:()=>++references===1?metadata:{}});assert.ok(clientTreeManifest(copy).bytes.equals(expected));assert.equal(references,1);
}));
test('codec-only UTF8 output accepts exact16MiB and refuses the next byte',()=>{
 const metadata=(mode,ino)=>({dev:'1',ino:String(ino),uid:'501',gid:'20',mode,nlink:'1',size:'0',mtimeNs:'1',ctimeNs:'1'}),empty='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';
 const names=Array.from({length:8},(_,i)=>String.fromCharCode(97+i)+'λ');
 const tree={schemaVersion:2,observations:2,root:'/codec-only',entries:[{path:'',kind:'directory',metadata:metadata('16832',1),names},...names.map((name,i)=>({path:name,kind:'file',metadata:metadata('33152',i+2),sha256:empty}))],bytes:0,chargedBytes:0,chargedEntries:18,complete:true};
 let remaining=CLIENT_TREE_AUDIT_MAX_BYTES-Buffer.byteLength(JSON.stringify(tree)+'\n');if(remaining%2){tree.root+='r';remaining--;}
 const perName=Math.floor(remaining/16),extra=(remaining/2)%8;
 for(let i=0;i<8;i++){names[i]=String.fromCharCode(97+i)+'x'.repeat(perName+(i<extra?1:0))+'λ';tree.entries[i+1].path=names[i];assert.ok(names[i].length<=1048576);}
 const expected=Buffer.from(JSON.stringify(tree)+'\n');assert.equal(expected.length,CLIENT_TREE_AUDIT_MAX_BYTES);const material=clientTreeManifest(tree);assert.equal(material.bytes.length,expected.length);assert.ok(material.bytes.equals(expected));assert.equal(material.commitment.manifest.sha256,sha(expected));
 assert.throws(()=>clientTreeManifest({...tree,root:tree.root+'r'}),/CX_TREE_MANIFEST_OUTPUT_BOUND/);
});

test('compact commitment strictly rejects stale versions, shape, roots and incoherent numeric counts',()=>runtimeFixture(({root})=>{
 const c=captureClientTreeCommitment(root);assert.equal(assertClientTreeCommitment(c,root),c);
 for(const mutate of [v=>v.schemaVersion=2,v=>v.captureSchemaVersion=1,v=>v.observations=1,v=>v.complete=false,v=>v.extra=true,v=>v.root='relative',v=>v.entryCount=true,v=>v.entryCount=1.5,v=>v.entryCount=0,v=>v.entryCount=25001,v=>v.bytes=-1,v=>v.bytes=Number.MAX_SAFE_INTEGER,v=>v.chargedEntries++,v=>v.chargedBytes++,v=>v.manifest.sha256='A'.repeat(64),v=>v.manifest.extent=0,v=>v.manifest.extent=CLIENT_TREE_AUDIT_MAX_BYTES+1,v=>v.manifest.encoding='unknown',v=>v.manifest.extra=true]){const bad=structuredClone(c);mutate(bad);assert.throws(()=>assertClientTreeCommitment(bad,root));}
 assert.throws(()=>assertClientTreeCommitment(c,root+'-other'));assert.throws(()=>assertClientTreeCommitment(captureClientTree(root)));
}));
test('fresh compact capture still charges both complete observations to entry and byte caps',()=>runtimeFixture(({root})=>{
 assert.throws(()=>captureClientTreeCommitment(root,{maxEntries:3}),/CX_COMPLETE_TREE_ENTRY_BOUND/);assert.throws(()=>captureClientTreeCommitment(root,{maxBytes:17}),/CX_COMPLETE_TREE_BYTE_BOUND/);
 const c=captureClientTreeCommitment(root,{maxEntries:4,maxBytes:18});assert.equal(c.entryCount,2);assert.equal(c.bytes,9);assert.equal(c.chargedEntries,4);assert.equal(c.chargedBytes,18);
}));
test('commitment encoding shares the capture deadline instead of resetting a second budget',()=>runtimeFixture(({root})=>{
 const originalNow=globalThis.performance,open=fs.openSync,close=fs.closeSync,byteLength=Buffer.byteLength,selected=new Set();let now=0,closes=0,encoded=false;globalThis.performance={now:()=>now};
 fs.openSync=(file,...args)=>{const fd=open(file,...args);if(file===path.join(root,'entry.mjs'))selected.add(fd);return fd;};
 fs.closeSync=fd=>{const chosen=selected.delete(fd),result=close(fd);if(chosen&&++closes===2)now=4000;return result;};
 Buffer.byteLength=(...args)=>{const n=byteLength(...args);if(closes===2){encoded=true;now=5001;}return n;};
 try{assert.throws(()=>captureClientTreeCommitment(root),/CX_COMPLETE_TREE_DEADLINE/);assert.equal(closes,2);assert.equal(encoded,true);assert.equal(selected.size,0);}finally{globalThis.performance=originalNow;fs.openSync=open;fs.closeSync=close;Buffer.byteLength=byteLength;}
}));
test('fresh public runtime inventory retains a full external audit and fits unchanged public transport',()=>runtimeFixture(({home,root,audit})=>{
 const captured=captureClientTreeInventory(root,audit),inventory=runtimeEnvelope(captured),full=fs.readFileSync(audit),file=path.join(home,'inventory.json');
 assert.equal(assertClientRuntimeInventory(inventory,'webdriver','ios'),inventory);assert.deepEqual(full,clientTreeManifest(captureClientTree(root)).bytes);assert.equal(sha(full),inventory.tree.manifest.sha256);
 if(process.getuid)assert.equal(fs.statSync(audit).mode&0o777,0o600); // POSIX bits; actual Windows ACL acceptance is separate.
 const bytes=Buffer.from(JSON.stringify(inventory)+'\n');assert.ok(bytes.length<1048576);const ref=writeClientProjection(file,bytes);
 isolatedFixtureAncestors(home,()=>assert.deepEqual(readClientPublicInput(file,{expectedSha256:ref.sha256}).value,inventory));
 assert.throws(()=>captureClientTreeInventory(root,audit),{code:'EEXIST'});assert.throws(()=>writeClientProjection(path.join(home,'large.json'),Buffer.alloc(1048577)));
}));
test('purpose-specific runtime inventories reject mismatched roots, audit identities and inline legacy shapes',()=>runtimeFixture(({root,audit})=>{
 const good=runtimeEnvelope(captureClientTreeInventory(root,audit));
 for(const mutate of [v=>v.schemaVersion=1,v=>v.kind='native-client-appium-inventory',v=>v.platform='android',v=>v.complete=false,v=>v.root+='/other',v=>v.extra=true,v=>v.tree=captureClientTree(root),v=>v.auditManifest.sha256='f'.repeat(64),v=>v.auditManifest.extent++,v=>v.auditManifest.path=path.join(root,'inside'),v=>v.auditManifest.metadata.nlink='2',v=>v.auditManifest.metadata.size='0']){const bad=structuredClone(good);mutate(bad);assert.throws(()=>assertClientRuntimeInventory(bad,'webdriver','ios'));}
 const appium={...good,kind:'native-client-appium-inventory',appiumEntry:path.join(root,'entry.mjs')};assertClientRuntimeInventory(appium,'appium','ios');assert.throws(()=>assertClientRuntimeInventory({...appium,appiumEntry:'/foreign/entry'},'appium','ios'));
}));
test('Appium admission freshly captures actual runtime and never uses its audit file as authority',()=>runtimeFixture(({root,audit})=>{
 const inventory=runtimeEnvelope(captureClientTreeInventory(root,audit),'appium'),ref={path:'/synthetic',sha256:'a'.repeat(64)},q={platform:'ios',appiumUrl:'http://127.0.0.1:4727',appiumServerEvidence:ref,appiumInventoryEvidence:ref},observed='synthetic-start '+inventory.appiumEntry;
 const server={observed:true,owned:true,platform:'ios',pid:10,inventoryEvidence:ref,appiumUrl:q.appiumUrl,uid:process.getuid(),utcStartAndCommandSha256:sha(observed)};let reads=0,commands=0;fs.unlinkSync(audit);
 const command=(_file,args)=>{commands++;return args.includes('uid=')?String(process.getuid()):args.includes('-Fpfn')?'p10\nf1\nn127.0.0.1:4727\n':observed;};
 assert.equal(admitClientServer(q,{read:()=>++reads===1?server:inventory,command}).inventory,inventory);assert.equal(commands,3);
 fs.writeFileSync(path.join(root,'.late'),'x');reads=0;commands=0;assert.throws(()=>admitClientServer(q,{read:()=>++reads===1?server:inventory,command}),/CX_COMPLETE_APPIUM_INVENTORY_CHANGED/);assert.equal(commands,0);
}));
test('Appium hash-only or legacy inline receipts refuse before any server command',()=>runtimeFixture(({root,audit})=>{
 const good=runtimeEnvelope(captureClientTreeInventory(root,audit),'appium'),ref={path:'/synthetic',sha256:'a'.repeat(64)},q={platform:'ios',appiumUrl:'http://127.0.0.1:4727',appiumServerEvidence:ref,appiumInventoryEvidence:ref},server={observed:true,owned:true,platform:'ios',pid:10,inventoryEvidence:ref,appiumUrl:q.appiumUrl};
 for(const tree of [captureClientTree(root),{sha256:good.tree.manifest.sha256},{...good.tree,observations:1},{...good.tree,manifest:{...good.tree.manifest,sha256:'f'.repeat(64)}}]){let reads=0,commands=0;assert.throws(()=>admitClientServer(q,{read:()=>++reads===1?server:{...good,tree,auditManifest:{...good.auditManifest,sha256:tree.manifest?.sha256??good.auditManifest.sha256}},command:()=>{commands++;throw Error('MUST_NOT_DISPATCH');}}));assert.equal(commands,0);}
}));
test('full audit writer rejects oversize, mismatched buffer, runtime-local outputs and overwrite',()=>runtimeFixture(({home,root,audit})=>{
 const material=clientTreeManifest(captureClientTree(root));let opened=0;const original=fs.openSync;fs.openSync=(...args)=>{opened++;return original(...args);};
 try{assert.throws(()=>writeClientTreeAuditManifest(audit,{...material,bytes:Buffer.alloc(CLIENT_TREE_AUDIT_MAX_BYTES+1)}),/CX_TREE_MANIFEST_OUTPUT_BOUND/);assert.equal(opened,0);assert.throws(()=>writeClientTreeAuditManifest(audit,{...material,bytes:Buffer.from('changed')}));assert.equal(opened,0);}finally{fs.openSync=original;}
 assert.throws(()=>writeClientTreeAuditManifest(path.join(root,'inside'),material),/CX_AUDIT_OUTPUT_OUTSIDE_RUNTIME_REQUIRED/);const result=writeClientTreeAuditManifest(audit,material);assert.equal(result.extent,material.bytes.length);assert.throws(()=>writeClientTreeAuditManifest(audit,material),{code:'EEXIST'});assert.equal(fs.existsSync(path.join(home,'large.json')),false);
}));
test('audit writer binds opened descriptor to named leaf before any bytes and closes on replacement',()=>runtimeFixture(({audit,root})=>{
 const material=clientTreeManifest(captureClientTree(root)),open=fs.openSync,fstat=fs.fstatSync,write=fs.writeSync;let fd,replaced=false,writes=0;
 fs.openSync=(file,...args)=>{const value=open(file,...args);if(file===audit)fd=value;return value;};fs.fstatSync=(value,...args)=>{const s=fstat(value,...args);if(value===fd&&!replaced){fs.renameSync(audit,audit+'.retained');fs.writeFileSync(audit,'replacement');replaced=true;}return s;};fs.writeSync=(value,...args)=>{if(value===fd)writes++;return write(value,...args);};
 try{assert.throws(()=>writeClientTreeAuditManifest(audit,material),/CX_NAMED_DESCRIPTOR_IDENTITY_CHANGED/);assert.ok(replaced);assert.equal(writes,0);}finally{fs.openSync=open;fs.fstatSync=fstat;fs.writeSync=write;}assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});
}));
test('failed full audit writes retain partial output, close the FD and never return a reference',()=>runtimeFixture(({audit,root})=>{
 const material=clientTreeManifest(captureClientTree(root)),open=fs.openSync,write=fs.writeSync;let fd,calls=0;
 fs.openSync=(file,...args)=>{const value=open(file,...args);if(file===audit)fd=value;return value;};fs.writeSync=(value,buffer,offset,length)=>{if(value!==fd)return write(value,buffer,offset,length);if(++calls>1)throw Error('OWNED_WRITE_FAILURE');return write(value,buffer,offset,Math.min(8,length));};
 try{assert.throws(()=>writeClientTreeAuditManifest(audit,material),/OWNED_WRITE_FAILURE/);}finally{fs.openSync=open;fs.writeSync=write;}assert.equal(fs.statSync(audit).size,8);assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});
}));
test('audit writer checks the original deadline after fsync and closes without success',()=>runtimeFixture(({audit,root})=>{
 const material=clientTreeManifest(captureClientTree(root)),original=globalThis.performance,sync=fs.fsyncSync,open=fs.openSync;let fd,now=0;globalThis.performance={now:()=>now};fs.openSync=(file,...args)=>{const value=open(file,...args);if(file===audit)fd=value;return value;};fs.fsyncSync=value=>{sync(value);if(value===fd)now=5000;};
 try{assert.throws(()=>writeClientTreeAuditManifest(audit,material),/CX_COMPLETE_TREE_DEADLINE/);}finally{globalThis.performance=original;fs.fsyncSync=sync;fs.openSync=open;}assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});
}));
test('public runtime producer executes the real fresh capture while leaving native and private actions unacknowledged',async()=>{
 const {prepareClientRuntimeInventory}=await import('./prepare-client-extensions.mjs');runtimeFixture(({home,root,audit})=>{
  const q={kind:'prepare-native-client-runtime-inventory',preparedOnly:true,purpose:'webdriver',platform:'ios',root,output:path.join(home,'public.json'),manifestOutput:audit},source={sourceDirty:false,sourceSha:'a'.repeat(40)};let snapshots=0;
  const result=prepareClientRuntimeInventory(q,{snapshot:()=>{snapshots++;return source;}});assert.equal(snapshots,2);assert.equal(result.inventory.tree.observations,2);assert.equal(result.nativeActions,0);assert.equal(result.privateReads,0);assert.equal(result.actualNativeAcceptance,false);assert.equal(fs.existsSync(audit),true);
 });
});
test('public runtime producer rejects invalid domains and output locations before capture',async()=>{
 const {prepareClientRuntimeInventory}=await import('./prepare-client-extensions.mjs');runtimeFixture(({home,root,audit})=>{
  const q={kind:'prepare-native-client-runtime-inventory',preparedOnly:true,purpose:'webdriver',platform:'ios',root,output:path.join(home,'public.json'),manifestOutput:audit};let effects=0;const io={snapshot:()=>{effects++;throw Error('NO_EFFECT');},capture:()=>{effects++;throw Error('NO_EFFECT');}};
  for(const change of [{preparedOnly:false},{purpose:'unknown'},{platform:'web'},{root:'relative'},{output:path.join(root,'inside')},{manifestOutput:path.join(root,'inside')},{manifestOutput:q.output},{purpose:'appium',appiumEntry:'/foreign/entry'}]){assert.throws(()=>prepareClientRuntimeInventory({...q,...change},io));assert.equal(effects,0);}
 });
});

test('runtime parser refuses nonnormalized root entry and audit paths before any authority',()=>runtimeFixture(({root,audit})=>{
 const good=runtimeEnvelope(captureClientTreeInventory(root,audit),'appium');
 for(const mutate of [v=>v.root+='/../sdk',v=>v.tree.root+='/../sdk',v=>v.appiumEntry=root+'/../outside/entry.mjs',v=>v.appiumEntry=root+'/./entry.mjs',v=>v.auditManifest.path=path.dirname(audit)+'/sdk/../manifest.json']){const bad=structuredClone(good);mutate(bad);assert.throws(()=>assertClientRuntimeInventory(bad,'appium','ios'));}
}));
test('Appium public producer binds its canonical regular entry to the actual complete captured tree',async()=>{
 const {prepareClientRuntimeInventory}=await import('./prepare-client-extensions.mjs');
 for(const kind of ['regular','missing','directory','alias'])runtimeFixture(({home,root,audit})=>{
  let entry=path.join(root,'entry.mjs');if(kind==='missing')entry=path.join(root,'missing');if(kind==='directory')entry=root;if(kind==='alias'){entry=path.join(root,'alias.mjs');fs.symlinkSync('entry.mjs',entry);}
  const q={kind:'prepare-native-client-runtime-inventory',preparedOnly:true,purpose:'appium',platform:'ios',root,appiumEntry:entry,output:path.join(home,'public.json'),manifestOutput:audit},io={snapshot:()=>({sourceDirty:false})};
  if(kind==='regular'){const value=prepareClientRuntimeInventory(q,io);assert.equal(value.inventory.appiumEntry,entry);assert.equal(value.nativeActions,0);}else{assert.throws(()=>prepareClientRuntimeInventory(q,io));assert.equal(fs.existsSync(audit),false);}
 });
});
test('Appium admission refuses uncaptured entry targets and traversal before server commands',()=>{
 for(const kind of ['missing','directory','alias','traversal'])runtimeFixture(({root,audit})=>{
  const entry=path.join(root,'entry.mjs');let target;if(kind==='alias'){target=path.join(root,'alias');fs.symlinkSync('entry.mjs',target);}else target=kind==='missing'?path.join(root,'missing'):kind==='directory'?root:root+'/../outside/entry.mjs';
  const inventory={...runtimeEnvelope(captureClientTreeInventory(root,audit),'appium'),appiumEntry:target},ref={path:'/synthetic',sha256:'a'.repeat(64)},q={platform:'ios',appiumUrl:'http://127.0.0.1:4727',appiumServerEvidence:ref,appiumInventoryEvidence:ref},server={observed:true,owned:true,platform:'ios',pid:10,inventoryEvidence:ref,appiumUrl:q.appiumUrl};let reads=0,commands=0;
  assert.throws(()=>admitClientServer(q,{read:()=>++reads===1?server:inventory,command:()=>{commands++;return 'synthetic process '+entry;}}));assert.equal(commands,0);
 });
});

const immediate=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};}
async function asyncReadFixture(files,operation){
 const root=temp();for(const[name,bytes]of Object.entries(files)){fs.mkdirSync(path.dirname(path.join(root,name)),{recursive:true});fs.writeFileSync(path.join(root,name),bytes);}
 const original={open:fs.openSync,openAsync:fs.open,close:fs.closeSync,read:fs.read,dir:fs.opendirSync,stat:fs.fstatSync};
 const state={root,records:[],live:new Map(),buffers:new Set(),pending:[],promises:[],outcomes:new Map(),reads:[],actualBytes:0,activeDirs:0,peakOwned:0,hold:false};
 const inside=file=>typeof file==='string'&&(file===root||file.startsWith(root+path.sep));
 const peak=()=>{state.peakOwned=Math.max(state.peakOwned,state.live.size+state.activeDirs);};
 const fixtureNow=performance.now.bind(performance),waiters=new Set(),timers=new Set();
 state.changed=()=>{for(const wake of [...waiters])wake();};
 state.barrierState=()=>({waiters:waiters.size,timers:timers.size});
 const waitChanged=end=>new Promise(resolve=>{
  let done=false,timer;const wake=()=>{if(done)return;done=true;waiters.delete(wake);if(timer!==undefined){clearTimeout(timer);timers.delete(timer);}resolve();};
  waiters.add(wake);timer=setTimeout(wake,Math.max(0,end-fixtureNow()));timers.add(timer);
 });
 state.track=promise=>{state.promises.push(promise);const value={settled:false};state.outcomes.set(promise,value);promise.then(result=>{value.settled=true;value.result=result;state.changed();},error=>{value.settled=true;value.error=error;state.changed();});return promise;};
 state.reached=async(predicate,promise)=>{
  const end=fixtureNow()+1000;
  const observed=()=>{if(predicate())return true;const outcome=state.outcomes.get(promise);if(outcome?.settled)throw outcome.error??Error('ASYNC_CONTROL_COMPLETED_BEFORE_BARRIER');return false;};
  for(let n=0;n<256&&fixtureNow()<end;n++){if(observed())return;await waitChanged(end);}
  if(observed())return;throw Error('ASYNC_CONTROL_BARRIER_NOT_REACHED');
 };
 state.releaseAll=()=>{state.hold=false;for(const entry of state.pending)if(!entry.delivered)entry.deliver();};
 const opened=(file,fd)=>{if(inside(file)){assert.equal(state.live.has(fd),false);const record={fd,file,closed:false};state.records.push(record);state.live.set(fd,record);peak();state.changed();}return fd;};
 fs.openSync=(file,...args)=>opened(file,original.open(file,...args));
 fs.open=(file,...args)=>{const callback=args.pop();return original.openAsync(file,...args,(error,fd)=>{if(!error)opened(file,fd);try{return callback(error,fd);}finally{state.changed();}});};
 fs.closeSync=fd=>{const record=state.live.get(fd);try{return original.close(fd);}finally{if(record){record.closed=true;state.live.delete(fd);state.changed();}}};
 fs.opendirSync=(file,...args)=>{const dir=original.dir(file,...args);if(!inside(file))return dir;state.activeDirs++;peak();let closed=false;return{readSync:()=>dir.readSync(),closeSync:()=>{assert.equal(closed,false);closed=true;try{return dir.closeSync();}finally{state.activeDirs--;}}};};
 fs.read=(fd,buffer,offset,width,position,callback)=>{
  const record=state.live.get(fd);if(!record)return original.read(fd,buffer,offset,width,position,callback);
  state.buffers.add(buffer);const selected=state.beforeRead?.({fd,file:record.file,buffer,width})??width;
  return original.read(fd,buffer,offset,selected,position,(error,n,result)=>{
   if(Number.isInteger(n))state.actualBytes+=n;state.reads.push({file:record.file,requested:width,actualRequested:selected,n});state.afterRead?.({fd,file:record.file,buffer,width,error,n});
   const entry={fd,file:record.file,delivered:false,deliver:(override=error)=>{assert.equal(entry.delivered,false);entry.delivered=true;callback(override,n,result);}};
   if(state.hold)state.pending.push(entry);else entry.deliver();state.changed();
  });
 };
 let value,primary;const cleanup=[];
 try{value=await operation(state);}catch(error){primary=error;}
 finally{
  state.releaseAll();await Promise.allSettled(state.promises);
  Object.assign(fs,{openSync:original.open,open:original.openAsync,closeSync:original.close,read:original.read,opendirSync:original.dir});
  try{assert.deepEqual(state.barrierState(),{waiters:0,timers:0});assert.equal(state.activeDirs,0);assert.equal(state.live.size,0);for(const record of state.records)assert.throws(()=>original.stat(record.fd),{code:'EBADF'});}catch(error){cleanup.push(error);}
  fs.rmSync(root,{recursive:true,force:true});
 }
 if(primary)throw cleanup.length?new AggregateError([primary,...cleanup],primary.message,{cause:primary}):primary;
 if(cleanup.length)throw cleanup[0];return value;
}

test('async complete capture preserves exact sync rows and canonical manifest bytes',async()=>asyncReadFixture({'empty':'','nested/Unicode-λ.txt':'synthetic λ','boundary.bin':Buffer.alloc(65536,7)},async state=>{
 fs.symlinkSync('nested/Unicode-λ.txt',path.join(state.root,'internal'));const expected=captureClientTree(state.root);
 const actual=await state.track(captureClientTreeAsync(state.root));assert.deepEqual(actual,expected);assert.deepEqual(clientTreeManifest(actual).bytes,clientTreeManifest(expected).bytes);
 assert.equal(actual.observations,2);assert.equal(actual.chargedBytes,actual.bytes*2);assert.ok(state.buffers.size<=4);
}));
test('async capture owns at most four buffers and descriptors including directory iterators',async()=>asyncReadFixture(Object.fromEntries(Array.from({length:8},(_,i)=>['file-'+i,'synthetic-'+i]).concat([['nested/last','last']])),async state=>{
 state.hold=true;const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>state.pending.length===4,capture);
 assert.equal(state.live.size,4);assert.equal(state.records.filter(x=>!x.closed).length,4);assert.equal(state.buffers.size,4);assert.ok(state.peakOwned<=4);assert.equal(state.records.filter(x=>x.file.endsWith('file-4')).length,0);
 state.releaseAll();const tree=await capture;assert.equal(tree.complete,true);assert.ok(state.peakOwned<=4);assert.equal(state.buffers.size,4);assert.ok([...state.buffers].every(b=>b.length===65536));
}));
test('async exact shared byte credit completes zero-byte files and required EOF probes without deadlock',async()=>asyncReadFixture({'a-empty':'','b-empty':'','c-byte':'x','d-empty':''},async state=>{
 const tree=await state.track(captureClientTreeAsync(state.root,{maxBytes:2,maxEntries:10}));assert.equal(tree.bytes,1);assert.equal(tree.chargedBytes,2);assert.equal(tree.chargedEntries,10);assert.equal(state.actualBytes,2);assert.ok(state.reads.some(x=>x.n===0));assert.ok(state.peakOwned<=4);
}));
test('async small sentinel, buffer boundary and partial reads retain exact complete hashes',async()=>{
 for(const[size,partial,expectedReads]of[[7,false,2],[65536,false,4],[7,true,8],[0,false,2]])await asyncReadFixture({'payload':Buffer.alloc(size,3)},async state=>{
  if(partial)state.beforeRead=({width})=>Math.min(width,2);
  const value=await state.track(captureClientTreeAsync(state.root));assert.equal(state.reads.length,expectedReads);assert.equal(state.actualBytes,size*2);assert.equal(value.entries.find(x=>x.kind==='file').sha256,sha(Buffer.alloc(size,3)));
 });
});
test('async growing payload consumes only the one shared overflow credit and drains every job',async()=>asyncReadFixture({'a':'abc','b-empty':'','c-empty':'','d-empty':''},async state=>{
 let grew=false;state.beforeRead=({file,width})=>{if(file.endsWith('/a')&&!grew){grew=true;fs.appendFileSync(file,'synthetic-growth');}return width;};
 const capture=state.track(captureClientTreeAsync(state.root,{maxBytes:8}));await assert.rejects(capture,/CX_COMPLETE_TREE_BYTE_BOUND/);assert.equal(grew,true);assert.equal(state.actualBytes,9);assert.equal(state.live.size,0);assert.ok(state.peakOwned<=4);
}));
test('async bounded directory discovery charges before retaining excess paths and closes the iterator',async()=>asyncReadFixture(Object.fromEntries(Array.from({length:20},(_,i)=>['file-'+i,'x'])),async state=>{
 const capture=state.track(captureClientTreeAsync(state.root,{maxEntries:3}));await assert.rejects(capture,/CX_COMPLETE_TREE_ENTRY_BOUND/);assert.equal(state.reads.length,0);assert.equal(state.records.length,1);assert.equal(state.activeDirs,0);
}));
test('async named replacement after descriptor admission consumes zero bytes and closes its FD',async()=>asyncReadFixture({'leaf':'original'},async state=>{
 const original=fs.fstatSync;let replaced=false;
 fs.fstatSync=(fd,...args)=>{const value=original(fd,...args),record=state.live.get(fd);if(record?.file.endsWith('/leaf')&&!replaced){replaced=true;fs.renameSync(record.file,record.file+'-retained');fs.writeFileSync(record.file,'replacement');}return value;};
 try{await assert.rejects(state.track(captureClientTreeAsync(state.root)));assert.equal(replaced,true);assert.equal(state.reads.length,0);assert.equal(state.live.size,0);}finally{fs.fstatSync=original;}
}));
test('async independent FD and named primitive frames reject every one of their nine field drifts',async()=>{
 for(const boundary of['fd','named'])for(const field of['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'])await asyncReadFixture({'leaf':'synthetic'},async state=>{
  const stat=fs.fstatSync,named=fs.lstatSync;let read=false,changed=false;state.afterRead=()=>{read=true;};
  const alter=value=>new Proxy(value,{get(target,key){return key===field?Reflect.get(target,key)+1n:Reflect.get(target,key);}});
  fs.fstatSync=(fd,...args)=>{const value=stat(fd,...args);if(boundary==='fd'&&read&&state.live.get(fd)?.file.endsWith('/leaf')&&!changed){changed=true;return alter(value);}return value;};
  fs.lstatSync=(file,...args)=>{const value=named(file,...args);if(boundary==='named'&&read&&file===path.join(state.root,'leaf')&&args[0]?.bigint&&!changed){changed=true;return alter(value);}return value;};
  try{await assert.rejects(state.track(captureClientTreeAsync(state.root)));assert.equal(changed,true);assert.equal(state.live.size,0);}finally{fs.fstatSync=stat;fs.lstatSync=named;}
 });
});
test('async parent rename and same-inode internal or external alias still refuse after held reads',async()=>{
 for(const kind of['internal','external'])await asyncReadFixture({'nested/leaf':'synthetic'},async state=>{
  const nested=path.join(state.root,'nested'),moved=kind==='internal'?path.join(state.root,'moved'):state.root+'-moved';let changed=false;
  state.afterRead=()=>{if(!changed){changed=true;fs.renameSync(nested,moved);fs.symlinkSync(moved,nested);}};
  try{await assert.rejects(state.track(captureClientTreeAsync(state.root)));assert.equal(changed,true);assert.equal(state.live.size,0);}finally{if(kind==='external')fs.rmSync(moved,{recursive:true,force:true});}
 });
});
test('async first complete inventory closes before the second begins and rejects between-observation mutation',async()=>asyncReadFixture({'leaf':'synthetic'},async state=>{
 const original=fs.open;let rootOpens=0,mutated=false;
 fs.open=(file,...args)=>{if(file===state.root&&++rootOpens===2){assert.equal(state.live.size,0);mutated=true;fs.writeFileSync(path.join(state.root,'leaf'),'changed');}return original(file,...args);};
 try{await assert.rejects(state.track(captureClientTreeAsync(state.root)),/CX_COMPLETE_TREE_INVENTORY_CHANGED/);assert.equal(mutated,true);assert.equal(rootOpens,2);}finally{fs.open=original;}
}));
test('async read failure stops new scheduling and refuses only after all held callbacks and FDs drain',async()=>asyncReadFixture(Object.fromEntries(Array.from({length:8},(_,i)=>['file-'+i,'synthetic'])),async state=>{
 state.hold=true;const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>state.pending.length===4,capture);const opened=state.records.length;
 const failure=Object.assign(new Error('SYNTHETIC_READ_REFUSAL'),{code:'EIO'});state.pending[0].deliver(failure);await immediate();await immediate();assert.equal(state.outcomes.get(capture).settled,false);assert.equal(state.records.length,opened);assert.equal(state.live.size,3);
 state.releaseAll();await assert.rejects(capture,error=>error===failure);assert.equal(state.live.size,0);assert.equal(state.records.length,opened);
}));
test('async synchronous read refusal releases its reserved credit and closes before returning',async()=>asyncReadFixture({'leaf':'synthetic'},async state=>{
 const failure=Error('SYNTHETIC_SYNCHRONOUS_READ');state.beforeRead=()=>{throw failure;};await assert.rejects(state.track(captureClientTreeAsync(state.root)),error=>error===failure);assert.equal(state.actualBytes,0);assert.equal(state.live.size,0);
}));
test('async close refusal preserves the original read error while closing independent pending jobs',async()=>asyncReadFixture({'a':'a','b':'b','c':'c','d':'d'},async state=>{
 state.hold=true;const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>state.pending.length===4,capture);const original=fs.closeSync,readError=Error('SYNTHETIC_PRIMARY_READ'),closeError=Error('SYNTHETIC_CLOSE');let injected=false;
 fs.closeSync=fd=>{const result=original(fd);if(!injected){injected=true;throw closeError;}return result;};
 try{state.pending[0].deliver(readError);await immediate();state.releaseAll();await assert.rejects(capture,error=>error instanceof AggregateError&&error.cause===readError&&error.errors.includes(closeError));assert.equal(state.live.size,0);assert.equal(injected,true);}finally{fs.closeSync=original;}
}));
test('async close failure is never retried and declares process cleanup uncertainty',async()=>asyncReadFixture({'a':'a','b':'b','c':'c','d':'d'},async state=>{
 state.hold=true;const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>state.pending.length===4,capture);const original=fs.closeSync,readError=Error('SYNTHETIC_PRIMARY_READ'),closeError=Error('SYNTHETIC_BEFORE_CLOSE');let selected,attempts=0;
 fs.closeSync=fd=>{if(selected===undefined){selected=fd;attempts++;throw closeError;}if(fd===selected)attempts++;return original(fd);};
 try{state.pending[0].deliver(readError);await immediate();state.releaseAll();await assert.rejects(capture,error=>error instanceof AggregateError&&error.cause===readError&&error.errors.includes(closeError)&&error.captureCleanupUncertain&&error.captureRequiresProcessExit);assert.equal(attempts,1);assert.equal(state.live.size,1);assert.doesNotThrow(()=>fs.fstatSync(selected));}
 finally{fs.closeSync=original;if(selected!==undefined&&state.live.has(selected))original(selected);}
 // Only this fault fixture knows that its intercepted close did not run.
 // Production cannot infer that lease and requires isolated process cleanup.
 assert.equal(state.live.size,0);
}));
test('async ambiguous close preserves a caller reopening the same file into the same descriptor number',async t=>asyncReadFixture({'a':'a','b':'b','c':'c','d':'d'},async state=>{
 state.hold=true;const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>state.pending.length===4,capture);const original=fs.closeSync,closeError=Object.assign(Error('SYNTHETIC_AFTER_CLOSE_REOPEN'),{code:'EIO'});let caller,callerFile,originalNumber,originalFrame,callerFrame,attempts=0;
 const frame=s=>['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'].map(key=>s[key]);
 fs.closeSync=fd=>{if(caller===undefined){const file=state.live.get(fd).file;callerFile=file;originalNumber=fd;originalFrame=frame(fs.fstatSync(fd,{bigint:true}));original(fd);caller=fs.openSync(file,fs.constants.O_RDONLY);callerFrame=frame(fs.fstatSync(caller,{bigint:true}));attempts++;assert.equal(caller,originalNumber);assert.deepEqual(callerFrame,originalFrame);throw closeError;}if(fd===caller)attempts++;return original(fd);};
 try{state.releaseAll();await assert.rejects(capture,error=>error instanceof AggregateError&&error.cause===closeError&&error.captureCleanupUncertain&&error.captureRequiresProcessExit);assert.equal(attempts,1);assert.equal(state.live.size,1);assert.doesNotThrow(()=>fs.fstatSync(caller));const byte=Buffer.alloc(1);assert.equal(fs.readSync(caller,byte),1);assert.equal(byte.toString(),({a:'a',b:'b',c:'c',d:'d'})[path.basename(callerFile)]);t.diagnostic(JSON.stringify({sameDescriptorNumber:caller===originalNumber,sameFullMetadata:true,callerDescriptorStillOpen:true,closeCalls:attempts,processCleanupRequired:true}));}
 finally{fs.closeSync=original;if(caller!==undefined&&state.live.has(caller))original(caller);}
}));
test('async directory iterator close uncertainty drains other leases without a retry',async()=>asyncReadFixture({'nested/leaf':'synthetic'},async state=>{
 const original=fs.opendirSync,error=Error('SYNTHETIC_DIRECTORY_CLOSE');let injected=false;
 fs.opendirSync=(file,...args)=>{const dir=original(file,...args);return{readSync:()=>dir.readSync(),closeSync:()=>{dir.closeSync();if(!injected){injected=true;throw error;}}};};
 try{await assert.rejects(state.track(captureClientTreeAsync(state.root)),value=>value instanceof AggregateError&&value.cause===error&&value.captureCleanupUncertain&&value.captureRequiresProcessExit);assert.equal(injected,true);assert.equal(state.live.size,0);assert.equal(state.activeDirs,0);}finally{fs.opendirSync=original;}
}));
test('async deadline stops queued work but does not return while an existing read callback is held',async()=>asyncReadFixture({'a':'a','b':'b','c':'c','d':'d','e':'e'},async state=>{
 const original=globalThis.performance;let clock=0;globalThis.performance={now:()=>clock};state.hold=true;const capture=state.track(captureClientTreeAsync(state.root));
 try{await state.reached(()=>state.pending.length===4,capture);clock=5001;state.pending[0].deliver();await immediate();await immediate();assert.equal(state.outcomes.get(capture).settled,false);assert.equal(state.records.filter(r=>r.file.endsWith('/e')).length,0);state.releaseAll();await assert.rejects(capture,/CX_COMPLETE_TREE_DEADLINE/);assert.equal(state.live.size,0);}finally{globalThis.performance=original;}
}));
test('async commitment codec and fsync share the original capture deadline',async()=>{
 for(const boundary of['codec','fsync'])await asyncReadFixture({'leaf':'synthetic'},async state=>{
  const original=globalThis.performance,byteLength=Buffer.byteLength,sync=fs.fsyncSync;let clock=0,entered=false;globalThis.performance={now:()=>clock};const home=temp(),audit=path.join(home,'manifest.json');
  Buffer.byteLength=(...args)=>{const value=byteLength(...args);if(boundary==='codec'){entered=true;clock=5001;}return value;};
  fs.fsyncSync=fd=>{const value=sync(fd);if(boundary==='fsync'){entered=true;clock=5001;}return value;};
  try{await assert.rejects(state.track(captureClientTreeInventoryAsync(state.root,audit)),/CX_COMPLETE_TREE_DEADLINE/);assert.equal(entered,true);assert.equal(state.live.size,0);}finally{globalThis.performance=original;Buffer.byteLength=byteLength;fs.fsyncSync=sync;fs.rmSync(home,{recursive:true,force:true});}
 });
});
test('async final root frame follows the last nested canonical directory observation',async()=>asyncReadFixture({'nested/leaf':'synthetic'},async state=>{
 const named=fs.lstatSync,real=fs.realpathSync,asyncReal=fs.realpath,nested=path.join(state.root,'nested');let nestedChecks=0,rootChecks=0,atInsert,inserted=false;
 const closed=()=>state.records.filter(x=>x.file.endsWith('/nested/leaf')&&x.closed).length;
 fs.lstatSync=(file,...args)=>{const value=named(file,...args);if(file===state.root&&closed()===2)rootChecks++;return value;};
 const observed=(file,value)=>{if(file===nested&&closed()===2&&++nestedChecks===2){atInsert=rootChecks;fs.writeFileSync(path.join(state.root,'late'),'late');inserted=true;}return value;};
 const resolve=(file,...args)=>observed(file,(real.native??real)(file,...args));
 const resolveAsync=(file,...args)=>{const callback=args.pop();return (asyncReal.native??asyncReal)(file,...args,(error,value)=>callback(error,error?value:observed(file,value)));};
 fs.realpath=(...args)=>resolveAsync(...args);if(asyncReal.native)fs.realpath.native=resolveAsync;
 fs.realpathSync=(...args)=>resolve(...args);if(real.native)fs.realpathSync.native=resolve;
 try{await assert.rejects(state.track(captureClientTreeAsync(state.root)),/CX_COMPLETE_TREE_FINAL_PATH_CHANGED/);assert.equal(inserted,true);assert.equal(closed(),2);assert.ok(rootChecks>atInsert);}finally{fs.lstatSync=named;fs.realpathSync=real;fs.realpath=asyncReal;}
}));
// Real filesystem operations complete first; only their callback delivery is held.
// Both callback constructors retain their original arguments/results and no
// fixture reads SDK data or invents a successful metadata observation.
async function asyncCanonicalFixture(state,operation){
 const original=fs.realpath,read=fs.read,open=fs.open,inside=file=>typeof file==='string'&&(file===state.root||file.startsWith(state.root+path.sep));
 const metadata={pending:[],calls:[],openPending:[],openCalls:[],active:0,peak:0,hold:false,openHold:false};state.metadata=metadata;
 const admitted=()=>{metadata.active++;metadata.peak=Math.max(metadata.peak,metadata.active);state.changed();};
 const canonical=(constructor,self,args)=>{
  const file=args[0];if(!inside(file))return Reflect.apply(constructor,self,args);
  admitted();const callback=args.at(-1);let completed=false;
  const deliver=(error,value)=>{assert.equal(completed,false);completed=true;metadata.active--;try{return callback(error,value);}finally{state.changed();}};
  args[args.length-1]=(error,value)=>{
   const entry={file,error,value,delivered:false,deliver:(override=error)=>{assert.equal(entry.delivered,false);entry.delivered=true;return deliver(override,value);}};
   metadata.calls.push(entry);try{if(metadata.hold===true||(typeof metadata.hold==='function'&&metadata.hold(entry)))metadata.pending.push(entry);else entry.deliver();}catch(error){if(!entry.delivered)entry.deliver(error);else throw error;}finally{state.changed();}
  };
  try{return Reflect.apply(constructor,self,args);}catch(error){if(!completed){completed=true;metadata.active--;}throw error;}
 };
 fs.realpath=function(...args){return canonical(original,this,args);};if(original.native)fs.realpath.native=function(...args){return canonical(original.native,this,args);};
 fs.open=function(file,...args){
  if(!inside(file))return Reflect.apply(open,this,[file,...args]);
  admitted();const callback=args.at(-1);let completed=false;
  const deliver=(error,fd)=>{assert.equal(completed,false);completed=true;metadata.active--;try{return callback(error,fd);}finally{state.changed();}};
  args[args.length-1]=(error,fd)=>{
   const entry={file,error,fd,delivered:false,deliver:(...overrides)=>{assert.equal(entry.delivered,false);entry.delivered=true;return deliver(overrides.length?overrides[0]:error,overrides.length>1?overrides[1]:fd);}};
   metadata.openCalls.push(entry);try{if(metadata.openHold===true||(typeof metadata.openHold==='function'&&metadata.openHold(entry)))metadata.openPending.push(entry);else entry.deliver();}catch(error){if(!entry.delivered)entry.deliver(error);else throw error;}finally{state.changed();}
  };
  try{return Reflect.apply(open,this,[file,...args]);}catch(error){if(!completed){completed=true;metadata.active--;state.changed();}throw error;}
 };
 fs.read=function(...args){
  if(!state.live.has(args[0]))return Reflect.apply(read,this,args);
  admitted();const callback=args.at(-1);let completed=false;
  args[args.length-1]=function(...values){assert.equal(completed,false);completed=true;metadata.active--;return Reflect.apply(callback,this,values);};
  try{return Reflect.apply(read,this,args);}catch(error){if(!completed){completed=true;metadata.active--;}throw error;}
 };
 metadata.releaseAll=()=>{metadata.hold=false;metadata.openHold=false;for(const entry of [...metadata.pending,...metadata.openPending])if(!entry.delivered)entry.deliver();};
 try{return await operation(metadata);}
 finally{metadata.releaseAll();await Promise.allSettled(state.promises);fs.realpath=original;fs.read=read;fs.open=open;assert.equal(metadata.active,0);}
}
test('async canonical and payload callbacks share four held jobs across both complete observations',async()=>asyncReadFixture(Object.fromEntries(Array.from({length:8},(_,i)=>['file-'+i,'synthetic-'+i])),async state=>asyncCanonicalFixture(state,async metadata=>{
 metadata.hold=true;const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>metadata.pending.length===4,capture);
 assert.equal(state.live.size,4);assert.equal(state.reads.length,0);assert.equal(metadata.active,4);assert.equal(metadata.peak,4);
 metadata.releaseAll();const tree=await capture;assert.equal(tree.complete,true);assert.equal(tree.observations,2);assert.equal(metadata.active,0);assert.ok(metadata.peak<=4);assert.ok(state.peakOwned<=4);assert.equal(state.live.size,0);
})));
test('async canonical leaf replacement after actual resolution refuses before the first byte',async()=>asyncReadFixture({'leaf':'original'},async state=>asyncCanonicalFixture(state,async metadata=>{
 metadata.hold=true;const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>metadata.pending.length===1,capture);
 const file=path.join(state.root,'leaf');assert.equal(metadata.pending[0].file,file);fs.renameSync(file,file+'-retained');fs.writeFileSync(file,'replacement');metadata.releaseAll();
 await assert.rejects(capture);assert.equal(state.reads.length,0);assert.equal(state.live.size,0);assert.equal(metadata.active,0);
})));
test('async canonical parent aliases inside or outside the captured root remain refused',async()=>{
 for(const kind of['internal','external-ancestor'])await asyncReadFixture({'outer/sdk/nested/leaf':'synthetic'},async state=>asyncCanonicalFixture(state,async metadata=>{
  const root=path.join(state.root,'outer/sdk'),parent=kind==='internal'?path.join(root,'nested'):path.join(state.root,'outer'),moved=parent+'-retained';metadata.hold=true;
  const capture=state.track(captureClientTreeAsync(root));await state.reached(()=>metadata.pending.length===1,capture);fs.renameSync(parent,moved);fs.symlinkSync(moved,parent);metadata.releaseAll();
  await assert.rejects(capture);assert.equal(state.live.size,0);assert.equal(metadata.active,0);if(kind==='internal')assert.equal(state.reads.length,0);
 }));
});
test('async read refusal drains other held canonical callbacks before returning',async()=>asyncReadFixture({'a':'a','b':'b','c':'c','d':'d','e':'e'},async state=>asyncCanonicalFixture(state,async metadata=>{
 state.hold=true;metadata.hold=entry=>!entry.file.endsWith('/a');const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>metadata.pending.length===3&&state.pending.length===1,capture);
 const opened=state.records.length,failure=Error('SYNTHETIC_PRIMARY_READ');state.pending[0].deliver(failure);await immediate();await immediate();assert.equal(state.outcomes.get(capture).settled,false);assert.equal(state.records.length,opened);assert.equal(metadata.active,3);
 metadata.releaseAll();state.releaseAll();await assert.rejects(capture,value=>value===failure);assert.equal(state.live.size,0);assert.equal(metadata.active,0);assert.equal(state.records.length,opened);
})));
test('async canonical deadline drains every held callback and descriptor before refusal',async()=>asyncReadFixture({'a':'a','b':'b','c':'c','d':'d','e':'e'},async state=>asyncCanonicalFixture(state,async metadata=>{
 const original=globalThis.performance;let clock=0;globalThis.performance={now:()=>clock};metadata.hold=true;const capture=state.track(captureClientTreeAsync(state.root));
 try{await state.reached(()=>metadata.pending.length===4,capture);clock=5001;metadata.pending[0].deliver();await immediate();await immediate();assert.equal(state.outcomes.get(capture).settled,false);assert.equal(metadata.active,3);assert.equal(state.reads.length,0);metadata.releaseAll();await assert.rejects(capture,/CX_COMPLETE_TREE_DEADLINE/);assert.equal(state.live.size,0);assert.equal(metadata.active,0);assert.equal(state.records.filter(row=>row.file.endsWith('/e')).length,0);}finally{globalThis.performance=original;}
})));
test('async final path mutation refuses after draining all final canonical workers',async()=>asyncReadFixture({'a':'a','b':'b','c':'c','d':'d'},async state=>asyncCanonicalFixture(state,async metadata=>{
 metadata.hold=()=>state.records.filter(row=>row.file===state.root).length===2&&state.live.size===0;const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>metadata.pending.length===4,capture);
 const selected=metadata.pending.find(entry=>entry.file.endsWith('/a'));assert.ok(selected);fs.appendFileSync(selected.file,'changed');selected.deliver();await immediate();await immediate();assert.equal(state.outcomes.get(capture).settled,false);assert.equal(metadata.active,3);metadata.releaseAll();
 await assert.rejects(capture,/CX_COMPLETE_TREE_FINAL_PATH_CHANGED/);assert.equal(state.live.size,0);assert.equal(metadata.active,0);assert.ok(metadata.peak<=4);
})));
test('async close ambiguity preserves a same-number caller while draining held canonical leases',async t=>asyncReadFixture({'a':'a','b':'b','c':'c','d':'d'},async state=>asyncCanonicalFixture(state,async metadata=>{
 metadata.hold=true;const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>metadata.pending.length===4,capture);
 const close=fs.closeSync,failure=Object.assign(Error('SYNTHETIC_AMBIGUOUS_CLOSE'),{code:'EIO'});let caller,number,attempts=0,callerFile;
 fs.closeSync=fd=>{if(caller===undefined){callerFile=state.live.get(fd).file;number=fd;const before=fs.fstatSync(fd,{bigint:true});close(fd);caller=fs.openSync(callerFile,fs.constants.O_RDONLY);const after=fs.fstatSync(caller,{bigint:true});for(const field of['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'])assert.equal(after[field],before[field]);assert.equal(caller,number);attempts++;throw failure;}if(fd===caller)attempts++;return close(fd);};
 try{metadata.hold=entry=>!entry.file.endsWith('/a');metadata.pending.find(entry=>entry.file.endsWith('/a')).deliver();await state.reached(()=>caller!==undefined,capture);assert.equal(state.outcomes.get(capture).settled,false);assert.equal(metadata.active,3);assert.doesNotThrow(()=>fs.fstatSync(caller));metadata.releaseAll();await assert.rejects(capture,error=>error instanceof AggregateError&&error.cause===failure&&error.captureCleanupUncertain&&error.captureRequiresProcessExit);assert.equal(attempts,1);assert.doesNotThrow(()=>fs.fstatSync(caller));assert.equal(state.live.size,1);t.diagnostic(JSON.stringify({sameNumber:caller===number,fullMetadataEqual:true,callerLeaseOpen:true,canonicalCallbacksDrained:metadata.active===0}));}
 finally{fs.closeSync=close;if(caller!==undefined&&state.live.has(caller))close(caller);}
})));
test('async canonical constructor refusal closes its admitted descriptor without a byte read',async()=>asyncReadFixture({'leaf':'synthetic'},async state=>{
 const original=fs.realpath,failure=Error('SYNTHETIC_CANONICAL_CONSTRUCTOR');fs.realpath=()=>{throw failure;};if(original.native)fs.realpath.native=fs.realpath;
 try{await assert.rejects(state.track(captureClientTreeAsync(state.root)),error=>error===failure);assert.equal(state.reads.length,0);assert.equal(state.live.size,0);}finally{fs.realpath=original;}
}));

test('async traversal reserves its open alongside three file jobs within four total operations',async()=>asyncReadFixture({'a':'a','b':'b','c':'c','d':'d','e':'e'},async state=>asyncCanonicalFixture(state,async metadata=>{
 metadata.hold=true;metadata.openHold=entry=>entry.file.endsWith('/d');const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>metadata.pending.length===3&&metadata.openPending.length===1,capture);
 assert.equal(state.live.size,4);assert.equal(metadata.active,4);assert.equal(metadata.peak,4);assert.equal(state.records.filter(row=>row.file.endsWith('/e')).length,0);metadata.releaseAll();const tree=await capture;assert.equal(tree.complete,true);assert.equal(tree.chargedBytes,10);assert.equal(metadata.active,0);assert.ok(metadata.peak<=4);assert.ok(state.peakOwned<=4);
})));
test('async successful open arriving after deadline enters one owned close before refusal',async()=>asyncReadFixture({'leaf':'synthetic'},async state=>asyncCanonicalFixture(state,async metadata=>{
 const original=globalThis.performance;let clock=0;globalThis.performance={now:()=>clock};metadata.openHold=entry=>entry.file.endsWith('/leaf');const capture=state.track(captureClientTreeAsync(state.root));
 try{await state.reached(()=>metadata.openPending.length===1,capture);const entry=metadata.openPending[0];assert.ok(Number.isInteger(entry.fd));clock=5001;await immediate();assert.equal(state.outcomes.get(capture).settled,false);assert.equal(state.live.size,1);entry.deliver();await assert.rejects(capture,/CX_COMPLETE_TREE_DEADLINE/);assert.equal(state.reads.length,0);assert.equal(state.live.size,0);assert.equal(metadata.active,0);assert.equal(state.records.filter(row=>row.fd===entry.fd&&!row.closed).length,0);}finally{globalThis.performance=original;}
})));
test('async read failure waits for a successful pending open and closes its later lease',async()=>asyncReadFixture({'a':'a','b':'b','c':'c','d':'d','e':'e'},async state=>asyncCanonicalFixture(state,async metadata=>{
 state.hold=true;metadata.openHold=entry=>entry.file.endsWith('/d');const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>metadata.openPending.length===1&&state.pending.length===3,capture);
 const opened=state.records.length,failure=Error('SYNTHETIC_READ_WITH_PENDING_OPEN');state.pending[0].deliver(failure);await immediate();await immediate();assert.equal(state.outcomes.get(capture).settled,false);assert.equal(state.records.length,opened);const entry=metadata.openPending[0];assert.ok(state.live.has(entry.fd));entry.deliver();await immediate();await immediate();assert.equal(state.live.has(entry.fd),false);assert.equal(state.outcomes.get(capture).settled,false);state.releaseAll();await assert.rejects(capture,error=>error===failure);assert.equal(state.live.size,0);assert.equal(metadata.active,0);assert.equal(state.records.length,opened);
})));
test('async opened lease stays unread across a leaf or parent replacement before callback delivery',async()=>{
 for(const kind of['leaf','parent'])await asyncReadFixture({'nested/leaf':'original'},async state=>asyncCanonicalFixture(state,async metadata=>{
  metadata.openHold=entry=>entry.file.endsWith('/leaf');const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>metadata.openPending.length===1,capture);const entry=metadata.openPending[0],parent=path.dirname(entry.file);
  if(kind==='leaf'){fs.renameSync(entry.file,entry.file+'-retained');fs.writeFileSync(entry.file,'replacement');}else{fs.renameSync(parent,parent+'-retained');fs.symlinkSync(parent+'-retained',parent);}entry.deliver();await assert.rejects(capture);assert.equal(state.reads.length,0);assert.equal(state.live.size,0);assert.equal(metadata.active,0);
 }));
});
test('async late-open cleanup never retries a close that reassigns the same-number caller lease',async t=>asyncReadFixture({'leaf':'synthetic'},async state=>asyncCanonicalFixture(state,async metadata=>{
 const originalClock=globalThis.performance,close=fs.closeSync;let clock=0;globalThis.performance={now:()=>clock};metadata.openHold=entry=>entry.file.endsWith('/leaf');const capture=state.track(captureClientTreeAsync(state.root));let caller,entry,attempts=0;
 try{await state.reached(()=>metadata.openPending.length===1,capture);entry=metadata.openPending[0];const before=fs.fstatSync(entry.fd,{bigint:true}),failure=Object.assign(Error('SYNTHETIC_LATE_OPEN_CLOSE_EIO'),{code:'EIO'});
  fs.closeSync=fd=>{if(fd===entry.fd&&caller===undefined){close(fd);caller=fs.openSync(entry.file,fs.constants.O_RDONLY);assert.equal(caller,fd);const after=fs.fstatSync(caller,{bigint:true});for(const field of['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'])assert.equal(after[field],before[field]);attempts++;throw failure;}if(fd===caller)attempts++;return close(fd);};
  clock=5001;entry.deliver();await assert.rejects(capture,error=>error instanceof AggregateError&&/CX_COMPLETE_TREE_DEADLINE/.test(error.cause.message)&&error.errors.includes(failure)&&error.captureCleanupUncertain&&error.captureRequiresProcessExit);assert.equal(attempts,1);assert.doesNotThrow(()=>fs.fstatSync(caller));assert.equal(state.live.size,1);assert.equal(state.reads.length,0);assert.equal(metadata.active,0);t.diagnostic(JSON.stringify({sameNumber:caller===entry.fd,sameFullMetadata:true,callerDescriptorOpen:true,closeCalls:attempts,processExitRequired:true}));
 }finally{globalThis.performance=originalClock;fs.closeSync=close;if(caller!==undefined&&state.live.has(caller))close(caller);}
})));
test('async malformed error acknowledgement never closes an unrelated caller descriptor',async()=>asyncReadFixture({'leaf':'synthetic'},async state=>asyncCanonicalFixture(state,async metadata=>{
 metadata.openHold=entry=>entry.file.endsWith('/leaf');const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>metadata.openPending.length===1,capture);const entry=metadata.openPending[0],home=temp(),file=path.join(home,'caller');fs.writeFileSync(file,'caller');const caller=fs.openSync(file,fs.constants.O_RDONLY),failure=Error('SYNTHETIC_MALFORMED_OPEN_ERROR');
 try{entry.deliver(failure,caller);await assert.rejects(capture,error=>error instanceof AggregateError&&error.cause===failure&&error.captureCleanupUncertain&&error.captureRequiresProcessExit);assert.doesNotThrow(()=>fs.fstatSync(caller));assert.doesNotThrow(()=>fs.fstatSync(entry.fd));assert.equal(state.reads.length,0);assert.equal(state.live.size,1);assert.equal(metadata.active,0);}
 finally{fs.closeSync(caller);if(state.live.has(entry.fd))fs.closeSync(entry.fd);fs.rmSync(home,{recursive:true,force:true});}
 // Only this fixture knows the successful underlying descriptor. Production
 // sees a nonconforming acknowledgement and requires isolated process exit.
})));
test('async malformed successful open acknowledgements remain cleanup-uncertain with zero bytes',async()=>{
 for(const value of[undefined,-1,'17'])await asyncReadFixture({'leaf':'synthetic'},async state=>asyncCanonicalFixture(state,async metadata=>{
  metadata.openHold=entry=>entry.file.endsWith('/leaf');const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>metadata.openPending.length===1,capture);const entry=metadata.openPending[0];
  try{entry.deliver(null,value);await assert.rejects(capture,error=>error instanceof AggregateError&&/CX_CAPTURE_OPEN_ACK_UNCERTAIN/.test(error.cause.message)&&error.captureCleanupUncertain&&error.captureRequiresProcessExit);assert.equal(state.live.size,1);assert.equal(state.reads.length,0);assert.equal(metadata.active,0);assert.doesNotThrow(()=>fs.fstatSync(entry.fd));}
  finally{if(state.live.has(entry.fd))fs.closeSync(entry.fd);}
 }));
});
test('async open constructor ambiguity refuses before bytes and requires isolated process cleanup',async()=>asyncReadFixture({'leaf':'synthetic'},async state=>{
 const open=fs.open,failure=Error('SYNTHETIC_OPEN_CONSTRUCTOR_AMBIGUITY');let dispatched=0;
 fs.open=(file,...args)=>{if(file===path.join(state.root,'leaf'))throw failure;dispatched++;return open(file,...args);};
 try{await assert.rejects(state.track(captureClientTreeAsync(state.root)),error=>error instanceof AggregateError&&error.cause===failure&&error.captureCleanupUncertain&&error.captureRequiresProcessExit);assert.equal(dispatched,1);assert.equal(state.reads.length,0);assert.equal(state.live.size,0);}finally{fs.open=open;}
}));

test('async safe numeric parent identities retain every field before and after payload reads',async()=>{
 for(const point of['before','after'])for(const field of['dev','ino','uid','gid','mode'])await asyncReadFixture({'nested/leaf':'synthetic'},async state=>{
  const named=fs.lstatSync,parent=path.join(state.root,'nested');let consumed=false,changed=false;state.afterRead=()=>{consumed=true;};
  fs.lstatSync=(file,...args)=>{const value=named(file,...args);if(file===parent&&!args[0]?.bigint&&!changed&&(point==='before'||consumed)){changed=true;return new Proxy(value,{get(target,key){return key===field?Reflect.get(target,key)+1:Reflect.get(target,key);}});}return value;};
  try{await assert.rejects(state.track(captureClientTreeAsync(state.root)),/CX_TREE_PARENT_IDENTITY_CHANGED/);assert.equal(changed,true);if(point==='before')assert.equal(state.reads.length,0);else assert.ok(state.actualBytes>0);assert.equal(state.live.size,0);}finally{fs.lstatSync=named;}
 });
});
test('async unsafe observed numeric parent identities refuse without a BigInt retry',async()=>{
 for(const unsafe of[Number.MAX_SAFE_INTEGER+1,NaN,Infinity,1.5,'17',17n])await asyncReadFixture({'nested/leaf':'synthetic'},async state=>{
  const named=fs.lstatSync,parent=path.join(state.root,'nested');let changed=false,retried=false;
  fs.lstatSync=(file,...args)=>{const value=named(file,...args);if(file===parent){if(changed&&args[0]?.bigint)retried=true;if(!args[0]?.bigint&&!changed){changed=true;return new Proxy(value,{get(target,key){return key==='ino'?unsafe:Reflect.get(target,key);}});}}return value;};
  try{await assert.rejects(state.track(captureClientTreeAsync(state.root)),/CX_TREE_PARENT_IDENTITY_UNSAFE/);assert.equal(changed,true);assert.equal(retried,false);assert.equal(state.reads.length,0);assert.equal(state.live.size,0);}finally{fs.lstatSync=named;}
 });
});
test('async unsafe admitted BigInt parent identities select the exact BigInt reader before observation',async()=>asyncReadFixture({'nested/leaf':'synthetic'},async state=>{
 const named=fs.lstatSync,stat=fs.fstatSync,parent=path.join(state.root,'nested'),unsafe=BigInt(Number.MAX_SAFE_INTEGER)+1n;let numericReads=0,bigintReads=0;
 const model=value=>new Proxy(value,{get(target,key){return key==='ino'?unsafe:Reflect.get(target,key);}});
 fs.fstatSync=(fd,...args)=>{const value=stat(fd,...args);return state.live.get(fd)?.file===parent&&args[0]?.bigint?model(value):value;};
 fs.lstatSync=(file,...args)=>{const value=named(file,...args);if(file===parent){if(args[0]?.bigint){bigintReads++;return model(value);}numericReads++;}return value;};
 try{const tree=await state.track(captureClientTreeAsync(state.root));assert.equal(tree.complete,true);assert.equal(tree.entries.find(row=>row.path==='nested').metadata.ino,String(unsafe));assert.equal(numericReads,0);assert.ok(bigintReads>0);assert.equal(state.live.size,0);}finally{fs.lstatSync=named;fs.fstatSync=stat;}
 // The unsafe inode is a modeled API boundary, not a claim about this filesystem.
}));
test('async numeric parent baselines retain frozen primitive values instead of mutable Stats getters',async()=>asyncReadFixture({'nested/leaf':'synthetic'},async state=>{
 const expected=captureClientTree(state.root),named=fs.lstatSync,stat=fs.fstatSync,parent=path.join(state.root,'nested');let repeated=0,numericReads=0,objects=0;
 const snapshot=value=>{let reads=0;objects++;return new Proxy(value,{get(target,key){if(key==='ino'){reads++;if(reads>1)repeated++;return Reflect.get(target,key)+(reads>1?1n:0n);}return Reflect.get(target,key);}});};
 fs.fstatSync=(fd,...args)=>{const value=stat(fd,...args);return state.live.get(fd)?.file===parent&&args[0]?.bigint?snapshot(value):value;};
 fs.lstatSync=(file,...args)=>{const value=named(file,...args);if(file===parent){if(args[0]?.bigint)return snapshot(value);numericReads++;}return value;};
 try{const tree=await state.track(captureClientTreeAsync(state.root));assert.deepEqual(tree,expected);assert.equal(repeated,0);assert.ok(numericReads>0);assert.ok(objects>0);assert.equal(state.live.size,0);}finally{fs.lstatSync=named;fs.fstatSync=stat;}
}));

test('async frozen parent paths retain the exact live constructor count for every ancestor',async()=>asyncReadFixture({'a/b/one':'one','a/c/two':'two','root-leaf':'three'},async state=>{
 const named=fs.lstatSync,observed=new Map();fs.lstatSync=(file,...args)=>{if((file===state.root||file.startsWith(state.root+path.sep))&&!args[0]?.bigint)observed.set(file,(observed.get(file)??0)+1);return named(file,...args);};
 try{const tree=await state.track(captureClientTreeAsync(state.root)),expected=new Map();for(const row of tree.entries){if(!row.path||row.kind==='symlink')continue;for(let parent=path.dirname(path.join(state.root,row.path));;parent=path.dirname(parent)){expected.set(parent,(expected.get(parent)??0)+(row.kind==='file'?4:2));if(parent===state.root)break;}}assert.deepEqual([...observed].sort(),[...expected].sort());assert.equal(tree.chargedEntries,tree.entries.length*2);assert.equal(state.live.size,0);}finally{fs.lstatSync=named;}
}));
test('async live parent field getters are consumed once in original identity order',async()=>asyncReadFixture({'a/b/leaf':'synthetic'},async state=>{
 const named=fs.lstatSync,frames=[],keys=['dev','ino','uid','gid','mode'];fs.lstatSync=(file,...args)=>{const value=named(file,...args);if((file===state.root||file.startsWith(state.root+path.sep))&&!args[0]?.bigint){const seen=[],counts=new Map();frames.push(seen);return new Proxy(value,{get(target,key){if(keys.includes(key)){seen.push(key);const n=(counts.get(key)??0)+1;counts.set(key,n);return Reflect.get(target,key)+(n>1?1:0);}const result=Reflect.get(target,key);return typeof result==='function'?result.bind(target):result;}});}return value;};
 try{const tree=await state.track(captureClientTreeAsync(state.root));assert.equal(tree.complete,true);assert.ok(frames.length>0);for(const frame of frames)assert.deepEqual(frame,keys);assert.equal(state.live.size,0);}finally{fs.lstatSync=named;}
}));
test('async parent fast comparisons retain signed zero and unsafe before mismatch diagnostics',async()=>{
 for(const kind of['zero-positive','zero-negative','unsafe','earlier-mismatch'])await asyncReadFixture({'nested/leaf':'synthetic'},async state=>{
  const named=fs.lstatSync,stat=fs.fstatSync,parent=path.join(state.root,'nested');let firstFields;
  const baseline=value=>new Proxy(value,{get(target,key){if(key==='ino')return 0n;const result=Reflect.get(target,key);return typeof result==='function'?result.bind(target):result;}});
  fs.fstatSync=(fd,...args)=>{const value=stat(fd,...args);return state.live.get(fd)?.file===parent&&args[0]?.bigint?baseline(value):value;};
  fs.lstatSync=(file,...args)=>{const value=named(file,...args);if(file!==parent)return value;if(args[0]?.bigint)return baseline(value);const seen=[];firstFields??=seen;return new Proxy(value,{get(target,key){if(['dev','ino','uid','gid','mode'].includes(key))seen.push(key);if(key==='dev'&&kind==='earlier-mismatch')return target.dev+1;if(key==='ino')return kind==='zero-negative'?-0:kind==='unsafe'||kind==='earlier-mismatch'?NaN:0;const result=Reflect.get(target,key);return typeof result==='function'?result.bind(target):result;}});};
  try{const capture=state.track(captureClientTreeAsync(state.root));if(kind==='zero-positive'){assert.equal((await capture).complete,true);assert.deepEqual(firstFields,['dev','ino','uid','gid','mode']);}else{await assert.rejects(capture,kind==='unsafe'?/CX_TREE_PARENT_IDENTITY_UNSAFE/:/CX_TREE_PARENT_IDENTITY_CHANGED/);assert.deepEqual(firstFields,kind==='earlier-mismatch'?['dev']:['dev','ino']);assert.equal(state.reads.length,0);}assert.equal(state.live.size,0);}finally{fs.lstatSync=named;fs.fstatSync=stat;}
  // Zero inode values are modeled metadata API boundaries, not actual FS facts.
 });
});
test('async frozen grandparent chains observe replacement and same held leaf symlinks before bytes',async()=>{
 for(const kind of['replacement','symlink'])await asyncReadFixture({'a/b/leaf':'synthetic'},async state=>asyncCanonicalFixture(state,async metadata=>{
  metadata.hold=true;const capture=state.track(captureClientTreeAsync(state.root));await state.reached(()=>metadata.pending.length===1,capture);const parent=path.join(state.root,'a'),moved=parent+'-retained';assert.equal(metadata.pending[0].file,path.join(parent,'b/leaf'));fs.renameSync(parent,moved);if(kind==='symlink')fs.symlinkSync(moved,parent);else{fs.mkdirSync(parent);fs.renameSync(path.join(moved,'b'),path.join(parent,'b'));}metadata.releaseAll();await assert.rejects(capture);assert.equal(state.reads.length,0);assert.equal(state.live.size,0);assert.equal(metadata.active,0);
 }));
});

test('fixture barrier waits for an actual held read across 256 unrelated immediate turns',async()=>asyncReadFixture({'leaf':'synthetic'},async state=>{
 const read=fs.read;let held,blocked=false,delivered=false;
 fs.read=function(...args){const callback=args.at(-1);args[args.length-1]=function(...values){if(!blocked){blocked=true;held=()=>{delivered=true;try{return Reflect.apply(callback,this,values);}finally{state.changed();}};state.changed();}else return Reflect.apply(callback,this,values);};return Reflect.apply(read,this,args);};
 const capture=state.track(captureClientTreeAsync(state.root));let barrier;
 try{await state.reached(()=>typeof held==='function',capture);barrier=state.reached(()=>delivered,capture);let settled=false;barrier.then(()=>{settled=true;},()=>{settled=true;});for(let n=0;n<256;n++)await immediate();assert.equal(settled,false);assert.equal(delivered,false);held();await barrier;assert.equal(delivered,true);assert.equal((await capture).complete,true);assert.deepEqual(state.barrierState(),{waiters:0,timers:0});}
 finally{if(held&&!delivered)held();if(barrier)await Promise.allSettled([barrier]);await Promise.allSettled([capture]);fs.read=read;}
}));
test('fixture barrier surfaces a completed request exception or missing event before timeout',async()=>asyncReadFixture({},async state=>{
 const failure=Error('SYNTHETIC_REQUEST_EXCEPTION');const rejected=state.track(Promise.reject(failure));await assert.rejects(state.reached(()=>false,rejected),error=>error===failure);
 const completed=state.track(Promise.resolve('completed'));await assert.rejects(state.reached(()=>false,completed),/ASYNC_CONTROL_COMPLETED_BEFORE_BARRIER/);
 await state.reached(()=>true,completed);assert.deepEqual(state.barrierState(),{waiters:0,timers:0});
}));
test('fixture barrier reconciles the final actual snapshot at its unchanged 1000ms boundary',async()=>asyncReadFixture({},async state=>{
 const gate=deferred(),capture=state.track(gate.promise),now=performance.now.bind(performance),start=now();let checks=0;
 try{await state.reached(()=>{checks++;return now()-start>=1000;},capture);assert.ok(checks<=257);assert.equal(state.outcomes.get(capture).settled,false);assert.deepEqual(state.barrierState(),{waiters:0,timers:0});}
 finally{gate.resolve();await capture;}
}));
test('fixture barrier retains the pending deadline and removes its waiter and timer',async()=>asyncReadFixture({},async state=>{
 const gate=deferred(),capture=state.track(gate.promise),now=performance.now.bind(performance),start=now();
 try{await assert.rejects(state.reached(()=>false,capture),/ASYNC_CONTROL_BARRIER_NOT_REACHED/);assert.ok(now()-start>=1000);assert.equal(state.outcomes.get(capture).settled,false);assert.deepEqual(state.barrierState(),{waiters:0,timers:0});}
 finally{gate.resolve();await capture;}
}));

test('actual async public producer waits for complete capture and retains refusal before acknowledgment',async()=>{
 const {prepareClientRuntimeInventoryAsync}=await import('./prepare-client-extensions.mjs');
 for(const outcome of['success','read-refusal','source-drift'])await asyncReadFixture({'entry.mjs':'synthetic'},async state=>{
  const home=temp(),audit=path.join(home,'audit.json'),output=path.join(home,'inventory.json');let snapshots=0;
  const q={kind:'prepare-native-client-runtime-inventory',preparedOnly:true,purpose:'appium',platform:'ios',root:state.root,appiumEntry:path.join(state.root,'entry.mjs'),output,manifestOutput:audit};
  state.hold=true;const promise=state.track(prepareClientRuntimeInventoryAsync(q,{snapshot:()=>{snapshots++;return{sourceDirty:false,version:outcome==='source-drift'&&snapshots===2?'changed':'original'};}}));
  try{await state.reached(()=>state.pending.length===1,promise);assert.equal(fs.existsSync(audit),false);assert.equal(fs.existsSync(output),false);
   if(outcome==='read-refusal'){const error=Error('SYNTHETIC_CAPTURE_REFUSAL');state.pending[0].deliver(error);state.releaseAll();await assert.rejects(promise,value=>value===error);assert.equal(fs.existsSync(audit),false);}
   else{state.releaseAll();if(outcome==='source-drift')await assert.rejects(promise);else{const result=await promise;assert.equal(result.inventory.tree.observations,2);assert.equal(result.privateReads,0);assert.equal(result.nativeActions,0);assert.equal(result.inventory.appiumEntry,q.appiumEntry);assert.equal(fs.existsSync(audit),true);}}
   assert.equal(fs.existsSync(output),false);assert.equal(state.live.size,0);
  }finally{state.releaseAll();await Promise.allSettled([promise]);fs.rmSync(home,{recursive:true,force:true});}
 });
});
test('actual async Appium admission dispatches no command until fresh capture succeeds',async()=>{
 for(const outcome of['success','changed'])await asyncReadFixture({'entry.mjs':'synthetic'},async state=>{
  const home=temp(),audit=path.join(home,'audit.json'),inventory=runtimeEnvelope(captureClientTreeInventory(state.root,audit),'appium'),ref={path:'/synthetic',sha256:'a'.repeat(64)},q={platform:'ios',appiumUrl:'http://127.0.0.1:4727',appiumServerEvidence:ref,appiumInventoryEvidence:ref},observed='synthetic-start '+inventory.appiumEntry;
  const server={observed:true,owned:true,platform:'ios',pid:10,inventoryEvidence:ref,appiumUrl:q.appiumUrl,uid:process.getuid(),utcStartAndCommandSha256:sha(observed)};let reads=0,commands=0,changed=false;fs.unlinkSync(audit);
  const command=(_file,args)=>{commands++;return args.includes('uid=')?String(process.getuid()):args.includes('-Fpfn')?'p10\nf1\nn127.0.0.1:4727\n':observed;};
  if(outcome==='changed')state.afterRead=()=>{if(!changed){changed=true;fs.appendFileSync(path.join(state.root,'entry.mjs'),'change');}};
  state.hold=true;const promise=state.track(admitClientServerAsync(q,{read:()=>++reads===1?server:inventory,command}));
  try{await state.reached(()=>state.pending.length===1,promise);assert.equal(commands,0);assert.equal(state.outcomes.get(promise).settled,false);state.releaseAll();if(outcome==='success'){assert.equal((await promise).inventory,inventory);assert.equal(commands,3);}else{await assert.rejects(promise);assert.equal(commands,0);}assert.equal(state.live.size,0);}
  finally{state.releaseAll();await Promise.allSettled([promise]);fs.rmSync(home,{recursive:true,force:true});}
 });
});
test('async admission awaits the actual server hook before runtime recapture or protected readers',async()=>{
 const f=clientAdmissionPacket(),gate=deferred(),tree=f.io.tree;let servers=0,trees=0;f.io.server=()=>++servers===1?gate.promise:{};f.io.tree=(...args)=>{trees++;return tree(...args);};
 const promise=admitClientExtensions(f.q,f.io);let settled=false;promise.then(()=>{settled=true;},()=>{settled=true;});
 try{await immediate();assert.equal(servers,1);assert.equal(trees,0);assert.equal(f.reads(),0);assert.equal(settled,false);gate.resolve({});const result=await promise;assert.equal(f.reads(),2);assert.equal(trees,1);assert.equal(servers,3);for(const member of result.members)for(const key of Object.keys(member.value))member.value[key]=undefined;}
 finally{gate.resolve({});await Promise.allSettled([promise]);}
});
test('async admission awaits runtime success or rejection before GET or private entry',async()=>{
 for(const outcome of['success','refused']){
  const f=clientAdmissionPacket(),gate=deferred(),read=f.io.getJson;let gets=0;f.io.tree=()=>gate.promise;f.io.getJson=(...args)=>{gets++;return read(...args);};const promise=admitClientExtensions(f.q,f.io);let settled=false;promise.then(()=>{settled=true;},()=>{settled=true;});
  try{await immediate();assert.equal(f.reads(),0);assert.equal(gets,0);assert.equal(settled,false);if(outcome==='refused'){const error=Error('SYNTHETIC_RUNTIME_REFUSED');gate.reject(error);await assert.rejects(promise,value=>value===error);assert.equal(f.reads(),0);assert.equal(gets,0);}else{gate.resolve(structuredClone(f.values.get(f.q.clientRuntimeInventoryEvidence.path).tree));const result=await promise;assert.equal(f.reads(),2);for(const member of result.members)for(const key of Object.keys(member.value))member.value[key]=undefined;}}
  finally{gate.resolve({});await Promise.allSettled([promise]);}
 }
});
test('each protected reader awaits its current server guard and prior transferred data clears on refusal',async()=>{
 const f=clientAdmissionPacket(),gate=deferred();let servers=0;f.io.server=()=>++servers===3?gate.promise:{};const promise=admitClientExtensions(f.q,f.io);let settled=false;promise.then(()=>{settled=true;},()=>{settled=true;});
 try{for(let n=0;n<128&&servers<3;n++){if(settled)await promise;await immediate();}assert.equal(servers,3);assert.equal(f.reads(),1);assert.equal(settled,false);const error=Error('SYNTHETIC_CURRENT_SERVER_REFUSAL');gate.reject(error);await assert.rejects(promise,value=>value===error);assert.equal(f.reads(),1);assert.ok(Object.values(f.loadedValues[0]).every(value=>value===undefined));}
 finally{gate.resolve({});await Promise.allSettled([promise]);}
});
test('run preflight waits before control construction and clears retained values after rejected guard',async t=>{
 const f=admittedCleanupFixture(t),gate=deferred();let controls=0;f.admitted.currentGuard=()=>gate.promise;f.dependencies.controls=async()=>{controls++;throw Error('MUST_NOT_CONSTRUCT');};
 const promise=runClientExtensions(f.q,f.dependencies);let settled=false;promise.then(()=>{settled=true;},()=>{settled=true;});
 try{await immediate();assert.equal(controls,0);assert.equal(settled,false);gate.reject(Error('SYNTHETIC_ASYNC_PREFLIGHT_REFUSAL'));const summary=await promise;assert.notEqual(summary.status,'passed');assert.equal(summary.actualNativeExecution,false);assert.equal(controls,0);f.verify();}
 finally{gate.resolve({});await Promise.allSettled([promise]);}
});
function asyncLiveFixture(t,server){
 const f=admittedCleanupFixture(t);f.q.leaseDeadlineMs=4000000;f.admitted.installed={};f.admitted.currentGuard=async()=>{};
 Object.assign(f.dependencies,{harness:()=>f.q.expectedHarnessFingerprint,snapshot:()=>f.admitted.source,installed:()=>f.admitted.installed,server,now:()=>0,controls:async()=>({closeRun:async()=>({allOwnedControlsClosed:true,authorityCleared:true}),dispose:()=>{}})});return f;
}
test('actual runner awaits live server recapture before its first native session attempt',async t=>{
 const gate=deferred();let servers=0;const f=asyncLiveFixture(t,()=>++servers===1?gate.promise:{}),promise=runClientExtensions(f.q,f.dependencies);let settled=false;promise.then(()=>{settled=true;},()=>{settled=true;});
 try{await immediate();assert.equal(servers,1);assert.equal(settled,false);assert.equal(fs.existsSync(path.join(f.q.report,'summary.json')),false);gate.reject(Error('SYNTHETIC_LIVE_RECAPTURE_REFUSAL'));const summary=await promise;assert.equal(summary.actualNativeExecution,false);assert.notEqual(summary.status,'passed');assert.equal(servers,2);f.verify();}
 finally{gate.resolve({});await Promise.allSettled([promise]);}
});
test('actual runner awaits its final live guard before summary publication and value cleanup',async t=>{
 const gate=deferred();let servers=0;const f=asyncLiveFixture(t,()=>{if(++servers===1)throw Error('SYNTHETIC_SETUP_STOP');return gate.promise;}),promise=runClientExtensions(f.q,f.dependencies);let settled=false;promise.then(()=>{settled=true;},()=>{settled=true;});
 try{for(let n=0;n<128&&servers<2;n++){if(settled)await promise;await immediate();}assert.equal(servers,2);assert.equal(settled,false);assert.equal(fs.existsSync(path.join(f.q.report,'summary.json')),false);gate.reject(Error('SYNTHETIC_FINAL_GUARD_REFUSAL'));const summary=await promise;assert.notEqual(summary.status,'passed');assert.equal(summary.actualNativeExecution,false);f.verify();}
 finally{gate.resolve({});await Promise.allSettled([promise]);}
});
test('actual runner quarantines uncertain runtime cleanup before any later guard or native attempt',async t=>{
 const error=Object.assign(Error('SYNTHETIC_CAPTURE_CLEANUP_UNCERTAIN'),{captureCleanupUncertain:true,captureRequiresProcessExit:true});let servers=0;const f=asyncLiveFixture(t,async()=>{servers++;throw error;});
 const summary=await runClientExtensions(f.q,f.dependencies);assert.notEqual(summary.status,'passed');assert.equal(summary.actualNativeExecution,false);assert.equal(summary.captureCleanupUncertain,true);assert.equal(summary.captureRequiresProcessExit,true);assert.equal(servers,1);f.verify();
});
test('async server legacy, hash-only and incoherent evidence refuses before commands or payload reads',async()=>asyncReadFixture({'entry.mjs':'synthetic'},async state=>{
 const home=temp(),audit=path.join(home,'manifest.json'),good=runtimeEnvelope(captureClientTreeInventory(state.root,audit),'appium'),ref={path:'/synthetic',sha256:'a'.repeat(64)},q={platform:'ios',appiumUrl:'http://127.0.0.1:4727',appiumServerEvidence:ref,appiumInventoryEvidence:ref},server={observed:true,owned:true,platform:'ios',pid:10,inventoryEvidence:ref,appiumUrl:q.appiumUrl};
 try{for(const tree of[captureClientTree(state.root),{sha256:good.tree.manifest.sha256},{...good.tree,observations:1},{...good.tree,chargedBytes:good.tree.chargedBytes+1}]){let reads=0,commands=0;const before=state.reads.length;await assert.rejects(state.track(admitClientServerAsync(q,{read:()=>++reads===1?server:{...good,tree},command:()=>{commands++;throw Error('MUST_NOT_DISPATCH');}})));assert.equal(commands,0);assert.equal(state.reads.length,before);}}
 finally{fs.rmSync(home,{recursive:true,force:true});}
}));
