import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readClientPublicInput } from './client-extension-public-input.mjs';

const fields=['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'];
const meta=s=>Object.fromEntries(fields.map(k=>[k,String(s[k])]));
const sha=b=>createHash('sha256').update(b).digest('hex');
function canonicalParents(file) {
  assert.equal(fs.realpathSync(file),file,'CX_CANONICAL_RUNTIME_NAMESPACE_REQUIRED');const result=[];
  for(let parent=path.dirname(file);;parent=path.dirname(parent)){
    const value=fs.lstatSync(parent,{bigint:true});assert.ok(value.isDirectory()&&!value.isSymbolicLink());
    result.push([parent,...['dev','ino','uid','gid','mode'].map(k=>String(value[k]))]);
    if(path.dirname(parent)===parent)return result;
  }
}
export function selectedClientExecutable(name,environment=process.env) {
  assert.ok(['git','node'].includes(name));
  const leaf=process.platform==='win32'?name+'.exe':name;
  for(const folder of(environment.PATH||'').split(path.delimiter))if(path.isAbsolute(folder)){
    const file=path.join(folder,leaf);try{fs.accessSync(file,fs.constants.X_OK);if(fs.statSync(file).isFile())return fs.realpathSync(file);}catch{}
  }
  throw Error('CX_ACCEPTED_EXECUTABLE_NOT_ON_PATH');
}
export function captureClientFile(file,maxBytes=268435456){
  const parents=canonicalParents(file);const before=fs.lstatSync(file,{bigint:true});
  assert.ok(before.isFile()&&!before.isSymbolicLink()&&before.nlink===1n&&before.size<=BigInt(maxBytes));
  let fd;try{fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
    assert.deepEqual(meta(fs.fstatSync(fd,{bigint:true})),meta(before));
    const hash=createHash('sha256'),buffer=Buffer.alloc(65536);let bytes=0;
    for(;;){const n=fs.readSync(fd,buffer,0,Math.min(buffer.length,maxBytes+1-bytes),null);if(!n)break;bytes+=n;assert.ok(bytes<=maxBytes);hash.update(buffer.subarray(0,n));}
    assert.equal(BigInt(bytes),before.size);assert.deepEqual(meta(fs.fstatSync(fd,{bigint:true})),meta(before));
    assert.deepEqual(meta(fs.lstatSync(file,{bigint:true})),meta(before));assert.deepEqual(canonicalParents(file),parents);
    return{path:file,sha256:hash.digest('hex'),extent:bytes,metadata:meta(before)};
  }finally{if(fd!==undefined)fs.closeSync(fd);}
}

/** Complete source/installed-tool trees, including every hidden entry. */
export function captureClientTree(root,{maxEntries=50000,maxBytes=536870912}={}) {
  assert.equal(fs.realpathSync(root),root); const entries=[]; let bytes=0;
  function walk(file) {
    assert.ok(entries.length<maxEntries,'CX_COMPLETE_TREE_ENTRY_BOUND');
    const before=fs.lstatSync(file,{bigint:true}),relative=path.relative(root,file);
    if(before.isDirectory()) {
      const names=fs.readdirSync(file).sort(); entries.push({path:relative,kind:'directory',metadata:meta(before),names});
      names.forEach(n=>walk(path.join(file,n)));
      assert.deepEqual(fs.readdirSync(file).sort(),names);
    } else if(before.isSymbolicLink()) {
      const target=fs.readlinkSync(file),real=fs.realpathSync(file);
      assert.ok(real===root||real.startsWith(root+path.sep),'CX_EXTERNAL_TOOL_SYMLINK');
      entries.push({path:relative,kind:'symlink',metadata:meta(before),target});
    } else {
      assert.ok(before.isFile()&&before.nlink===1n); let fd;
      try {
        fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
        assert.deepEqual(meta(fs.fstatSync(fd,{bigint:true})),meta(before));
        const hash=createHash('sha256'),buffer=Buffer.alloc(65536); let size=0;
        for(;;) {const n=fs.readSync(fd,buffer,0,Math.min(buffer.length,maxBytes-bytes+1),null); if(!n)break;bytes+=n;size+=n;assert.ok(bytes<=maxBytes,'CX_COMPLETE_TREE_BYTE_BOUND');hash.update(buffer.subarray(0,n));}
        assert.equal(BigInt(size),before.size);assert.deepEqual(meta(fs.fstatSync(fd,{bigint:true})),meta(before));
        entries.push({path:relative,kind:'file',metadata:meta(before),sha256:hash.digest('hex')});
      } finally {if(fd!==undefined)fs.closeSync(fd);}
    }
    assert.deepEqual(meta(fs.lstatSync(file,{bigint:true})),meta(before));
  }
  walk(root);return {root,entries,bytes,complete:true};
}

