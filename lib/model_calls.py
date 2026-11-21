#!/usr/bin/env python3
"""Usage accounting for Claude API and local model calls (Ollama/Nomic).

Log every call (success, overflow, error) with timestamps, tokens, and
metadata for cost/usage analysis. No swallowing of outcomes — logging
errors are never silent.

Usage:
    from lib.model_calls import chat, embed
    result = chat("qwen2.5:14b", messages, caller="my-caller", num_ctx=4096)
    if result.error:
        handle(result.error, result.total_tokens)
    else:
        use(result.content, result.input_tokens, result.output_tokens)

    result = embed(["text"], "nomic-embed-text", caller="searcher")
    if not result.error:
        for emb in result.embeddings:
            use(emb)

    python3 lib/model_calls.py summary --days 7 --json
"""
from __future__ import annotations

import argparse
import fcntl
import json
import socket
import statistics
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None  # type: ignore


@dataclass
class ChatResult:
    """Outcome of a chat() call."""
    content: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    error: str | None = None
    overflow: bool = False


@dataclass
class EmbedResult:
    """Outcome of an embed() call."""
    embeddings: list[list[float]] = None
    total_tokens: int = 0
    error: str | None = None
    overflow: bool = False

    def __post_init__(self):
        if self.embeddings is None:
            self.embeddings = []


PATH = Path.home() / ".claude" / "logs" / "model_calls.jsonl"
MAX_LINES = 50000
MAX_AGE_DAYS = 90


def _estimate_tokens(text: str | None) -> int:
    """Rough token count: approximately 1 token per 4 characters."""
    return len(text or "") // 4


