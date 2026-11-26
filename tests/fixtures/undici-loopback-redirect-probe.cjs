'use strict';

const http = require('node:http');
const assert = require('node:assert/strict');

// The caller supplies the actual npm Undici client, never the embedded client.
// Both endpoints and every transmitted value are fixed public loopback fixtures.
async function probeUndiciRedirect(fetch) {
  assert.equal(typeof fetch, 'function');
  assert.notEqual(fetch, globalThis.fetch);
  const end = performance.now() + 4500, workEnd = end - 500;
  const rows = [], servers = [];
  const check = () => { if (performance.now() >= workEnd) throw new Error('PUBLIC_LOOPBACK_REDIRECT_BOUND'); };
  const listen = server => new Promise((resolve, reject) => {
    check(); servers.push(server);
    const timer = setTimeout(() => reject(new Error('PUBLIC_LOOPBACK_LISTEN_BOUND')), Math.min(1000, workEnd - performance.now()));
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.listen(0, '127.0.0.1', () => {
      clearTimeout(timer);
      try {
        check(); const address = server.address(); assert.equal(address.address, '127.0.0.1');
        resolve(`http://127.0.0.1:${address.port}`);
      } catch (error) { reject(error); }
    });
  });
  let caught = false, original;
  try {
    const destination = await listen(http.createServer((request, response) => {
      rows.push({ route: request.url, marker: request.headers['x-caseops-automated-test'], publicHeader: request.headers.authorization });
      response.writeHead(200, { 'Content-Type': 'text/plain' }); response.end('public-loopback-complete');
    }));
    const source = await listen(http.createServer((request, response) => {
      rows.push({ route: request.url, marker: request.headers['x-caseops-automated-test'], publicHeader: request.headers.authorization });
      response.writeHead(302, { Location: `${destination}/second` }); response.end();
    }));
    assert.notEqual(source, destination); check();
    const response = await fetch(`${source}/first`, {
      redirect: 'follow', signal: AbortSignal.timeout(Math.min(3000, Math.floor(workEnd - performance.now()))),
      headers: [['X-CaseOps-Automated-Test', 'no-paid-providers'], ['Authorization', 'CaseOps-PUBLIC-redirect-fixture']],
    });
    check(); assert.equal(response.status, 200); assert.equal(await response.text(), 'public-loopback-complete'); check();
    assert.deepEqual(rows, [
      { route: '/first', marker: 'no-paid-providers', publicHeader: 'CaseOps-PUBLIC-redirect-fixture' },
      { route: '/second', marker: 'no-paid-providers', publicHeader: undefined },
    ]);
  } catch (error) { caught = true; original = error; }
  const cleanupErrors = [];
  for (const server of servers.reverse()) {
    try {
      server.closeAllConnections();
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('PUBLIC_LOOPBACK_CLOSE_BOUND')), Math.max(0, end - performance.now()));
        server.close(error => { clearTimeout(timer); if (error && error.code !== 'ERR_SERVER_NOT_RUNNING') reject(error); else resolve(); });
      });
      assert.equal(server.listening, false); assert.equal(server.address(), null);
      if (performance.now() >= end) throw new Error('PUBLIC_LOOPBACK_FINAL_BOUND');
    } catch (error) { cleanupErrors.push(error); }
  }
  if (caught && cleanupErrors.length) throw new AggregateError([original, ...cleanupErrors], 'PUBLIC_LOOPBACK_BODY_AND_CLEANUP');
  if (caught) throw original;
  if (cleanupErrors.length) throw new AggregateError(cleanupErrors, 'PUBLIC_LOOPBACK_CLEANUP');
}

module.exports = { probeUndiciRedirect };