export function clientHarnessFingerprint(root) {
  const names=['compose.mobile-local.yml','package.json','package-lock.json','apps/mobile/package.json','apps/mobile/package-lock.json'];
  for(const dir of ['apps/mobile/e2e','scripts/mobile'])for(const name of fs.readdirSync(path.join(root,dir)))
    if(/\.(mjs|py|json)$/.test(name))names.push(dir+'/'+name);
  const hash=createHash('sha256');for(const name of [...new Set(names)].sort()){
    const observed=captureClientFile(path.join(root,name),1048576);hash.update(name+'\0'+observed.sha256+'\0');
  }return hash.digest('hex');
}

export function clientListenerIdentity(value,pid,port) {
 assert.ok(typeof value==='string'&&Buffer.byteLength(value)<=65536);const rows=value.trim().split('\n');let processId=null,fd=null;const descriptors=[];
 for(const row of rows){if(/^p[1-9][0-9]{0,9}$/.test(row)){assert.equal(processId,null);processId=Number(row.slice(1));}
  else if(/^f[0-9]{1,6}$/.test(row)){assert.equal(fd,null);fd=Number(row.slice(1));}
  else if(row.startsWith('n')){assert.ok(fd!==null);assert.ok(['127.0.0.1:'+port,'[::1]:'+port].includes(row.slice(1)),'CX_LOOPBACK_APPIUM_LISTENER_REQUIRED');descriptors.push(fd);fd=null;}
  else assert.fail('CX_EXACT_LISTENER_FIELDS_REQUIRED');
 }
 assert.equal(processId,pid);assert.equal(fd,null);assert.ok(descriptors.length>=1&&descriptors.length<=2);assert.equal(new Set(descriptors).size,descriptors.length);return{pid,port,descriptors};
}

export function admitClientServer(q,{command=execFileSync,read=ref=>readClientPublicInput(ref.path,{expectedSha256:ref.sha256}).value}={}) {
  const server=read(q.appiumServerEvidence),inventory=read(q.appiumInventoryEvidence);
  assert.equal(server.observed,true);assert.equal(server.owned,true);assert.equal(server.platform,q.platform);
  assert.ok(Number.isSafeInteger(server.pid)&&server.pid>1);assert.equal(server.inventoryEvidence.sha256,q.appiumInventoryEvidence.sha256);
  assert.equal(server.appiumUrl,q.appiumUrl);const url=new URL(server.appiumUrl);
  assert.equal(url.protocol,'http:');assert.ok(['127.0.0.1','localhost','[::1]'].includes(url.hostname));assert.ok(Number(url.port)>=1024);
  assert.equal(inventory.complete,true);assert.equal(inventory.platform,q.platform);
  assert.deepEqual(captureClientTree(inventory.root),inventory.tree,'CX_COMPLETE_APPIUM_INVENTORY_CHANGED');
  const observed=command('/bin/ps',['-p',String(server.pid),'-o','lstart=','-o','command='],{
    encoding:'utf8',timeout:5000,maxBuffer:65536,env:{PATH:'/usr/bin:/bin',LC_ALL:'C',TZ:'UTC'}}).trim();
  assert.equal(sha(Buffer.from(observed)),server.utcStartAndCommandSha256,'CX_OWNED_SERVER_IDENTITY_CHANGED');
  assert.ok(observed.includes(inventory.appiumEntry),'CX_EXACT_APPIUM_ENTRY_REQUIRED');
  const owner=command('/bin/ps',['-p',String(server.pid),'-o','uid='],{encoding:'utf8',timeout:5000,maxBuffer:65536,env:{PATH:'/usr/bin:/bin',LC_ALL:'C',TZ:'UTC'}}).trim();assert.match(owner,/^[0-9]{1,10}$/);assert.equal(Number(owner),process.getuid());assert.equal(server.uid,process.getuid());
  const listener=command('/usr/sbin/lsof',['-nP','-a','-p',String(server.pid),'-iTCP:'+url.port,'-sTCP:LISTEN','-Fpfn'],{encoding:'utf8',timeout:5000,maxBuffer:65536,env:{PATH:'/usr/bin:/bin',LC_ALL:'C',TZ:'UTC'}});clientListenerIdentity(listener,server.pid,Number(url.port));
  return {server,inventory};
}
