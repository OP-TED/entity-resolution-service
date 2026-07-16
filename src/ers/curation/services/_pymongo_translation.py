"""Decorator translating PyMongo connection errors at the curation service boundary.

The Curation API exposes a large surface of read endpoints that each call into
one or more Mongo-backed repositories (decisions, statistics, user actions,
entity mentions). When MongoDB is unreachable, the raw ``pymongo`` exception
must be translated into a ``ServiceUnavailableError`` so the API exception
handler can map it to HTTP 503; otherwise the global 500 handler kicks in
and the operator sees an opaque "Internal server error" instead of the
documented 503 contract.

Applying this translation site-by-site yields a lot of identical
``try/except ConnectionFailure: raise ServiceUnavailableError`` blocks. The
decorator below collapses that boilerplate into a single ``@translate_mongo_errors``
annotation on each public service coroutine.

Scope: covers async methods on curation service classes. Async generators and
synchronous methods are intentionally not supported — the curation services
do not currently expose any.
"""
from collections.abc import Awaitable, Callable
from functools import wraps

from pymongo.errors import ConnectionFailure

from ers.commons.services.exceptions import ServiceUnavailableError


def translate_mongo_errors[**P, R](
    fn: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Wrap ``fn`` so PyMongo ``ConnectionFailure`` becomes ``ServiceUnavailableError``.

    The wrapped coroutine preserves the underlying exception via ``raise ... from``
    so log/trace pipelines retain the original cause.
    """

    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except ConnectionFailure as exc:
            raise ServiceUnavailableError("mongodb", str(exc)) from exc

    return wrapper
