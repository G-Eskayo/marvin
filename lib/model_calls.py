#!/usr/bin/env python3
"""Unified wrapper for local Ollama model calls (chat and embed).

Provides two functions:
  chat(model, messages, *, caller, num_ctx, base_url, timeout, **options)
  embed(model, input_text, *, caller, num_ctx, base_url, timeout)

Both require explicit caller and num_ctx (no defaults — a missing one is a bug).
Pre-flight token estimation prevents silent truncation.
Post-hoc logging to ~/.claude/logs/model-calls.jsonl for observability.

Usage:
    result = model_calls.chat(
        "qwen2.5:7b",
        [{"role": "user", "content": "..."}],
        caller="logic_auditor",
        num_ctx=8192
    )

    embedding = model_calls.embed(
        "nomic-embed-text",
        "Some text to embed",
        caller="intent_classify",
        num_ctx=2048
    )

    model_calls.py summary [--days 7] [--caller X] [--model Y] [--json]
"""
from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

import requests


class PromptTooLargeError(RuntimeError):
    """Raised when estimated prompt tokens would exceed num_ctx."""
    pass


class OllamaUnavailableError(RuntimeError):
    """Raised when Ollama is unreachable or times out."""
    pass


# Default log path, mirroring error_log.py and ADR 0066/0080's outbox pattern
_DEFAULT_LOG_PATH = Path.home() / ".claude" / "logs" / "model-calls.jsonl"
_MAX_LOG_LINES = 2000
_MAX_LOG_AGE_DAYS = 30

