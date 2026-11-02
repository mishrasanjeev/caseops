import fs from 'node:fs';
import path from 'node:path';
import tls from 'node:tls';
import { test, expect } from 'vitest';

test('real tiny worker retains inherited host-trust bootstrap',async()=>{
 const {assertHostNodeTrust}=await import(process.env.CASEOPS_VITEST_H_SOURCE_URI);
 const report=assertHostNodeTrust({policyRef:{path:process.env.CASEOPS_HOST_NODE_TRUST_POLICY_FILE,sha256:process.env.CASEOPS_HOST_NODE_TRUST_POLICY_SHA256}});
 const expectedDefaultCount={'22.14.0':148,'22.23.4':116,'24.15.0':144}[process.versions.node];
 expect(expectedDefaultCount).toBeDefined();expect(report.expectedDefaultCount).toBe(expectedDefaultCount);
 expect(report.selectedStoreVerified).toBe(true);
 expect(7+5).toBe(12);
 fs.writeFileSync(path.join(process.env.CASEOPS_VITEST_FIXTURE_REPORT_DIR,'tiny-worker-ran-node'+process.versions.node.split('.')[0]+'.json'),JSON.stringify({
  pid:process.pid,argv:process.argv,execArgv:process.execArgv,report,
  defaultCount:typeof tls.getCACertificates==='function'?tls.getCACertificates('default').length:null})+'\n',{flag:'wx',mode:0o600});
});
