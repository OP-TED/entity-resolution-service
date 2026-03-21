"""Shared fixtures and helpers for the ere_contract_client feature tests."""

import asyncio


def run_async(coro):
    """Run a coroutine synchronously.

    pytest-bdd step functions cannot be async, so this helper bridges the gap
    between synchronous step definitions and async service calls.

    Args:
        coro: The coroutine to execute.

    Returns:
        The coroutine's return value.
    """
    return asyncio.run(coro)
