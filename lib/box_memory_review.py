#!/usr/bin/env python3
"""box_memory_review.py — memories and handoffs made on the Linux box reach shared memory through layered trust with
review (ADR 0082). Runs on the primary Mac (the Mini).

- **pull**: runs `box_memory_export.py export` on the box over ssh (the box never pushes) and reads its JSON, capped.
  A box that is offline or drops mid-transfer changes nothing. Every item is untrusted: checked (box_memory_items.check:
  kind, plain name, size, hidden characters, recomputed id), scanned (push-guard patterns, instruction-shaped text,
  the safety monitor's judge, which fails closed here), and never trusted for anything it says about itself. An id
  already seen is ignored, so a replay does nothing.
- **Trust layers**: kind x risk (a feedback/user memory is high risk). A layer passes on its own after N clean
  approvals in a row (config/box_memory_trust.json; null = never), counted with trust_ramp.py in its own file. A flagged
  item, Block, Fix it or a revert resets its layer. A flagged item or a collision (the Mac's file changed since the box
  read it) never passes on its own.
- **Held items** are `box_memory` entries in ~/.claude/quarantine.md, so they show as cards in Health > Safety reviews.
  **settle** reads the answer from the ticked entry itself (a file the box cannot write), never from calibration
  labels (the primary's webhook takes labels from any Tailscale host, the box included). Fine applies, Block drops,
  Fix it drops with the note. The answer is then recorded as a calibration label and the entry removed.
- **Audit**: ~/.claude/box-memory/audit.jsonl keeps what each apply replaced; `revert <audit id>` restores it if the
  file is untouched since, and resets the layer.

    box_memory_review.py pull | settle | status | audit | revert AUDIT_ID

Cost: O(items in one export) per pull, plus one judge call per new item with content; settle is O(quarantine.md).
"""
from __future__ import annotations

import difflib
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ENGINE = Path(__file__).resolve().parents[1]
SAFETY = ENGINE / "skills" / "safety-monitor" / "scripts"
sys.path.insert(0, str(ENGINE / "lib"))
sys.path.insert(0, str(SAFETY))
import box_memory_items as bi  # noqa: E402
import process_quarantine_reviews as pqr  # noqa: E402
import trust_ramp  # noqa: E402

LOOP = "box_memory"
CONFIG_PATH = ENGINE / "config" / "box_memory_trust.json"
PUSH_GUARD = ENGINE / "config" / "push-guard" / "patterns.txt"
EXPORT_CMD = "~/.agents/venv/bin/python ~/.agents/lib/box_memory_export.py export"
FETCH_TIMEOUT_S = 120
LOCK_TIMEOUT_S = 5.0

INSTRUCTION_SHAPES = [
    (r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|any|other)\b.{0,30}"
     r"\b(instructions?|rules?|prompts?|guidelines?)\b", "an instruction to drop earlier rules"),
    (r"\byou are now\b|\bfrom now on,? you\b|\bnew instructions?\b", "an instruction to future sessions"),
    (r"\b(system|developer)\s+(prompt|message)\b|</?\s*(system|assistant|instructions?)\s*>", "a fake system message"),
    (r"\b(curl|wget)\b[^\n]{0,200}\|\s*(ba|z)?sh\b", "a command that runs downloaded code"),
    (r"\b(auto[- ]?approve|approve (it )?without|skip (the )?review|bypass (the )?(review|guard|gate|hook|check))",
     "an instruction to skip a review"),
    (r"--dangerously|authorized_keys|\.credentials\.json|private-push-patterns", "a reference to keys or guards"),
    (r"\bbase64\b.{0,20}(-d|--decode)|[A-Za-z0-9+/]{200,}={0,2}", "an encoded blob"),
]
HIGH_NAME = re.compile(r"^(feedback|user)[-_]", re.IGNORECASE)
HIGH_TYPE = re.compile(r"^\s*type:\s*[\"']?(feedback|user)\b", re.IGNORECASE | re.MULTILINE)

TITLES = {"memory-new": "New memory", "memory-edit": "Edit to memory", "memory-delete": "Delete memory",
          "handoff": "Handoff", "handoff-delete": "Delete handoff"}


class BoxError(Exception):
    """The box couldn't be read: offline, dropped mid-transfer, or sent too much."""


def _home_slug() -> str:
    return str(Path.home()).replace("/", "-")


