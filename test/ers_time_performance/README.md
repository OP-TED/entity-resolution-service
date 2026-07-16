# ERS Time Performance Scripts

This folder contains:

- timing matrix exporters for the ERS pipeline
- timing matrix exporters for the old (non-ERS) pipeline
- stress-test utilities for ERS resolution throughput/latency benchmarking

All scripts are standalone Python CLIs and can be run directly with `python ...`.

## What each output means

Most exporter scripts produce two CSV files:

- **matrix CSV**: rows are pipeline steps, columns are `run_1 ... run_N`, plus `total_step_time` and `average_step_time`
- **mapping CSV**: maps `run_1 ... run_N` back to the real Airflow `run_id`, timestamp, and notice ids used in that run

This lets you:

- compare step-level performance between runs
- correlate an outlier column with the exact Airflow run it came from
- create transposed/Excel summaries afterward

---

## 1) ERS pipeline timing matrix (same goal, different data source)

Scripts:

- `test/test_data/ers_time_performance/export_ers_notice_execution_matrix_from_html.py`
- `test/test_data/ers_time_performance/export_ers_notice_execution_matrix_postgres.py`

Both generate:

- step x run duration matrix CSV (ERS task path)
- run mapping CSV (`run_n -> airflow_run_id/timestamp/notice_ids`)

Use this pair when your pipeline includes URI + Entity Resolution steps.

### A) From Airflow Grid HTML + Airflow REST API

Use this variant when:

- you already have a saved Airflow Grid HTML, or
- you want to fetch run ids from a Grid URL,
- and you want task durations from Airflow REST API (hosted Airflow, not local Postgres).

```bash
python test/test_data/ers_time_performance/export_ers_notice_execution_matrix_from_html.py \
  --html test/test_data/ers_time_performance/02-12-2025-ers-enabled.html \
  --grid-url "https://<your-airflow-host>/dags/notice_processing_pipeline/grid?num_runs=365" \
  --username admin \
  --password "YOUR_AIRFLOW_PASSWORD" \
  --output test/test_data/ers_time_performance/new_code.csv \
  --mapping-output test/test_data/ers_time_performance/current_airflow_ers_run_mapping.csv
```

Useful options:

- `--prefer-grid-url` to always fetch the Grid URL even if `--html` exists
- `--max-runs N` to export only first N runs found in Grid HTML
- `--cookie "..."` instead of username/password (session cookie auth)
- `--dag-id ...` when the DAG id cannot be inferred correctly

Authentication notes:

- You can pass `--username/--password` directly.
- Or set env vars `AIRFLOW_USERNAME` and `AIRFLOW_PASSWORD`.
- For cookie auth, use `--cookie` or `AIRFLOW_COOKIE`.

### B) Directly from Airflow metadata Postgres

Use when you can query Airflow metadata DB (`dag_run` + `task_instance`) with `psql`.
This is typically the fastest and most deterministic source when DB access is available.

```bash
python test/test_data/ers_time_performance/export_ers_notice_execution_matrix_postgres.py \
  --dag-id notice_processing_pipeline \
  --num-runs 100 \
  --psql-command "docker exec airflow-postgres psql -U airflow -d airflow" \
  --output test/test_data/ers_time_performance/new_code.csv \
  --mapping-output test/test_data/ers_time_performance/current_airflow_ers_run_mapping.csv
```

Useful options:

- `--num-runs N` to control sample size
- `--psql-command "..."` to point to your own Postgres access command
- `--dag-id ...` for other DAGs using the same metadata schema

---

## 2) Old pipeline timing matrix (no ERS; same goal, different data source)

Scripts:

- `test/test_data/ers_time_performance/export_notice_execution_matrix.py`
- `test/test_data/ers_time_performance/export_notice_execution_matrix_postgres.py`

Both generate:

- step x run duration matrix CSV for old pipeline task path
- run mapping CSV (`run_n -> airflow_run_id/timestamp/notice_ids`)

Use this pair when processing follows the old path (distillation path, no ERS tasks).

### A) From Airflow Grid HTML + Airflow REST API

This variant mirrors the ERS HTML/API exporter but uses old pipeline task steps.

