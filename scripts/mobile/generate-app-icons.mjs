import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const root = fileURLToPath(new URL('../../', import.meta.url));
const directory = path.join(root, 'apps/mobile/assets');
const logo = readFileSync(path.join(root, 'apps/web/components/marketing/Logo.tsx'), 'utf8');
const paths = [...logo.matchAll(/\bd="([^"]+)"/g)].map(match => match[1]);
assert.equal(paths.length, 3, 'REVIEW_EXISTING_CASEOPS_LOGO_GEOMETRY');
assert.ok(paths.every(value => /^[MmLlHhVvCcSsQqTtAaZz0-9., +\-]+$/.test(value)), 'SVG_PATH_GEOMETRY_ONLY');
const glyph = paths.map(d => `<path d="${d}"/>`).join('');
const svg = (adaptive) => `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">${adaptive ? '' : '<rect width="1024" height="1024" fill="#0b1220"/>'}<g transform="${adaptive ? 'translate(188 174.5) scale(27)' : 'translate(128 112) scale(32)'}" fill="none" stroke="#fff" stroke-width="1.75" stroke-linejoin="round" stroke-linecap="round">${glyph}</g></svg>\n`;

mkdirSync(directory, { recursive: true });
const result = [];
for (const [name, adaptive] of [['app-icon', false], ['app-icon-foreground', true]]) {
  const source = svg(adaptive);
  const pipeline = sharp(Buffer.from(source));
  if (!adaptive) pipeline.removeAlpha();
  const bytes = await pipeline.png({ compressionLevel: 9, palette: false }).toBuffer();
  const metadata = await sharp(bytes).metadata();
  assert.equal(metadata.width, 1024);
  assert.equal(metadata.height, 1024);
  assert.equal(metadata.hasAlpha, adaptive, 'OPAQUE_IOS_AND_TRANSPARENT_ADAPTIVE_ICON_REQUIRED');
  writeFileSync(path.join(directory, `${name}.svg`), source);
  writeFileSync(path.join(directory, `${name}.png`), bytes);
  result.push({ file: `${name}.png`, width: 1024, height: 1024, alpha: metadata.hasAlpha,
    sha256: createHash('sha256').update(bytes).digest('hex') });
}
console.log(JSON.stringify({ source: 'apps/web/components/marketing/Logo.tsx', icons: result }, null, 2));
