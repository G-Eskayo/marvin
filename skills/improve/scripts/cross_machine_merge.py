#!/usr/bin/env python3
"""Reconcile MARVIN's daily outputs across Gil's registered machines
(~/.claude/marvin-network.json). Runs on every registered machine via launchd
at 09:30, after daily_digest.py (08:30) and research-colony (09:00) have both
finished.

Two different operations, two different concurrency rules:

1. Item sync (research-feed, qa-knowledge) — deterministic set-union by id.
   Safe to run on EVERY machine symmetrically: each one pulls the others'
   items and imports whatever it's missing into its own local ChromaDB. Order
   doesn't matter, it converges either way. This is what makes the machines'
   knowledge actually grow together instead of staying siloed. qa-knowledge
   sync is incremental (a per-remote sync-state cursor in
   ~/.claude/marvin-sync-state.json, filtered via dump_collection.py --since)
   so a collection that's been running for months doesn't get fully
   re-transferred every single day.

2. LLM-generated merge digest (daily-digest, research-digest) — NOT
   deterministic. Running this independently on every machine would produce a
   different merged write-up per machine, recreating the exact divergence
   problem one level up. So: only the merge authority (a "desktop"-kind
   device per marvin-network.json — less likely to be asleep/lid-closed at
   merge time than a laptop) does this Claude call, then pushes the single
   canonical result to the other machine(s).

   NOTE: this authority logic assumes exactly one desktop-kind device. With
   more than one, or more than two machines total, the pairwise-merge design
   below doesn't generalize to an N-way merge — that's a real gap, deliberately
   deferred until Gil actually adds a third device.

Every merge that touches machine-specific facts is told to preserve
attribution ("found on mac-mini-1" / "found on macbook-pro-1") rather than
generalizing it away — a pattern that only applies to one machine's install
method, OS version, etc. is a real signal, not noise to dedupe.

Machines are addressed by their Tailscale MagicDNS hostname (not a stored IP,
which can change) and identified by hardware UUID (not hostname/label, which
can be renamed or collide once a second machine of the same kind exists).

Fails silently (logs, doesn't raise) on any per-machine-connectivity problem —
matches the rest of MARVIN's background jobs, which are built not to
interrupt an interactive session over a missed background sync.
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from machine_profile import load_or_build, registry_id, remote_devices  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from daily_digest import call_claude  # noqa: E402  (shares claude-bin resolution + timeout handling)

CLAUDE_DIR     = Path.home() / ".claude"
CHROMA_PATH    = CLAUDE_DIR / "chroma"
SYNC_STATE_PATH = CLAUDE_DIR / "marvin-sync-state.json"
VENV_PYTHON    = str(Path.home() / ".agents" / "venv" / "bin" / "python")
DUMP_SCRIPT    = str(Path.home() / ".agents" / "lib" / "dump_collection.py")
LOG_PREFIX     = "[cross-machine-merge]"

MERGE_AUTHORITY_KIND = "desktop"

TODAY = date.today().isoformat()


# ── sync-state cursor (local only — never pushed to other machines) ────────

def load_sync_state() -> dict:
    if SYNC_STATE_PATH.exists():
        try:
            return json.loads(SYNC_STATE_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_sync_state(state: dict) -> None:
    SYNC_STATE_PATH.write_text(json.dumps(state, indent=2))


# ── remote helpers ──────────────────────────────────────────────────────────

def ssh_run(host: str, remote_cmd: str, timeout: int = 30) -> str | None:
    """Returns stdout on success, None on any failure (unreachable, non-zero exit, timeout)."""
    try:
        proc = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
             "-o", "StrictHostKeyChecking=accept-new", host, remote_cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            print(f"{LOG_PREFIX} remote command failed on {host} (rc={proc.returncode}): {proc.stderr[:200]}", file=sys.stderr)
            return None
        return proc.stdout
    except Exception as exc:
        print(f"{LOG_PREFIX} ssh to {host} failed: {exc}", file=sys.stderr)
        return None


def scp_push(host: str, local_path: Path, remote_path: str) -> bool:
    try:
        proc = subprocess.run(
            ["scp", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
             "-o", "StrictHostKeyChecking=accept-new", str(local_path), f"{host}:{remote_path}"],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            print(f"{LOG_PREFIX} scp push to {host} failed: {proc.stderr[:200]}", file=sys.stderr)
            return False
        return True
    except Exception as exc:
        print(f"{LOG_PREFIX} scp push to {host} failed: {exc}", file=sys.stderr)
        return False


# ── item sync (symmetric, every machine) ────────────────────────────────────

def sync_research_feed(host: str) -> None:
    local_cache = CLAUDE_DIR / "research-feed" / f"{TODAY}.json"
    if not local_cache.exists():
        print(f"{LOG_PREFIX} no local research-feed cache for {TODAY} yet — skipping", file=sys.stderr)
        return

    remote_json = ssh_run(host, f"cat ~/.claude/research-feed/{TODAY}.json")
    if remote_json is None:
        print(f"{LOG_PREFIX} could not read {host}'s research-feed for {TODAY} — skipping", file=sys.stderr)
        return

    try:
        remote_items = json.loads(remote_json)
    except json.JSONDecodeError:
        print(f"{LOG_PREFIX} {host}'s research-feed JSON malformed — skipping", file=sys.stderr)
        return

    local_items = json.loads(local_cache.read_text())
    local_urls = {i["url"] for i in local_items}
    missing = [i for i in remote_items if i["url"] not in local_urls]
    if not missing:
        print(f"{LOG_PREFIX} research-feed already in sync with {host} ({len(local_items)} local items)", file=sys.stderr)
        return

    import hashlib
    try:
        import chromadb
    except ImportError:
        print(f"{LOG_PREFIX} chromadb not installed — skipping research-feed KB import", file=sys.stderr)
        return

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    col = client.get_or_create_collection("research-feed")
    existing_ids: set[str] = set()
    offset = 0
    while True:
        page = col.get(limit=5000, offset=offset, include=[])["ids"]
        if not page:
            break
        existing_ids.update(page)
        offset += len(page)

    new_docs, new_metas, new_ids = [], [], []
    for item in missing:
        uid = "rf-" + hashlib.sha256(item["url"].encode()).hexdigest()[:16]
        if uid in existing_ids:
            continue
        new_ids.append(uid)
        new_docs.append(f"{item['title']}\n{item['summary']}")
        new_metas.append({
            "title": item["title"][:500],
            "url": item["url"][:500],
            "source": item["source"],
            "date": TODAY,
            "published": item.get("date", ""),
            "tags": item.get("tags", ""),
            "correlated": "false",
            "matched_topics": "",
            "source_machine": item.get("source_machine", "unknown"),
        })

    if new_ids:
        col.add(documents=new_docs, metadatas=new_metas, ids=new_ids)
    print(f"{LOG_PREFIX} research-feed: imported {len(new_ids)} item(s) from {host}", file=sys.stderr)


def sync_qa_knowledge(remote_id: str, host: str, sync_state: dict) -> None:
    cursor = sync_state.get(remote_id, {}).get("qa-knowledge", {}).get("last_synced_epoch", 0)

    remote_dump = ssh_run(host, f"{VENV_PYTHON} {DUMP_SCRIPT} qa-knowledge --since {cursor}", timeout=60)
    if remote_dump is None:
        print(f"{LOG_PREFIX} could not dump {remote_id}'s qa-knowledge — skipping", file=sys.stderr)
        return

    try:
        remote_data = json.loads(remote_dump)
    except json.JSONDecodeError:
        print(f"{LOG_PREFIX} {remote_id}'s qa-knowledge dump malformed — skipping", file=sys.stderr)
        return

    if not remote_data["ids"]:
        print(f"{LOG_PREFIX} qa-knowledge already in sync with {remote_id} (cursor={cursor})", file=sys.stderr)
        return

    try:
        import chromadb
    except ImportError:
        print(f"{LOG_PREFIX} chromadb not installed — skipping qa-knowledge sync", file=sys.stderr)
        return

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    col = client.get_or_create_collection("qa-knowledge")
    existing_ids: set[str] = set()
    offset = 0
    while True:
        page = col.get(limit=5000, offset=offset, include=[])["ids"]
        if not page:
            break
        existing_ids.update(page)
        offset += len(page)

    new_ids, new_docs, new_metas, max_epoch = [], [], [], cursor
    for i, rid in enumerate(remote_data["ids"]):
        meta = remote_data["metadatas"][i]
        max_epoch = max(max_epoch, meta.get("created_epoch", 0))
        if rid in existing_ids:
            continue
        new_ids.append(rid)
        new_docs.append(remote_data["documents"][i])
        # Preserve the remote entry's own source_machine tag untouched — the
        # whole point is a pattern learned on one machine still says so once
        # it's mirrored onto another.
        new_metas.append(meta)

    if new_ids:
        col.add(documents=new_docs, metadatas=new_metas, ids=new_ids)

    sync_state.setdefault(remote_id, {})["qa-knowledge"] = {
        "last_synced_epoch": max_epoch,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
    }
    print(f"{LOG_PREFIX} qa-knowledge: imported {len(new_ids)} new entry(ies) from {remote_id} (cursor now {max_epoch})", file=sys.stderr)


def sync_paper_knowledge(remote_id: str, host: str, sync_state: dict) -> None:
    """Identical shape to sync_qa_knowledge -- same deterministic-set-union-
    by-id item sync, same incremental cursor via created_epoch. Added
    2026-07-13 once paper_graph.py's record_paper() started stamping that
    field (previously only qa-knowledge had it, so this collection was
    silently uncovered by the .gitignore's claim that 'chroma/' is already
    handled by this script -- it wasn't, for this specific collection)."""
    cursor = sync_state.get(remote_id, {}).get("paper-knowledge", {}).get("last_synced_epoch", 0)

    remote_dump = ssh_run(host, f"{VENV_PYTHON} {DUMP_SCRIPT} paper-knowledge --since {cursor}", timeout=60)
    if remote_dump is None:
        print(f"{LOG_PREFIX} could not dump {remote_id}'s paper-knowledge — skipping", file=sys.stderr)
        return

    try:
        remote_data = json.loads(remote_dump)
    except json.JSONDecodeError:
        print(f"{LOG_PREFIX} {remote_id}'s paper-knowledge dump malformed — skipping", file=sys.stderr)
        return

    if not remote_data["ids"]:
        print(f"{LOG_PREFIX} paper-knowledge already in sync with {remote_id} (cursor={cursor})", file=sys.stderr)
        return

    try:
        import chromadb
    except ImportError:
        print(f"{LOG_PREFIX} chromadb not installed — skipping paper-knowledge sync", file=sys.stderr)
        return

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    col = client.get_or_create_collection("paper-knowledge")
    existing_ids: set[str] = set()
    offset = 0
    while True:
        page = col.get(limit=5000, offset=offset, include=[])["ids"]
        if not page:
            break
        existing_ids.update(page)
        offset += len(page)

    new_ids, new_docs, new_metas, max_epoch = [], [], [], cursor
    for i, rid in enumerate(remote_data["ids"]):
        meta = remote_data["metadatas"][i]
        max_epoch = max(max_epoch, meta.get("created_epoch", 0))
        if rid in existing_ids:
            continue
        new_ids.append(rid)
        new_docs.append(remote_data["documents"][i])
        new_metas.append(meta)

    if new_ids:
        col.add(documents=new_docs, metadatas=new_metas, ids=new_ids)

    sync_state.setdefault(remote_id, {})["paper-knowledge"] = {
        "last_synced_epoch": max_epoch,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
    }
    print(f"{LOG_PREFIX} paper-knowledge: imported {len(new_ids)} new entry(ies) from {remote_id} (cursor now {max_epoch})", file=sys.stderr)


# ── LLM-generated merge (desktop-kind authority only) ───────────────────────

def profile_blurb(profile: dict) -> str:
    return (
        f"{profile.get('label', 'unknown')} — {profile.get('mobility_class', '?')}, "
        f"macOS {profile.get('macos_version', '?')}, "
        f"Python {profile.get('python_venv_version', '?')}, "
        f"claude via {profile.get('claude_install_method', '?')}"
    )


MERGE_PROMPT_TEMPLATE = """You are merging today's independently-generated MARVIN output from two of Gil's machines into one combined write-up.

--- MACHINE A: {label_a} ---
{profile_a}

--- MACHINE B: {label_b} ---
{profile_b}

--- {label_a} output ---
{content_a}

--- {label_b} output ---
{content_b}

Merge these into one combined write-up:
- Deduplicate anything that's genuinely the same point made on both machines.
- CRITICAL: if something is specific to one machine's environment (install method, OS version, hardware, a bug that only reproduces on one of them), KEEP that attribution explicit — label it "(seen on {label_a})" or "(seen on {label_b})" rather than generalizing it into a universal statement. Two machines behaving differently is signal, not noise — don't erase it by merging it away.
- If both machines found the same actionable item, state it once, but note it was confirmed on both.
- Keep the original section structure of the source material where it makes sense.
"""


def build_merged(label_a: str, profile_a: dict, content_a: str,
                  label_b: str, profile_b: dict, content_b: str) -> str:
    prompt = MERGE_PROMPT_TEMPLATE.format(
        label_a=label_a, profile_a=profile_blurb(profile_a), content_a=content_a,
        label_b=label_b, profile_b=profile_blurb(profile_b), content_b=content_b,
    )
    return call_claude(prompt)


def run_merge_authority(remote_id: str, host: str, own_profile: dict) -> None:
    remote_profile_json = ssh_run(host, "cat ~/.claude/machine-profile.json")
    remote_profile = json.loads(remote_profile_json) if remote_profile_json else {}
    remote_label = remote_profile.get("label", remote_id)
    own_label = own_profile.get("label", registry_id())

    for kind, local_dir in (
        ("daily-digest", CLAUDE_DIR / "daily-digest"),
        ("research-digest", CLAUDE_DIR / "research-digest"),
    ):
        local_file = local_dir / f"{TODAY}.md"
        merged_file = local_dir / f"{TODAY}-merged.md"
        remote_relpath = f"~/.claude/{kind}/{TODAY}.md"

        if merged_file.exists():
            print(f"{LOG_PREFIX} {kind} merge for {TODAY} already exists — skipping", file=sys.stderr)
            continue
        if not local_file.exists():
            print(f"{LOG_PREFIX} own {kind} for {TODAY} not written yet — skipping merge", file=sys.stderr)
            continue

        remote_content = ssh_run(host, f"cat {remote_relpath}")
        if remote_content is None:
            print(f"{LOG_PREFIX} {remote_id}'s {kind} for {TODAY} unavailable — skipping merge (may not have run yet)", file=sys.stderr)
            continue

        print(f"{LOG_PREFIX} merging {kind} with {remote_id}...", file=sys.stderr)
        merged = build_merged(
            own_label, own_profile, local_file.read_text(),
            remote_label, remote_profile, remote_content,
        )

        header = (
            f"# MARVIN {kind.replace('-', ' ').title()} — Merged — {TODAY}\n\n"
            f"> Combined from {own_label} and {remote_label} by `cross_machine_merge.py` "
            f"at {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n\n"
        )
        merged_file.write_text(header + merged + "\n")
        print(f"{LOG_PREFIX} wrote {merged_file}", file=sys.stderr)

        if scp_push(host, merged_file, f"~/.claude/{kind}/{TODAY}-merged.md"):
            print(f"{LOG_PREFIX} pushed merged {kind} to {remote_id}", file=sys.stderr)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    own_profile = load_or_build(max_age_hours=0)  # always refresh — this is the one daily point we snapshot it
    my_id = registry_id()
    remotes = remote_devices()

    print(f"{LOG_PREFIX} running as {my_id} ({own_profile.get('label')}), {len(remotes)} remote(s) registered", file=sys.stderr)

    if not remotes:
        print(f"{LOG_PREFIX} no other devices in marvin-network.json — nothing to sync", file=sys.stderr)
        return

    sync_state = load_sync_state()
    # mobility_class "stationary" is machine_profile.py's own term for exactly
    # what marvin-network.json calls kind "desktop" — this machine is the
    # merge authority iff it's the stationary one.
    we_are_authority = own_profile.get("mobility_class") == "stationary"

    for remote_id, info in remotes.items():
        host = info.get("tailscale_hostname")
        if not host:
            print(f"{LOG_PREFIX} {remote_id} has no tailscale_hostname registered — skipping", file=sys.stderr)
            continue

        sync_research_feed(host)
        sync_qa_knowledge(remote_id, host, sync_state)
        sync_paper_knowledge(remote_id, host, sync_state)

        if we_are_authority:
            run_merge_authority(remote_id, host, own_profile)
        else:
            print(f"{LOG_PREFIX} not the merge authority ({remote_id} may be, or neither is) — item sync only", file=sys.stderr)

    save_sync_state(sync_state)


if __name__ == "__main__":
    main()
