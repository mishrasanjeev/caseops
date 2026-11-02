import path from 'node:path';
import { prepareHostNodeTrust } from '../../host-node-trust.mjs';
import { held } from './io.mjs';
const root=process.env.CASEOPS_VITEST_TLS_COMPONENT_OUT,nonce=process.env.CASEOPS_VITEST_TLS_COMPONENT_NONCE;
if(process.env.CASEOPS_VITEST_TLS_COMPONENT_GO!=='VITEST_FORK_TLS_01'||!path.isAbsolute(root||'')||!/^[a-f0-9]{32}$/.test(nonce||''))throw Error('VITEST_TLS_PREPARE_ADMISSION');
const ready=JSON.parse(held(JSON.parse(process.env.CASEOPS_VITEST_TLS_READY_REF),16384));
if(ready.kind!=='vitest-owned-tls-ready'||ready.nonce!==nonce)throw Error('VITEST_TLS_READY_IDENTITY');
const version=process.versions.node.split('.')[0];if(!['22','24'].includes(version))throw Error('VITEST_TLS_RUNTIME');
console.log(JSON.stringify(prepareHostNodeTrust({directory:path.join(root,'runs/node'+version+'-policy'),role:'native-qa',fixtureCA:ready.fixtureCA})));
