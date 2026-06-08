"""Smoke test that the running engine supports aggregation-update pipelines.

``MongoDecisionRepository.record_review`` relies on an aggregation-update
pipeline (``update_one(filter, [{"$set": {...}}])`` — a list of stages rather
than a single update document) so a single atomic write can both increment
``previous_review_count`` and conditionally set ``reviewed_since_placement``
based on the stored placement boundary.

MongoDB 4.2+ supports this; FerretDB and DocumentDB compatibility is not
guaranteed. If this test fails, the curator writer in ``record_review`` must
fall back to a two-write CAS sequence — see the writer's docstring.
"""

from datetime import UTC, datetime

import pytest


@pytest.mark.asyncio
@pytest.mark.integration
async def test_aggregation_update_pipeline_set_with_cond(mongo_db) -> None:
    """An update_one with a $set pipeline + $cond must apply atomically.

    Mirrors the exact pipeline shape used by ``record_review``: a single
    ``$set`` stage that uses ``$ifNull``, ``$add``, ``$cond`` and ``$gt``.
    A passing run proves the engine evaluates the stages and persists the
    result; a failing run requires a fallback strategy in the writer.
    """
    coll = mongo_db["pipeline_update_smoke"]
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC)

    await coll.insert_one(
        {
            "_id": "doc-1",
            "previous_review_count": 0,
            "reviewed_since_placement": False,
            "updated_at": now,
        }
    )

    action_after = datetime(2026, 6, 5, 12, 30, 0, tzinfo=UTC)
    await coll.update_one(
        {"_id": "doc-1"},
        [
            {
                "$set": {
                    "previous_review_count": {
                        "$add": [{"$ifNull": ["$previous_review_count", 0]}, 1]
                    },
                    "reviewed_since_placement": {
                        "$cond": [
                            {
                                "$gt": [
                                    action_after,
                                    {"$ifNull": ["$updated_at", "$created_at"]},
                                ]
                            },
                            True,
                            {"$ifNull": ["$reviewed_since_placement", False]},
                        ]
                    },
                }
            }
        ],
    )

    after_action_after = await coll.find_one({"_id": "doc-1"})
    assert after_action_after is not None
    assert after_action_after["previous_review_count"] == 1
    assert after_action_after["reviewed_since_placement"] is True

    action_before = datetime(2026, 6, 5, 11, 0, 0, tzinfo=UTC)
    new_updated_at = datetime(2026, 6, 5, 13, 0, 0, tzinfo=UTC)
    await coll.update_one(
        {"_id": "doc-1"},
        {"$set": {"reviewed_since_placement": False, "updated_at": new_updated_at}},
    )

    await coll.update_one(
        {"_id": "doc-1"},
        [
            {
                "$set": {
                    "previous_review_count": {
                        "$add": [{"$ifNull": ["$previous_review_count", 0]}, 1]
                    },
                    "reviewed_since_placement": {
                        "$cond": [
                            {
                                "$gt": [
                                    action_before,
                                    {"$ifNull": ["$updated_at", "$created_at"]},
                                ]
                            },
                            True,
                            {"$ifNull": ["$reviewed_since_placement", False]},
                        ]
                    },
                }
            }
        ],
    )

    after_action_before = await coll.find_one({"_id": "doc-1"})
    assert after_action_before is not None
    assert after_action_before["previous_review_count"] == 2
    assert after_action_before["reviewed_since_placement"] is False
