#!/usr/bin/env python3
"""Unified wrapper for local Ollama calls, with logging and cost/token tracking.

Every local model call (embed, chat) routes through here to give MARVIN observable,
bounded, and consistent behavior around context windows and token limits.

Logs every call to ~/.claude/logs/model_calls.jsonl with timing, token counts, and
overflow flags, rotating to keep the file bounded. Estimation uses the proven ratio
(chars / 1.953) from rebuild-embeddings.py's empirical tuning of nomic-embed-text's
~2048-token context.

CLI usage:
    python3 model_calls.py summary [--days 7] [--caller X] [--model X] [--json]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

LOG_PATH = Path.home() / ".claude" / "logs" / "model_calls.jsonl"
MAX_LINES = 10000
MAX_AGE_DAYS = 90

# Tokens per character ratio derived from rebuild-embeddings.py's tuning
TOKENS_PER_CHAR = 1 / 1.953


class PromptTooLong(Exception):
    """Prompt exceeds num_ctx and on_overflow='raise'."""
    pass


class ModelCallError(Exception):
    """Network, timeout, or malformed response from Ollama."""
    pass


def estimate_tokens(text: str) -> int:
    """Rough token count from character length (nomic-embed-text tuning)."""
    if not isinstance(text, str):
        text = str(text)
    return max(1, round(len(text) * TOKENS_PER_CHAR))


def _machine() -> str:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import machine_profile
        return machine_profile.registry_id()
    except Exception:
        return socket.gethostname().split(".")[0]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _append(entry: dict, path: Path) -> None:
    """Append one JSON line and rotate if past the bounds."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        f.seek(0)
        all_lines = f.read().splitlines()
        if len(all_lines) > MAX_LINES:
            cutoff = (_now_for(entry) - timedelta(days=MAX_AGE_DAYS)).isoformat()
            keep = []
            for l in all_lines[-MAX_LINES:]:
                try:
                    if json.loads(l).get("t", "") >= cutoff:
                        keep.append(l)
                except ValueError:
                    continue
            f.seek(0)
            f.truncate()
            f.write("".join(k + "\n" for k in keep))


def _now_for(entry: dict) -> datetime:
    try:
        return datetime.fromisoformat(entry["t"])
    except (KeyError, ValueError):
        return _now()


def _record_call(endpoint: str, model: str, caller: str, prompt_tokens: int | str, response_tokens: int | str = "unknown",
                 duration_ms: int | str = "unknown", overflow_flag: bool = False, error: str = "") -> None:
    """Log one model call. Never raises."""
    try:
        entry = {
            "t": _now().isoformat(),
            "machine": _machine(),
            "endpoint": endpoint,
            "model": model,
            "caller": caller,
            "prompt_tokens": prompt_tokens if isinstance(prompt_tokens, (int, str)) else "unknown",
            "response_tokens": response_tokens if isinstance(response_tokens, (int, str)) else "unknown",
            "duration_ms": duration_ms if isinstance(duration_ms, (int, str)) else "unknown",
        }
        if overflow_flag:
            entry["possibly_truncated"] = True
        if error:
            entry["error"] = str(error)[:500]
        _append(entry, LOG_PATH)
    except Exception:
        pass


