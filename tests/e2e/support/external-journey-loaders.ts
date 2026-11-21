// Load runtime libraries and application validators inside journey bodies.
// Literal require preserves Playwright's native CommonJS worker loader.
export function loadAxeBuilder(): typeof import("@axe-core/playwright").default {
  return require("@axe-core/playwright").default;
}

export function loadJsQR(): typeof import("jsqr").default {
  return require("jsqr");
}

export function loadJSZip(): typeof import("jszip") {
  return require("jszip");
}

export function loadDomainCatalogue(): typeof import("../../../apps/web/lib/ip/domain-catalog") {
  return require("../../../apps/web/lib/ip/domain-catalog");
}

export function loadPlatformSchemas(): typeof import("../../../apps/web/lib/platform/schemas") {
  return require("../../../apps/web/lib/platform/schemas");
}
