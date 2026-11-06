// The site's build check (marvin#1007, plan §3.1). Fails the build when the site would say something it can't back:
//
//   source (before the build)
//     - every feature has a known area and status, and ids are unique
//     - a Released or Built-in-testing feature has evidence and a "verified on" date; local evidence paths and ADR ids
//       exist in the engine repo
//     - a Planned feature has no docs page and links a ticket or an ADR
//     - every feature page exists, shows its status block, and every page file belongs to a feature
//   --dist (after the build)
//     - dist/CNAME is exactly the host of site.config.json url (GitHub Pages' custom domain, marvin.gileskayo.me)
//     - no private pattern in any built page: the owner's own patterns file when present (the same file the engine's
//       pre-commit secret scan uses, ~/.claude/private-push-patterns.txt, or $MARVIN_SITE_PRIVATE_PATTERNS), plus
//       home-folder paths and email addresses other than the configured contact. A match is reported by file and
//       pattern number only, never echoed.
//     - every internal link points at a page or file that was built
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { parse } from 'yaml';

const SITE = resolve(import.meta.dirname, '..');
const ROOT = resolve(SITE, '..');
const STATUSES = ['released', 'testing', 'progress', 'planned', 'retired'];

export function checkFeatures(data, { exists, adrFiles, pageFile }) {
  const errs = [];
  const areas = new Set((data.areas ?? []).map((a) => a.id));
  const seen = new Set();
  for (const f of data.features ?? []) {
    const at = `feature "${f.id}"`;
    if (!f.id || !f.title || !f.summary) errs.push(`${at}: needs id, title and summary`);
    if (seen.has(f.id)) errs.push(`${at}: duplicate id`);
    seen.add(f.id);
    if (!areas.has(f.area)) errs.push(`${at}: unknown area "${f.area}"`);
    if (!STATUSES.includes(f.status)) errs.push(`${at}: unknown status "${f.status}"`);
    if (f.status === 'released' || f.status === 'testing' || f.status === 'progress') {
      if (!f.evidence?.length) errs.push(`${at}: ${f.status} needs evidence`);
      if (!f.verified_on) errs.push(`${at}: ${f.status} needs verified_on`);
    }
    if ((f.status === 'testing' || f.status === 'progress') && !f.why_testing) errs.push(`${at}: ${f.status} needs why_testing`);
    if (f.status === 'progress' && f.page) errs.push(`${at}: in-progress features live on the roadmap only, never a docs page`);
    if (f.status === 'planned') {
      if (f.page) errs.push(`${at}: planned features live on the roadmap only, never a docs page`);
      if (!f.ticket && !f.adrs?.length) errs.push(`${at}: planned needs a ticket or an ADR to link`);
    }
    for (const e of f.evidence ?? []) {
      if (!/^https?:/.test(e) && !exists(e)) errs.push(`${at}: evidence path not in the repo: ${e}`);
    }
    for (const id of f.adrs ?? []) {
      const hit = adrFiles.filter((a) => (id.length === 4 ? a.startsWith(`${id}-`) : a.startsWith(id)));
      if (!hit.length) errs.push(`${at}: no ADR file for ${id}`);
    }
    if (f.page) {
      const text = pageFile(f.page);
      if (text === null) errs.push(`${at}: page "${f.page}" has no file`);
      else if (!text.includes(`<FeatureStatus page="${f.page}"`)) errs.push(`page "${f.page}": missing its status block`);
    }
  }
  return errs;
}

export function checkPagesHaveFeatures(pageSlugs, data) {
  const used = new Set((data.features ?? []).map((f) => f.page).filter(Boolean));
  return pageSlugs.filter((p) => !used.has(p)).map((p) => `page "${p}": no feature in features.yaml points at it`);
}

export function loadPatterns(file) {
  if (!file || !existsSync(file)) return [];
  const out = [];
  for (const line of readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim() || line.trimStart().startsWith('#')) continue;
    try {
      out.push(new RegExp(line));
    } catch {
      /* an ERE JavaScript can't read: the pre-push guard still applies it */
    }
  }
  return out;
}

export function scanText(text, { privatePatterns = [], allowEmail = '' }) {
  const hits = [];
  privatePatterns.forEach((re, i) => {
    if (re.test(text)) hits.push(`private pattern #${i + 1}`);
  });
  if (/\/Users\/[A-Za-z]/.test(text)) hits.push('a home-folder path');
  // The machine names the engine's own identity rule forbids (lib/tests/test_instance.py IDENTITY).
  if (/gils-mac-mini|marvin-laptop/i.test(text)) hits.push('a private machine name');
  const emails = (text.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g) ?? []).filter(
    (e) => e !== allowEmail && !/@(example\.(com|invalid)|anthropic\.com)$/.test(e) && !/\.(png|svg|jpe?g|webp)$/.test(e),
  );
  if (emails.length) hits.push(`${emails.length} email address(es)`);
  return hits;
}

/** The bare host GitHub Pages serves as the custom domain (dist/CNAME), from site.config.json `url`. Refuses anything
 * Pages can't serve that way: not https, a path, a port, credentials, or GitHub's own github.io host. */
