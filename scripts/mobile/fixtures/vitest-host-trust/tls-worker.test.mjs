import path from 'node:path';
import { test, expect } from 'vitest';
import { probe } from '../../host-node-trust-fixture.mjs';
import { held, json } from './io.mjs';

test('actual delegated fork preserves default fetch and HTTPS TLS verification',async()=>{
 if(process.env.CASEOPS_VITEST_TLS_COMPONENT_GO!=='VITEST_FORK_TLS_01')throw Error('VITEST_TLS_WORKER_ADMISSION');
 const root=process.env.CASEOPS_VITEST_TLS_COMPONENT_OUT;
 const ready=JSON.parse(held(JSON.parse(process.env.CASEOPS_VITEST_TLS_READY_REF),16384));
 if(ready.nonce!==process.env.CASEOPS_VITEST_TLS_COMPONENT_NONCE||ready.kind!=='vitest-owned-tls-ready')throw Error('VITEST_TLS_READY_IDENTITY');
 const version=process.versions.node.split('.')[0],reports=[];
 expect(ready.targets.map(({kind})=>kind)).toEqual(['trusted','untrusted','wrongHost']);
 for(const target of ready.targets){
  const report=await probe(target.url);reports.push({kind:target.kind,...report});
  json(path.join(root,'outputs/node'+version+'-'+target.kind+'.json'),{pid:process.pid,argv:process.argv,execArgv:process.execArgv,...reports.at(-1)});
  expect(report.selectedStoreVerified).toBe(true);expect(report.expectedDefaultCount).toBe(version==='22'?149:145);
  if(target.kind==='trusted')expect(report.output).toEqual(['local-only','local-only']);
  else if(target.kind==='wrongHost')expect(report.output).toEqual(['ERR_TLS_CERT_ALTNAME_INVALID','ERR_TLS_CERT_ALTNAME_INVALID']);
  else for(const code of report.output)expect(['DEPTH_ZERO_SELF_SIGNED_CERT','SELF_SIGNED_CERT_IN_CHAIN','UNABLE_TO_VERIFY_LEAF_SIGNATURE']).toContain(code);
 }
 expect(reports.flatMap(({output})=>output)).toHaveLength(6);
 json(path.join(root,'outputs/node'+version+'-complete.json'),{complete:true,pid:process.pid,attempts:6,markedHTTP:2,tlsDenials:4,reports});
},15_000);