# Token estimate heuristic: 1 token ≈ 4 characters (conservative)
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    """Rough token count using character heuristic (1 token ≈ 4 chars)."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _machine_id() -> str:
    """Get machine identifier (matches error_log.py)."""
    try:
        # Try to use registry_id if available (MARVIN convention)
        import machine_profile
        return machine_profile.registry_id()
    except Exception:
        # Fallback to hostname
        return socket.gethostname().split(".")[0]


def _now() -> datetime.datetime:
    """Current UTC time."""
    return datetime.datetime.now(datetime.timezone.utc)


def _append(entry: dict, path: Path) -> None:
    """Append one JSON line to log, with rotation when size exceeds bound.

    Mirrors error_log.py's pattern: flock while writing, rotate-in-place past
    MAX_LOG_LINES * 1.25, keeping newest MAX_LOG_LINES and anything newer than
    MAX_LOG_AGE_DAYS.

    Never raises — logging failures are swallowed, the caller's result is unaffected.
    """
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "a+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()

                # Check if rotation needed
                f.seek(0)
                all_lines = f.read().splitlines()

                if len(all_lines) > _MAX_LOG_LINES * 1.25:
                    # Keep newest MAX_LOG_LINES and anything newer than MAX_LOG_AGE_DAYS
                    cutoff = (_now() - datetime.timedelta(days=_MAX_LOG_AGE_DAYS)).isoformat()
                    keep = []

                    for line in all_lines[-_MAX_LOG_LINES:]:
                        try:
                            entry_time = json.loads(line).get("timestamp", "")
                            if entry_time >= cutoff:
                                keep.append(line)
                        except (ValueError, KeyError):
                            continue

                    # Rewrite file
                    f.seek(0)
                    f.truncate()
                    f.write("".join(k + "\n" for k in keep))
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        # Logging failures never raise
        pass


def chat(
    model: str,
    messages: list[dict],
    *,
    caller: str,
    num_ctx: int,
    base_url: str = "http://localhost:11434",
    timeout: int | float = 120,
    _log_path: Path | None = None,
    **options,
) -> dict:
    """Call Ollama /api/chat endpoint with pre-flight guard and post-hoc logging.

    Args:
        model: Model name (e.g., "qwen2.5:7b")
        messages: List of message dicts with "role" and "content"
        caller: Module/function name for telemetry (e.g., "logic_auditor")
        num_ctx: Expected context window size (raises if prompt exceeds 90%)
        base_url: Ollama server URL (default localhost:11434)
        timeout: Request timeout in seconds (default 120)
        **options: Additional Ollama options (temperature, etc.)

    Returns:
        dict with keys: "content", "prompt_tokens", "eval_count",
                       "load_duration_ms", "prompt_eval_duration_ms", "eval_duration_ms",
                       "possibly_truncated"

    Raises:
        ValueError: if messages is empty or wrong type
        TypeError: if caller or num_ctx is missing
        PromptTooLargeError: if estimated prompt tokens exceed num_ctx
        OllamaUnavailableError: on network failure, timeout, or invalid response
    """
    # Validate mandatory keyword args
    if not caller:
        raise ValueError("caller is required")
    if not num_ctx or num_ctx <= 0:
        raise ValueError("num_ctx must be a positive integer")

    # Validate input
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list")

    # Pre-flight: estimate tokens and reject if too large
    prompt_text = "".join(
        msg.get("content", "") for msg in messages if isinstance(msg, dict)
    )
    estimated_tokens = _estimate_tokens(prompt_text)

    if estimated_tokens / num_ctx >= 0.9:
        raise PromptTooLargeError(
            f"Estimated prompt tokens ({estimated_tokens}) would exceed 90% of num_ctx ({num_ctx}). "
            f"Caller: {caller}"
        )

    # Build request
    log_path = _log_path or _DEFAULT_LOG_PATH
    request_body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {**options, "num_ctx": num_ctx},
    }

    t_start = _now()
    status = "success"
    prompt_tokens = "unknown"
    eval_count = "unknown"
    load_duration_ms = None
    prompt_eval_duration_ms = None
    eval_duration_ms = None
    possibly_truncated = False
    result = None
    response_content = ""

    try:
        # Make request
        resp = requests.post(
            f"{base_url}/api/chat",
            json=request_body,
            timeout=timeout,
        )
        resp.raise_for_status()

        # Parse response
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("response is not a JSON object")

        message = data.get("message")
        if message is not None and not isinstance(message, dict):
            raise ValueError("message field is not a dict")

        response_content = (message or {}).get("content", "") if message else ""

        # Extract duration fields
        load_duration_ms = data.get("load_duration", 0) // 1_000_000 if "load_duration" in data else None
        prompt_eval_duration_ms = data.get("prompt_eval_duration", 0) // 1_000_000 if "prompt_eval_duration" in data else None
        eval_duration_ms = data.get("eval_duration", 0) // 1_000_000 if "eval_duration" in data else None

        result = {
            "content": response_content,
            "prompt_tokens": data.get("prompt_eval_count", "unknown"),
            "eval_count": data.get("eval_count", "unknown"),
            "load_duration_ms": load_duration_ms,
            "prompt_eval_duration_ms": prompt_eval_duration_ms,
            "eval_duration_ms": eval_duration_ms,
        }

        # Compute possibly_truncated flag
        pt = data.get("prompt_eval_count")
        if isinstance(pt, int) and pt >= 0:
            prompt_tokens = pt
            possibly_truncated = pt / num_ctx >= 0.9

        if isinstance(data.get("eval_count"), int):
            eval_count = data["eval_count"]

        result["possibly_truncated"] = possibly_truncated

    except (requests.ConnectionError, requests.Timeout) as e:
        status = "timeout" if isinstance(e, requests.Timeout) else "error"
        raise OllamaUnavailableError(f"Ollama unavailable ({status}): {e}")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as e:
        status = "error"
        raise OllamaUnavailableError(f"Invalid Ollama response: {e}")
    except requests.RequestException as e:
        status = "error"
        raise OllamaUnavailableError(f"Request failed: {e}")
    finally:
        # Always log (even on failure)
        log_entry = {
            "timestamp": t_start.isoformat(),
            "machine": _machine_id(),
            "caller": caller,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "eval_count": eval_count,
            "load_duration_ms": load_duration_ms,
            "prompt_eval_duration_ms": prompt_eval_duration_ms,
            "eval_duration_ms": eval_duration_ms,
            "possibly_truncated": possibly_truncated,
            "status": status,
        }
        _append(log_entry, log_path)

    return result


def embed(
    model: str,
    input_text: str,
    *,
    caller: str,
    num_ctx: int,
    base_url: str = "http://localhost:11434",
    timeout: int | float = 30,
    _log_path: Path | None = None,
) -> dict:
    """Call Ollama /api/embed endpoint with pre-flight guard and post-hoc logging.

    Args:
        model: Model name (e.g., "nomic-embed-text")
        input_text: Text to embed
        caller: Module/function name for telemetry
        num_ctx: Expected context window size
        base_url: Ollama server URL (default localhost:11434)
        timeout: Request timeout in seconds (default 30)

    Returns:
        dict with keys: "embedding", "prompt_tokens", status fields

    Raises:
        ValueError: if input_text is empty or wrong type
        TypeError: if caller or num_ctx is missing
        PromptTooLargeError: if estimated prompt tokens exceed num_ctx
        OllamaUnavailableError: on network failure, timeout, or invalid response
    """
    # Validate mandatory keyword args
    if not caller:
        raise ValueError("caller is required")
    if not num_ctx or num_ctx <= 0:
        raise ValueError("num_ctx must be a positive integer")

    # Validate input
    if not isinstance(input_text, str) or not input_text:
        raise ValueError("input_text must be a non-empty string")

    # Pre-flight: estimate tokens and reject if too large
    estimated_tokens = _estimate_tokens(input_text)

    if estimated_tokens / num_ctx >= 0.9:
        raise PromptTooLargeError(
            f"Estimated prompt tokens ({estimated_tokens}) would exceed 90% of num_ctx ({num_ctx}). "
            f"Caller: {caller}"
        )

    # Build request (use newer /api/embed endpoint, not legacy /api/embeddings)
    log_path = _log_path or _DEFAULT_LOG_PATH
    request_body = {
        "model": model,
        "input": input_text,
        "options": {"num_ctx": num_ctx, "truncate": False},
    }

    t_start = _now()
    status = "success"
    prompt_tokens = "unknown"
    possibly_truncated = False
    result = None

    try:
        # Make request
        resp = requests.post(
            f"{base_url}/api/embed",
            json=request_body,
            timeout=timeout,
        )
        resp.raise_for_status()

        # Parse response
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("response is not a JSON object")

        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) == 0:
            raise ValueError("embeddings missing or empty in response")

        embedding = embeddings[0]
        if not isinstance(embedding, list) or len(embedding) == 0:
            raise ValueError("embedding vector is not a non-empty list")

        result = {
            "embedding": embedding,
            "prompt_tokens": data.get("prompt_eval_count", "unknown"),
        }

        # Compute possibly_truncated flag
        pt = data.get("prompt_eval_count")
        if isinstance(pt, int) and pt >= 0:
            prompt_tokens = pt
            possibly_truncated = pt / num_ctx >= 0.9

        result["possibly_truncated"] = possibly_truncated

    except (requests.ConnectionError, requests.Timeout) as e:
        status = "timeout" if isinstance(e, requests.Timeout) else "error"
        raise OllamaUnavailableError(f"Ollama unavailable ({status}): {e}")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as e:
        status = "error"
        raise OllamaUnavailableError(f"Invalid Ollama response: {e}")
    except requests.RequestException as e:
        status = "error"
        raise OllamaUnavailableError(f"Request failed: {e}")
    finally:
        # Always log (even on failure)
        log_entry = {
            "timestamp": t_start.isoformat(),
            "machine": _machine_id(),
            "caller": caller,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "possibly_truncated": possibly_truncated,
            "status": status,
        }
        _append(log_entry, log_path)

    return result


def summary(days: int = 7, caller: str | None = None, model: str | None = None,
            path: Path | None = None) -> list[dict]:
    """Analyze model-calls.jsonl log and return statistical summary.

    Groups rows by (caller, model) and reports p50/p95/max prompt_tokens,
    counts of unknown/possibly_truncated rows.

    Args:
        days: Time window in days (default 7)
        caller: Filter to specific caller (optional)
        model: Filter to specific model (optional)
        path: Custom log path (default ~/.claude/logs/model-calls.jsonl)

    Returns:
        List of dicts, one per (caller, model) pair with stats.
    """
    log_path = Path(path or _DEFAULT_LOG_PATH)

    if not log_path.exists():
        return []

    cutoff = _now() - datetime.timedelta(days=days)
    rows = []

    try:
        for line in log_path.read_text(errors="ignore").strip().split("\n"):
            if not line:
                continue
            try:
                entry = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue

            # Check timestamp
            try:
                ts = datetime.datetime.fromisoformat(entry.get("timestamp", ""))
                if ts < cutoff:
                    continue
            except (ValueError, TypeError):
                pass

            # Apply filters
            if caller and entry.get("caller") != caller:
                continue
            if model and entry.get("model") != model:
                continue

            rows.append(entry)
    except (OSError, IOError):
        return []

    # Group by (caller, model)
    groups = {}
    for row in rows:
        key = (row.get("caller"), row.get("model"))
        if key not in groups:
            groups[key] = []
        groups[key].append(row)

    # Compute stats for each group
    results = []
    for (c, m), group_rows in groups.items():
        tokens = []
        unknown_count = 0
        truncated_count = 0
        error_count = 0

        for row in group_rows:
            if row.get("status") == "error" or row.get("status") == "timeout":
                error_count += 1

            pt = row.get("prompt_tokens")
            if isinstance(pt, int):
                tokens.append(pt)
            else:
                unknown_count += 1

            if row.get("possibly_truncated"):
                truncated_count += 1

        # Compute percentiles
        entry = {
            "caller": c,
            "model": m,
            "count": len(group_rows),
            "unknown_count": unknown_count,
            "truncated_count": truncated_count,
            "error_count": error_count,
        }

        if tokens:
            tokens.sort()
            n = len(tokens)
            entry["min"] = tokens[0]
            entry["p50"] = tokens[n // 2]
            entry["p95"] = tokens[int(n * 0.95)]
            entry["max"] = tokens[-1]

        results.append(entry)

    return results


def main() -> None:
    """CLI for model_calls.py."""
    parser = argparse.ArgumentParser(
        description="Analyze Ollama model call log"
    )
    subparsers = parser.add_subparsers(dest="command")

    # summary subcommand
    summary_parser = subparsers.add_parser("summary", help="Show call statistics")
    summary_parser.add_argument("--days", type=int, default=7,
                               help="Time window in days (default 7)")
    summary_parser.add_argument("--caller", help="Filter by caller")
    summary_parser.add_argument("--model", help="Filter by model")
    summary_parser.add_argument("--json", action="store_true",
                               help="Output as JSON")

    args = parser.parse_args()

    if args.command == "summary" or not args.command:
        days = getattr(args, "days", 7)
        results = summary(
            days=days,
            caller=getattr(args, "caller", None),
            model=getattr(args, "model", None),
        )

        if getattr(args, "json", False):
            print(json.dumps(results, indent=2))
        else:
            if not results:
                print("No data available.")
                return

            # Pretty-print table format
            print(f"Model Calls Summary (last {days} days)\n")

            for entry in results:
                print(f"Caller: {entry['caller']}")
                print(f"Model:  {entry['model']}")
                print(f"Calls:  {entry['count']}")

                if "p50" in entry:
                    print(f"Tokens (prompt): p50={entry['p50']} p95={entry['p95']} max={entry['max']}")

                if entry["unknown_count"]:
                    print(f"Unknown tokens: {entry['unknown_count']}")
                if entry["truncated_count"]:
                    print(f"Possibly truncated: {entry['truncated_count']}")
                if entry["error_count"]:
                    print(f"Errors: {entry['error_count']}")

                print()


if __name__ == "__main__":
    main()
