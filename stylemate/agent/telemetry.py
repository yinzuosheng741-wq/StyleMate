"""Content-free run diagnostics. No prompts, identities, payloads or exception text."""
import json
import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from time import monotonic

logger = logging.getLogger(__name__)
_current = ContextVar("stylemate_run_diagnostics", default=None)
_COUNTERS = ("model_calls", "tool_attempts", "tool_successes", "tool_failures", "capacity_rejections",
             "tool_outcome_success", "tool_outcome_empty", "tool_outcome_not_found",
             "tool_outcome_needs_clarification", "tool_outcome_unavailable", "tool_outcome_error")


class RunObservation:
    def __init__(self):
        self.run_id = uuid.uuid4().hex
        self.started = monotonic()
        self.counts = dict.fromkeys(_COUNTERS, 0)
        self.outcome = "failed"
        self.tool_calls = 0
        self._lock = Lock()
        self._closed = False

    def increment(self, name):
        if name not in _COUNTERS:
            raise ValueError("unknown_diagnostic_counter")
        with self._lock:
            if not self._closed:
                self.counts[name] += 1

    def finish(self):
        with self._lock:
            self._closed = True
            return {"schema_version": 2, "run_id": self.run_id, "outcome": self.outcome,
                    "duration_ms": max(0, round((monotonic() - self.started) * 1000)),
                    "tool_calls": self.tool_calls, **self.counts}


def record_counter(name):
    observation = _current.get()
    if observation:
        observation.increment(name)


def current_run_id():
    observation = _current.get()
    return observation.run_id if observation else None


def configure_run_logging(directory: Path):
    """Attach only this content-free logger; never attach provider/root logs."""
    path = (directory / "agent-runs.log").resolve()
    if any(getattr(handler, "baseFilename", None) == str(path) for handler in logger.handlers):
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    except OSError:
        # Observability cannot prevent the application from starting.
        logger.warning("run_log_unavailable")


@contextmanager
def observe_run(observer=None):
    observation = RunObservation()
    token = _current.set(observation)
    try:
        yield observation
    finally:
        _current.reset(token)
        snapshot = observation.finish()
        logger.info("agent_run %s", json.dumps(snapshot, separators=(",", ":")))
        if observer:
            try:
                observer(snapshot)
            except Exception:
                logger.warning("run_observer_failed")
