"""Shared fixtures and helpers for the ere_contract_client feature tests."""

import asyncio


def run_async(coro):
    """Run a coroutine synchronously in a fresh event loop.

    pytest-bdd step functions cannot be async, so this helper bridges the gap
    between synchronous step definitions and async service calls.

    Args:
        coro: The coroutine to execute.

    Returns:
        The coroutine's return value.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
