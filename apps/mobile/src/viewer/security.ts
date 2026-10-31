import { VIEWER_LIMITS } from "./contracts.ts";
export const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2] as const;
// '*' prevents react-native-webview's JS wrapper from invoking Linking for a
// non-whitelisted URL. Every navigation is then denied by the callback below.
export const PRIVATE_WEBVIEW_POLICY = Object.freeze({
  originWhitelist: ["*"],
  incognito: true,
  cacheEnabled: false,
  cacheMode: "LOAD_NO_CACHE" as const,
  domStorageEnabled: false,
  sharedCookiesEnabled: false,
  thirdPartyCookiesEnabled: false,
  allowFileAccess: false,
  allowFileAccessFromFileURLs: false,
  allowUniversalAccessFromFileURLs: false,
  mixedContentMode: "never" as const,
  javaScriptCanOpenWindowsAutomatically: false,
  setSupportMultipleWindows: true,
  allowsLinkPreview: false,
  allowsBackForwardNavigationGestures: false,
  allowsFullscreenVideo: false,
  allowsInlineMediaPlayback: false,
  mediaPlaybackRequiresUserAction: true,
  mediaCapturePermissionGrantType: "deny" as const,
  dataDetectorTypes: "none" as const,
  webviewDebuggingEnabled: false,
  textInteractionEnabled: false,
  fraudulentWebsiteWarningEnabled: true,
});
export function allowViewerNavigation(request: {
  url: string;
  isTopFrame?: boolean;
  navigationType?: string;
}): boolean {
  return (
    request.url === "about:blank" &&
    request.isTopFrame !== false &&
    (!request.navigationType || request.navigationType === "other")
  );
}
export type RendererEvent =
  | { type: "ready" | "error" | "expired"; id: string }
  | { type: "ack"; id: string; sequence: number }
  | { type: "page"; id: string; page: number; pages: number; zoom: number };
export function decodeRendererEvent(data: string, id: string): RendererEvent {
  if (data.length > 1024) throw new Error("Oversized renderer event");
  const row = JSON.parse(data);
  if (!row || typeof row !== "object" || row.id !== id)
    throw new Error("Wrong renderer identity");
  const keys = Object.keys(row).sort().join(",");
  if (["ready", "error", "expired"].includes(row.type) && keys === "id,type")
    return row;
  if (
    row.type === "ack" &&
    keys === "id,sequence,type" &&
    Number.isSafeInteger(row.sequence) &&
    row.sequence >= -1 &&
    row.sequence <= Math.ceil(VIEWER_LIMITS.maxBytes / VIEWER_LIMITS.chunkBytes)
  )
    return row;
  if (
    row.type === "page" &&
    keys === "id,page,pages,type,zoom" &&
    Number.isSafeInteger(row.page) &&
    Number.isSafeInteger(row.pages) &&
    row.page > 0 &&
    row.pages >= row.page &&
    row.pages <= VIEWER_LIMITS.maxPages &&
    ZOOMS.includes(row.zoom)
  )
    return row;
  throw new Error("Invalid renderer event");
}
