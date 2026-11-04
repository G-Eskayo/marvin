// Copy the engine's diagrams (docs/diagrams/*.svg) that the site's pages reference into public/diagrams/, so pages
// show the same files the repo documents with. Only referenced files are copied: an older diagram can carry text
// that doesn't belong on a public site, and nothing reaches the site unless a page asks for it (the dist check then
// scans it). Copied at build, never committed here, so they can't drift from the source.
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const site = resolve(import.meta.dirname, '..');
const src = resolve(site, '..', 'docs', 'diagrams');
const out = join(site, 'public', 'diagrams');

function walk(dir, acc = []) {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) walk(p, acc);
    else if (/\.(mdx?|astro)$/.test(f)) acc.push(p);
  }
  return acc;
}

const wanted = new Set();
for (const f of walk(join(site, 'src'))) {
  for (const m of readFileSync(f, 'utf8').matchAll(/\/diagrams\/([A-Za-z0-9._-]+\.svg)/g)) wanted.add(m[1]);
}

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
const missing = [];
for (const f of wanted) {
  if (existsSync(join(src, f))) cpSync(join(src, f), join(out, f));
  else missing.push(f);
}
if (missing.length) {
  console.error(`copy-diagrams: pages reference diagrams that don't exist in docs/diagrams: ${missing.join(', ')}`);
  process.exit(1);
}
console.log(`copy-diagrams: ${wanted.size} diagrams`);