def _registry_box() -> str | None:
    try:
        data = json.loads((Path.home() / ".claude" / "marvin-network.json").read_text())
    except (OSError, ValueError):
        return None
    for info in (data.get("devices") or {}).values() if isinstance(data, dict) else []:
        if isinstance(info, dict) and info.get("os") == "linux" and info.get("tailscale_hostname"):
            return str(info["tailscale_hostname"])
    return None


def run_capped(argv: list[str], cap: int = bi.BUNDLE_CAP, timeout: float = FETCH_TIMEOUT_S) -> bytes:
    """stdout of argv, refused (BoxError) when it exits non-zero, runs past `timeout`, or writes more than `cap`
    bytes. Never reads more than cap + 1 bytes into memory."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    try:
        chunks, size = [], 0
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > cap:
                proc.kill()
                proc.wait()
                raise BoxError(f"too big: more than {cap} bytes")
            chunks.append(chunk)
        rc = proc.wait()
    finally:
        timer.cancel()
        if proc.stdout:
            proc.stdout.close()
    if rc != 0:
        raise BoxError(f"exit {rc}")
    return b"".join(chunks)


def ssh_fetch() -> bytes:
    host = os.environ.get("MARVIN_BOX_HOST") or _registry_box()
    if not host or not re.match(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$", host):
        raise BoxError("no Linux box in the network registry")
    return run_capped(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, EXPORT_CMD])


def judge(text: str) -> float | None:
    import verify
    return verify.verify(text, LOOP, fail_value=None)


def _tau() -> float:
    import calibrate
    return calibrate.get_tau(LOOP)


def _labeler(loop, score, label, note, entry_id) -> None:
    import shared_labels
    shared_labels.submit(loop, score, label, note=note, entry_id=entry_id)


@dataclass
class Ctx:
    memory_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "projects" / _home_slug() / "memory")
    handoffs_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "handoffs")
    state_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "box-memory")
    quarantine: Path = field(default_factory=lambda: pqr.QUARANTINE_FILE)
    config_path: Path = CONFIG_PATH
    fetch: Callable[[], bytes] = ssh_fetch
    scorer: Callable[[str], float | None] = judge
    tau: Callable[[], float] = _tau
    labeler: Callable = _labeler
    now: Callable[[], float] = time.time

    @property
    def store_path(self) -> Path:
        return Path(self.state_dir) / "items.json"

    @property
    def audit_path(self) -> Path:
        return Path(self.state_dir) / "audit.jsonl"

    @property
    def ramp_path(self) -> Path:
        return Path(self.state_dir) / "trust-ramp.json"


# --- state -------------------------------------------------------------------------------------------------------

@contextmanager
def _locked(ctx: Ctx, timeout: float = LOCK_TIMEOUT_S):
    Path(ctx.state_dir).mkdir(parents=True, exist_ok=True)
    fd = os.open(Path(ctx.state_dir) / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise TimeoutError("box memory review is busy")
                time.sleep(0.02)
        yield
    finally:
        os.close(fd)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _load_store(ctx: Ctx) -> dict:
    try:
        data = json.loads(ctx.store_path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        # Never start over silently: a lost store would make every old item look new (a replay).
        raise RuntimeError(f"{ctx.store_path} is unreadable; fix or move it by hand")
    if not isinstance(data, dict):
        raise RuntimeError(f"{ctx.store_path} is not a JSON object")
    return data


def _save_store(ctx: Ctx, store: dict) -> None:
    _write_text(ctx.store_path, json.dumps(store, indent=1))


def _audit(ctx: Ctx, row: dict) -> None:
    ctx.audit_path.parent.mkdir(parents=True, exist_ok=True)
    with ctx.audit_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()
        os.fsync(f.fileno())


def audit_rows(ctx: Ctx) -> list[dict]:
    rows = []
    try:
        for line in ctx.audit_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except FileNotFoundError:
        pass
    return rows


def _load_config(ctx: Ctx) -> dict:
    """{layer: N or None}. Unreadable means every layer waits for Gil."""
    try:
        needed = json.loads(Path(ctx.config_path).read_text())["needed"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    if not isinstance(needed, dict):
        return {}
    return {k: v for k, v in needed.items()
            if v is None or (isinstance(v, int) and not isinstance(v, bool) and v > 0)}


# --- trust layers -------------------------------------------------------------------------------------------------

def is_high(name: str, *texts: str | None) -> bool:
    if HIGH_NAME.match(name):
        return True
    return any(t and HIGH_TYPE.search(t[:4000]) for t in texts)


def layer_of(item: dict, mac_text: str | None) -> str:
    kind = item["kind"]
    if kind in bi.MEMORY_KINDS:
        return f"{kind}.{'high' if is_high(item['name'], item.get('content'), mac_text) else 'normal'}"
    return kind


def _ramp_key(layer: str) -> str:
    return f"box-memory/{layer}"


def _ramp_pr(item_id: str) -> int:
    return int(item_id, 16) % 10**15 + 1


def _streak(ctx: Ctx, layer: str) -> int:
    st = trust_ramp.status(path=ctx.ramp_path)
    if not st and ctx.ramp_path.exists():
        return 0   # unreadable ramp: closed
    for name, s in st.items():
        if name.lower() == _ramp_key(layer).lower():
            return int(s.get("streak", 0))
    return 0


def _ramp(ctx: Ctx, layer: str, item_id: str, event: str, reason: str = "") -> None:
    try:
        trust_ramp.record(_ramp_key(layer), _ramp_pr(item_id), event, path=ctx.ramp_path, reason=reason)
    except ValueError as e:  # a corrupt ramp file stays as it is (closed for everyone); say so
        _report(f"trust layer {layer} not updated: {e}")


def layer_status(ctx: Ctx) -> dict:
    config = _load_config(ctx)
    out = {}
    for layer, needed in sorted(config.items()):
        streak = _streak(ctx, layer)
        out[layer] = {"needed": needed, "streak": streak, "open": needed is not None and streak >= needed}
    return out


# --- scanning -----------------------------------------------------------------------------------------------------

def _push_guard_patterns() -> list[re.Pattern]:
    out = []
    try:
        lines = PUSH_GUARD.read_text().splitlines()
    except OSError:
        return out
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        try:
            out.append(re.compile(ln.strip()))
        except re.error:
            continue
    return out


def scan(text: str) -> list[str]:
    """Why this text is flagged (plain reasons, never the matching text itself), or []."""
    reasons = []
    if any(p.search(text) for p in _push_guard_patterns()):
        reasons.append("matches a push-guard pattern (a secret or transcript shape)")
    for pattern, why in INSTRUCTION_SHAPES:
        if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
            reasons.append(f"looks like {why}")
    return reasons


def _redact(text: str) -> str:
    for p in _push_guard_patterns():
        text = p.sub("[hidden: matches a push-guard pattern]", text)
    return text


# --- applying -----------------------------------------------------------------------------------------------------

def _target(ctx: Ctx, item: dict) -> Path:
    folder = Path(ctx.handoffs_dir if item["kind"] in bi.HANDOFF_KINDS else ctx.memory_dir)
    name = item["name"]
    if (name != bi.INDEX and not bi.NAME_RE.match(name)) or "/" in name or name in (".", ".."):
        raise ValueError("bad name")
    path = folder / name
    if path.is_symlink() or path.parent.resolve() != folder.resolve():
        raise ValueError("target is not a plain file in its folder")
    return path


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _sha(text: str | None) -> str | None:
    return None if text is None else bi.sha(text)


def _after(item: dict, before: str | None) -> str | None:
    kind = item["kind"]
    if kind in bi.DELETES:
        return None
    if kind != "index-line":
        return item["content"]
    line = item["content"]
    lines = (before or "").splitlines()
    if item["op"] == "add":
        if line in lines:
            return before
        text = before or ""
        return text + ("" if not text or text.endswith("\n") else "\n") + line + "\n"
    if line not in lines:
        return before
    lines.remove(line)
    return "\n".join(lines) + ("\n" if lines else "")


def _write_or_remove(path: Path, text: str | None) -> None:
    if text is None:
        path.unlink(missing_ok=True)
    else:
        _write_text(path, text)


def _apply(ctx: Ctx, rec: dict, by: str) -> dict:
    item = rec["item"]
    path = _target(ctx, item)
    before = _read(path)
    after = _after(item, before)
    row = {"audit_id": bi.sha(f"{item['id']}:{ctx.now()}")[:16], "item": item["id"], "layer": rec["layer"],
           "kind": item["kind"], "name": item["name"], "op": item.get("op"), "line": item["content"]
           if item["kind"] == "index-line" else None, "by": by, "at": ctx.now(), "before": before,
           "after_sha": _sha(after)}
    _audit(ctx, row)   # first: nothing changes that the log can't put back
    if after != before:
        _write_or_remove(path, after)
    return row


# --- the review card ----------------------------------------------------------------------------------------------

def _fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _card_text(item: dict, mac_text: str | None) -> str:
    kind, name = item["kind"], item["name"]
    if kind == "index-line":
        verb = "Add to" if item["op"] == "add" else "Remove from"
        return f"**{verb} MEMORY.md** from the Linux box · item {item['id']}\n\n{_redact(item['content'])}"
    head = f"**{TITLES[kind]}** `{name}` from the Linux box · item {item['id']}"
    if kind in bi.DELETES:
        body = mac_text if mac_text is not None else "(already gone on this Mac)"
        f = _fence(body)
        return f"{head}\n\nWhat would be deleted:\n\n{f}\n{_redact(body)}\n{f}"
    content = _redact(item["content"])
    if mac_text is not None and kind in ("memory-edit", "handoff"):
        diff = "\n".join(difflib.unified_diff(_redact(mac_text).splitlines(), content.splitlines(),
                                              "on this Mac", "from the box", lineterm=""))
        f = _fence(diff)
        return f"{head}\n\n{f}diff\n{diff}\n{f}"
    f = _fence(content)
    return f"{head}\n\n{f}\n{content}\n{f}"


def _hold_block(ctx: Ctx, item: dict, mac_text: str | None, score: float, tau: float, reasons: list[str]) -> str:
    today = datetime.fromtimestamp(ctx.now(), timezone.utc).strftime("%Y-%m-%d")
    # splitlines(): the same line ends the review parser uses, so no line of box text can ever start unquoted.
    quoted = "\n".join(f"> {ln}" if ln else ">" for ln in _card_text(item, mac_text).splitlines())
    reason = "; ".join(reasons)
    return (f"## {today} — {LOOP} [SAFETY, score {score:.2f}, tau {tau:.2f}]\n{quoted}\n\n"
            f"Flagged reason: {reason}\n\n" + pqr.FOOTER)


def _hold(ctx: Ctx, block: str) -> str:
    """Appends the card to quarantine.md through the review's own lock; returns its entry id."""
    path = Path(ctx.quarantine)
    with pqr.locked(path):
        existing = _read(path)
        if existing is None:
            existing = ("# Quarantine\n\nArtifacts flagged by the safety monitor, awaiting review. For each item: check "
                        "approve (ships as-is), modify (note the correction), or deny.\n")
        pqr.atomic_write(path, existing + "\n---\n" + block)
    return pqr.entry_id(block)


