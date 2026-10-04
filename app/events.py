"""In-process pub/sub for live list updates, delivered to browsers as Server-Sent Events.

Assumes a single server process (one uvicorn worker), which is what the Docker setup runs.
"""

import asyncio
import json
from collections import defaultdict


class Broker:
    def __init__(self):
        self._subscribers = defaultdict(set)  # household_id -> {asyncio.Queue}
        self._loop = None

    def bind_loop(self, loop):
        self._loop = loop

    def subscribe(self, household_id):
        queue = asyncio.Queue(maxsize=100)
        self._subscribers[household_id].add(queue)
        return queue

    def unsubscribe(self, household_id, queue):
        subs = self._subscribers.get(household_id)
        if subs:
            subs.discard(queue)
            if not subs:
                del self._subscribers[household_id]

    def _deliver(self, household_id, message):
        for queue in list(self._subscribers.get(household_id, ())):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass  # a stalled client; it'll resync on reconnect

    def publish(self, household_id, kind, origin=None, **data):
        """Safe to call from sync route handlers (which run in a worker thread)."""
        if self._loop is None or not self._subscribers.get(household_id):
            return
        message = json.dumps({"kind": kind, "origin": origin, **data})
        self._loop.call_soon_threadsafe(self._deliver, household_id, message)


broker = Broker()