export function cnameFor(url) {
  let u;
  try {
    u = new URL(url);
  } catch {
    throw new Error(`site.config.json url ${JSON.stringify(url)} is not a custom domain GitHub Pages can serve`);
  }
  if (u.protocol !== 'https:' || u.pathname !== '/' || u.port || u.username || u.password || u.search || u.hash ||
      /(^|\.)github\.io$/.test(u.hostname)) {
    throw new Error(`site.config.json url ${JSON.stringify(url)} is not a custom domain GitHub Pages can serve`);
  }
  return u.hostname;
}

/** Problems with the built CNAME: it must exist and be exactly one line, the configured host. */
export function checkCname(text, url) {
  if (text == null) return ['no CNAME in the built site: GitHub Pages would drop the custom domain'];
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
  if (lines.length !== 1) return [`CNAME must be one line (the domain), found ${lines.length}`];
  const want = cnameFor(url);
  return lines[0] === want ? [] : [`CNAME says ${lines[0]}, site.config.json url says ${want}`];
}

function walk(dir, out = []) {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

/** Repo paths linked as github.com/<owner>/<repo>/blob|tree/main/<path> (any owner: the check is about the path). */
export function sourceLinks(text) {
  return [...text.matchAll(/github\.com\/[^/\s]+\/[^/\s]+\/(?:blob|tree)\/main\/([^\s)`"'#?]+)/g)].map((m) => m[1].replace(/\/$/, ''));
}

export function internalLinks(html) {
  return [...html.matchAll(/(?:href|src)="(\/[^"#?]*)/g)].map((m) => m[1]).filter((u) => !u.startsWith('//'));
}

function resolves(dist, url) {
  const p = join(dist, decodeURIComponent(url));
  return existsSync(p) && (statSync(p).isFile() || existsSync(join(p, 'index.html')));
}

function main() {
  const errs = [];
  const data = parse(readFileSync(join(SITE, 'src', 'data', 'features.yaml'), 'utf8'));
  const adrFiles = readdirSync(join(ROOT, 'docs', 'adr')).filter((f) => /^\d{4}-.*\.md$/.test(f));
  const pagesDir = join(SITE, 'src', 'content', 'docs', 'docs', 'features');
  const pageSlugs = existsSync(pagesDir) ? readdirSync(pagesDir).filter((f) => /\.mdx?$/.test(f)).map((f) => f.replace(/\.mdx?$/, '')) : [];
  const pageFile = (slug) => {
    for (const ext of ['mdx', 'md']) {
      const p = join(pagesDir, `${slug}.${ext}`);
      if (existsSync(p)) return readFileSync(p, 'utf8');
    }
    return null;
  };
  errs.push(...checkFeatures(data, { exists: (p) => existsSync(join(ROOT, p)), adrFiles, pageFile }));
  errs.push(...checkPagesHaveFeatures(pageSlugs, data));
  // Source links in page text must point at files that exist in this checkout.
  for (const f of walk(join(SITE, 'src')).filter((p) => /\.(mdx?|astro)$/.test(p))) {
    for (const p of sourceLinks(readFileSync(f, 'utf8'))) {
      if (!existsSync(join(ROOT, p))) errs.push(`${f.slice(SITE.length)}: links to ${p}, which isn't in the repo`);
    }
  }

  if (process.argv.includes('--dist')) {
    const dist = join(SITE, 'dist');
    const cfg = JSON.parse(readFileSync(join(SITE, 'site.config.json'), 'utf8'));
    const patternsFile = process.env.MARVIN_SITE_PRIVATE_PATTERNS || join(homedir(), '.claude', 'private-push-patterns.txt');
    const privatePatterns = loadPatterns(patternsFile);
    const files = walk(dist).filter((f) => /\.(html|xml|txt|json|js|css|svg)$/.test(f) && !f.includes(`${join('dist', 'pagefind')}`));
    for (const f of files) {
      const text = readFileSync(f, 'utf8');
      // Bundled third-party JS and CSS carry package strings that look like emails; only private patterns apply there.
      const content = /\.(html|xml|txt|json|svg)$/.test(f);
      const hits = content ? scanText(text, { privatePatterns, allowEmail: cfg.contactEmail }) : scanText(text, { privatePatterns }).filter((h) => h.startsWith('private'));
      for (const h of hits) errs.push(`${f.slice(dist.length)}: ${h}`);
      if (f.endsWith('.html')) {
        for (const u of internalLinks(text)) if (!resolves(dist, u)) errs.push(`${f.slice(dist.length)}: broken link ${u}`);
      }
    }
    const cnameFile = join(dist, 'CNAME');
    errs.push(...checkCname(existsSync(cnameFile) ? readFileSync(cnameFile, 'utf8') : null, cfg.url));
    console.log(`check: scanned ${files.length} built files with ${privatePatterns.length} private patterns`);
  }

  if (errs.length) {
    console.error(`site check failed (${errs.length}):\n  ${[...new Set(errs)].join('\n  ')}`);
    process.exit(1);
  }
  console.log(`check: ${(data.features ?? []).length} features, ${pageSlugs.length} feature pages, all backed`);
}

if (import.meta.url === `file://${process.argv[1]}`) main();
