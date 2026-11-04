// Tests for the site's build check: try to sneak an unbacked claim or a private string past it.
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { checkCname, checkFeatures, checkPagesHaveFeatures, cnameFor, internalLinks, loadPatterns, scanText, sourceLinks } from './check.mjs';

const areas = [{ id: 'a', title: 'A' }];
const ok = { id: 'x', title: 'X', area: 'a', status: 'released', summary: 's', evidence: ['lib/x.py'], verified_on: '2026-11-02' };
const env = (over = {}) => ({
  exists: (p) => p === 'lib/x.py',
  adrFiles: ['0052-parallel.md', '0080-one-store.md', '0080-the-work-loop.md'],
  pageFile: () => null,
  ...over,
});
const run = (features, e = env()) => checkFeatures({ areas, features }, e);

test('a backed released feature passes', () => {
  assert.deepEqual(run([ok]), []);
});

test('released without evidence or a verified date fails', () => {
  const errs = run([{ ...ok, evidence: [], verified_on: undefined }]);
  assert.ok(errs.some((e) => e.includes('needs evidence')));
  assert.ok(errs.some((e) => e.includes('needs verified_on')));
});

test('evidence that points at a file not in the repo fails; a URL is not checked', () => {
  assert.ok(run([{ ...ok, evidence: ['lib/missing.py'] }]).some((e) => e.includes('not in the repo')));
  assert.deepEqual(run([{ ...ok, evidence: ['https://github.com/o/r/pull/1'] }]), []);
});

test('a planned feature with a docs page is refused (roadmap only)', () => {
  const errs = run([{ id: 'p', title: 'P', area: 'a', status: 'planned', summary: 's', ticket: 1, page: 'p' }]);
  assert.ok(errs.some((e) => e.includes('roadmap only')));
});

test('a planned feature with nothing to link is refused', () => {
  assert.ok(run([{ id: 'p', title: 'P', area: 'a', status: 'planned', summary: 's' }]).some((e) => e.includes('ticket or an ADR')));
});

test('testing needs a reason it is not released', () => {
  assert.ok(run([{ ...ok, status: 'testing' }]).some((e) => e.includes('why_testing')));
});

test('unknown status, unknown area and duplicate ids are caught', () => {
  const errs = run([{ ...ok, status: 'beta', area: 'zzz' }, ok]);
  assert.ok(errs.some((e) => e.includes('unknown status')));
  assert.ok(errs.some((e) => e.includes('unknown area')));
  assert.ok(errs.some((e) => e.includes('duplicate id')));
});

test('ADR ids resolve, including a slug prefix to pick one of two files with the same number', () => {
  assert.deepEqual(run([{ ...ok, adrs: ['0052', '0080-the-work'] }]), []);
  assert.ok(run([{ ...ok, adrs: ['0099'] }]).some((e) => e.includes('no ADR file for 0099')));
  assert.ok(run([{ ...ok, adrs: ['0080-nope'] }]).some((e) => e.includes('no ADR file')));
});

test('a page must exist and carry its own status block', () => {
  assert.ok(run([{ ...ok, page: 'x' }]).some((e) => e.includes('has no file')));
  const wrong = env({ pageFile: () => '<FeatureStatus page="other" />' });
  assert.ok(run([{ ...ok, page: 'x' }], wrong).some((e) => e.includes('missing its status block')));
  const right = env({ pageFile: () => '<FeatureStatus page="x" />' });
  assert.deepEqual(run([{ ...ok, page: 'x' }], right), []);
});

test('a page file no feature points at is reported', () => {
  assert.deepEqual(checkPagesHaveFeatures(['x', 'orphan'], { features: [{ ...ok, page: 'x' }] }), [
    'page "orphan": no feature in features.yaml points at it',
  ]);
});

test('scanText finds private patterns without echoing them', () => {
  const hits = scanText('hello Secretname here', { privatePatterns: [/Secretname/] });
  assert.deepEqual(hits, ['private pattern #1']);
  assert.ok(!hits.join(' ').includes('Secretname'));
});

test('scanText catches home paths, machine names and stray emails, but allows the configured contact', () => {
  assert.ok(scanText('see /Users/someone/x', {}).includes('a home-folder path'));
  assert.ok(scanText('host gils-mac-mini.local', {}).includes('a private machine name'));
  assert.ok(scanText('mail a.person@somewhere.org', {}).some((h) => h.includes('email')));
  assert.deepEqual(scanText('mail me@site.dev', { allowEmail: 'me@site.dev' }), []);
  assert.deepEqual(scanText('the `/Users/` prefix and noreply@example.com', {}), []);
});

test('loadPatterns skips comments, blanks and regexes JavaScript cannot read, and a missing file', () => {
  const dir = mkdtempSync(join(tmpdir(), 'site-check-'));
  const f = join(dir, 'p.txt');
  writeFileSync(f, '# comment\n\nabc\n[unclosed\n');
  assert.equal(loadPatterns(f).length, 1);
  assert.deepEqual(loadPatterns(join(dir, 'nope.txt')), []);
});

test('sourceLinks pulls repo paths out of blob and tree links, without anchors or trailing slashes', () => {
  const md = '[a](https://github.com/o/r/blob/main/lib/x.py#L3) and `https://github.com/o/r/tree/main/dashboard/` and https://github.com/o/r/pull/9';
  assert.deepEqual(sourceLinks(md), ['lib/x.py', 'dashboard']);
});

test('internalLinks keeps site paths, drops external and protocol-relative ones', () => {
  const html = '<a href="/docs/">d</a><a href="https://x.y/">x</a><img src="/diagrams/a.svg"><a href="//cdn.x/y">c</a><a href="/why/#n">w</a>';
  assert.deepEqual(internalLinks(html), ['/docs/', '/diagrams/a.svg', '/why/']);
});

// ── The custom domain (GitHub Pages reads dist/CNAME; marvin.gileskayo.me) ──────────────────────────────────────
test('the CNAME is the bare host of site.config.json url', () => {
  assert.equal(cnameFor('https://marvin.gileskayo.me'), 'marvin.gileskayo.me');
  assert.equal(cnameFor('https://marvin.gileskayo.me/'), 'marvin.gileskayo.me');
});

test('a url GitHub Pages cannot serve as a custom domain is refused', () => {
  for (const bad of ['http://marvin.gileskayo.me', 'https://marvin.gileskayo.me/docs/', 'https://u:p@marvin.gileskayo.me',
    'https://marvin.gileskayo.me:8443', 'https://g-eskayo.github.io', 'not a url', '', undefined]) {
    assert.throws(() => cnameFor(bad), /custom domain/, String(bad));
  }
});

test('the built CNAME must match the configured domain exactly', () => {
  const url = 'https://marvin.gileskayo.me';
  assert.deepEqual(checkCname('marvin.gileskayo.me\n', url), []);
  assert.match(checkCname(null, url).join(), /no CNAME/);
  assert.match(checkCname('', url).join(), /CNAME/);
  assert.match(checkCname('evil.example.com\n', url).join(), /evil\.example\.com/);
  assert.match(checkCname('marvin.gileskayo.me\nextra.example.com\n', url).join(), /one line/);
});
