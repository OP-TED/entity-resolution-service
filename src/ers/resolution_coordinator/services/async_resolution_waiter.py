"""In-process coordination primitive for async ERE response waiting."""

import asyncio
from weakref import WeakValueDictionary


class AsyncResolutionWaiter:
    """Bridge between ResolutionCoordinatorService (waiter) and EPIC-05 (signaller).

    Manages a dict of ``asyncio.Event`` objects keyed by triad key. Multiple
    concurrent coroutines waiting on the same triad share a single Event and
    are all unblocked by one ``notify`` call.

    Memory management is handled automatically via ``WeakValueDictionary``:
    each caller holds a strong reference to the event for the lifetime of its
    wait. When the last reference is dropped (end of ``finally`` block in the
    coordinator), CPython's GC removes the entry from the dict immediately.
    No explicit reference counting is needed.

    This class contains no business logic, no logging, and no OTel spans.
    """

    def __init__(self) -> None:
        self._events: WeakValueDictionary[str, asyncio.Event] = WeakValueDictionary()

    async def get_or_create(self, triad_key: str) -> asyncio.Event:
        """Return the shared Event for this triad, creating it if absent.

        The caller must hold the returned Event in a local variable for the
        duration of its wait to keep the entry alive in the dict.

        Args:
            triad_key: Concatenation of source_id + request_id + entity_type
                (no separator), consistent with ``derive_provisional_cluster_id``.

        Returns:
            The ``asyncio.Event`` for this triad. Shared across all concurrent
            callers for the same key.
        """
        event = self._events.get(triad_key)
        if event is None:
            event = asyncio.Event()
            self._events[triad_key] = event
        return event

    async def notify(self, triad_key: str) -> bool:
        """Signal all waiters for this triad that an ERE outcome is available.

        Called by EPIC-05 (OutcomeIntegrationService) after writing the ERE
        outcome to the Decision Store. If all waiters have already timed out
        and released their references, this is a no-op.

        Args:
            triad_key: Concatenation of source_id + request_id + entity_type.

        Returns:
            True if a local event was found and set (request is owned by this
            instance); False if the key is unknown (request originated elsewhere
            or has already timed out).
        """
        event = self._events.get(triad_key)
        if event is not None:
            event.set()
            return True
        return False

    async def release(self, triad_key: str) -> None:
        """No-op — exists to satisfy the integration contract with T6.3.

        ``ResolutionCoordinatorService`` calls this in a ``finally`` block after
        each wait. The actual cleanup is handled automatically: when the caller
        drops its strong reference to the event (end of scope), CPython's GC
        evicts the entry from the ``WeakValueDictionary`` immediately.

        Args:
            triad_key: Concatenation of source_id + request_id + entity_type.
        """
