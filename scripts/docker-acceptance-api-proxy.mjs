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
  const headers = {
    ...request.headers,
    connection: "close",
  };
  delete headers["keep-alive"];
  delete headers["proxy-connection"];

  const upstream = http.request(
    {
      agent: false,
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

  upstream.setTimeout(125_000, () => {
    upstream.destroy(new Error("Docker API upstream timed out after 125 seconds."));
  });
  upstream.on("error", (error) => {
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
  request.on("aborted", () => upstream.destroy());
  request.pipe(upstream);
});

server.requestTimeout = 130_000;
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
  server.close(() => process.exit(0));
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