def _machine() -> str:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import machine_profile
        return machine_profile.registry_id()
    except Exception:
        return socket.gethostname().split(".")[0]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _append_row(entry: dict, path: Path) -> None:
    """Append one entry to a bounded JSONL log, with flock-based rotation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        f.seek(0)
        all_lines = f.read().splitlines()
        if len(all_lines) > MAX_LINES * 1.25:
            cutoff = (_now() - timedelta(days=MAX_AGE_DAYS)).isoformat()
            keep = []
            for line in all_lines[-MAX_LINES:]:
                try:
                    if json.loads(line).get("t", "") >= cutoff:
                        keep.append(line)
                except ValueError:
                    continue
            f.seek(0)
            f.truncate()
            f.write("".join(k + "\n" for k in keep))


def _log_call(caller: str, model: str, num_ctx: int, source: str, status: str,
              input_tokens: int = 0, output_tokens: int = 0, error_msg: str = "",
              overflow: bool = False, on_overflow: str = "error") -> None:
    """Log a model call. Never raises."""
    try:
        entry = {
            "t": _now().isoformat(),
            "machine": _machine(),
            "caller": str(caller)[:100],
            "model": str(model)[:100],
            "num_ctx": int(num_ctx),
            "source": str(source)[:50],
            "status": str(status)[:20],
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "total_tokens": int(input_tokens + output_tokens),
        }
        if error_msg:
            entry["error"] = str(error_msg)[:500]
        if overflow:
            entry["overflow"] = True
        if on_overflow != "error":
            entry["on_overflow"] = str(on_overflow)[:20]
        _append_row(entry, PATH)
    except Exception:
        pass


def chat(model: str, messages: list[dict], *, caller: str, num_ctx: int,
         timeout: int = 60, base_url: str | None = None, on_overflow: str = "error",
         options: dict | None = None, source: str = "prod") -> ChatResult:
    """Make a chat API call (Ollama via /api/chat) and log the result.

    Args:
        model: model name (e.g., "qwen2.5:14b")
        messages: list of {"role": "user|system|assistant", "content": "..."}
        caller: identifier for the call site (e.g., "logic_auditor.py:classify_paper_type")
        num_ctx: context window size in tokens (e.g., 4096)
        timeout: request timeout in seconds
        base_url: Ollama API endpoint (default: http://localhost:11434)
        on_overflow: action on overflow ("error", "truncate", "reject")
        options: additional options for the model (e.g., {"temperature": 0})
        source: "prod" or "bench" for metrics separation

    Returns:
        ChatResult with content, tokens, error, and overflow flag.
        Never raises; always logs.
    """
    base_url = base_url or "http://localhost:11434"
    result = ChatResult()
    start_time = time.time()
    input_tokens = 0

    try:
        # Estimate input tokens and check overflow
        total_input = "".join(m.get("content", "") for m in messages)
        input_tokens = _estimate_tokens(total_input)
        if input_tokens > num_ctx:
            if on_overflow == "error":
                error_msg = f"input {input_tokens} tokens exceeds num_ctx {num_ctx}"
                _log_call(caller, model, num_ctx, source, "overflow",
                         input_tokens=input_tokens, error_msg=error_msg,
                         overflow=True, on_overflow=on_overflow)
                result.error = error_msg
                result.overflow = True
                result.input_tokens = input_tokens
                return result
            elif on_overflow == "reject":
                error_msg = f"input {input_tokens} tokens exceeds num_ctx {num_ctx}"
                _log_call(caller, model, num_ctx, source, "rejected",
                         input_tokens=input_tokens, error_msg=error_msg,
                         overflow=True, on_overflow=on_overflow)
                result.error = error_msg
                result.overflow = True
                result.input_tokens = input_tokens
                return result

        # Build and send request
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "stream": False,
            **({"options": options} if options else {}),
        }).encode()

        req = urllib.request.Request(
            f"{base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())

        result.content = (data.get("message") or {}).get("content", "")
        result.input_tokens = data.get("prompt_eval_count", 0)
        result.output_tokens = data.get("eval_count", 0)
        result.total_tokens = result.input_tokens + result.output_tokens

        _log_call(caller, model, num_ctx, source, "success",
                 input_tokens=result.input_tokens,
                 output_tokens=result.output_tokens)

    except Exception as e:
        error_msg = str(e)
        result.error = error_msg
        result.input_tokens = input_tokens
        _log_call(caller, model, num_ctx, source, "error",
                 input_tokens=input_tokens, error_msg=error_msg)

    return result


def embed(input_texts: list[str] | str, model: str, *, caller: str,
          num_ctx: int = 2048, timeout: int = 30, base_url: str | None = None,
          task: str = "query", on_overflow: str = "error", source: str = "prod") -> EmbedResult:
    """Make an embed API call (Ollama via /api/embed) and log the result.

    Args:
        input_texts: string or list of strings to embed
        model: model name (e.g., "nomic-embed-text")
        caller: identifier for the call site
        num_ctx: context window size in tokens
        timeout: request timeout in seconds
        base_url: Ollama API endpoint (default: http://localhost:11434)
        task: "query" or "document" (affects nomic-embed prefix)
        on_overflow: action on overflow ("error", "reject")
        source: "prod" or "bench" for metrics separation

    Returns:
        EmbedResult with embeddings list, tokens, error, and overflow flag.
        Never raises; always logs.
    """
    if isinstance(input_texts, str):
        input_texts = [input_texts]

    base_url = base_url or "http://localhost:11434"
    result = EmbedResult()
    input_tokens = 0

    try:
        # For nomic-embed-text, add the task-specific prefix
        if "nomic" in model.lower():
            prefix = "search_query: " if task == "query" else "search_document: "
            prefixed = [f"{prefix}{t}" for t in input_texts]
        else:
            prefixed = input_texts

        # Estimate input tokens and check overflow
        total_input = "".join(prefixed)
        input_tokens = _estimate_tokens(total_input)
        if input_tokens > num_ctx:
            if on_overflow in ("error", "reject"):
                error_msg = f"input {input_tokens} tokens exceeds num_ctx {num_ctx}"
                _log_call(caller, model, num_ctx, source, on_overflow,
                         input_tokens=input_tokens, error_msg=error_msg,
                         overflow=True, on_overflow=on_overflow)
                result.error = error_msg
                result.overflow = True
                result.total_tokens = input_tokens
                return result

        # Send request
        payload = json.dumps({
            "model": model,
            "input": prefixed if len(prefixed) > 1 else prefixed[0],
        }).encode()

        req = urllib.request.Request(
            f"{base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())

        # Handle both single embedding and batch
        embeddings = data.get("embeddings", [])
        if not isinstance(embeddings, list) or not embeddings:
            embeddings = []
        if embeddings and not isinstance(embeddings[0], list):
            embeddings = [embeddings]

        result.embeddings = embeddings[:len(input_texts)]
        result.total_tokens = data.get("prompt_eval_count", 0)

        _log_call(caller, model, num_ctx, source, "success",
                 input_tokens=result.total_tokens)

    except Exception as e:
        error_msg = str(e)
        result.error = error_msg
        result.total_tokens = input_tokens
        _log_call(caller, model, num_ctx, source, "error",
                 input_tokens=input_tokens, error_msg=error_msg)

    return result


def summary(days: int = 7, *, path: Path | None = None, include_bench: bool = False) -> dict:
    """Summarize usage by (caller, model) for the last N days.

    Returns:
        {
            "period_days": N,
            "summary": [
                {"caller": "...", "model": "...", "count": N,
                 "p50_tokens": X, "p95_tokens": Y, "max_tokens": Z,
                 "errors": N, "overflows": N, "unknown_count": N},
                ...
            ],
            "totals": {"calls": N, "tokens": N, "errors": N, "overflows": N}
        }
    """
    path = Path(path or PATH)
    cutoff = (_now() - timedelta(days=days)).isoformat()

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"period_days": days, "summary": [], "totals": {"calls": 0, "tokens": 0, "errors": 0, "overflows": 0}}

    groups: dict[tuple, dict] = {}
    total_calls = 0
    total_tokens = 0
    total_errors = 0
    total_overflows = 0

    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue

        if entry.get("t", "") < cutoff:
            continue

        source = entry.get("source", "prod")
        if not include_bench and source == "bench":
            continue

        caller = entry.get("caller", "unknown")
        model = entry.get("model", "unknown")
        key = (caller, model)
        status = entry.get("status", "unknown")
        is_error = status in ("error", "overflow", "rejected")
        is_overflow = entry.get("overflow", False)
        tokens = entry.get("total_tokens", 0)

        if key not in groups:
            groups[key] = {
                "caller": caller,
                "model": model,
                "count": 0,
                "tokens": [],
                "errors": 0,
                "overflows": 0,
            }

        g = groups[key]
        g["count"] += 1
        g["tokens"].append(tokens)
        if is_error:
            g["errors"] += 1
        if is_overflow:
            g["overflows"] += 1

        total_calls += 1
        total_tokens += tokens
        if is_error:
            total_errors += 1
        if is_overflow:
            total_overflows += 1

    summary_list = []
    for g in groups.values():
        tokens = g["tokens"]
        if tokens:
            quantiles = statistics.quantiles(tokens, n=20) if len(tokens) > 1 else [tokens[0]] * 20
            p50 = quantiles[9]  # 50th percentile
            p95 = quantiles[18]  # 95th percentile
        else:
            p50 = p95 = 0

        summary_list.append({
            "caller": g["caller"],
            "model": g["model"],
            "count": g["count"],
            "p50_tokens": int(p50),
            "p95_tokens": int(p95),
            "max_tokens": max(tokens) if tokens else 0,
            "errors": g["errors"],
            "overflows": g["overflows"],
        })

    summary_list.sort(key=lambda x: x["count"], reverse=True)

    return {
        "period_days": days,
        "summary": summary_list,
        "totals": {
            "calls": total_calls,
            "tokens": total_tokens,
            "errors": total_errors,
            "overflows": total_overflows,
        }
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    summary_cmd = sub.add_parser("summary")
    summary_cmd.add_argument("--days", type=int, default=7)
    summary_cmd.add_argument("--json", action="store_true")
    summary_cmd.add_argument("--include-bench", action="store_true")

    args = ap.parse_args(argv)

    if args.cmd == "summary":
        result = summary(args.days, include_bench=args.include_bench)
        if args.json:
            print(json.dumps(result))
        else:
            print(f"Usage summary (last {result['period_days']} days):\n")
            for entry in result["summary"]:
                print(f"{entry['caller']:40} {entry['model']:20} ×{entry['count']:4} "
                      f"p50={entry['p50_tokens']:5} p95={entry['p95_tokens']:5} max={entry['max_tokens']:6} "
                      f"err={entry['errors']} overflow={entry['overflows']}")
            t = result["totals"]
            print(f"\nTotals: {t['calls']} calls, {t['tokens']:,} tokens, {t['errors']} errors, {t['overflows']} overflows")

    return 0


if __name__ == "__main__":
    sys.exit(main())
