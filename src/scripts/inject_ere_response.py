"""Inject a fake ERE response into the Redis ere_responses channel.

Mimics step 4 of the re-resolution cycle (Basic ERE cannot do this itself):
  1. ERE resolves
  2. User curates and rejects
  3. ERS sends re-resolution request with feedback
  4. [this script] pushes a new EntityMentionResolutionResponse to Redis

Note that this script is not integrated into the ERS codebase and requires
manual execution. It is intended for testing and demonstration purposes only.

Usage (CLI) — single object or list of objects:
    poetry run python scripts/inject_ere_response.py --input '{"entity_mention": {...}, ...}'
    poetry run python scripts/inject_ere_response.py --input '[{"entity_mention": {...}}, ...]'
    poetry run python scripts/inject_ere_response.py --input-file payload.json

    Note: install dependencies with poetry before running.
    
Usage (Python):
    from scripts.inject_ere_response import build_response, inject_response
    inject_response(data)                          # single dict
    inject_response([data1, data2], redis_config={"host": "localhost", "port": 6379})
"""

import argparse
import hashlib
import json
import os
import random
import uuid
from datetime import UTC, datetime
from pathlib import Path

import redis
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "infra" / ".env")
from erspec.models.core import ClusterReference, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionResponse


def build_response(data: dict) -> EntityMentionResolutionResponse:
    """Construct an EntityMentionResolutionResponse from the input payload.

    Args:
        data: Dict with keys:
            - entity_mention: {source_id, request_id, entity_type}
            - proposed_cluster_ids: list[str]  (optional, may be empty)
            - excluded_cluster_ids: list[str]  (optional, ignored in output)

    Returns:
        A fully-populated EntityMentionResolutionResponse.
    """
    em = data["entity_mention"]
    source_id: str = em["source_id"]
    request_id: str = em["request_id"]
    entity_type: str = em["entity_type"]
    proposed_cluster_ids: list[str] = data.get("proposed_cluster_ids") or []

    now = datetime.now(UTC)
    timestamp_str = now.isoformat()

    ere_request_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(now.timestamp())))

    if proposed_cluster_ids:
        cluster_ids = proposed_cluster_ids
    else:
        cluster_ids = [
            hashlib.sha256(
                f"{source_id}:{request_id}:{entity_type}:{timestamp_str}".encode()
            ).hexdigest()
        ]

    candidates = [
        ClusterReference(
            cluster_id=cid,
            confidence_score=round(random.uniform(0, 1), 6),
            similarity_score=round(random.uniform(0, 1), 6),
        )
        for cid in cluster_ids
    ]

    return EntityMentionResolutionResponse(
        ere_request_id=ere_request_id,
        timestamp=timestamp_str,
        entity_mention_id=EntityMentionIdentifier(
            source_id=source_id,
            request_id=request_id,
            entity_type=entity_type,
        ),
        candidates=candidates,
    )


def inject_response(
    data: dict | list[dict], redis_config: dict | None = None
) -> list[str]:
    """Build and push one or more EntityMentionResolutionResponses to Redis.

    Accepts either a single payload dict or a list of payload dicts. All items
    are pushed over a single Redis connection.

    Args:
        data: A single input payload dict or a list of them. Each dict has keys:
            - entity_mention: {source_id, request_id, entity_type}
            - proposed_cluster_ids: list[str]  (optional, may be empty)
            - excluded_cluster_ids: list[str]  (optional, ignored in output)
        redis_config: Optional overrides for Redis connection. Keys:
            host, port, db, password, channel.
            Any missing key falls back to the corresponding env var or default.

    Returns:
        List of serialized JSON messages that were pushed (one per input item).
    """
    items = data if isinstance(data, list) else [data]

    cfg = redis_config or {}
    host = cfg.get("host") or os.environ.get("REDIS_HOST", "localhost")
    port = int(cfg.get("port") or os.environ.get("REDIS_PORT", "6379"))
    db = int(cfg.get("db") or os.environ.get("REDIS_DB", "0"))
    password = cfg.get("password") or os.environ.get("REDIS_PASSWORD") or None
    channel = cfg.get("channel") or os.environ.get("ERE_RESPONSE_CHANNEL", "ere_responses")

    print(f"Injecting {len(items)} response(s) into Redis...")
    messages = [build_response(item).model_dump_json() for item in items]

    client = redis.Redis(host=host, port=port, db=db, password=password)
    try:
        for message in messages:
            client.lpush(channel, message)
    finally:
        client.close()

    return messages


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inject a fake ERE response into the Redis ere_responses channel."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", "-i", metavar="JSON", help="Inline JSON payload")
    input_group.add_argument(
        "--input-file", "-f", metavar="FILE", help="Path to JSON payload file"
    )
    args = parser.parse_args()

    if args.input:
        data = json.loads(args.input)
    else:
        with open(args.input_file, encoding="utf-8") as fh:
            data = json.load(fh)

    channel = os.environ.get("ERE_RESPONSE_CHANNEL", "ere_responses")
    messages = inject_response(data)
    for i, message in enumerate(messages, 1):
        print(f"[{i}/{len(messages)}] Pushed response to '{channel}':\n{message}")


if __name__ == "__main__":
    main()
