'use strict';

const https = require('node:https');

const target = new URL(process.argv[2]);
if (target.protocol !== 'https:' || target.hostname !== '127.0.0.1' ||
    !target.port || target.username || target.password || target.pathname !== '/' ||
    target.search || target.hash) {
  throw new Error('The native TLS fixture accepts only an explicit loopback HTTPS origin.');
}

async function probe() {
  const output = [];
  // One total deadline bounds both default-runtime clients, including body reads.
  const signal = AbortSignal.timeout(5_000);
  try {
    const response = await fetch(target, { signal });
    output.push(await response.text());
  } catch (error) {
    output.push(error.cause?.code ?? error.code);
  }
  try {
    output.push(await new Promise((resolve, reject) => {
      const request = https.get(target, { signal, timeout: 5_000 }, async (response) => {
        try {
          let body = '';
          for await (const chunk of response) body += chunk;
          resolve(body);
        } catch (error) {
          reject(error);
        }
      });
      request.once('timeout', () => request.destroy(new Error('Native TLS fixture deadline exceeded.')));
      request.once('error', reject);
    }));
  } catch (error) {
    output.push(error.code);
  }
  console.log(JSON.stringify(output));
}

probe().catch(() => { process.exitCode = 1; });
