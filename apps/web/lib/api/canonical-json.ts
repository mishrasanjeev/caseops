const MAX_SAFE_INTEGER = 9_007_199_254_740_991;

function assertScalarString(value: string, path: string): void {
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      const following = value.charCodeAt(index + 1);
      if (Number.isNaN(following) || following < 0xdc00 || following > 0xdfff) {
        throw new TypeError(`JSON string at ${path} contains an unpaired surrogate.`);
      }
      index += 1;
    } else if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
      throw new TypeError(`JSON string at ${path} contains an unpaired surrogate.`);
    }
  }
}

function encodeCanonicalJson(value: unknown, path = "$"): string {
  if (value === null || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "string") {
    assertScalarString(value, path);
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || Math.abs(value) > MAX_SAFE_INTEGER) {
      throw new TypeError(
        `JSON number at ${path} must be an interoperable safe integer.`,
      );
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value
      .map((item, index) => encodeCanonicalJson(item, `${path}[${index}]`))
      .join(",")}]`;
  }
  if (typeof value === "object") {
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) {
      throw new TypeError(`Unsupported canonical JSON value at ${path}.`);
    }
    const source = value as Record<string, unknown>;
    const members = Object.keys(source)
      // ECMAScript's default sort is lexicographic by UTF-16 code units,
      // matching the Python implementation and the persisted contract.
      .sort()
      .map((key) => {
        assertScalarString(key, path);
        return `${JSON.stringify(key)}:${encodeCanonicalJson(source[key], `${path}.${key}`)}`;
      });
    return `{${members.join(",")}}`;
  }
  throw new TypeError(`Unsupported canonical JSON value at ${path}.`);
}

export function canonicalJson(value: unknown): string {
  return encodeCanonicalJson(value);
}
