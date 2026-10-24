#!/usr/bin/env python3
"""build_data.py — Vitals v4 prototype data: reads MARVIN's live state on every Mac in the registry and writes data.json.

    ~/.agents/venv/bin/python build_data.py [--days 14] [--out data.json]

Nothing below names a machine, service, job, ticket or caller. Every one of them is discovered:
  machines   ~/.claude/marvin-network.json (lib/machine_profile) + each Mac's ~/.claude/machine-profile.json
  services   `launchctl list` rows whose label contains "marvin", plus every ~/.claude/logs/jobs/*.json
  traffic    gh-calls.jsonl (grouped with lib/github_usage.group_of), launches.jsonl (tokens, cost, exit),
             dashboard-timing.jsonl, dashboard-webhook.log ("change detected" lines)
  health     health-status.json non-green checks, launchd last-exit, each job's last run
  tickets    launches.jsonl `ticket` + `kind` (planner / executor = the stage)
  arcs       job step/summaries on one machine that name another machine's id, label or tailscale host
The other Macs are read over `ssh <tailscale_hostname>` with read-only commands (tar to stdout, launchctl list).
Non-macOS devices are listed but not read (lib/machine_profile.remote_macs, ADR 0069).

Complexity: one pass over every log line, so time O(R) for R log rows across all machines, plus O(N·C) to match
C non-green checks to N nodes. Space O(L·H + N + E): L lanes × H hourly buckets (14 days = 336), N nodes, E edges.
Raw rows are not kept; only the aggregates are. data.json size is bounded by L·H, not by log length.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import statistics
import subprocess
import sys
import tarfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
sys.path.insert(0, str(HOME / ".agents" / "lib"))
import machine_profile as mp  # noqa: E402
from github_usage import group_of, display_name  # noqa: E402

LOG_FILES = ["gh-calls.jsonl", "launches.jsonl", "dashboard-timing.jsonl.1", "dashboard-timing.jsonl",
             "dashboard-webhook.log", "health-status.json", "gh-budget.jsonl", "gh-usage-hourly.v2.json"]
HOUR = 3600


# ── reading ────────────────────────────────────────────────────────────────
def read_local() -> dict:
    logs = HOME / ".claude" / "logs"
    files = {}
    for name in LOG_FILES:
        p = logs / name
        if p.exists():
            files[name] = p.read_bytes()
    for p in sorted((logs / "jobs").glob("*.json")):
        files["jobs/" + p.name] = p.read_bytes()
    prof = HOME / ".claude" / "machine-profile.json"
    if prof.exists():
        files["machine-profile.json"] = prof.read_bytes()
    files["launchctl"] = subprocess.run(["launchctl", "list"], capture_output=True).stdout
    return files


def read_remote(host: str) -> tuple[dict, str]:
    """Two read-only ssh calls: tar the logs to stdout, and launchctl list."""
    names = " ".join(LOG_FILES)
    cmd = (f"cd ~/.claude && tar cf - machine-profile.json "
           f"$(cd logs && for f in {names}; do [ -f $f ] && echo logs/$f; done) logs/jobs 2>/dev/null")
    try:
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", host, cmd],
                           capture_output=True, timeout=120)
        lc = subprocess.run(["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", host, "launchctl list"],
                            capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {}, "ssh timed out"
    if not r.stdout:
        return {}, (r.stderr.decode(errors="replace").strip() or "ssh returned nothing")[:200]
    files = {}
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
        for m in tf.getmembers():
            if m.isfile():
                key = m.name.removeprefix("logs/")
                files[key] = tf.extractfile(m).read()
    files["launchctl"] = lc.stdout
    return files, ""


def jsonl(b: bytes):
    for line in (b or b"").decode(errors="replace").splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def to_epoch(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


# ── naming ─────────────────────────────────────────────────────────────────
def norm(name: str) -> str:
    """One key per program: launchd labels, job files and gh callers all reduce to e.g. 'ticket-pipeline'."""
    s = (name or "").lower()
    s = re.sub(r"^com\.marvin\.", "", s)
    s = re.sub(r"^application\.com\.[a-z0-9]+\.", "", s)
    s = re.sub(r"(\.\d+)+$", "", s)          # dashboard app label carries changing pids
    s = re.sub(r"\.(py|sh|json|log)$", "", s)
    return s.replace("_", "-")


# ── build ──────────────────────────────────────────────────────────────────
class Graph:
    def __init__(self, start: float, end: float):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple, dict] = {}
        self.start, self.end = start, end
        self.H = int((end - start) // HOUR) + 1
        self.lanes: dict[str, dict] = {}

    def node(self, nid, **kw):
        n = self.nodes.setdefault(nid, {"id": nid, "load24": 0, "health": "grey", "why": [], "numbers": {}})
        for k, v in kw.items():
            n.setdefault(k, v)
        return n

    def edge(self, frm, to, kind):
        return self.edges.setdefault((frm, to, kind), {"from": frm, "to": to, "kind": kind, "n24": 0,
                                                        "hours24": [0] * 24, "numbers": Counter()})

    def lane(self, nid, unit):
        return self.lanes.setdefault((nid, unit), {"node": nid, "unit": unit, "v": [0] * self.H, "fail": [0] * self.H})

    def hit(self, t, nid, unit="events", amount=1, failed=False, edge=None):
        if t is None or t < self.start or t > self.end:
            return
        i = int((t - self.start) // HOUR)
        ln = self.lane(nid, unit)
        ln["v"][i] += amount
        if failed:
            ln["fail"][i] += 1
        if t >= self.end - 24 * HOUR:
            self.nodes[nid]["load24"] += 1
            if edge is not None:
                edge["n24"] += 1
                edge["hours24"][min(23, int((t - (self.end - 24 * HOUR)) // HOUR))] += 1


def worse(a, b):
    order = ["grey", "green", "yellow", "red"]
    return a if order.index(a) >= order.index(b) else b


def set_health(n, sev, why):
    n["health"] = worse(n["health"], sev)
    if why and sev != "green" and why not in n["why"]:
        n["why"].append(why)


def build(days: int) -> dict:
    now = (int(time.time()) // HOUR + 1) * HOUR   # end of the current hour, so buckets are clock hours
    g = Graph(now - days * 86400, now - 1)
    registry = mp._load_registry()
    me = mp.registry_id()
    remote_ok = mp.remote_macs()
    machines = []
    sources = {}
    for mid, info in registry.items():
        m = {"id": mid, "kind": info.get("kind"), "os": info.get("os", "macos"),
             "host": info.get("tailscale_hostname"), "accepts": info.get("accepts", []), "read": False, "note": ""}
        if mid == me:
            sources[mid] = read_local(); m["read"] = True; m["note"] = "this machine"
        elif mid in remote_ok and m["host"]:
            files, err = read_remote(m["host"])
            if files:
                sources[mid] = files; m["read"] = True; m["note"] = f"read over ssh {m['host']}"
            else:
                m["note"] = f"unreachable: {err}"
        else:
            m["note"] = "not read: not a Mac (lib/machine_profile.remote_macs, ADR 0069)"
        prof = {}
        if mid in sources and "machine-profile.json" in sources[mid]:
            try:
                prof = json.loads(sources[mid]["machine-profile.json"])
            except ValueError:
                pass
        m["label"] = prof.get("label") or mid
        m["profile"] = {k: prof.get(k) for k in ("hw_model", "macos_version", "claude_version", "mobility_class") if prof.get(k)}
        machines.append(m)
        g.node(mid, type="machine", machine=mid, label=m["label"])
        g.nodes[mid]["health"] = "green" if m["read"] else "grey"
        if not m["read"]:
            g.nodes[mid]["why"].append(m["note"])

    ext_gh = None
    tickets = defaultdict(lambda: {"stages": Counter(), "cost": 0.0, "times": [], "machines": set(), "fails": 0})
    arcs = Counter()
    arc_ev = defaultdict(list)
    arc_h = defaultdict(lambda: [0] * 24)
    machine_names = {m["id"]: {m["id"], m["label"], m["host"] or m["id"]} for m in machines}

    for mid, files in sources.items():
        nid_of = {}  # norm -> node id on this machine

        def svc(name, kind):
            key = norm(name)
            nid = f"{mid}/{key}"
            nid_of[key] = nid
            nid_of[norm(display_name(name))] = nid   # the gate's hourly cache names callers by display name
            n = g.node(nid, type="service", machine=mid, label=display_name(name) if kind == "launchd" else key)
            n.setdefault("sources", [])
            if kind not in n["sources"]:
                n["sources"].append(kind)
            g.edge(nid, mid, "runs-on")
            return n

        # launchd
        for line in files.get("launchctl", b"").decode(errors="replace").splitlines()[1:]:
            parts = line.split(None, 2)
            if len(parts) == 3 and "marvin" in parts[2].lower():
                pid, status, label = parts
                n = svc(label, "launchd")
                n["numbers"]["launchd pid"] = pid
                n["numbers"]["launchd last exit"] = int(status)
                if int(status) != 0 and pid != "-":
                    set_health(n, "yellow", f"running again (pid {pid}) after its last instance exited {status}")
                elif int(status) != 0:
                    set_health(n, "red", f"launchd last exit {status}, not running")
                else:
                    set_health(n, "green", None)
        # jobs
        for key, b in files.items():
            if not key.startswith("jobs/"):
                continue
            try:
                d = json.loads(b)
            except ValueError:
                continue
            n = svc(d.get("job") or key[5:], "job")
            n["numbers"]["job label"] = d.get("label")
            runs = d.get("runs", [])
            fails = 0
            for r in runs:
                t = to_epoch(r.get("started_at"))
                bad = r.get("status") == "failed"
                fails += bad
                g.hit(t, n["id"], "job runs", 1, bad)
                text = " ".join([r.get("summary", "")] + [f"{s.get('step','')} {s.get('detail','')}" for s in r.get("steps", [])])
                for other, names in machine_names.items():
                    if other != mid and any(nm and re.search(rf"(?<![\w-]){re.escape(nm)}(?![\w-])", text) for nm in names):
                        arcs[(mid, other, n["id"])] += 1
                        if t and t >= now - 86400:
                            arc_h[(mid, other, n["id"])][min(23, int((t - (now - 86400)) // HOUR))] += 1
                        if len(arc_ev[(mid, other, n["id"])]) < 3:
                            arc_ev[(mid, other, n["id"])].append(text[:140])
            if runs:
                last = runs[-1]
                n["numbers"].update({"job runs kept": len(runs), "failed of kept": fails,
                                     "last run": last.get("started_at"), "last status": last.get("status"),
                                     "last summary": (last.get("summary") or "")[:160]})
                set_health(n, "red" if last.get("status") == "failed" else "green",
                           f"last run failed {last.get('started_at','')[:16]}" if last.get("status") == "failed" else None)

        # GitHub calls
        calls = list(jsonl(files.get("gh-calls.jsonl")))
        if calls:
            ext_gh = g.node("github", type="external", machine=None, label="GitHub (gh gate)")
        refused24 = 0
        def gh_node(caller):
            grp = group_of(caller)
            nid = nid_of.get(norm(caller))
            if nid is None:
                nid = f"{mid}/gh:{grp}"
                g.node(nid, type="caller-group", machine=mid, label=f"gh callers: {grp}")
                g.edge(nid, mid, "runs-on")
                g.nodes[nid]["health"] = worse(g.nodes[nid]["health"], "green")
                g.nodes[nid]["numbers"].setdefault("callers", Counter())[display_name(caller)[:40]] += 0
            return nid, grp

        # older hours: the gate's own hourly cache (lib/github_usage, 30 days, per caller), for hours before the raw log
        first_raw = min((r.get("t") or now for r in calls), default=now)
        try:
            cache = json.loads(files.get("gh-usage-hourly.v2.json", b"{}")).get("hours", {})
        except ValueError:
            cache = {}
        if cache and ext_gh is None:
            ext_gh = g.node("github", type="external", machine=None, label="GitHub (gh gate)")
        for hk, rec in cache.items():
            t = to_epoch(hk.replace("Z", ":00Z"))
            if t is None or t + HOUR > first_raw:
                continue
            for caller, cc in (rec.get("callers") or {}).items():
                nid, _ = gh_node(caller)
                g.edge(nid, "github", "gh")
                g.hit(t, nid, "GitHub calls", cc.get("calls", 0), False)
                g.hit(t, "github", f"calls from {mid}", cc.get("calls", 0), False)

        for r in calls:
            caller = r.get("caller", "")
            nid, grp = gh_node(caller)
            e = g.edge(nid, "github", "gh")
            bad = r.get("rc", 0) != 0
            t = r.get("t")
            if t and t >= now - 86400:
                e["numbers"][(r.get("cmd") or "?")[:24]] += 1
                if bad:
                    refused24 += 1
                    e["numbers"]["non-zero exit"] += 1
                if nid.endswith(f"gh:{grp}"):
                    g.nodes[nid]["numbers"]["callers"][display_name(caller)[:40]] += 1
            g.hit(t, nid, "GitHub calls", 1, bad, e)
            g.hit(t, "github", f"calls from {mid}", 1, bad)
        if ext_gh is not None:
            ext_gh["numbers"][f"calls 24h from {mid}"] = sum(1 for r in calls if (r.get("t") or 0) >= now - 86400)
            ext_gh["numbers"][f"non-zero exits 24h from {mid}"] = refused24
            ext_gh["health"] = worse(ext_gh["health"], "green")
        for r in jsonl(files.get("gh-budget.jsonl")):
            if ext_gh is not None and (r.get("at") or 0) >= now - 86400:
                lo = min(r.get("core", 1), r.get("graphql", 1))
                ext_gh["numbers"]["lowest allowance left 24h"] = round(min(lo, ext_gh["numbers"].get("lowest allowance left 24h", 1)), 3)
        if ext_gh is not None and "lowest allowance left 24h" in ext_gh["numbers"]:
            lo = ext_gh["numbers"]["lowest allowance left 24h"]
            ext_gh["why"] = [w for w in ext_gh["why"] if not w.startswith("allowance")]
            if lo < 0.3:
                set_health(ext_gh, "red" if lo < 0.1 else "yellow", f"allowance down to {lo:.0%} in the last 24h")

        # model launches
        for r in jsonl(files.get("launches.jsonl")):
            t = to_epoch(r.get("at"))
            kind = r.get("kind") or "?"
            kid = f"{mid}/launch:{kind}"
            kn = g.node(kid, type="launch-kind", machine=mid, label=f"{kind} launches")
            g.edge(kid, mid, "runs-on")
            model = r.get("model") or "?"
            mn = g.node(f"model:{model}", type="external", machine=None, label=model)
            mn["health"] = worse(mn["health"], "green")
            e = g.edge(kid, mn["id"], "model")
            bad = (r.get("exit_code") or 0) != 0
            g.hit(t, kid, "launches", 1, bad, e)
            g.hit(t, kid, "cost usd", r.get("cost_usd") or 0)
            g.hit(t, mn["id"], "launches", 1, bad)
            if t and t >= now - 86400:
                kn["numbers"]["launches 24h"] = kn["numbers"].get("launches 24h", 0) + 1
                kn["numbers"]["cost usd 24h"] = round(kn["numbers"].get("cost usd 24h", 0) + (r.get("cost_usd") or 0), 2)
                kn["numbers"]["output tokens 24h"] = kn["numbers"].get("output tokens 24h", 0) + (r.get("output_tokens") or 0)
                kn["numbers"]["non-zero exits 24h"] = kn["numbers"].get("non-zero exits 24h", 0) + bad
                mn["numbers"]["cost usd 24h"] = round(mn["numbers"].get("cost usd 24h", 0) + (r.get("cost_usd") or 0), 2)
                e["numbers"]["output tokens"] += r.get("output_tokens") or 0
            set_health(kn, "red" if bad and t and t >= now - 86400 else "green", f"exit {r.get('exit_code')} at {r.get('at','')[:16]}" if bad else None)
            tk = r.get("ticket")
            if tk:
                T = tickets[tk]
                T["stages"][kind] += 1
                T["cost"] += r.get("cost_usd") or 0
                T["times"].append((t, kind, mid, r.get("exit_code")))
                T["machines"].add(mid)
                T["fails"] += bad
                T.setdefault("kinds_by_machine", set()).add(kid)

        # dashboard timing: who in the app spends time (name prefix), plus webhook hits
        dash = next((nid for k, nid in nid_of.items() if k.startswith("marvin-metrics")), None)
        for r in jsonl(files.get("dashboard-timing.jsonl")):
            t = to_epoch(r.get("t"))
            if dash and t:
                side = r.get("side")
                area = (r.get("name") or "?").split(":")[0].split(" ")[0]
                g.hit(t, dash, f"app {side} calls", 1, r.get("ok") is False)
                if t >= now - 86400:
                    c = g.nodes[dash]["numbers"].setdefault("app calls 24h by area", Counter())
                    c[f"{side}:{area}"] += 1
        # webhook change alarms -> the service that wrote the log, feeding the app
        wh_key = norm("dashboard-webhook.log")
        wh = nid_of.get(wh_key)
        alarms24 = 0
        for line in files.get("dashboard-webhook.log", b"").decode(errors="replace").splitlines():
            m = re.search(r"change detected on (\S+) at (\S+)", line)
            if m and wh:
                t = to_epoch(m.group(2))
                e = g.edge(dash, wh, "triggers") if dash else None
                g.hit(t, wh, "change alarms", 1, False, e)
                if t and t >= now - 86400:
                    alarms24 += 1
        if wh:
            g.nodes[wh]["numbers"]["change alarms 24h"] = alarms24

        # health checks (non-green) -> the node whose name appears in the check, else the machine
        hs = {}
        try:
            hs = json.loads(files.get("health-status.json", b"{}"))
        except ValueError:
            pass
        gen = to_epoch(hs.get("generated_at"))
        mnode = g.nodes[mid]
        mnode["numbers"]["health sweep at"] = hs.get("generated_at")
        mnode["numbers"]["health overall"] = hs.get("overall")
        if gen and now - gen > 6 * HOUR:
            set_health(mnode, "yellow", f"health sweep is {(now-gen)/86400:.1f} days old")
        cov = hs.get("coverage") or {}
        if cov:
            mnode["numbers"]["checks cover jobs"] = f"{cov.get('covered')}/{cov.get('total')}"
        mine = [n for n in g.nodes.values() if n.get("machine") == mid and n["type"] != "machine"]
        for c in hs.get("checks", []):
            sev = {"yellow": "yellow", "red": "red"}.get(c.get("severity"))
            if not sev:
                continue
            text = f"{c.get('id','')} {c.get('label','')}".lower()
            target = next((n for n in sorted(mine, key=lambda n: -len(n["id"]))
                           if n["type"] == "service" and n["id"].split("/", 1)[1] in text), None)
            if target is None and "github" in text and ext_gh is not None:
                target = ext_gh
            target = target or mnode
            set_health(target, sev, f"check {c.get('id')}: {(c.get('detail') or '')[:120]}")

    # tickets: stage counts; a ticket planned again and again in 24h is a loop
    ticket_out = []
    for tk, T in tickets.items():
        recent = [x for x in T["times"] if x[0] and x[0] >= now - 86400]
        if not recent:
            continue
        plans = sum(1 for x in recent if "planner" in x[1])
        tid = f"ticket:{tk}"
        n = g.node(tid, type="ticket", machine=None, label=tk.split("/")[-1])
        n["numbers"] = {"ticket": tk, "launches 24h": len(recent), "plans 24h": plans,
                        "stages 24h": dict(Counter(x[1] for x in recent)), "cost usd (all kept)": round(T["cost"], 2),
                        "machines": sorted(T["machines"]), "non-zero exits": T["fails"]}
        n["health"] = "red" if plans >= 5 else "yellow" if plans >= 3 else "green"
        if plans >= 3:
            n["why"].append(f"planned {plans} times in 24h (re-plan loop)")
        for kid in T["kinds_by_machine"]:
            e = g.edge(tid, kid, "ticket-run")
            for t, kind, m_, _ in recent:
                if kid == f"{m_}/launch:{kind}":
                    e["n24"] += 1
                    e["hours24"][min(23, int((t - (now - 86400)) // HOUR))] += 1
        n["load24"] = len(recent)
        ticket_out.append({"id": tid, "ticket": tk, "runs": [{"t": t, "kind": k, "machine": m_, "exit": x}
                                                              for t, k, m_, x in sorted(T["times"], key=lambda r: r[0] or 0)
                                                              if t and t >= g.start]})

    # lanes + storms
    lanes = []
    events = []
    for (nid, unit), ln in g.lanes.items():
        if not any(ln["v"]):
            continue
        n = g.nodes[nid]
        lane = {"id": f"{nid}|{unit}", "node": nid, "machine": n.get("machine"), "label": n["label"], "unit": unit,
                "v": [round(x, 2) for x in ln["v"]], "fail": ln["fail"]}
        lanes.append(lane)
        nz = [x for x in ln["v"] if x]
        if len(nz) >= 6 and (unit in ("GitHub calls", "change alarms", "launches") or unit.startswith("calls from")):
            med = statistics.median(nz)
            for i, x in enumerate(ln["v"]):
                if x >= max(100, 6 * med):
                    events.append({"kind": "storm", "lane": lane["id"], "i": i, "t": g.start + i * HOUR, "value": x,
                                   "median_hour": med, "why": f"{x:g} {unit} in one hour vs median {med:g}"})
    for T in ticket_out:
        plans = [r for r in T["runs"] if "planner" in r["kind"]]
        for k, r in enumerate(plans):
            if k == 0:
                continue
            events.append({"kind": "loop", "lane": f"{r['machine']}/launch:{r['kind']}|launches",
                           "i": int((r["t"] - g.start) // HOUR), "t": r["t"], "ticket": T["ticket"], "nth_plan": k + 1,
                           "why": f"{T['ticket']} planned for the {k+1}th time"})

    # downstream: who depends on whom (edge from = dependent). Reverse adjacency for red highlight.
    edges = []
    for e in g.edges.values():
        e = dict(e)
        e["numbers"] = dict(Counter(e["numbers"]).most_common(8))
        edges.append(e)
    for n in g.nodes.values():   # a machine's load is everything that runs on it
        if n["type"] == "machine":
            n["load24"] = sum(x["load24"] for x in g.nodes.values() if x.get("machine") == n["id"] and x is not n)
    nodes = []
    for n in g.nodes.values():
        n = dict(n)
        nums = {}
        for k, v in n["numbers"].items():
            nums[k] = dict(Counter(v).most_common(8)) if isinstance(v, Counter) else v
        n["numbers"] = nums
        nodes.append(n)
    arc_out = [{"from": a, "to": b, "via": via, "runs": c, "hours24": arc_h[(a, b, via)], "evidence": arc_ev[(a, b, via)]} for (a, b, via), c in arcs.items()]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": g.start, "end": g.end, "hours": g.H, "bucket_s": HOUR,
                   "tz_offset_min": int(datetime.now().astimezone().utcoffset().total_seconds() // 60)},
        "machines": machines, "nodes": nodes, "edges": edges, "lanes": lanes, "events": events,
        "tickets": ticket_out, "arcs": arc_out,
        "complexity": "time O(R) over R log rows + O(N*C) check matching; space O(L*H + N + E)",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "data.json"))
    a = ap.parse_args()
    t0 = time.time()
    data = build(a.days)
    Path(a.out).write_text(json.dumps(data, separators=(",", ":")))
    # also a JS copy so the views open from file:// without fetch
    Path(a.out).with_suffix(".js").write_text("window.VITALS=" + json.dumps(data, separators=(",", ":")) + ";")
    print(f"{len(data['machines'])} machines, {len(data['nodes'])} nodes, {len(data['edges'])} edges, "
          f"{len(data['lanes'])} lanes, {len(data['events'])} events, {len(data['arcs'])} arcs "
          f"in {time.time()-t0:.1f}s -> {a.out}", file=sys.stderr)
