import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import http from "node:http";
import { fileURLToPath } from "node:url";
import test from "node:test";

async function listen(server) {
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  return server.address().port;
}

async function fixture(t, handler) {
  const target = http.createServer(handler);
  const targetPort = await listen(target);
  const reservation = http.createServer();
  const proxyPort = await listen(reservation);
  await new Promise((resolve) => reservation.close(resolve));
  const child = spawn(process.execPath, [
    fileURLToPath(new URL("./docker-acceptance-api-proxy.mjs", import.meta.url)),
    String(proxyPort), String(targetPort),
  ], { windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let errors = "";
  child.stderr.on("data", (chunk) => { errors += chunk.toString(); });
  t.after(async () => {
    child.kill();
    target.closeAllConnections();
    await new Promise((resolve) => target.close(resolve));
  });
  await once(child.stdout, "data", { signal: AbortSignal.timeout(10_000) });
  return { url: `http://127.0.0.1:${proxyPort}`, errors: () => errors };
}

test("forwards a complete mutation response exactly once", async (t) => {
  let calls = 0;
  const payload = JSON.stringify({ id: "saved", body: "x".repeat(512 * 1024) });
  const { url, errors } = await fixture(t, async (request, response) => {
    calls += 1;
    assert.equal(request.method, "POST");
    assert.equal(request.headers.connection, "close");
    let body = "";
    for await (const chunk of request) body += chunk.toString();
    assert.equal(body, "original mutation");
    response.writeHead(201, { "content-type": "application/json" });
    response.end(payload);
  });
  const response = await fetch(url, { method: "POST", body: "original mutation" });
  assert.equal(response.status, 201);
  assert.equal(await response.text(), payload);
  assert.equal(calls, 1);
  assert.equal(errors(), "");
});

for (const phase of ["before headers", "during streaming"]) {
  test(`releases abandoned upstream ${phase}`, async (t) => {
    let releaseReceived;
    let releaseClosed;
    const received = new Promise((resolve) => { releaseReceived = resolve; });
    const closed = new Promise((resolve) => { releaseClosed = resolve; });
    const { url, errors } = await fixture(t, (_request, response) => {
      releaseReceived();
      response.on("close", releaseClosed);
      if (phase === "during streaming") {
        response.writeHead(200, { "content-type": "application/json" });
        response.write("[");
        const timer = setInterval(() => response.write(" ".repeat(64 * 1024)), 10);
        response.on("close", () => clearInterval(timer));
      }
    });
    const request = http.get(`${url}/api/courts/forum-catalog`);
    request.on("error", () => {});
    await received;
    if (phase === "during streaming") {
      const [response] = await once(request, "response");
      await once(response, "data");
      response.destroy();
    } else {
      request.destroy();
    }
    let deadline;
    try {
      await Promise.race([
        closed,
        new Promise((_, reject) => {
          deadline = setTimeout(() => reject(new Error("Abandoned upstream was retained")), 1500);
        }),
      ]);
    } finally {
      clearTimeout(deadline);
    }
    assert.equal(errors(), "");
  });
}

test("does not suppress a real transport failure while the client is connected", async (t) => {
  const { url, errors } = await fixture(t, (request) => request.socket.destroy());
  const response = await fetch(url);
  assert.equal(response.status, 502);
  assert.equal((await response.json()).title, "Docker acceptance transport failure");
  assert.match(errors(), /docker_acceptance_api_proxy_error/);
});