```bash
python test/test_data/ers_time_performance/export_notice_execution_matrix.py \
  --html test/test_data/ers_time_performance/2023-8-10-old-code.html \
  --grid-url "https://<your-airflow-host>/dags/notice_processing_pipeline/grid?num_runs=365" \
  --username admin \
  --password "YOUR_AIRFLOW_PASSWORD" \
  --output test/test_data/ers_time_performance/old_code.csv \
  --mapping-output test/test_data/ers_time_performance/current_airflow_run_mapping.csv
```

Useful options:

- `--prefer-grid-url` to always fetch live Grid HTML
- `--cookie "..."` for authenticated Airflow sessions
- `--dag-id ...` if needed

### B) Directly from Airflow metadata Postgres

This variant reads old-pipeline durations directly from Airflow metadata tables.

```bash
python test/test_data/ers_time_performance/export_notice_execution_matrix_postgres.py \
  --dag-id notice_processing_pipeline \
  --num-runs 100 \
  --psql-command "docker exec airflow-postgres psql -U airflow -d airflow" \
  --output test/test_data/ers_time_performance/old_code.csv \
  --mapping-output test/test_data/ers_time_performance/current_airflow_run_mapping.csv
```

Tip: if your Postgres is not in Docker, replace `--psql-command` with your local/remote `psql` connection command.

---

## 3) ERS stress test helpers

Scripts:

- `test/test_data/ers_time_performance/extract_organisation_mentions.py`
- `test/test_data/ers_time_performance/benchmark_ers_resolution.py`

### Step 1: Extract organisation fragments and manifest

This scans notice TTL files, extracts `org:Organization` fragments, and writes one `.ttl` fragment per organisation in `test/test_data/organisations` plus:

- `manifest.jsonl`
- `resolve_bulk_request.json`

`manifest.jsonl` includes metadata per extracted fragment (source notice file, entity URI, etc.).  
`resolve_bulk_request.json` is a ready-made bulk payload snapshot.

```bash
python test/test_data/ers_time_performance/extract_organisation_mentions.py \
  --input-dir test/test_data/notice_transformer/test_repository \
  --output-dir test/test_data/organisations \
  --limit 5000 \
  --seed 42 \
  --clear-output
```

### Step 2: Run ERS benchmark scenarios

This sends mentions to ERS endpoints and writes one row per scenario in a summary CSV.

Scenarios covered by default:

- individual requests (`1 mention/request`)
- sequential batch requests (`10,30,100,300` by default)
- parallel batches (`100` and `50` requests by default, each request containing 4-12 mentions)

```bash
python test/test_data/ers_time_performance/benchmark_ers_resolution.py \
  --ers-url "https://<your-ers-host>" \
  --input-dir test/test_data/organisations \
  --limit 5000 \
  --batch-sizes "10,30,100,300" \
  --parallel-requests "100,50" \
  --parallel-workers 100 \
  --parallel-batch-min 4 \
  --parallel-batch-max 12 \
  --identifier-suffix "ERSBenchmark_$(date +%Y%m%d_%H%M%S)" \
  --output test/test_data/ers_time_performance/ers-benchmark-resolution-enabled.csv \
  --append
```

Useful options:

- `--individual-only` (run only one-mention requests)
- `--skip-sequential` or `--skip-parallel`
- `--dry-run` (build scenarios without sending HTTP)
- `--header KEY=VALUE` (repeatable custom HTTP headers)
- `--identifier-suffix ...` to avoid ERS cache hits across benchmark iterations
- `--append` to keep adding rows to an existing report file

Important benchmarking note:

- If you are repeating the same dataset, always use a different `--identifier-suffix` per run to avoid measuring cached resolution behavior.

## Typical end-to-end flow

1. Export matrix CSV + mapping CSV (choose HTML/API or Postgres source).
2. Optionally transpose or convert CSV to XLSX for analysis/presentation.
3. For ERS stress testing, first extract fragments, then run benchmark scenarios, then compare output rows by scenario.

---

## Quick script map

- ERS matrix from HTML/API: `export_ers_notice_execution_matrix_from_html.py`
- ERS matrix from Postgres: `export_ers_notice_execution_matrix_postgres.py`
- Old pipeline matrix from HTML/API: `export_notice_execution_matrix.py`
- Old pipeline matrix from Postgres: `export_notice_execution_matrix_postgres.py`
- Build org mention dataset: `extract_organisation_mentions.py`
- Stress test ERS endpoints: `benchmark_ers_resolution.py`
