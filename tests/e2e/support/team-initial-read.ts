import type { APIResponse, Page, Route } from "@playwright/test";

import { localTransportHeaders } from "./cost-controls";

type SnapshotRoute = Pick<Route, "request" | "fetch">;

function listUrl(origin: string): string {
  const url = new URL(origin);
  const loopback = url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
  if (url.origin !== origin || url.username || url.password || url.search || url.hash
    || (!loopback && origin !== "https://api.caseops.ai")) {
    throw new Error("Team snapshot requires the admitted API origin.");
  }
  return `${origin}/api/teams/`;
}

/** Retain the owned QA response in memory; no response bytes become evidence. */
export async function fetchInitialTeamList(route: SnapshotRoute, origin: string): Promise<{ response: APIResponse; body: Buffer }> {
  const request = route.request();
  if (request.url() !== listUrl(origin) || request.method() !== "GET") {
    throw new Error("Team snapshot requires the exact initial list read.");
  }
  const headers = Object.fromEntries(Object.entries(request.headers())
    .filter(([name]) => name.toLowerCase() !== "x-caseops-automated-test"));
  const response = await route.fetch({
    headers: { ...headers, ...localTransportHeaders(origin) },
    timeout: 30_000, maxRedirects: 0, maxRetries: 0,
  });
  if (response.status() !== 200 || response.headers()["content-type"]?.split(";", 1)[0] !== "application/json") {
    throw new Error("Team initial list snapshot response was refused.");
  }
  // APIResponse is already SDK-buffered. This checks the fixture payload size,
  // not a streaming-allocation bound, before retaining or fulfilling its bytes.
  const body = await response.body();
  if (body.byteLength > 4_194_304) throw new Error("Team initial list snapshot exceeds the fixture contract.");
  const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
  if (!value || typeof value !== "object" || !Array.isArray(Reflect.get(value, "teams"))
    || typeof Reflect.get(value, "team_scoping_enabled") !== "boolean") {
    throw new Error("Team initial list snapshot is not a list response.");
  }
  return { response, body };
}

/** Hold one real pre-create response; all later reads use normal browser I/O. */
export async function holdInitialTeamList(page: Pick<Page, "route" | "unroute">, origin: string) {
  const url = listUrl(origin);
  let ready!: () => void;
  let failed!: (error: unknown) => void;
  const captured = new Promise<void>((resolve, reject) => { ready = resolve; failed = reject; });
  // The caller awaits this exact promise through ready(); failures before page
  // navigation finishes must not become an unobserved rejection in the meantime.
  void captured.catch(() => {});
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let handling: Promise<void> | undefined;
  let disposal: Promise<void> | undefined;
  let started = false;
  const handler = async (route: Route) => {
    if (started || route.request().method() !== "GET") { await route.continue(); return; }
    started = true;
    handling = (async () => {
      try {
        const snapshot = await fetchInitialTeamList(route, origin);
        ready();
        await gate;
        const headers = Object.fromEntries(Object.entries(snapshot.response.headers())
          .filter(([name]) => !["content-encoding", "content-length"].includes(name.toLowerCase())));
        await route.fulfill({ response: snapshot.response, headers, body: snapshot.body });
      } catch (error) {
        failed(error);
        try { await route.abort("failed"); }
        catch (cleanupError) { throw new AggregateError([error, cleanupError], "Snapshot and route cleanup both failed"); }
        throw error;
      }
    })();
    // ready()/release()/dispose() retain the operation's original rejection.
    await handling.catch(() => {});
  };
  await page.route(url, handler);
  return {
    async ready() {
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([captured, new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error("Team initial list snapshot was not captured.")), 15_000);
        })]);
      } finally { if (timer !== undefined) clearTimeout(timer); }
    },
    async release() { release(); await handling; },
    dispose(): Promise<void> { return disposal ??= (async () => {
      release();
      const errors: unknown[] = [];
      try { await handling; } catch (error) { errors.push(error); }
      try { await page.unroute(url, handler); } catch (error) { errors.push(error); }
      if (errors.length === 1) throw errors[0];
      if (errors.length > 1) throw new AggregateError(errors, "Snapshot and unroute failures are retained separately");
    })(); },
  };
}
