export function isPlatformPath(pathname: string): boolean {
  return pathname === "/platform" || pathname.startsWith("/platform/");
}

export function platformPrivacyHeaders(pathname: string): Record<string, string> {
  if (!isPlatformPath(pathname)) return {};
  return {
    "Cache-Control": "private, no-store, max-age=0, must-revalidate",
    Pragma: "no-cache",
    Expires: "0",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
  };
}

// Tokens stay in the caller's memory only; the returned URL never contains one.
export function consumePlatformLink(href: string): {
  token: string | null;
  cleanUrl: string;
  invalid: boolean;
} {
  const url = new URL(href);
  if (!isPlatformPath(url.pathname)) {
    return { token: null, cleanUrl: `${url.pathname}${url.search}${url.hash}`, invalid: true };
  }
  const fragment = new URLSearchParams(url.hash.slice(1));
  const values = fragment.getAll("token");
  const invalid = url.searchParams.has("token") || values.length > 1 || (values.length === 1 && (!values[0] || values[0].length > 2048));
  url.searchParams.delete("token");
  // Auth fragments have no navigation purpose and may contain a credential.
  url.hash = "";
  return {
    token: invalid ? null : (values[0] ?? null),
    cleanUrl: `${url.pathname}${url.search}`,
    invalid,
  };
}
