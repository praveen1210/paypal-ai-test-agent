"""Guards for the public demo: cap concurrent runs and runs per visitor.

Every run drives real sandbox API calls and LLM calls, so a public URL needs limits. State is in memory,
which is right for a single Render instance; it resets on restart.
"""

from __future__ import annotations

import os
import time
from collections import deque


class LimitExceeded(Exception):
    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class DemoLimiter:
    def __init__(self, max_concurrent: int, runs_per_window: int, window_seconds: int) -> None:
        self.max_concurrent = max_concurrent
        self.runs_per_window = runs_per_window
        self.window_seconds = window_seconds
        self.active = 0
        self._history: dict[str, deque[float]] = {}

    @classmethod
    def from_env(cls) -> DemoLimiter:
        return cls(
            max_concurrent=int(os.getenv("DEMO_MAX_CONCURRENT", "2")),
            runs_per_window=int(os.getenv("DEMO_RUNS_PER_IP", "6")),
            window_seconds=int(os.getenv("DEMO_WINDOW_MINUTES", "10")) * 60,
        )

    def acquire(self, client: str) -> None:
        """Reserve a run slot for `client` or raise LimitExceeded. Call release() when the run ends."""
        now = time.monotonic()
        history = self._history.setdefault(client, deque())
        while history and now - history[0] > self.window_seconds:
            history.popleft()
        if len(history) >= self.runs_per_window:
            wait = int(self.window_seconds - (now - history[0])) + 1
            raise LimitExceeded(
                f"Demo limit: {self.runs_per_window} runs per {self.window_seconds // 60} minutes. "
                f"Try again in {wait // 60 + 1} min, or run it locally from the GitHub repo.", wait)
        if self.active >= self.max_concurrent:
            raise LimitExceeded("The demo is busy with other test runs. Try again in about 30 seconds.", 30)
        history.append(now)
        self.active += 1

    def release(self) -> None:
        self.active = max(0, self.active - 1)