def chat(messages: list[dict], model: str, num_ctx: int = 4096, timeout: float = 60, caller: str = "",
         on_overflow: str = "trim") -> dict:
    """Call Ollama /api/chat endpoint. Returns {"message": {"content": str}, "eval_count": int, "prompt_eval_count": int, ...}

    Args:
        messages: list of {"role": "user"|"assistant", "content": str} dicts
        model: Ollama model name (e.g., "qwen2.5:14b")
        num_ctx: context window size (sent to Ollama options.num_ctx)
        timeout: request timeout in seconds
        caller: identifier for who called this (logged for attribution)
        on_overflow: "raise" to raise PromptTooLong, "trim" to silently reduce prompt size

    Raises:
        ValueError: if caller is blank or num_ctx <= 0
        PromptTooLong: if prompt exceeds num_ctx and on_overflow="raise"
        ModelCallError: network, timeout, or malformed response
    """
    if not caller or not caller.strip():
        raise ValueError("caller must be provided and non-empty")
    if num_ctx <= 0:
        raise ValueError("num_ctx must be positive")

    caller = caller.strip()

    # Estimate total prompt tokens
    prompt_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
    prompt_tokens = estimate_tokens(prompt_text)

    if prompt_tokens > num_ctx:
        if on_overflow == "raise":
            _record_call("/api/chat", model, caller, prompt_tokens, error=f"Prompt too long ({prompt_tokens} > {num_ctx})")
            raise PromptTooLong(f"Prompt estimated at {prompt_tokens} tokens, exceeds num_ctx={num_ctx}")
        elif on_overflow == "trim":
            # Trim the prompt to fit
            trim_ratio = 0.9  # keep 90% of content to be safe
            max_chars = int(len(prompt_text) * trim_ratio)
            trimmed = prompt_text[:max_chars]
            messages = [{"role": m.get("role"), "content": trimmed if m.get("role") == "user" else m.get("content")}
                        for m in messages]
            prompt_tokens = estimate_tokens(trimmed)

    if not requests:
        raise ModelCallError("requests library not available")

    start = _now()
    try:
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json={"model": model, "messages": messages, "options": {"num_ctx": num_ctx}, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        body = resp.json()

        response_tokens = body.get("eval_count", "unknown")
        prompt_eval = body.get("prompt_eval_count", "unknown")
        duration_ms = int((body.get("total_duration", 0) or 0) / 1_000_000)

        # Flag if prompt filled 90%+ of context window
        overflow_flag = False
        if isinstance(prompt_eval, int) and prompt_eval >= num_ctx * 0.9:
            overflow_flag = True

        _record_call("/api/chat", model, caller, prompt_eval, response_tokens, duration_ms, overflow_flag)
        return body
    except requests.exceptions.Timeout:
        duration_ms = int(((_now() - start).total_seconds() * 1000))
        _record_call("/api/chat", model, caller, prompt_tokens, duration_ms=duration_ms,
                     error=f"Timeout after {timeout}s")
        raise ModelCallError(f"Ollama request timed out after {timeout}s") from None
    except requests.exceptions.ConnectionError as e:
        _record_call("/api/chat", model, caller, prompt_tokens, error="Connection failed")
        raise ModelCallError(f"Cannot reach Ollama: {e}") from None
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        _record_call("/api/chat", model, caller, prompt_tokens, error=f"Malformed response: {e}")
        raise ModelCallError(f"Malformed response from Ollama: {e}") from None
    except Exception as e:
        _record_call("/api/chat", model, caller, prompt_tokens, error=str(e))
        raise ModelCallError(f"Ollama error: {e}") from None


def embed(texts: str | list[str], model: str = "nomic-embed-text", task: str = "query", num_ctx: int = 2048,
          timeout: float = 10, caller: str = "", on_overflow: str = "trim") -> list[list[float]]:
    """Call Ollama /api/embed endpoint. Returns list of embedding vectors.

    Args:
        texts: single string or list of strings to embed
        model: Ollama model name (default: nomic-embed-text)
        task: "query" or "document" (affects nomic's internal prefix)
        num_ctx: context window size (sent to Ollama options.num_ctx)
        timeout: request timeout in seconds
        caller: identifier for who called this (logged for attribution)
        on_overflow: "raise" or "trim" (see chat() above)

    Returns:
        List of embedding vectors (one per input text)

    Raises:
        ValueError: if caller is blank or num_ctx <= 0
        PromptTooLong: if any text exceeds num_ctx and on_overflow="raise"
        ModelCallError: network, timeout, or malformed response
    """
    if not caller or not caller.strip():
        raise ValueError("caller must be provided and non-empty")
    if num_ctx <= 0:
        raise ValueError("num_ctx must be positive")

    caller = caller.strip()

    if isinstance(texts, str):
        texts = [texts]

    if not texts:
        raise ValueError("texts must not be empty")

    # Build the prefixed prompts
    prefix = "search_query: " if task == "query" else "search_document: "
    prefixed = [f"{prefix}{t}" for t in texts]

    # Check for overflow
    all_tokens = sum(estimate_tokens(t) for t in texts)
    overflow_flag = False
    if all_tokens > num_ctx:
        if on_overflow == "raise":
            _record_call("/api/embed", model, caller, all_tokens, error=f"Input too long ({all_tokens} > {num_ctx})")
            raise PromptTooLong(f"Input estimated at {all_tokens} tokens, exceeds num_ctx={num_ctx}")
        else:
            overflow_flag = True

    if not requests:
        raise ModelCallError("requests library not available")

    start = _now()
    try:
        resp = requests.post(
            "http://localhost:11434/api/embed",
            json={"model": model, "input": prefixed, "options": {"num_ctx": num_ctx}},
            timeout=timeout,
        )
        resp.raise_for_status()
        body = resp.json()

        # Handle both old .embedding and new .embeddings keys
        if "embeddings" in body:
            embeddings = body["embeddings"]
        elif "embedding" in body:
            embeddings = [body["embedding"]]
        else:
            raise KeyError("Response has neither 'embeddings' nor 'embedding' field")

        response_tokens = body.get("eval_count", "unknown")
        prompt_eval = body.get("prompt_eval_count", "unknown")
        duration_ms = int((body.get("total_duration", 0) or 0) / 1_000_000)

        _record_call("/api/embed", model, caller, prompt_eval, response_tokens, duration_ms, overflow_flag)
        return embeddings
    except requests.exceptions.Timeout:
        duration_ms = int(((_now() - start).total_seconds() * 1000))
        _record_call("/api/embed", model, caller, all_tokens, duration_ms=duration_ms,
                     error=f"Timeout after {timeout}s")
        raise ModelCallError(f"Ollama request timed out after {timeout}s") from None
    except requests.exceptions.ConnectionError as e:
        _record_call("/api/embed", model, caller, all_tokens, error="Connection failed")
        raise ModelCallError(f"Cannot reach Ollama: {e}") from None
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        _record_call("/api/embed", model, caller, all_tokens, error=f"Malformed response: {e}")
        raise ModelCallError(f"Malformed response from Ollama: {e}") from None
    except Exception as e:
        _record_call("/api/embed", model, caller, all_tokens, error=str(e))
        raise ModelCallError(f"Ollama error: {e}") from None


def summary(*, days: int = 7, caller: str | None = None, model: str | None = None, json_output: bool = False) -> dict:
    """Summarize model calls by (caller, model) with percentile token counts.

    Args:
        days: include calls from the last N days
        caller: filter to specific caller (None = all)
        model: filter to specific model (None = all)
        json_output: return as JSON string instead of dict

    Returns:
        {"(caller, model)": {"calls": N, "prompt_p50": int, "prompt_p95": int, "prompt_max": int, ...}, ...}
    """
    since = (_now() - timedelta(days=days)).isoformat()
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {} if not json_output else "{}"

    stats: dict[tuple[str, str], dict] = {}
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue

        if entry.get("t", "") < since:
            continue

        if caller and entry.get("caller") != caller:
            continue
        if model and entry.get("model") != model:
            continue

        key = (entry.get("caller", "unknown"), entry.get("model", "unknown"))
        if key not in stats:
            stats[key] = {"calls": 0, "prompt_tokens": [], "response_tokens": [], "durations": []}

        stats[key]["calls"] += 1
        pt = entry.get("prompt_tokens", "unknown")
        if isinstance(pt, int):
            stats[key]["prompt_tokens"].append(pt)
        rt = entry.get("response_tokens", "unknown")
        if isinstance(rt, int):
            stats[key]["response_tokens"].append(rt)
        dur = entry.get("duration_ms", "unknown")
        if isinstance(dur, int):
            stats[key]["durations"].append(dur)

    # Compute percentiles
    result = {}
    for (c, m), vals in stats.items():
        key_str = f"{c}:{m}"
        pdata = {}
        pdata["calls"] = vals["calls"]

        if vals["prompt_tokens"]:
            sorted_pt = sorted(vals["prompt_tokens"])
            pdata["prompt_p50"] = sorted_pt[len(sorted_pt) // 2]
            pdata["prompt_p95"] = sorted_pt[int(len(sorted_pt) * 0.95)] if len(sorted_pt) > 1 else sorted_pt[0]
            pdata["prompt_max"] = max(vals["prompt_tokens"])

        if vals["response_tokens"]:
            sorted_rt = sorted(vals["response_tokens"])
            pdata["response_p50"] = sorted_rt[len(sorted_rt) // 2]
            pdata["response_p95"] = sorted_rt[int(len(sorted_rt) * 0.95)] if len(sorted_rt) > 1 else sorted_rt[0]
            pdata["response_max"] = max(vals["response_tokens"])

        if vals["durations"]:
            sorted_d = sorted(vals["durations"])
            pdata["duration_p50_ms"] = sorted_d[len(sorted_d) // 2]
            pdata["duration_p95_ms"] = sorted_d[int(len(sorted_d) * 0.95)] if len(sorted_d) > 1 else sorted_d[0]
            pdata["duration_max_ms"] = max(vals["durations"])

        result[key_str] = pdata

    if json_output:
        return json.dumps(result, indent=2)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Model call logging and analysis")
    subparsers = parser.add_subparsers(dest="command")

    summary_parser = subparsers.add_parser("summary", help="Summarize model calls")
    summary_parser.add_argument("--days", type=int, default=7, help="Include calls from the last N days")
    summary_parser.add_argument("--caller", help="Filter to specific caller")
    summary_parser.add_argument("--model", help="Filter to specific model")
    summary_parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.command == "summary":
        result = summary(days=args.days, caller=args.caller, model=args.model, json_output=args.json)
        if args.json:
            print(result)
        else:
            print(json.dumps(result, indent=2))
    else:
        parser.print_help()
