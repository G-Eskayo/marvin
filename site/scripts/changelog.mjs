// Generate src/data/changelog.json from the engine's CHANGELOG.md (ADR 0028: label-driven versions, one line per
// merged PR). CHANGELOG.md has no version headings: each line lands in its own "Version x.y.z" commit, so git blame
// gives every entry its version and date. Without git history (a shallow clone) entries are kept, undated.
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const site = resolve(import.meta.dirname, '..');
const root = resolve(site, '..');

/** Parse "- Title ([#123](url))" lines. Exported for the test. */
export function parseEntries(markdown) {
  const out = [];
  markdown.split('\n').forEach((line, i) => {
    const m = line.match(/^- (.*?)\s*\(\[#(\d+)\]\((https:\/\/[^)\s]+)\)\)\s*$/);
    if (m) out.push({ line: i + 1, title: m[1].trim(), pr: Number(m[2]), url: m[3] });
    else if (/^- \S/.test(line)) out.push({ line: i + 1, title: line.slice(2).trim(), pr: null, url: null });
  });
  return out;
}

/** git blame --line-porcelain → line number → { version, date }. */
export function parseBlame(porcelain) {
  const byLine = new Map();
  const commits = new Map();
  let cur = null;
  for (const l of porcelain.split('\n')) {
    const head = l.match(/^([0-9a-f]{40}) \d+ (\d+)/);
    if (head) {
      cur = { sha: head[1], line: Number(head[2]) };
      if (!commits.has(cur.sha)) commits.set(cur.sha, {});
      continue;
    }
    if (!cur) continue;
    const c = commits.get(cur.sha);
    if (l.startsWith('committer-time ')) c.time = Number(l.slice(15));
    else if (l.startsWith('summary ')) c.summary = l.slice(8);
    else if (l.startsWith('\t')) byLine.set(cur.line, cur.sha);
  }
  const res = new Map();
  for (const [line, sha] of byLine) {
    const c = commits.get(sha);
    const v = c.summary?.match(/^Version (\d+\.\d+\.\d+)$/);
    res.set(line, {
      version: v ? v[1] : null,
      date: c.time ? new Date(c.time * 1000).toISOString().slice(0, 10) : null,
    });
  }
  return res;
}

const vkey = (v) => (v ? v.split('.').map(Number) : [-1, -1, -1]);
const vcmp = (a, b) => {
  const pa = vkey(a);
  const pb = vkey(b);
  for (let i = 0; i < 3; i++) if (pa[i] !== pb[i]) return pb[i] - pa[i];
  return 0;
};

/** Entries grouped by day (newest first); each entry keeps the version it shipped in. Every merged PR bumps the
 *  version (ADR 0028), so a day is the useful unit to read, and the version range says what it covers. */
export function build(markdown, blame, currentVersion) {
  const entries = parseEntries(markdown).map((e) => ({ ...e, ...(blame.get(e.line) ?? { version: null, date: null }) }));
  const days = new Map();
  for (const e of entries) {
    const key = e.date ?? 'undated';
    if (!days.has(key)) days.set(key, { date: e.date, entries: [] });
    days.get(key).entries.push({ title: e.title, pr: e.pr, url: e.url, version: e.version });
  }
  const out = [...days.values()].sort((a, b) => (!a.date ? 1 : !b.date ? -1 : b.date.localeCompare(a.date)));
  for (const d of out) {
    d.entries.sort((a, b) => vcmp(a.version, b.version));
    const vs = d.entries.map((e) => e.version).filter(Boolean);
    d.from = vs.at(-1) ?? null;
    d.to = vs[0] ?? null;
  }
  return { current: currentVersion, count: entries.length, days: out };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const md = readFileSync(resolve(root, 'CHANGELOG.md'), 'utf8');
  let blame = new Map();
  try {
    blame = parseBlame(
      execFileSync('git', ['blame', '--line-porcelain', 'CHANGELOG.md'], { cwd: root, encoding: 'utf8', maxBuffer: 1 << 26 }),
    );
  } catch (e) {
    console.warn(`changelog: no git blame (${e.message.split('\n')[0]}); entries stay undated`);
  }
  const version = readFileSync(resolve(root, 'VERSION'), 'utf8').trim();
  const data = build(md, blame, version);
  writeFileSync(resolve(site, 'src', 'data', 'changelog.json'), JSON.stringify(data, null, 2) + '\n');
  console.log(`changelog: ${data.count} entries over ${data.days.length} days, current ${version}`);
}
