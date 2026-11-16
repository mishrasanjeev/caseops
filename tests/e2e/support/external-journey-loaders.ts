// These pure libraries are needed by journey bodies, never native --list metadata.
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
