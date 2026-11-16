"""Honor provider request limits across clients sharing a credential in this process."""
import asyncio
import hashlib
import time
from weakref import WeakKeyDictionary

from .errors import retry_delay

_loops = WeakKeyDictionary()


class Gate:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.interval = 0.0
        self.next_at = 0.0

    async def wait(self):
        async with self.lock:
            delay = self.next_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self.next_at = time.monotonic() + self.interval

    def observe(self, response):
        for header, window in (('x-ratelimit-limit-req-minute', 60), ('x-ratelimit-limit-req-second', 1)):
            try:
                limit = float(response.headers.get(header, '0'))
            except (TypeError, ValueError):
                continue
            if limit > 0:
                self.interval = max(self.interval, window / limit + 0.1)
                self.next_at = max(self.next_at, time.monotonic() + self.interval)
        if response.status_code == 429:
            self.next_at = max(self.next_at, time.monotonic() + retry_delay(response.headers, 60))


def for_provider(base_url, api_key):
    gates = _loops.setdefault(asyncio.get_running_loop(), {})
    # The registry retains a digest, never the API key.
    key = (base_url, hashlib.sha256(api_key.encode()).digest())
    return gates.setdefault(key, Gate())
