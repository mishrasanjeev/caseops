const POST_LOGIN_FALLBACK = "/app";
const POST_LOGIN_ORIGIN = new URL("https://caseops.invalid");
const RAW_UNSAFE_CHARACTERS = /[\u0000-\u001f\u007f\\]/;
const ENCODED_UNSAFE_PATH_CHARACTERS = /%(?:0[0-9a-f]|1[0-9a-f]|2f|5c|7f)/i;

/**
 * Limit a post-authentication redirect to the CaseOps workspace.
 *
 * URL parsing canonicalizes dot segments before the /app allow-list check,
 * while the explicit raw checks cover browser backslash normalization and
 * encoded separator variants that can be interpreted differently downstream.
 */
export function safePostLoginPath(candidate: string | null | undefined): string {
  if (!candidate || candidate !== candidate.trim()) {
    return POST_LOGIN_FALLBACK;
  }
  if (
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    RAW_UNSAFE_CHARACTERS.test(candidate)
  ) {
    return POST_LOGIN_FALLBACK;
  }

  try {
    const parsed = new URL(candidate, POST_LOGIN_ORIGIN);
    if (parsed.origin !== POST_LOGIN_ORIGIN.origin) {
      return POST_LOGIN_FALLBACK;
    }
    if (
      ENCODED_UNSAFE_PATH_CHARACTERS.test(parsed.pathname) ||
      (parsed.pathname !== "/app" && !parsed.pathname.startsWith("/app/"))
    ) {
      return POST_LOGIN_FALLBACK;
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return POST_LOGIN_FALLBACK;
  }
}
