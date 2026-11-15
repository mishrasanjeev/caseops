import assert from 'node:assert/strict';
function boundedLines(value, limit) {
  assert.ok(typeof value === 'string' && Buffer.byteLength(value) <= limit && !value.includes('\0'), 'SDK_DUMP_SIZE_BOUND');
  const lines = value.split(/\r?\n/);
  assert.ok(lines.length <= 200000 && lines.every((line) => line.length <= 8192), 'SDK_DUMP_LINE_BOUND');
  return lines;
}

// AAPT's indented XML dump is a tree, not a collection of matching substrings.
export function sdkXmlTree(dump) {
  const roots = [], stack = [];
  let count = 0;
  for (const line of boundedLines(dump, 4 * 1024 * 1024)) {
    if (!line.trim() || /^ *N: [\w-]+=\S+ \(line=\d+\)$/.test(line)) continue;
    const element = /^( *)E: ([\w.:-]+) \(line=\d+\)$/.exec(line);
    const attribute = /^( *)A: ([^\s(=]+)(?:\((0x[0-9a-fA-F]{8})\))?=(.+)$/.exec(line);
    const text = /^( *)T: '([^'\\]*)'$/.exec(line);
    const row = element || attribute || text;
    assert.ok(row, 'UNRECOGNIZED_SDK_XML_ROW');
    const indent = row[1].length;
    while (stack.length && stack.at(-1).indent >= indent) stack.pop();
    if (element) {
      assert.ok(++count <= 20000 && stack.length < 64, 'SDK_XML_TREE_BOUND');
      const node = { name: element[2], indent, attrs: new Map(), children: [], texts: [] };
      (stack.length ? stack.at(-1).children : roots).push(node);
      stack.push(node);
    } else {
      assert.ok(stack.length, 'SDK_XML_ROW_WITHOUT_ELEMENT');
      const owner = stack.at(-1);
      if (attribute) {
        assert.ok(!owner.attrs.has(attribute[2]), 'DUPLICATE_SDK_XML_ATTRIBUTE');
        owner.attrs.set(attribute[2], { id: attribute[3]?.toLowerCase(), raw: attribute[4] });
      } else owner.texts.push(text[2]);
    }
  }
  assert.equal(roots.length, 1, 'ONE_COMPILED_XML_ROOT_REQUIRED');
  return roots[0];
}

export function sdkValue(attribute) {
  assert.ok(attribute, 'REQUIRED_COMPILED_ATTRIBUTE_MISSING');
  if (/^@0x[0-9a-fA-F]{8}$/.test(attribute.raw)) return attribute.raw.toLowerCase();
  if (['true', 'false'].includes(attribute.raw)) return attribute.raw === 'true';
  const quoted = /^("(?:[^"\\]|\\.)*")(?: \(Raw: ("(?:[^"\\]|\\.)*")\))?$/.exec(attribute.raw);
  assert.ok(quoted, 'COMPILED_ATTRIBUTE_VALUE_INVALID');
  const value = JSON.parse(quoted[1]);
  if (quoted[2]) assert.equal(JSON.parse(quoted[2]), value, 'COMPILED_RAW_VALUE_MISMATCH');
  return value;
}