# --- pull ---------------------------------------------------------------------------------------------------------

def _report(message: str, raw: str = "") -> None:
    print(f"[box-memory] {message}", file=sys.stderr)
    try:
        import error_log
        error_log.record("box-memory", message, raw=raw)
    except Exception:
        pass


def _collision(item: dict, mac_text: str | None) -> bool:
    kind = item["kind"]
    if kind == "index-line":
        return False
    if item["base"] is None:   # a new memory or a new handoff
        return mac_text is not None and mac_text != item["content"]
    return _sha(mac_text) != item["base"]


def _nothing_to_do(item: dict, mac_text: str | None) -> bool:
    return _after(item, mac_text) == mac_text


def assess(ctx: Ctx, item: dict, config: dict) -> dict:
    path = _target(ctx, item)
    mac_text = _read(path)
    layer = layer_of(item, mac_text)
    reasons: list[str] = []
    text = item.get("content")
    flags = scan(f"{item['name']}\n{text or ''}")
    score: float | None = 0.0
    if text is not None:
        try:
            score = ctx.scorer(text)
        except Exception:
            score = None
    tau = ctx.tau()
    judged_risky = score is not None and score >= tau
    if judged_risky:
        flags.append(f"safety monitor risk {score:.2f}")
    collision = _collision(item, mac_text)
    needed = config.get(layer)
    streak = _streak(ctx, layer)
    open_ = needed is not None and streak >= needed
    reasons += [f"flagged: {f}" for f in flags]
    if collision:
        reasons.append("changed on a Mac since the box read it")
    if score is None:
        reasons.append("not scored by the safety monitor")
    if needed is None:
        reasons.append(f"{layer} always waits for you")
    elif not open_:
        reasons.append(f"{layer}: {min(streak, needed)} of {needed} clean approvals")
    auto = open_ and not flags and not collision and score is not None
    return {"item": item, "layer": layer, "flagged": bool(flags), "reasons": reasons, "score": score or 0.0,
            "tau": tau, "collision": collision, "auto": auto, "mac_text": mac_text,
            "noop": _nothing_to_do(item, mac_text)}


