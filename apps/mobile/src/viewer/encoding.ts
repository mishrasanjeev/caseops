const alphabet =
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
export function encodeBase64(bytes: Uint8Array): string {
  const parts: string[] = [];
  for (let offset = 0; offset < bytes.length; offset += 3) {
    const a = bytes[offset],
      b = bytes[offset + 1],
      c = bytes[offset + 2];
    parts.push(
      alphabet[a >> 2],
      alphabet[((a & 3) << 4) | ((b || 0) >> 4)],
      offset + 1 < bytes.length
        ? alphabet[((b & 15) << 2) | ((c || 0) >> 6)]
        : "=",
      offset + 2 < bytes.length ? alphabet[c & 63] : "=",
    );
  }
  return parts.join("");
}
export function decodeBase64(value: string): Uint8Array {
  if (
    value.length % 4 ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(
      value,
    )
  )
    throw new Error("Invalid base64");
  const size =
    (value.length / 4) * 3 -
    (value.endsWith("==") ? 2 : value.endsWith("=") ? 1 : 0);
  const bytes = new Uint8Array(size);
  let cursor = 0;
  for (let i = 0; i < value.length; i += 4) {
    const n =
      (alphabet.indexOf(value[i]) << 18) |
      (alphabet.indexOf(value[i + 1]) << 12) |
      (Math.max(0, alphabet.indexOf(value[i + 2])) << 6) |
      Math.max(0, alphabet.indexOf(value[i + 3]));
    if (cursor < size) bytes[cursor++] = n >> 16;
    if (cursor < size) bytes[cursor++] = n >> 8;
    if (cursor < size) bytes[cursor++] = n;
  }
  return bytes;
}
