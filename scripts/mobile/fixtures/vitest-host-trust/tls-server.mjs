// Explicitly armed loopback component only. Fresh synthetic keys stay in RAM.
import fs from 'node:fs';
import path from 'node:path';
import https from 'node:https';
import { once } from 'node:events';
import { X509Certificate } from 'node:crypto';
import { localCertificates } from '../../host-node-trust-fixture.mjs';
import { held, sha, save, json, journal } from './io.mjs';

const root=process.env.CASEOPS_VITEST_TLS_COMPONENT_OUT;
const nonce=process.env.CASEOPS_VITEST_TLS_COMPONENT_NONCE;
const end=Number(process.env.CASEOPS_VITEST_TLS_COMPONENT_END_MS);
if(process.env.CASEOPS_VITEST_TLS_COMPONENT_GO!=='VITEST_FORK_TLS_01'||!path.isAbsolute(root||'')||!/^[a-f0-9]{32}$/.test(nonce||'')||!Number.isSafeInteger(end)||end<=Date.now()||end>Date.now()+180000)throw Error('VITEST_TLS_SERVER_ADMISSION');
const records=journal(path.join(root,'outputs/server-events.jsonl'));
let materials=localCertificates(),primary=null,closed=false;
const servers=[],requests=[],tlsErrors=[];
function remember(error){primary??=error;}
function emit(row){try{records.emit(row);}catch(error){remember(error);}}
function active(){let result=null;for(const version of ['22','24']){const file=path.join(root,'runs/node'+version+'-begin.json');if(fs.existsSync(file)){const raw=Buffer.from(JSON.stringify({kind:'vitest-tls-client-begin',version,nonce})+'\n');held({path:file,sha256:sha(raw),sizeBytes:raw.length},16384);result=version;}}return result;}
async function serve(kind){
 const sockets=new Set();
 const server=https.createServer({key:materials[kind].privateKey,cert:materials[kind].cert},(request,response)=>{
  const row={version:active(),kind,method:request.method,url:request.url,rawHeaders:request.rawHeaders,marker:request.headers['x-caseops-automated-test']};requests.push(row);emit({event:'received',...row});
  if(row.version===null||requests.length>4||kind!=='trusted'||row.method!=='GET'||row.url!=='/'||row.marker!=='no-paid-providers'||request.headers.authorization!==undefined||request.headers.cookie!==undefined){remember(Error('VITEST_TLS_RECEIVER'));response.statusCode=400;response.end('fixture-refused');}else response.end('local-only');
 });
 const record={server,sockets,kind};servers.push(record);server.on('error',remember);
 server.on('tlsClientError',error=>{const row={version:active(),kind,code:/^[A-Z0-9_]+$/.test(error.code||'')?error.code:'TLS_CLIENT_ERROR'};tlsErrors.push(row);emit({event:'tls-client-error',...row});if(tlsErrors.length>16)remember(Error('VITEST_TLS_ERROR_BOUND'));});
 server.on('connection',socket=>{sockets.add(socket);if(sockets.size>8){remember(Error('VITEST_TLS_SOCKET_BOUND'));socket.destroy();}socket.once('close',()=>sockets.delete(socket));});
 server.listen(0,'127.0.0.1');await once(server,'listening');const port=server.address().port;
 emit({event:'owned-server',kind,host:'127.0.0.1',port});return{kind,url:`https://127.0.0.1:${port}/`};
}
try{
 const targets=[];for(const kind of ['trusted','untrusted','wrongHost'])targets.push(await serve(kind));
 const ca=save(path.join(root,'runs/qa-ca.pem'),Buffer.from(materials.trusted.cert));
 const fixtureCA={path:ca.path,sha256:ca.sha256,certificateSha256:sha(new X509Certificate(materials.trusted.cert).raw)};
 const ready=path.join(root,'outputs/server-ready.json');json(ready+'.publishing',{kind:'vitest-owned-tls-ready',pid:process.pid,nonce,targets,fixtureCA});if(fs.existsSync(ready))throw Error('VITEST_TLS_READY_COLLISION');fs.renameSync(ready+'.publishing',ready);
 let stopped=false;for(let count=0;count<3000&&Date.now()<end;count++){const file=path.join(root,'runs/stop.json');if(fs.existsSync(file)){const raw=Buffer.from(JSON.stringify({kind:'vitest-owned-tls-stop',nonce})+'\n');held({path:file,sha256:sha(raw),sizeBytes:raw.length},16384);stopped=true;break;}await new Promise(resolve=>setTimeout(resolve,50));}if(!stopped)throw Error('VITEST_TLS_SERVER_BODY_DEADLINE');
}catch(error){remember(error);}finally{
 for(const {server,sockets}of servers){const pending=[...sockets].map(socket=>new Promise(resolve=>socket.once('close',resolve)));const stopped=new Promise((resolve,reject)=>server.close(error=>error&&!(error.code==='ERR_SERVER_NOT_RUNNING'&&!server.listening)?reject(error):resolve()));for(const socket of sockets)socket.destroy();try{await Promise.all([stopped,...pending]);}catch(error){remember(error);}}
 closed=servers.every(({server,sockets})=>!server.listening&&sockets.size===0);materials=null;
 emit({event:'servers-closed',closed});try{records.close();}catch(error){remember(error);}
 json(path.join(root,'outputs/server-summary.json'),{complete:primary===null,primary:primary?.message??null,closed,requests,tlsErrors,privateKeysWritten:0,privateKeyReferencesDropped:true});
}
if(primary)throw primary;
console.log(JSON.stringify({complete:true,requests:requests.length,closed}));
