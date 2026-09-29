# ERE Resolution Demo

A standalone Python script that exercises the full entity resolution lifecycle
through the ERS REST API — the correct black-box interface for this ops repo.

## Prerequisites

Start the full stack before running the demo:

```bash
make up
make install  # install test dependencies
```

> **Curation step prerequisite:** The curation loop (Step 5) requires
> `inject_ere_response.py` located in [`src/scripts`](../../src/scripts)
> of this repository. Run with `--skip-curation` to bypass this step.

## How to run

```bash
# Default run (6 synthetic mentions, 60s per-mention timeout)
poetry -C src run python ../test/demo/demo_full_cycle.py

# Adjust polling timeout (useful on slower machines)
poetry -C src run python ../test/demo/demo_full_cycle.py --timeout 120

# Skip the curation loop (faster smoke run)
poetry -C src run python ../test/demo/demo_full_cycle.py --skip-curation

# Use a custom mentions file
poetry -C src run python ../test/demo/demo_full_cycle.py --data /path/to/mentions.json
```

## What to expect

The demo runs six steps and prints timestamped log lines for each:

1. **Health check** — confirms ERS API, Curation API, and Redis are reachable.
2. **Submit mentions** — sends 6 synthetic org mentions (3 German, 3 French) to `/api/v1/resolve`.
3. **Poll for results** — polls `/api/v1/lookup` per mention until a `cluster_id` arrives.
4. **Clustering summary** — prints a block showing which mentions clustered together.
5. **Curation loop** — submits a placement recommendation and shows the re-evaluation effect.
6. **Bulk refresh** — calls `/api/v1/refresh-bulk` and prints the delta output. Note: the bulk refresh requires resolved entities to be updated in the meantime.

Expected clustering: the 3 German mentions form one cluster; the 3 French mentions form another.

## How to reset stale ERE state

If a previous demo run left data in the ERE DuckDB volume, results may mix old
and new mentions. To start from a clean slate:

```bash
make down-volumes   # removes all Docker volumes, including ERE state
make up             # restart the stack with fresh volumes
```