def _parse_bundle(raw: bytes) -> list:
    if len(raw) > bi.BUNDLE_CAP:
        raise BoxError("too big")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BoxError("torn or not JSON (the box may have dropped mid-transfer)")
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("items"), list):
        raise BoxError("not an export")
    if len(data["items"]) > bi.MAX_ITEMS:
        raise BoxError(f"more than {bi.MAX_ITEMS} items")
    return data["items"]


def pull(ctx: Ctx | None = None) -> dict:
    ctx = ctx or Ctx()
    out = {"status": "ok", "new": 0, "auto": 0, "held": 0, "ignored": 0, "refused": 0, "nothing": 0}
    try:
        items = _parse_bundle(ctx.fetch())
    except BoxError as e:
        _report(f"pull from the box failed: {e}")
        return {**out, "status": "failed", "error": str(e)}
    with _locked(ctx, timeout=60):
        store = _load_store(ctx)
        config = _load_config(ctx)
        refusals = []
        for raw in items:
            why = bi.check(raw)
            if why:
                out["refused"] += 1
                refusals.append(why)
                continue
            item = {k: raw[k] for k in ("kind", "name", "base", "content", "op", "id")}  # nothing else is read
            if item["id"] in store:
                out["ignored"] += 1
                continue
            try:
                a = assess(ctx, item, config)
            except ValueError as e:
                out["refused"] += 1
                refusals.append(str(e))
                continue
            rec = {"item": item, "layer": a["layer"], "flagged": a["flagged"], "reasons": a["reasons"],
                   "score": a["score"], "collision": a["collision"], "received": ctx.now()}
            out["new"] += 1
            if a["flagged"]:
                _ramp(ctx, a["layer"], item["id"], "break", "; ".join(a["reasons"])[:300])
            if a["noop"]:
                rec["status"] = "nothing-to-do"
                out["nothing"] += 1
            elif a["auto"]:
                row = _apply(ctx, rec, by="auto")
                rec.update(status="auto-applied", audit_id=row["audit_id"])
                out["auto"] += 1
            else:
                block = _hold_block(ctx, item, a["mac_text"], a["score"], a["tau"], a["reasons"])
                rec.update(status="held", qid=_hold(ctx, block))
                out["held"] += 1
            store[item["id"]] = rec
            _save_store(ctx, store)
        if refusals:
            _report(f"{len(refusals)} item(s) from the box refused", raw=json.dumps(refusals[:50]))
    out["settled"] = settle(ctx).get("decided", 0)
    return out


