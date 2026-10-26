const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const {once} = require('node:events');
const path = require('node:path');
const vm = require('node:vm');
const {createRequire} = require('node:module');

const [root, mode, code] = process.argv.slice(2);
const ts = createRequire(path.join(root, 'package.json'))('typescript');
function sourceFunction(relative, name) {
  const source = fs.readFileSync(path.join(root, relative), 'utf8');
  const ast = ts.createSourceFile(relative, source, ts.ScriptTarget.ES2022, true, ts.ScriptKind.JS);
  const matches = ast.statements.filter(node => ts.isFunctionDeclaration(node) && node.name?.text === name);
  assert.equal(matches.length, 1);
  return matches[0].getText(ast);
}

async function main() {
  const records = [];
  if (mode === 'embedded') {
    const writes = [];
    await vm.runInNewContext(code, {
      AbortSignal,
      process: {env:{CASEOPS_API_BASE_URL:'http://api:8000',CASEOPS_RELEASE_SHA:'a'.repeat(40)},
        stdout:{write:value=>writes.push(value)},exit:status=>{throw new Error(`Probe exit ${status}`);}},
      fetch: async (url, options) => {
        assert.ok(['http://api:8000/api/health','http://api:8000/api/build'].includes(url));
        records.push({url,headers:options?.headers??{},deadlinePresent:Boolean(options?.signal)});
        return {ok:true,json:async()=>({status:'ok',release_sha:'a'.repeat(40)})};
      },
    });
    assert.deepEqual(writes,['internal-api-origin-and-identity-ok']);
    return {mode,records,external_requests:0};
  }
  const server = http.createServer((req,res)=>{
    records.push({url:req.url,headers:req.headers});
    res.writeHead(200,{'Content-Type':'text/plain','Connection':'close'});
    res.end('ok');
  });
  server.listen(0,'127.0.0.1');
  await once(server,'listening');
  const origin=`http://127.0.0.1:${server.address().port}`;
  try {
    if (mode === 'functional') {
      const get=(url,...args)=>{assert.equal(new URL(url).origin,origin);return http.get(url,...args);};
      const wait=vm.runInNewContext(`(${sourceFunction('scripts/run-functional-qa-e2e.mjs','waitForUrl')})`,
        {http:{get},Date,setTimeout});
      await wait(`${origin}/api/health`,2000);
    } else if (mode === 'public') {
      const guardedFetch=(url,options)=>{assert.equal(new URL(url).origin,origin);return fetch(url,options);};
      const wait=vm.runInNewContext(`(${sourceFunction('scripts/run-public-content-e2e.mjs','waitForServer')})`,
        {fetch:guardedFetch,localBaseUrl:origin,Date,setTimeout});
      await wait({exitCode:null});
    } else throw new Error('Unknown probe mode');
  } finally {
    const closed=once(server,'close');
    server.close();
    server.closeAllConnections();
    await closed;
  }
  assert.equal(records.length,1);
  return {mode,records,external_requests:0,server_closed:!server.listening};
}
main().then(result=>console.log(JSON.stringify(result)),error=>{console.error(error);process.exitCode=1;});
