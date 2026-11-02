// Re-count the numbers on the site and rewrite src/data/facts.json with today's date (`npm run facts`).
// Run it by hand on a machine with the engine checkout, its venv, the dashboard's node_modules and gh signed in.
// It never runs in CI: the counts need the owner's GitHub access and the full test toolchain. Each count is the
// command recorded next to it in facts.json, so a reader can repeat it.
import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';

const site = resolve(import.meta.dirname, '..');
const root = resolve(site, '..');
const cfg = JSON.parse(readFileSync(join(site, 'site.config.json'), 'utf8'));
const file = join(site, 'src', 'data', 'facts.json');
const facts = JSON.parse(readFileSync(file, 'utf8'));
const sh = (cmd, args, cwd = root) => execFileSync(cmd, args, { cwd, encoding: 'utf8', maxBuffer: 1 << 28 });
const gh = process.env.MARVIN_GH || join(homedir(), '.agents', 'bin', 'gh');
const fmt = (n) => n.toLocaleString('en-US');
const set = (id, value, detail) => {
  const f = facts.items.find((x) => x.id === id);
  f.value = value;
  if (detail) f.detail = detail;
};

const pipelinePrs = (repo) =>
  JSON.parse(sh(gh, ['pr', 'list', '-R', repo, '--state', 'merged', '--limit', '2000', '--json', 'headRefName'])).filter((p) =>
    p.headRefName.startsWith('pipeline/'),
  ).length;

const adrs = readdirSync(join(root, 'docs', 'adr')).filter((f) => /^\d{4}-.*\.md$/.test(f)).length;
set('adrs', `${Math.floor(adrs / 10) * 10}+`, `${adrs} architecture decision records in docs/adr.`);

const skills = sh('git', ['ls-tree', '-r', '--name-only', 'origin/main', 'skills'])
  .split('\n')
  .filter((l) => /^skills\/[^/]+\/SKILL\.md$/.test(l)).length;
set('skills', String(skills));

const python = process.env.MARVIN_PYTHON || join(homedir(), '.agents', 'venv', 'bin', 'python');
const py = Number(sh(python, ['-m', 'pytest', 'lib/tests', '--collect-only', '-q']).match(/(\d+) tests? collected/)[1]);
const js = sh('npx', ['vitest', 'list'], join(root, 'dashboard')).split('\n').filter((l) => l.trim()).length;
const tests = py + js;
set(
  'tests',
  `${fmt(Math.floor(tests / 100) * 100)}+`,
  `${fmt(tests)} counted: ${fmt(py)} Python tests collected by pytest in lib/tests, plus ${fmt(js)} dashboard tests listed by vitest.`,
);

const own = pipelinePrs(cfg.repo);
const built = cfg.builtWith[0];
const other = built.repo ? pipelinePrs(built.repo) : 0;
set('pipeline_prs', String(own + other), `${own} on ${cfg.name} itself, ${other} on ${built.name}. Counted as merged PRs whose branch starts with pipeline/.`);

const merged = JSON.parse(sh(gh, ['pr', 'list', '-R', cfg.repo, '--state', 'merged', '--limit', '5000', '--json', 'number'])).length;
set('merged_prs', fmt(merged));

facts.counted_on = new Date().toISOString().slice(0, 10);
writeFileSync(file, JSON.stringify(facts, null, 2) + '\n');
console.log(`facts: counted on ${facts.counted_on}: ${facts.items.map((f) => `${f.id}=${f.value}`).join(', ')}`);
console.log('facts: "machines" is not counted by this script; check the network config by hand.');
