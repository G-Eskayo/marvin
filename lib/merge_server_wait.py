#!/usr/bin/env python3
"""
Wait for any running merges to finish before restarting the dashboard webhook.
Polls the merge queue status and returns only when safe to restart, or when time bound is reached.
"""
import urllib.request
import json
import time
import sys


def _merge_running(url="http://localhost:7878/merge-queue", timeout=5):
    """
    Check if any merge is currently running.
    Returns True if any merge is running, False otherwise.
    Fails open (returns False) on any network or JSON error.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            repos = data.get('repos', {})
            for repo_name, repo_data in repos.items():
                if repo_data.get('running'):
                    return True
            return False
    except Exception:
        return False


def decide(running, waited_s, bound_s=2700):
    """
    Decide when to proceed with the restart.

    Args:
        running: bool - whether a merge is currently running
        waited_s: int - seconds waited so far
        bound_s: int - maximum seconds to wait (default 45 minutes = 2700s)

    Returns:
        "restart" when safe to restart, or None to continue waiting
    """
    if not running:
        return "restart"
    if waited_s >= bound_s:
        return "restart"
    return None


def main():
    """Poll merge server until decide() says to restart."""
    waited = 0
    poll_interval = 15
    bound = 2700

    while True:
        running = _merge_running()
        result = decide(running, waited, bound)

        if result == "restart":
            sys.exit(0)

        time.sleep(poll_interval)
        waited += poll_interval


if __name__ == '__main__':
    main()
