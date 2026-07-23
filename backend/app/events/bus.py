"""In-process event bus.

Producers (engine, scheduler) publish events; consumers (WebSocket,
SSE, webhook dispatcher — added in later slices) subscribe. The bus is
process-local: real-time streams are fire-and-forget (§3.8.6), so we do
not buffer for disconnected clients.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Type alias: an event is a (event_type, payload_dict) pair.
EventListener = Callable[[str, dict], None]
AsyncEventListener = Callable[[str, dict], "asyncio.Awaitable[None]"]

_sync_listeners: dict[str, list[EventListener]] = defaultdict(list)
_async_listeners: dict[str, list[AsyncEventListener]] = defaultdict(list)
_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Capture the running event loop so sync callers can schedule async
    listeners (e.g. the engine thread firing into the asyncio world)."""
    global _loop
    _loop = loop


def subscribe_sync(event_type: str, listener: EventListener) -> None:
    _sync_listeners[event_type].append(listener)


def subscribe_async(event_type: str, listener: AsyncEventListener) -> None:
    _async_listeners[event_type].append(listener)


def unsubscribe_sync(event_type: str, listener: EventListener) -> None:
    lst = _sync_listeners.get(event_type, [])
    if listener in lst:
        lst.remove(listener)


def unsubscribe_async(event_type: str, listener: AsyncEventListener) -> None:
    lst = _async_listeners.get(event_type, [])
    if listener in lst:
        lst.remove(listener)


def publish(event_type: str, payload: dict) -> None:
    """Publish an event. Sync listeners run inline; async listeners are
    scheduled on the event loop if one is available."""
    for listener in _sync_listeners.get(event_type, []):
        try:
            listener(event_type, payload)
        except Exception:
            logger.exception("sync event listener failed for %s", event_type)

    if _async_listeners.get(event_type) and _loop is not None:
        for listener in _async_listeners[event_type]:
            try:
                asyncio.run_coroutine_threadsafe(listener(event_type, payload), _loop)
            except Exception:
                logger.exception("async event listener failed for %s", event_type)
