// Playwright installs its native CommonJS TypeScript hook in collection and workers.
// Invoke only inside a journey: listing test metadata does not need API validators.
export function canonicalApiValidators(): Pick<
  typeof import("../../../apps/web/lib/api/schemas"), "authContext" | "authSession" | "draft"
> {
  return require("../../../apps/web/lib/api/schemas");
}
