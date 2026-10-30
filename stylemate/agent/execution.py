"""Process-wide bounded read-tool execution; timed-out work keeps its slot."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore, Lock


class ToolCapacityExceeded(RuntimeError):
    pass


class BoundedToolRunner:
    def __init__(self, max_workers=4):
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self.limit = max_workers
        self._slots = BoundedSemaphore(max_workers)
        self._lock = Lock()
        self._active = 0
        self._rejected = 0
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="stylemate-read")

    def submit(self, handler, *args):
        if not self._slots.acquire(blocking=False):
            with self._lock:
                self._rejected += 1
            raise ToolCapacityExceeded("tool_capacity_exhausted")
        with self._lock:
            self._active += 1
        context = copy_context()
        def invoke():
            try:
                return context.run(handler, *args)
            finally:
                self._release()
        try:
            future = self._executor.submit(invoke)
        except BaseException:
            self._release()
            raise
        # Cancellation before execution never enters invoke's finally block.
        future.add_done_callback(lambda completed: self._release() if completed.cancelled() else None)
        return future

    def _release(self):
        with self._lock:
            self._active -= 1
        self._slots.release()

    def stats(self):
        with self._lock:
            return {"limit": self.limit, "in_flight": self._active, "capacity_rejections": self._rejected}

    def shutdown(self, wait=True):
        self._executor.shutdown(wait=wait, cancel_futures=True)


READ_TOOL_RUNNER = BoundedToolRunner()
