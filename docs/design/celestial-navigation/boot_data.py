"""Build boot-data.json: the single, real-data contract the boot sequence reads.

Prototype of the data layer. The dashboard's main process will produce the same shape
(from the same sources) when this is built for real.

Sources (all existing, nothing invented):
  ~/.claude/logs/health-status.json   health_checks.py output (every 15 min, ADR 0033)
  ~/.claude/projects/-Users-gileskayo/memory/   memory files + MEMORY.md index
  ~/.claude/commands/                  wired skills (a skill is wired when its command wrapper exists)
  ~/.claude/handoffs/                  latest handoff
"""
import json, os, re, sys, datetime as dt
from pathlib import Path

HOME = Path.home()
HEALTH = HOME / '.claude/logs/health-status.json'
MEM = HOME / '.claude/projects/-Users-gileskayo/memory'
CMDS = HOME / '.claude/commands'
HANDOFFS = HOME / '.claude/handoffs'
STALE_MIN = 20          # health_checks runs every 15 min; older than this is stale
RANK = {'green': 0, 'yellow': 1, 'red': 2}


def worst(levels):
    levels = [l for l in levels if l in RANK]
    return max(levels, key=RANK.get) if levels else 'yellow'


def build(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    h = json.loads(HEALTH.read_text()) if HEALTH.exists() else {'checks': [], 'overall': 'grey', 'generated_at': None}
    checks = h.get('checks', [])
    by = lambda pred: [c for c in checks if pred(c['id'])]
    age_min = None
    if h.get('generated_at'):
        age_min = (now - dt.datetime.fromisoformat(h['generated_at'])).total_seconds() / 60

    lines = [{'chip': 'LOCK', 'text': 'ORIGIN · MARVIN', 'level': 'lock'}]

    # Memory sync: both machines' ~/.claude + any stuck-sync / integrity check
    sync = by(lambda i: i.startswith('repo:sync:~/.claude') or i.startswith('sync:stuck') or i == 'repo:integrity:~/.claude')
    lvl = worst(c['severity'] for c in sync)
    bad = [c for c in sync if c['severity'] != 'green']
    lines.append({'chip': 'SYNC', 'level': lvl,
                  'text': 'MEMORY SYNC · MBP ⇄ MINI' + ('' if not bad else ' · ' + bad[0]['label'].upper())})

    # Memories + skills: count files, check the index for broken links
    idx = (MEM / 'MEMORY.md').read_text() if (MEM / 'MEMORY.md').exists() else ''
    links = re.findall(r'\]\(([^)]+\.md)\)', idx)
    broken = [l for l in links if not (MEM / l).exists()]
    skills = len([p for p in CMDS.glob('*.md')]) if CMDS.exists() else 0
    lines.append({'chip': 'OK' if not broken else 'WARN', 'level': 'green' if not broken else 'yellow',
                  'text': f'{len(links)} MEMORIES CHARTED · {skills} SKILLS WIRED' + (f' · {len(broken)} BROKEN LINKS' if broken else '')})

    # Mac Mini: reachable + disk + jobs
    mini = by(lambda i: i.endswith('mac-mini-1') or i.startswith('machine:mac-mini'))
    mini_key = [c for c in mini if c['id'] in ('machine:mac-mini-1', 'disk:space@mac-mini-1', 'jobs:exit@mac-mini-1')]
    lvl = worst(c['severity'] for c in mini_key)
    reason = next((c for c in mini_key if c['severity'] == lvl and lvl != 'green'), None)
    lines.append({'chip': 'LINK', 'level': lvl,
                  'text': 'MAC-MINI · ' + ('NOMINAL' if not reason else short(reason))})

    # Handoff + tests
    hs = sorted(HANDOFFS.glob('handoff-*.md'), key=lambda p: p.stat().st_mtime) if HANDOFFS.exists() else []
    tests = next((c for c in checks if c['id'] == 'main:green'), None)
    lines.append({'chip': 'PLOT', 'level': 'lock',
                  'text': 'HANDOFF · ' + (handoff_name(hs[-1]) if hs else 'NONE')})
    if tests:
        lines.append({'chip': 'TEST', 'level': tests['severity'],
                      'text': 'TESTS · ' + ' · '.join(re.findall(r'\d+ (?:passed|failed|skipped)', tests['detail'])).upper()})

    if age_min is not None and age_min > STALE_MIN:
        lines.append({'chip': 'STALE', 'level': 'yellow', 'text': f'HEALTH SNAPSHOT {int(age_min)} MIN OLD'})

    counts = {k: sum(1 for c in checks if c['severity'] == k) for k in RANK}
    counts['total'] = len(checks)
    nominal = h.get('overall') == 'green' and (age_min is not None and age_min <= STALE_MIN)
    return {
        'generated_at': now.isoformat(), 'health_at': h.get('generated_at'),
        'overall': h.get('overall'), 'nominal': nominal, 'counts': counts,
        'lines': lines,
        'feed': [{'id': c['id'], 'label': c['label'], 'level': c['severity']} for c in checks],
    }


def handoff_name(p):
    m = re.match(r'handoff-(\d{4}-\d{2}-\d{2})(?:-\d{2}-\d{2})?-?(.*)', p.stem)
    day, topic = (m.group(1), m.group(2)) if m else (p.stem, '')
    return (day + (' · ' + topic.replace('-', ' ') if topic else '')).upper()[:44]


def short(c):
    d = c['detail']
    m = re.search(r'\((\d+)%\)', d)
    if c['id'].startswith('disk:space') and m:
        return f'DISK {m.group(1)}% FREE'
    if c['id'].startswith('jobs:exit'):
        return f"{len(re.findall(r'exit \d+', d))} JOBS FAILED"
    return re.split(r' -- |; |:', d)[0].upper()[:40]


if __name__ == '__main__':
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('boot-data.json')
    data = build()
    out.write_text(json.dumps(data, indent=1))
    print(json.dumps({k: data[k] for k in ('overall', 'nominal', 'counts')}), *[f"{l['chip']:5} {l['level']:6} {l['text']}" for l in data['lines']], sep='\n')
    # file:// pages can't fetch JSON, so the prototype also gets a script-tag copy
    out.with_suffix('.js').write_text('window.BOOT_DATA = ' + json.dumps(data) + ';\n')
