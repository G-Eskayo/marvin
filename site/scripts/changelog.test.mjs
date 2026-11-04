// Tests for the changelog generator: malformed lines, missing history, version ordering.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { build, parseBlame, parseEntries } from './changelog.mjs';

const MD = `# Changelog

- Fix the thing ([#12](https://github.com/o/r/pull/12))

- A line with no PR link

not a bullet
- Second ([#9](https://github.com/o/r/pull/9))
`;

const sha = (c) => c.repeat(40);
const blame = (rows) =>
  rows
    .map(
      ([s, line, time, summary]) =>
        `${sha(s)} ${line} ${line} 1\ncommitter-time ${time}\nsummary ${summary}\n\t- content`,
    )
    .join('\n');

test('parseEntries reads title, PR and url, keeps a bullet without a link, ignores the rest', () => {
  const e = parseEntries(MD);
  assert.equal(e.length, 3);
  assert.deepEqual(e[0], { line: 3, title: 'Fix the thing', pr: 12, url: 'https://github.com/o/r/pull/12' });
  assert.deepEqual(e[1], { line: 5, title: 'A line with no PR link', pr: null, url: null });
  assert.equal(e[2].pr, 9);
});

test('parseBlame gives each line its version and UTC date; a non-version commit has no version', () => {
  const b = parseBlame(
    blame([
      ['a', 3, 1793577600, 'Version 0.23.8'],
      ['b', 5, 1793491200, 'Hand edit'],
    ]),
  );
  assert.deepEqual(b.get(3), { version: '0.23.8', date: '2026-11-02' });
  assert.deepEqual(b.get(5), { version: null, date: '2026-11-01' });
});

test('build groups by day, newest first, versions descending numerically (0.10 after 0.9)', () => {
  const b = new Map([
    [3, { version: '0.10.0', date: '2026-10-30' }],
    [5, { version: null, date: null }],
    [8, { version: '0.9.1', date: '2026-10-30' }],
  ]);
  const d = build(MD, b, '0.10.0');
  assert.equal(d.count, 3);
  assert.equal(d.days[0].date, '2026-10-30');
  assert.deepEqual(d.days[0].entries.map((e) => e.version), ['0.10.0', '0.9.1']);
  assert.equal(d.days[0].from, '0.9.1');
  assert.equal(d.days[0].to, '0.10.0');
  assert.equal(d.days.at(-1).date, null, 'undated entries go last');
});

test('build without any git history still lists every entry', () => {
  const d = build(MD, new Map(), '1.0.0');
  assert.equal(d.days.length, 1);
  assert.equal(d.days[0].entries.length, 3);
});

test('an empty changelog builds an empty page, not a crash', () => {
  assert.deepEqual(build('# Changelog\n', new Map(), '0.0.1'), { current: '0.0.1', count: 0, days: [] });
});
