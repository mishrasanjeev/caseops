import http from "node:http";

const [, , listenPortRaw, targetPortRaw] = process.argv;
const listenPort = Number.parseInt(listenPortRaw ?? "", 10);
const targetPort = Number.parseInt(targetPortRaw ?? "", 10);

if (
  !Number.isInteger(listenPort) ||
  listenPort < 1 ||
  listenPort > 65_535 ||
  !Number.isInteger(targetPort) ||
  targetPort < 1 ||
  targetPort > 65_535
) {
  console.error("Usage: node docker-acceptance-api-proxy.mjs <listen-port> <target-port>");
  process.exit(2);
}

const server = http.createServer((request, response) => {
  let downstreamAborted = false;
  const headers = {
    ...request.headers,
  };
  delete headers["keep-alive"];
  delete headers["proxy-connection"];

  const upstream = http.request(
    {
      agent: upstreamAgent,
      headers,
      host: "127.0.0.1",
      method: request.method,
      path: request.url,
      port: targetPort,
    },
    (upstreamResponse) => {
      response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers);
      upstreamResponse.pipe(response);
    },
  );
  upstream.on("socket", clearFreeSocketTimeout);

  upstream.setTimeout(125_000, () => {
    upstream.destroy(new Error("Docker API upstream timed out after 125 seconds."));
  });
  upstream.on("error", (error) => {
    if (downstreamAborted) return;
    console.error(
      JSON.stringify({
        event: "docker_acceptance_api_proxy_error",
        message: error.message,
        method: request.method,
        path: request.url,
      }),
    );
    if (!response.headersSent) {
      response.writeHead(502, { "content-type": "application/problem+json" });
    }
    if (!response.writableEnded) {
      response.end(
        JSON.stringify({
          detail: "The local Docker API transport failed before a response was received.",
          status: 502,
          title: "Docker acceptance transport failure",
          type: "about:blank",
        }),
      );
    }
  });
  const cancelUpstream = () => {
    if (response.writableFinished) return;
    downstreamAborted = true;
    upstream.destroy();
  };
  request.on("aborted", cancelUpstream);
  response.on("close", cancelUpstream);
  request.pipe(upstream);
});

// Keep the long acceptance run below the host's ephemeral-port budget while
// bounding concurrent upstream work. Aborted responses still destroy only the
// request in flight, leaving completed sockets reusable.
const upstreamAgent = new http.Agent({
  keepAlive: true,
  keepAliveMsecs: 1_000,
  maxFreeSockets: 8,
  maxSockets: 32,
  scheduling: "lifo",
});
upstreamAgent.on("free", (socket) => {
  armFreeSocketTimeout(socket);
});

const freeSocketTimeoutHandlers = new WeakMap();

function clearFreeSocketTimeout(socket) {
  const handler = freeSocketTimeoutHandlers.get(socket);
  if (handler) {
    socket.removeListener("timeout", handler);
    freeSocketTimeoutHandlers.delete(socket);
  }
  socket.setTimeout(0);
}

function armFreeSocketTimeout(socket) {
  clearFreeSocketTimeout(socket);
  const handler = () => {
    freeSocketTimeoutHandlers.delete(socket);
    socket.destroy();
  };
  freeSocketTimeoutHandlers.set(socket, handler);
  socket.setTimeout(4_000);
  socket.once("timeout", handler);
}

server.requestTimeout = 130_000;
server.keepAliveTimeout = 5_000;
server.headersTimeout = 10_000;
server.listen(listenPort, "127.0.0.1", () => {
  console.log(
    JSON.stringify({
      event: "docker_acceptance_api_proxy_ready",
      listen: `127.0.0.1:${listenPort}`,
      target: `127.0.0.1:${targetPort}`,
    }),
  );
});

function shutdown() {
  server.close(() => {
    upstreamAgent.destroy();
    process.exit(0);
  });
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
