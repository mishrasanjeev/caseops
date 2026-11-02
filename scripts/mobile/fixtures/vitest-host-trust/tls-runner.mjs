import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { startVitest, ForksPoolWorker } from 'vitest/node';
import { hostTrustedForks } from '../../../../apps/web/lib/vitest-host-pool.ts';
import { journal } from './io.mjs';
if(process.env.CASEOPS_VITEST_TLS_COMPONENT_GO!=='VITEST_FORK_TLS_01')throw Error('VITEST_TLS_RUNNER_ADMISSION');
const root=process.env.CASEOPS_VITEST_TLS_COMPONENT_OUT,version=process.versions.node.split('.')[0];
const records=journal(path.join(root,'outputs/node'+version+'-constructors.jsonl'));
const original=ForksPoolWorker.prototype.start;
ForksPoolWorker.prototype.start=function(...args){const promise=Reflect.apply(original,this,args);records.emit({operation:'actual-vitest-fork',pid:this._fork?.pid??null,file:this._fork?.spawnfile??null,args:this._fork?.spawnargs??null,execArgv:this.execArgv,entrypoint:this.entrypoint,originalPromiseReturnedUnchanged:true});return promise;};
try{
 const context=await startVitest('test',['tls-worker.test.mjs'],{root:path.dirname(fileURLToPath(import.meta.url)),config:false,run:true,maxWorkers:2,pool:hostTrustedForks,environment:'node',include:['tls-worker.test.mjs'],testTimeout:15000,coverage:{enabled:true,provider:'v8',reporter:['json-summary'],reportsDirectory:path.join(root,'outputs/node'+version+'-coverage')}},{cacheDir:path.join(root,'runs/node'+version+'-vite-cache')});
 await context?.close();if(!context||context.state.getUnhandledErrors().length)throw Error('VITEST_TLS_RUNNER_UNHANDLED');
}finally{ForksPoolWorker.prototype.start=original;records.close();}
