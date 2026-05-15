"""ERE Async boundary suite — fixtures for Redis injection and queue reading.

Background steps (ERS API reachable, Curation API reachable, etc.) are
defined in tests/e2e/conftest.py to avoid duplicate-step errors across suites.
"""
import json
import time

import pytest


@pytest.fixture
def publish_to_ere_responses(redis_client):
    """Factory fixture: push a message onto the ere_responses Redis list.

    The ERS worker reads from this list queue via BRPOP/BLPOP.
    Uses rpush (not publish) because the queue is a Redis list, not pub/sub.
    """
    def _publish(message: dict) -> None:
        redis_client.rpush("ere_responses", json.dumps(message))

    return _publish


@pytest.fixture
def read_ere_requests(redis_client):
    """Factory fixture: read messages from the ere_requests queue.

    Waits briefly for async message arrival.
    Queue name is a placeholder — replace after GitNexus discovery.
    """
    def _read(timeout_s: float = 5.0) -> list[dict]:
        messages = []
        deadline = time.monotonic() + timeout_s
        queue = "ere_requests"  # placeholder
        while time.monotonic() < deadline:
            msg = redis_client.lpop(queue)
            if msg:
                messages.append(json.loads(msg))
            else:
                if messages:
                    break
                time.sleep(0.2)
        return messages

    return _read
