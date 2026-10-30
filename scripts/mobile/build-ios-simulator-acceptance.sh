#!/bin/bash
set -euo pipefail
trap ':' EXIT
for name in ${!DYLD_@} LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT LD_DEBUG LD_PROFILE LD_ASSUME_KERNEL LD_BIND_NOW; do if declare -p "$name" >/dev/null 2>&1; then echo IOS_HOST_DYNAMIC_LOADER_OVERRIDE_REFUSED >&2; exit 1; fi; done
[[ "$(uname -s)" == Darwin ]] || { echo "An actual Mac with Xcode is required." >&2; exit 1; }
: "${CASEOPS_IOS_HOST_NODE:?Supply the admitted Node24 executable}"
: "${CASEOPS_IOS_HOST_POLICY_FILE:?Prepare an immutable iOS host policy}"
: "${CASEOPS_IOS_HOST_POLICY_SHA256:?Bind the exact iOS host policy bytes}"
: "${CASEOPS_IOS_HOST_POLICY_SIZE:?Bind the exact policy extent}"
: "${CASEOPS_IOS_SIMULATOR_BUILD_GO:?An explicit reviewed local simulator build is required}"
repo="$(cd "$(dirname "$0")/../.." && pwd)"
# IOS_HOST_REVIEWED_ENTRY: execute retained reviewed bytes, never a module-path reopen.
"$CASEOPS_IOS_HOST_NODE" --input-type=module -e 'import fs from'\''node:fs'\'';import path from'\''node:path'\'';import{createHash}from'\''node:crypto'\'';
const[file,pin,size,role,...args]=process.argv.slice(1),end=Date.now()+20000;let fd,b;
const fail=()=>{throw Error('\''IOS_HOST_SHIM_SOURCE_REFUSED'\'')};
const frame=s=>['\''dev'\'','\''ino'\'','\''mode'\'','\''uid'\'','\''gid'\'','\''nlink'\'','\''size'\'','\''mtimeNs'\'','\''ctimeNs'\''].map(k=>String(s[k])).join('\'':'\'');
const ns=()=>{const out=[fs.realpathSync(file)];for(let p=path.dirname(out[0]);;p=path.dirname(p)){const s=fs.lstatSync(p,{bigint:true});if(!s.isDirectory()||s.isSymbolicLink()||out.length>128)fail();out.push([p,...['\''dev'\'','\''ino'\'','\''mode'\'','\''uid'\'','\''gid'\''].map(k=>String(s[k]))]);if(p===path.dirname(p))return JSON.stringify(out)}};
try{if(!path.isAbsolute(file)||!/^\d+$/.test(size)||Number(size)>131072)fail();fd=fs.openSync(file,fs.constants.O_RDONLY|(fs.constants.O_NOFOLLOW??0)|(fs.constants.O_NONBLOCK??0));const a=fs.fstatSync(fd,{bigint:true}),n=fs.lstatSync(file,{bigint:true}),before=ns();if(!a.isFile()||n.isSymbolicLink()||a.uid!==BigInt(process.getuid())||a.nlink!==1n||a.size!==BigInt(size)||frame(a)!==frame(n)||(a.mode&0o022n)!==0n)fail();b=Buffer.alloc(Number(size)+1);let count=0;while(count<b.length){if(Date.now()>=end)fail();const v=fs.readSync(fd,b,count,Math.min(65536,b.length-count),null);if(!v)break;count+=v}if(count!==Number(size)||frame(a)!==frame(fs.fstatSync(fd,{bigint:true}))||frame(n)!==frame(fs.lstatSync(file,{bigint:true}))||ns()!==before||createHash('\''sha256'\'').update(b.subarray(0,count)).digest('\''hex'\'')!==pin)fail();const module=await import('\''data:text/javascript;base64,'\''+b.subarray(0,count).toString('\''base64'\''));process.exitCode=await module.iosHostCli([role,...args]);}catch(error){const code=String(error?.message||'\'''\'').split('\''\n'\'',1)[0];console.error(/^IOS_HOST_[A-Z0-9_]+$/.test(code)?code:'\''IOS_HOST_CHILD_REFUSED'\'');process.exitCode=1}finally{b?.fill(0);if(fd!==undefined)fs.closeSync(fd)}
' "$repo/scripts/mobile/ios-host-launch.mjs" '9996dbc6a44b4e94c147178a60f0b188639e5fa66a26077e9aa4fa278f01e467' '76254' simulator