# --- settle -------------------------------------------------------------------------------------------------------

def _remove_entries(path: Path, eids: set[str]) -> None:
    """Removes answered box_memory entries (their own lines; the trailing divider stays, as the review does)."""
    with pqr.locked(path):
        text = _read(path)
        if text is None:
            return
        preamble, blocks = pqr._split_entries(text)
        out = [preamble] + [pqr._tail(b) if pqr.entry_id(b) in eids else b for b in blocks]
        new = "".join(out)
        if new != text:
            pqr.atomic_write(path, new)


def settle(ctx: Ctx | None = None) -> dict:
    """Acts on every answered box_memory card: Fine applies, Block drops, Fix it drops with the note."""
    ctx = ctx or Ctx()
    if not _answered(ctx):   # the common case touches nothing but quarantine.md
        return {"status": "ok", "decided": 0}
    try:
        with _locked(ctx, timeout=LOCK_TIMEOUT_S):
            return _settle_locked(ctx)
    except TimeoutError:
        return {"status": "busy", "decided": 0}


def _answered(ctx: Ctx) -> list[tuple[str, str, str | None]]:
    text = _read(Path(ctx.quarantine)) or ""
    answered = []
    for b in pqr._split_entries(text)[1]:
        info = pqr._parse_block(b)
        if info and info["loop_name"] == LOOP and info["checked"]:
            answered.append((pqr.entry_id(b), info["checked"], info["note"]))
    return answered


