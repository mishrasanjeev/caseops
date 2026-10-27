import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readV1Member } from './v1-workflows-credentials.mjs';
const ROOT=path.resolve(fileURLToPath(new URL('../../../',import.meta.url)));
import { QP,expectedQueue,validateDataset,hash,reference } from './queue-privacy-contract.mjs';
import { randomBytes } from 'node:crypto';
import { v1Identity } from './v1-workflows-contract.mjs';
// This fixed producer creates business data only through the normal APIs. Its
// caller owns normal login/MFA and current precredential admission, as with the
// existing V1 producer. There is no implicit live transport or fake DB fallback.
export const QP_PRODUCER=Object.freeze({requests:74,posts:53,patches:1,milliseconds:180000,perReadMs:10000});
export function pendingProducer(){return{schemaVersion:1,inventoryId:QP.inventoryId,readyForLive:false,preparedOnly:true,environment:'docker-integration',syntheticDataOnly:true,
 sourceSha:null,runId:null,companyId:null,membershipId:null,ownerMembershipId:null,privatePeerFiles:null,foreignOwnerMembershipId:null,
 memberUserId:null,secondUserId:null,baseActorEvidence:null,
 admissionEvidence:null,buildReceipt:null,dockerReceipt:null,installedEvidence:null,codeClosure:null,legalDay:null,steps:null};}
