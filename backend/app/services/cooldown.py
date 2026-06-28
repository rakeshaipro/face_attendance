"""In-memory per-employee cooldown tracker (SRS §3.4.9).

After an employee is detected and logged, subsequent detections within
the cooldown window are suppressed to avoid duplicate records when
someone lingers in frame (§3.4.10).

State is in-memory and resets on service restart. The attendance log is
the durable source of truth; this cache exists only to suppress rapid
re-detection within a single run.
"""
from __future__ import annotations

import threading
import time


class CooldownTracker:
    """Thread-safe {employee_id: expiry_monotonic} map."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._expiry: dict[str, float] = {}

    def should_suppress(self, employee_id: str, *, now: float | None = None) -> bool:
        """True if `employee_id` is still within its cooldown window."""
        t = time.monotonic() if now is None else now
        with self._lock:
            expiry = self._expiry.get(employee_id)
            return expiry is not None and t < expiry

    def mark(self, employee_id: str, cooldown_seconds: float, *, now: float | None = None) -> None:
        """Start (or extend) the cooldown window for `employee_id`.

        A cooldown of 0 disables suppression entirely (§3.4.10).
        """
        if cooldown_seconds <= 0:
            with self._lock:
                self._expiry.pop(employee_id, None)
            return
        t = time.monotonic() if now is None else now
        with self._lock:
            self._expiry[employee_id] = t + cooldown_seconds

    def clear(self) -> None:
        with self._lock:
            self._expiry.clear()
