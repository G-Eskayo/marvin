#!/usr/bin/env python3
"""
ollama_chat.py — shared Ollama chat utility for paper-dive synthesis tools.

Kept beside the scripts (not ~/.agents/lib) because paper-dive ships as a
standalone skill and needs its own dependencies bundled within the skill.
"""
import json
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/chat"


def ollama_chat(model: str, messages: list[dict], timeout: int = 60, options: dict | None = None) -> str:
    """Call the Ollama API with the given model and messages.

    Args:
        model: The model name (e.g., "qwen2.5:3b")
        messages: List of message dicts with "role" and "content"
        timeout: Request timeout in seconds
        options: Optional dict of Ollama API options. temperature/num_predict go in
                 body["options"]; format is a top-level field (body["format"]).

    Returns:
        The model's response text
    """
    body = {"model": model, "messages": messages, "stream": False}
    if options:
        # format is top-level in Ollama API; other options go in body["options"]
        opts_copy = options.copy()
        format_val = opts_copy.pop("format", None)
        if opts_copy:  # Only set if there are other options
            body["options"] = opts_copy
        if format_val:
            body["format"] = format_val

    payload = json.dumps(body).encode()
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"]