def _settle_locked(ctx: Ctx) -> dict:
    answered = _answered(ctx)
    if not answered:
        return {"status": "ok", "decided": 0}
    store = _load_store(ctx)
    by_qid = {r.get("qid"): r for r in store.values() if r.get("status") == "held"}
    done: set[str] = set()
    decided = 0
    for eid, kind, note in answered:
        rec = by_qid.get(eid)
        if rec is None:
            _report(f"an answered box memory card ({eid}) has no item on this Mac; removed")
            done.add(eid)
            continue
        item = rec["item"]
        try:
            if kind == "approve":
                row = _apply(ctx, rec, by="gil")
                rec.update(status="applied", audit_id=row["audit_id"])
                if not rec.get("flagged"):
                    _ramp(ctx, rec["layer"], item["id"], "approved-merge")
            else:
                rec["status"] = "fix-requested" if kind == "modify" else "dropped"
                if note:
                    rec["note"] = note
                _ramp(ctx, rec["layer"], item["id"], "deny", f"{kind}: {note or ''}"[:300])
        except (OSError, ValueError) as e:
            rec["status"] = "failed"
            rec["error"] = str(e)[:300]
            _report(f"box item {item['id']} could not be applied: {e}")
        rec["decided"] = ctx.now()
        _save_store(ctx, store)
        try:
            ctx.labeler(LOOP, float(rec.get("score") or 0.0), 1 if kind == "deny" else 0, note, eid)
        except Exception as e:  # the decision stands; only the calibration misses it
            print(f"[box-memory] label not recorded: {e}", file=sys.stderr)
        done.add(eid)
        decided += 1
    _remove_entries(Path(ctx.quarantine), done)
    return {"status": "ok", "decided": decided}


# --- revert -------------------------------------------------------------------------------------------------------

def revert(audit_id: str, ctx: Ctx | None = None) -> dict:
    ctx = ctx or Ctx()
    with _locked(ctx, timeout=30):
        rows = audit_rows(ctx)
        row = next((r for r in rows if r.get("audit_id") == audit_id and not r.get("revert_of")), None)
        if row is None:
            return {"status": "unknown"}
        if any(r.get("revert_of") == audit_id for r in rows):
            return {"status": "already-reverted"}
        store = _load_store(ctx)
        rec = store.get(row["item"]) or {"item": {"kind": row["kind"], "name": row["name"]}}
        item = {**rec["item"], "kind": row["kind"], "name": row["name"]}
        path = _target(ctx, item)
        current = _read(path)
        if row["kind"] == "index-line":
            inverse = {"kind": "index-line", "name": bi.INDEX, "content": row["line"],
                       "op": "remove" if row["op"] == "add" else "add"}
            restored = _after(inverse, current)
        else:
            if _sha(current) != row["after_sha"]:
                return {"status": "changed-since"}
            restored = row["before"]
        _audit(ctx, {"audit_id": bi.sha(f"revert:{audit_id}:{ctx.now()}")[:16], "revert_of": audit_id,
                     "item": row["item"], "layer": row["layer"], "kind": row["kind"], "name": row["name"],
                     "by": "gil", "at": ctx.now(), "before": current, "after_sha": _sha(restored)})
        if restored != current:
            _write_or_remove(path, restored)
        _ramp(ctx, row["layer"], row["item"], "revert", f"reverted {audit_id}")
        if row["item"] in store:
            store[row["item"]]["status"] = "reverted"
            _save_store(ctx, store)
        return {"status": "reverted"}


# --- CLI ----------------------------------------------------------------------------------------------------------

def _is_primary() -> bool:
    try:
        import shared_labels
        return shared_labels.is_primary()
    except Exception:
        return False


def main(argv: list[str]) -> int:
    cmd = argv[:1]
    if cmd in (["pull"], ["settle"]) and not _is_primary():
        print(json.dumps({"status": "skipped", "reason": "not the primary Mac"}))
        return 0
    if cmd == ["pull"]:
        print(json.dumps(pull()))
    elif cmd == ["settle"]:
        print(json.dumps(settle()))
    elif cmd == ["status"]:
        print(json.dumps(layer_status(Ctx()), indent=1))
    elif cmd == ["audit"]:
        for r in audit_rows(Ctx())[-50:]:
            what = f"revert of {r['revert_of']}" if r.get("revert_of") else r.get("kind")
            print(f"{r.get('audit_id')}  {datetime.fromtimestamp(r.get('at', 0)):%Y-%m-%d %H:%M}  "
                  f"{r.get('by'):<4}  {what:<16} {r.get('name')}")
    elif cmd == ["revert"] and len(argv) == 2 and re.match(r"^[0-9a-f]{16}$", argv[1]):
        print(json.dumps(revert(argv[1])))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
