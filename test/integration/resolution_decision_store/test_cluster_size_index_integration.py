"""Integration tests for MongoClusterSizeIndex against a real engine (FerretDB).

Verifies the delete-on-zero + decrement-below-zero guard (B4) on the production
engine, which mocks cannot prove.
"""
import pytest

from ers.resolution_decision_store.adapters.cluster_size_index import MongoClusterSizeIndex

_COLLECTION = "cluster_sizes"


@pytest.fixture()
async def index(mongo_db):
    return MongoClusterSizeIndex(mongo_db)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_insert_path_increments_to_one(index):
    await index.shift(from_cluster=None, to_cluster="A")
    assert await index.get_size("A") == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_placement_move_conserves_total(index):
    await index.shift(from_cluster=None, to_cluster="A")
    await index.shift(from_cluster=None, to_cluster="A")  # A=2
    await index.shift(from_cluster="A", to_cluster="B")   # A=1, B=1
    assert await index.get_size("A") == 1
    assert await index.get_size("B") == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_decrement_to_zero_deletes_entry(index, mongo_db):
    await index.shift(from_cluster=None, to_cluster="A")  # A=1
    await index.shift(from_cluster="A", to_cluster="B")   # A=0 -> deleted

    assert await index.get_size("A") == 0
    # delete-on-zero: the row is physically removed, not left at size 0.
    assert await mongo_db[_COLLECTION].find_one({"_id": "A"}) is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_removal_path_deletes_on_zero(index, mongo_db):
    await index.shift(from_cluster=None, to_cluster="A")  # A=1
    await index.shift(from_cluster="A", to_cluster=None)  # A=0 -> deleted

    assert await index.get_size("A") == 0
    assert await mongo_db[_COLLECTION].find_one({"_id": "A"}) is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_decrement_absent_cluster_creates_no_negative(index, mongo_db):
    # Decrementing a cluster that was never tracked must not upsert a negative row.
    await index.shift(from_cluster="ghost", to_cluster=None)

    assert await index.get_size("ghost") == 0
    assert await mongo_db[_COLLECTION].find_one({"_id": "ghost"}) is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_size_zero_rows_ever_persist(index, mongo_db):
    await index.shift(from_cluster=None, to_cluster="A")  # A=1
    await index.shift(from_cluster="A", to_cluster="B")   # A=0 -> deleted, B=1

    # Stats must never observe a size:0 row.
    zero_rows = await mongo_db[_COLLECTION].count_documents({"size": {"$lte": 0}})
    assert zero_rows == 0
