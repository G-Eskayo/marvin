#!/usr/bin/env python3
"""
Wait for any other running rebuilds to finish before proceeding with this one.
Polls process list and returns only when safe to rebuild, or when time bound is reached.
"""
import subprocess
import os
import time
import sys


def _rebuild_running(exclude_pid=None):
  """
  Check if any other rebuild_and_install.sh is running (excluding our own PID if given).
  Returns True if another build is running, False otherwise.
  """
  try:
    result = subprocess.run(['pgrep', '-f', 'rebuild_and_install.sh'],
                          capture_output=True, text=True)
    if result.returncode != 0:
      return False
    pids = result.stdout.strip().split('\n') if result.stdout.strip() else []
    if exclude_pid:
      pids = [p for p in pids if p != str(exclude_pid)]
    return len(pids) > 0
  except Exception:
    return False


def decide(running, waited_s, bound_s=600):
  """
  Decide when to proceed with the rebuild.

  Args:
      running: bool - whether another rebuild is running
      waited_s: int - seconds waited so far
      bound_s: int - maximum seconds to wait (default 10 minutes = 600s)

  Returns:
      "proceed" when safe to rebuild, or None to continue waiting
  """
  if not running:
    return "proceed"
  if waited_s >= bound_s:
    return "proceed"
  return None


def main():
  """Poll for other rebuilds until decide() says to proceed."""
  our_pid = os.getpid()
  waited = 0
  poll_interval = 5
  bound = 600

  while True:
    running = _rebuild_running(exclude_pid=our_pid)
    result = decide(running, waited, bound)

    if result == "proceed":
      sys.exit(0)

    time.sleep(poll_interval)
    waited += poll_interval


if __name__ == '__main__':
  main()
