import test from "node:test";
import assert from "node:assert/strict";
import {
  PRIVATE_WEBVIEW_POLICY,
  allowViewerNavigation,
  decodeRendererEvent,
} from "./security.ts";
import { createViewerHtml } from "./html.ts";
const id = "a".repeat(32);

test("native-viewer security: navigation never hands off network/file/custom schemes", () => {
  for (const url of [
    "https://caseops.ai",
    "https://example.com",
    "file:///private/a.pdf",
    "content://x",
    "data:text/html,test",
    "blob:test",
    "intent:x",
    "tel:123",
    "javascript:alert(1)",
    "about:blank#x",
  ])
    assert.equal(allowViewerNavigation({ url }), false, url);
  assert.equal(
    allowViewerNavigation({ url: "about:blank", navigationType: "other" }),
    true,
  );
  assert.equal(
    allowViewerNavigation({ url: "about:blank", navigationType: "click" }),
    false,
  );
  assert.equal(
    allowViewerNavigation({ url: "about:blank", isTopFrame: false }),
    false,
  );
  assert.deepEqual(PRIVATE_WEBVIEW_POLICY.originWhitelist, ["*"]);
});
test("native-viewer security: isolated WebView has no cache, cookies, file access or debugging", () => {
  for (const field of [
    "cacheEnabled",
    "domStorageEnabled",
    "sharedCookiesEnabled",
    "thirdPartyCookiesEnabled",
    "allowFileAccess",
    "allowFileAccessFromFileURLs",
    "allowUniversalAccessFromFileURLs",
    "javaScriptCanOpenWindowsAutomatically",
    "allowsLinkPreview",
    "webviewDebuggingEnabled",
    "textInteractionEnabled",
  ] as const)
    assert.equal(PRIVATE_WEBVIEW_POLICY[field], false, field);
  assert.equal(PRIVATE_WEBVIEW_POLICY.incognito, true);
  assert.equal(PRIVATE_WEBVIEW_POLICY.fraudulentWebsiteWarningEnabled, true);
  assert.equal(PRIVATE_WEBVIEW_POLICY.mixedContentMode, "never");
  assert.equal(PRIVATE_WEBVIEW_POLICY.mediaCapturePermissionGrantType, "deny");
});
test("native-viewer security: exact bounded bridge schemas reject arbitrary content and actions", () => {
  assert.equal(
    decodeRendererEvent(
      JSON.stringify({ id, type: "page", page: 1, pages: 2, zoom: 1 }),
      id,
    ).type,
    "page",
  );
  assert.equal(
    decodeRendererEvent(JSON.stringify({ id, type: "ack", sequence: -1 }), id)
      .type,
    "ack",
  );
  for (const row of [
    { id, type: "open", url: "https://x" },
    { id, type: "page", page: 2, pages: 1, zoom: 1 },
    { id, type: "page", page: 1, pages: 1001, zoom: 1 },
    { id, type: "page", page: 1, pages: 2, zoom: 3 },
    { id, type: "ready", secret: "anything" },
    { id: "wrong", type: "ready" },
  ])
    assert.throws(() => decodeRendererEvent(JSON.stringify(row), id));
  assert.throws(() => decodeRendererEvent("a".repeat(1025), id));
});
test("native-viewer security: generated HTML is public-only with nonce CSP, no eval/network/remote assets", () => {
  const html = createViewerHtml(id);
  assert.equal((html.match(/<script type="module" nonce=/g) || []).length, 3);
  assert.match(html, /connect-src 'none'/);
  assert.match(html, /worker-src 'none'/);
  assert.match(html, /font-src 'none'/);
  assert.doesNotMatch(
    html.slice(0, html.indexOf("<title>")),
    /unsafe-eval|unsafe-inline|https?:/,
  );
  assert.doesNotMatch(
    html,
    /<script[^>]+src=|<iframe|<a\s|<link|<input|<form/i,
  );
  assert.match(html, /isEvalSupported: false/);
  assert.match(html, /enableScripting: false/);
  assert.match(html, /enableXfa: false/);
  assert.match(html, /AnnotationMode.DISABLE/);
  assert.doesNotMatch(
    html,
    /Bearer |access_token|refresh_token|\/api\/matters\//,
  );
  assert.throws(() => createViewerHtml(`"><script`));
});
