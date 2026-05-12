from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass(eq=False, frozen=True)
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]


class GameEventBus:
    """In-process pub/sub for live game events.

    HTTP game runners are synchronous and may execute in a worker thread, while
    WebSocket subscribers live on the async server loop. Store each subscriber's
    loop so publishers can safely enqueue messages across threads.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[_Subscriber]] = {}
        self._lock = Lock()

    def subscribe(self, game_id: str) -> _Subscriber:
        subscriber = _Subscriber(
            loop=asyncio.get_running_loop(),
            queue=asyncio.Queue(maxsize=500),
        )
        with self._lock:
            self._subscribers.setdefault(game_id, set()).add(subscriber)
        return subscriber

    def unsubscribe(self, game_id: str, subscriber: _Subscriber) -> None:
        with self._lock:
            subscribers = self._subscribers.get(game_id)
            if subscribers is None:
                return
            subscribers.discard(subscriber)
            if not subscribers:
                self._subscribers.pop(game_id, None)

    def publish(self, game_id: str, message: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers.get(game_id, set()))

        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(
                self._put_nowait,
                subscriber.queue,
                message,
            )

    @staticmethod
    def _put_nowait(queue: asyncio.Queue[dict[str, Any]], message: dict[str, Any]) -> None:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # Drop oldest pressure by clearing one item; live UI prefers newest state.
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            queue.put_nowait(message)


game_event_bus = GameEventBus()