export function writePrivatePeer(file,value){
 assert.ok(path.isAbsolute(file)&&path.resolve(file)===file&&!file.startsWith(ROOT+path.sep));assert.equal(fs.realpathSync(path.dirname(file)),path.dirname(file));
 const parent=fs.lstatSync(path.dirname(file));assert.ok(parent.isDirectory()&&!parent.isSymbolicLink());if(process.getuid)assert.equal(parent.uid,process.getuid());assert.equal(parent.mode&0o077,0);
 const bytes=Buffer.from(JSON.stringify(value)+'\n');assert.ok(bytes.length<=16384);const fd=fs.openSync(file,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK,0o600);
 try{const a=fs.fstatSync(fd);assert.equal(a.mode&0o777,0o600);assert.equal(a.nlink,1);let offset=0;while(offset<bytes.length){const n=fs.writeSync(fd,bytes,offset,bytes.length-offset);assert.ok(n>0);offset+=n;}fs.fsyncSync(fd);}
 finally{fs.closeSync(fd);bytes.fill(0);}
 const loaded=readV1Member(file);try{assert.deepEqual(loaded.value,value);return{createdBeforeFirstPost:true,credentialEvidence:{path:file,sha256:loaded.sha256,uid:loaded.uid}};}finally{loaded.bytes.fill(0);}
}
function day(value,offset){const d=new Date(value+'T00:00:00Z');assert.ok(Number.isFinite(+d));d.setUTCDate(d.getUTCDate()+offset);return d.toISOString().slice(0,10);}
export async function produceQueuePrivacy(plan,{request,admit,persist,claim,persistPrivate=writePrivatePeer,now=Date.now}){
 assert.equal(plan.readyForLive,true,'QP_PRODUCER_PENDING');assert.equal(plan.preparedOnly,false,'QP_PRODUCER_PENDING');assert.equal(plan.inventoryId,QP.inventoryId);
 assert.equal(plan.environment,'docker-integration');assert.equal(plan.syntheticDataOnly,true);assert.match(plan.sourceSha,/^[a-f0-9]{40}$/);assert.match(plan.runId,/^qp-[a-f0-9-]{16,48}$/);assert.match(plan.legalDay,/^\d{4}-\d{2}-\d{2}$/);assert.equal(day(plan.legalDay,0),plan.legalDay,'QP_EXACT_LEGAL_DAY_REQUIRED');
 for(const key of['companyId','membershipId','ownerMembershipId','foreignOwnerMembershipId','memberUserId','secondUserId'])v1Identity(plan[key]);
 assert.notEqual(plan.memberUserId,plan.secondUserId);
 for(const key of ['baseActorEvidence','admissionEvidence','buildReceipt','dockerReceipt','installedEvidence','codeClosure'])reference(plan[key]);
 assert.equal(typeof request,'function');assert.equal(typeof admit,'function');assert.equal(typeof persist,'function');assert.equal(typeof claim,'function');assert.equal(typeof persistPrivate,'function');assert.ok(Array.isArray(plan.privatePeerFiles)&&plan.privatePeerFiles.length===2);assert.equal(new Set(plan.privatePeerFiles).size,2);for(const file of plan.privatePeerFiles){assert.ok(path.isAbsolute(file)&&path.resolve(file)===file&&!file.startsWith(ROOT+path.sep));assert.equal(fs.existsSync(file),false);const parent=fs.lstatSync(path.dirname(file));assert.ok(parent.isDirectory()&&!parent.isSymbolicLink());assert.equal(fs.realpathSync(path.dirname(file)),path.dirname(file));assert.equal(parent.mode&0o077,0);if(process.getuid)assert.equal(parent.uid,process.getuid());}
 // Actors come from retained normal fixture receipts; all four current API
 // identities are reread below. New parents are created only by normal APIs.
 claim(hash(Buffer.from(JSON.stringify(plan))));const start=now(),deadline=start+180000,attempted=new Set();let requests=0,posts=0,patches=0,admissions=0;
 const call=async(key,actor,method,route,body)=>{
  assert.ok(!attempted.has(key));attempted.add(key);assert.ok(++requests<=74&&now()<deadline);if(method==='POST')assert.ok(++posts<=53);if(method==='PATCH')assert.ok(++patches<=1);
  assert.ok(['owner','member','second-company','foreign-owner'].includes(actor));assert.ok(['GET','POST','PATCH'].includes(method));
  assert.ok(/^\/api\/(?:companies\/current\/users|teams\/(?:[a-f0-9-]{36}\/members)?|matters\/(?:[a-f0-9-]{36}(?:\/(?:tasks|lifecycle\/status))?)?|matter-work-queue(?:\?[^#]*)?|account\/deletion-requests|auth\/me|build)$/.test(route),'QP_NORMAL_FIXED_ROUTE_REQUIRED');
  persist({type:'qp_fixture_started',key,actor,method,route:route.split('?')[0],bodyKeys:body?Object.keys(body).sort():[],automaticRetry:false});
  const response=await request(actor,method,route,body,{headers:{'X-CaseOps-Automated-Test':'no-paid-providers'},signal:AbortSignal.timeout(Math.max(1,Math.min(10000,deadline-now()))),redirect:'error',maxResponseBytes:1048576,automaticRetry:false});
  assert.ok([200,201].includes(response.status),'QP_FIXTURE_ACK_UNKNOWN_NO_REPLAY');assert.equal(response.releaseSha,plan.sourceSha,'QP_ACTUAL_ACK_SOURCE_REQUIRED');const value=response.value;
  persist({type:'qp_fixture_ack',key,status:response.status,responseSha256:hash(Buffer.from(JSON.stringify(value)))});return value;
 };
 const before=await admit(plan,{boundary:'before',charge:({method})=>{assert.ok(++requests<=74&&++admissions<=12);if(method==='POST')assert.ok(++posts<=53);},deadline});
 assert.equal(before.beforeMemberRead,true);assert.equal(before.sourceSha,plan.sourceSha);assert.equal(before.apiSourceSha,plan.sourceSha);assert.equal(before.webSourceSha,plan.sourceSha);
 for(const key of ['buildReceipt','dockerReceipt','installedEvidence','codeClosure','baseActorEvidence','admissionEvidence'])assert.deepEqual(before[key],plan[key],'QP_EXACT_PREREQUISITE_ADMISSION_REQUIRED');
 for(const[actor,id,user]of[['member',plan.membershipId,plan.memberUserId],['owner',plan.ownerMembershipId,null],['second-company',null,plan.secondUserId],['foreign-owner',null,null]]){
  const me=await call('identity-'+actor,actor,'GET','/api/auth/me');if(id)assert.equal(me.membership.id,id);if(user)assert.equal(me.user.id,user);
 }
 const peers=[];for(let i=0;i<2;i++){
  const credentials={email:'qp-'+plan.runId+'-'+i+'@example.com',full_name:'Synthetic queue peer '+i,password:'Aa1!'+randomBytes(24).toString('base64url')};
  const saved=await persistPrivate(plan.privatePeerFiles[i],credentials);assert.equal(saved.createdBeforeFirstPost,true);assert.ok(saved.credentialEvidence?.sha256);
  try{const value=await call('peer-'+i,'owner','POST','/api/companies/current/users',{...credentials,role:'member'});v1Identity(value.membership_id);v1Identity(value.user_id);peers.push({membershipId:value.membership_id,userId:value.user_id,credentialEvidence:saved.credentialEvidence});}
  finally{credentials.password=undefined;}
 }
 const teamPeerId=peers[0].membershipId,otherPeerId=peers[1].membershipId;
 const parents={};for(const[key,actor]of[['main','owner'],['closed','owner'],['foreign','foreign-owner']]){
  const value=await call('parent-'+key,actor,'POST','/api/matters/',{title:'Synthetic queue '+key+' '+plan.runId,matter_code:plan.runId+'-'+key,practice_area:'Litigation',forum_level:'advisory',status:'intake'});v1Identity(value.id);assert.equal(value.is_active,true);parents[key]=value;
 }
 const main=parents.main;assert.equal(main.company_id,plan.companyId);
 const shared=await call('shared-team','owner','POST','/api/teams/',{name:'Synthetic queue shared '+plan.runId,slug:plan.runId+'-shared',kind:'team'});v1Identity(shared.id);
 const other=await call('other-team','owner','POST','/api/teams/',{name:'Synthetic queue other '+plan.runId,slug:plan.runId+'-other',kind:'team'});v1Identity(other.id);
 for(const[key,team,member]of[['actor',shared.id,plan.membershipId],['peer',shared.id,teamPeerId],['other',other.id,otherPeerId]]){
  const value=await call('team-'+key,'owner','POST','/api/teams/'+team+'/members',{membership_id:member,is_lead:false});assert.equal(value.id,team);assert.ok(value.members.some(x=>x.membership_id===member));
 }
 const tasks=[];const definitions=[...Array.from({length:27},(_,i)=>({role:'mine',owner:plan.membershipId,due:i===26?null:day(plan.legalDay,14+Math.floor(i/2))})),
  {role:'team',owner:teamPeerId,due:day(plan.legalDay,14)},{role:'team',owner:teamPeerId,due:null},
  {role:'unassigned',owner:null,due:day(plan.legalDay,14)},{role:'unassigned',owner:null,due:null},
  {role:'excluded',owner:otherPeerId,due:day(plan.legalDay,14)},{role:'excluded',owner:plan.membershipId,due:day(plan.legalDay,14),status:'done'}];
 for(const[i,spec]of definitions.entries()){
  const body={title:'Synthetic queue '+plan.runId+' '+i,owner_membership_id:spec.owner,due_on:spec.due,status:spec.status||'todo',priority:'medium',expected_lifecycle_version:main.lifecycle_version};
  const value=await call('task-'+i,'owner','POST','/api/matters/'+main.id+'/tasks',body);v1Identity(value.id);assert.equal(value.matter_id,main.id);for(const key of['title','due_on','owner_membership_id','status','priority'])assert.equal(value[key],body[key]);
  tasks.push({...value,role:spec.role,matter:{id:main.id,title:main.title,matter_code:main.matter_code,status:main.status,is_active:true,lifecycle_version:main.lifecycle_version}});
 }
 for(const[key,actor,p,owner]of[['closed','owner',parents.closed,plan.membershipId],['foreign','foreign-owner',parents.foreign,plan.foreignOwnerMembershipId]]){
  const value=await call('excluded-'+key,actor,'POST','/api/matters/'+p.id+'/tasks',{title:'Synthetic excluded '+key+' '+plan.runId,owner_membership_id:owner,due_on:day(plan.legalDay,14),status:'todo',priority:'medium',expected_lifecycle_version:p.lifecycle_version});v1Identity(value.id);assert.equal(value.matter_id,p.id);tasks.push({...value,role:'excluded',matter:p});
 }
 const closed=await call('close-parent','owner','PATCH','/api/matters/'+parents.closed.id+'/lifecycle/status',{to_status:'disposed',expected_from_status:parents.closed.status,expected_updated_at:parents.closed.updated_at,reason:'Synthetic queue exclusion lifecycle proof'});assert.equal(closed.status,'disposed');
 const pages=[];
 for(const ownership of['mine','team','unassigned'])for(const dates of['all','dated','undated']){
  const value=await call('page-'+ownership+'-'+dates,'member','GET','/api/matter-work-queue?'+new URLSearchParams({ownership,dates,limit:'25'}));pages.push({ownership,dates,after:null,value});
  if(ownership==='mine'&&dates==='all'){
   assert.ok(value.next_cursor);const next=await call('page-mine-all-next','member','GET','/api/matter-work-queue?'+new URLSearchParams({ownership,dates,limit:'25',cursor:value.next_cursor}));pages.push({ownership,dates,after:value.next_cursor,value:next});
  }
 }
 const privacyBefore=await call('privacy-before','member','GET','/api/account/deletion-requests');const secondPrivacyBefore=await call('privacy-second-before','second-company','GET','/api/account/deletion-requests');
 const after=await admit(plan,{boundary:'after',charge:({method})=>{assert.ok(++requests<=74&&++admissions<=12);if(method==='POST')assert.ok(++posts<=53);},deadline});assert.equal(after.sourceSha,plan.sourceSha);assert.equal(after.apiSourceSha,plan.sourceSha);assert.equal(after.webSourceSha,plan.sourceSha);
 for(const key of ['buildReceipt','dockerReceipt','installedEvidence','codeClosure','baseActorEvidence','admissionEvidence'])assert.deepEqual(after[key],plan[key],'QP_EXACT_PREREQUISITE_ADMISSION_REQUIRED');
 const anchor=pages[0].value.items.at(-1);
 const result={schemaVersion:1,kind:'actual-normal-api-queue-privacy-fixture',inventoryId:QP.inventoryId,observed:true,nativeReady:false,sourceSha:plan.sourceSha,runId:plan.runId,
  companyId:plan.companyId,membershipId:plan.membershipId,memberUserId:plan.memberUserId,secondUserId:plan.secondUserId,teamPeerId,peers,matter:main,
  tasks,pages,privacyBefore,secondPrivacyBefore,anchor:{id:anchor.id,matterId:main.id,due_on:anchor.due_on,changedDueOn:day(plan.legalDay,90)},
  requests,posts,patches,admissions,startedAtMs:start,completedAtMs:now(),automaticRetry:false,mutationUncertain:false,directDatabaseWrites:false,noPaidMarker:'no-paid-providers',
  prerequisiteEvidence:plan.baseActorEvidence,admissionEvidence:plan.admissionEvidence};
 assert.equal(admissions,12,'QP_COMPLETE_HTTP_ADMISSION_INVENTORY');assert.equal(requests,74,'QP_COMPLETE_PRODUCER_HTTP_INVENTORY');assert.equal(posts,53,'QP_COMPLETE_PRODUCER_POST_INVENTORY');assert.equal(patches,1);assert.ok(now()<=deadline);validateDataset(result);persist({type:'qp_fixture_completed',requests,posts,mutationUncertain:false});return result;
}
