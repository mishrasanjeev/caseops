import fs from'node:fs';import path from'node:path';import{createHash}from'node:crypto';
export const sha=b=>createHash('sha256').update(b).digest('hex');
const F=['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'];
const frame=s=>F.map(k=>String(s[k])),same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const need=(v,c)=>{if(!v)throw Error(c);};
export function namespace(file){const rows=[];need(path.resolve(file)===file,'TLS_COMPONENT_CANONICAL');for(let p=path.dirname(file);;p=path.dirname(p)){need(rows.length<128,'TLS_COMPONENT_NAMESPACE_BOUND');const s=fs.lstatSync(p,{bigint:true});need(s.isDirectory()&&!s.isSymbolicLink(),'TLS_COMPONENT_NAMESPACE');rows.push([p,...F.slice(0,5).map(k=>String(s[k]))]);if(path.dirname(p)===p)return rows;}}
export function held(ref,maximum=1048576){
 need(ref&&typeof ref.path==='string'&&/^[a-f0-9]{64}$/.test(ref.sha256)&&Number.isSafeInteger(ref.sizeBytes)&&ref.sizeBytes>0&&ref.sizeBytes<=maximum,'TLS_COMPONENT_REFERENCE');
 const before=namespace(ref.path);let fd,failed=false,original,answer;
 try{fd=fs.openSync(ref.path,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);const a=fs.fstatSync(fd,{bigint:true}),n=fs.lstatSync(ref.path,{bigint:true});need(a.isFile()&&n.isFile()&&!n.isSymbolicLink()&&a.uid===BigInt(process.getuid())&&a.nlink===1n&&a.size===BigInt(ref.sizeBytes)&&same(frame(a),frame(n))&&fs.realpathSync(ref.path)===ref.path,'TLS_COMPONENT_INPUT');const b=Buffer.alloc(ref.sizeBytes+1);let count=0;while(count<b.length){const width=fs.readSync(fd,b,count,Math.min(65536,b.length-count),null);if(!width)break;count+=width;}need(count===ref.sizeBytes&&sha(b.subarray(0,count))===ref.sha256&&same(frame(a),frame(fs.fstatSync(fd,{bigint:true})))&&same(frame(n),frame(fs.lstatSync(ref.path,{bigint:true})))&&same(before,namespace(ref.path)),'TLS_COMPONENT_INPUT_CHANGED');answer=Buffer.from(b.subarray(0,count));}
 catch(e){failed=true;original=e;}finally{if(fd!==undefined)try{fs.closeSync(fd);}catch(e){if(!failed){failed=true;original=e;}else process.stderr.write('TLS_COMPONENT_SECONDARY_CLOSE\n');}}
 if(failed)throw original;return answer;
}
export function save(file,bytes){
 need(Buffer.isBuffer(bytes)&&bytes.length<=16777216,'TLS_COMPONENT_OUTPUT_BOUND');const before=namespace(file);let fd,failed=false,original,answer;
 try{fd=fs.openSync(file,fs.constants.O_RDWR|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);const a=fs.fstatSync(fd,{bigint:true});need(a.isFile()&&a.uid===BigInt(process.getuid())&&a.nlink===1n&&a.size===0n,'TLS_COMPONENT_EXCLUSIVE_OUTPUT');let n=0;while(n<bytes.length){const width=fs.writeSync(fd,bytes,n,bytes.length-n,n);need(width>0,'TLS_COMPONENT_WRITE_PROGRESS');n+=width;}fs.fsyncSync(fd);const last=fs.fstatSync(fd,{bigint:true}),named=fs.lstatSync(file,{bigint:true});need(F.slice(0,6).every(k=>a[k]===last[k])&&last.size===BigInt(bytes.length)&&same(frame(last),frame(named))&&same(before,namespace(file)),'TLS_COMPONENT_OUTPUT_CHANGED');answer={path:file,sha256:sha(bytes),sizeBytes:bytes.length};}
 catch(e){failed=true;original=e;}finally{if(fd!==undefined)try{fs.closeSync(fd);}catch(e){if(!failed){failed=true;original=e;}else process.stderr.write('TLS_COMPONENT_SECONDARY_CLOSE\n');}}
 if(failed)throw original;return answer;
}
export const json=(file,v)=>save(file,Buffer.from(JSON.stringify(v)+'\n'));
export function journal(file){
 const ns=namespace(file);let fd,last,bytes=0,ordinal=0,closed=false;
 try{fd=fs.openSync(file,fs.constants.O_RDWR|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);last=fs.fstatSync(fd,{bigint:true});need(last.isFile()&&last.uid===BigInt(process.getuid())&&last.nlink===1n&&last.size===0n,'TLS_COMPONENT_JOURNAL');}
 catch(e){if(fd!==undefined)try{fs.closeSync(fd);}catch{process.stderr.write('TLS_COMPONENT_SECONDARY_CLOSE\n');}throw e;}
 return{emit(v){need(!closed&&same(frame(last),frame(fs.fstatSync(fd,{bigint:true})))&&same(frame(last),frame(fs.lstatSync(file,{bigint:true})))&&same(ns,namespace(file)),'TLS_COMPONENT_JOURNAL_CHANGED');const b=Buffer.from(JSON.stringify({ordinal:ordinal++,...v})+'\n');need(b.length<=32768&&bytes+b.length<=1048576,'TLS_COMPONENT_JOURNAL_BOUND');let n=0;while(n<b.length){const width=fs.writeSync(fd,b,n,b.length-n,bytes);need(width>0,'TLS_COMPONENT_WRITE_PROGRESS');n+=width;bytes+=width;}fs.fsyncSync(fd);last=fs.fstatSync(fd,{bigint:true});need(last.size===BigInt(bytes)&&same(frame(last),frame(fs.lstatSync(file,{bigint:true}))),'TLS_COMPONENT_JOURNAL_CHANGED');},close(){need(!closed,'TLS_COMPONENT_JOURNAL_CLOSED');closed=true;fs.closeSync(fd);}};
}
