"""HTTP wrapper for the ERE response injector.

Exposes a single POST /push endpoint that accepts the same JSON payload(s)
as inject_ere_response.py and pushes them to the Redis ere_responses channel.

Redis connection and channel are configured via environment variables (loaded
from infra/.env automatically):

    REDIS_HOST              Redis hostname          (default: localhost)
    REDIS_PORT              Redis port              (default: 6379)
    REDIS_DB                Redis database index    (default: 0)
    REDIS_PASSWORD          Redis password          (default: none)
    ERE_RESPONSE_CHANNEL    Target list/channel     (default: ere_responses)

Server port:

    INJECT_APP_PORT         HTTP server port        (default: 8002)

Usage:
    make redis-rest-api-start   # start in background (reads infra/.env automatically)
    make redis-rest-api-stop    # stop the background process

    poetry run python scripts/inject_ere_response_app.py  # direct invocation

Endpoints:
    POST /push   — single object or list of objects
                   Returns: {"pushed": N, "messages": [...]}
"""

import os
import sys
from pathlib import Path

# Allow importing inject_ere_response as a sibling script regardless of cwd.
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from inject_ere_response import inject_response

app = FastAPI(title="ERE Response Injector")

_redis_config = {
    "host": os.environ.get("REDIS_HOST", "localhost"),
    "port": int(os.environ.get("REDIS_PORT", "6379")),
    "db": int(os.environ.get("REDIS_DB", "0")),
    "password": os.environ.get("REDIS_PASSWORD") or None,
    "channel": os.environ.get("ERE_RESPONSE_CHANNEL", "ere_responses"),
}


@app.post("/push")
async def push(request: Request) -> dict:
    """Push one or more ERE responses into Redis.

    Accepts a single payload object or a list of payload objects.
    Each object must have the shape expected by inject_response().
    """
    data = await request.json()
    try:
        messages = inject_response(data, redis_config=_redis_config)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"pushed": len(messages), "messages": messages}


if __name__ == "__main__":
    port = int(os.environ.get("INJECT_APP_PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port)
