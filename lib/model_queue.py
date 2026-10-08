#!/usr/bin/env python3
"""Per-machine heavy-model queue and lock management (ADR 0061).

Heavy models (FLUX, qwen2.5:14b) can't fit two at once on 16GB Macs.
This module provides acquire/release semantics: block until the previous
heavy model is freed, then lock for this job.

State tracking (locks and waiters) is local to the machine: ~/.claude/logs/model-queue.json
Mutual exclusion of state updates uses fcntl.flock on a shared lock file.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HOME = Path.home()


class ModelQueue:
    """Per-machine queue for exclusive heavy-model access."""

    def __init__(self, state_path: Path = None):
        if state_path is None:
            state_path = HOME / ".claude" / "logs" / "model-queue.json"
        self.state_path = Path(state_path)
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self._write({"locks": {}, "waiters": {}})

    def _read(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {"locks": {}, "waiters": {}}

    def _write(self, data: dict) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp, self.state_path)

    def _get_state_lock_path(self) -> Path:
        """Get the lock file for protecting state updates."""
        return self.state_path.parent / f".{self.state_path.name}.lock"

    def acquire(self, model: str, job_id: str, is_heavy: bool = True, timeout: Optional[float] = None) -> bool:
        """Acquire exclusive lock for a heavy model.

        Non-heavy models return True immediately without locking.
        Heavy models block until any other heavy model is released.

        Args:
            model: Model name (e.g., "qwen2.5:14b")
            job_id: Job identifier
            is_heavy: Whether this model consumes exclusive resources
            timeout: Max seconds to wait for lock (None = indefinite)

        Returns:
            True if lock acquired (or not needed), False if timeout.
        """
        if not is_heavy:
            return True

        lock_path = self._get_state_lock_path()
        start = time.time()

        while True:
            with open(lock_path, "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    data = self._read()
                    locks = data.get("locks", {})
                    waiters = data.get("waiters", {})

                    # If this job already holds a lock, allow re-acquire
                    if model in locks and locks[model]["job_id"] == job_id:
                        return True

                    # If any other heavy model is locked, add to waiters and keep retrying
                    other_locks = [m for m in locks if m != model]
                    if other_locks:
                        waiter_key = f"{model}::{job_id}"
                        if waiter_key not in waiters:
                            waiters[waiter_key] = {"queued_at": datetime.now(timezone.utc).isoformat()}
                            data["waiters"] = waiters
                            self._write(data)
                        # Don't return here; fall through to sleep and retry
                    else:
                        # No other locks held; acquire this one
                        locks[model] = {"job_id": job_id, "acquired_at": datetime.now(timezone.utc).isoformat()}
                        data["locks"] = locks
                        # Remove from waiters if present
                        waiter_key = f"{model}::{job_id}"
                        if waiter_key in waiters:
                            del waiters[waiter_key]
                        data["waiters"] = waiters
                        self._write(data)
                        return True
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)

            # Check timeout
            if timeout is not None and (time.time() - start) > timeout:
                return False

            # Brief sleep before retry (only if we're still waiting)
            time.sleep(0.05)

    def release(self, model: str, job_id: str) -> None:
        """Release exclusive lock for a heavy model."""
        lock_path = self._get_state_lock_path()
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = self._read()
                locks = data.get("locks", {})
                waiters = data.get("waiters", {})

                # Remove lock if this job holds it
                if model in locks and locks[model]["job_id"] == job_id:
                    del locks[model]

                # Remove from waiters if present
                waiter_key = f"{model}::{job_id}"
                if waiter_key in waiters:
                    del waiters[waiter_key]

                data["locks"] = locks
                data["waiters"] = waiters
                self._write(data)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def status(self) -> dict:
        """Get current lock/waiter status.

        Returns:
            {"locks": {model: {job_id, acquired_at}}, "waiters": {model::job_id: {queued_at}}}
        """
        return self._read()


if __name__ == "__main__":
    import sys
    queue = ModelQueue()
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "status":
            print(json.dumps(queue.status(), indent=2))
        elif cmd == "acquire" and len(sys.argv) >= 4:
            model, job_id = sys.argv[2], sys.argv[3]
            result = queue.acquire(model, job_id, is_heavy=True, timeout=5)
            print(f"{'acquired' if result else 'timeout'}")
        elif cmd == "release" and len(sys.argv) >= 4:
            model, job_id = sys.argv[2], sys.argv[3]
            queue.release(model, job_id)
            print("released")
