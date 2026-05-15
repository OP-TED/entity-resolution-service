#!/usr/bin/env python3
"""Export an Airflow step-by-run timing matrix from the metadata Postgres DB.

This uses Airflow's source-of-truth metadata tables:

* dag_run: run ids, execution timestamps, and run config / notice ids
* task_instance: task ids and task durations

By default it connects through the local Docker container:

    docker exec airflow-postgres psql -U airflow -d airflow
"""

import argparse
import csv
import json
import pickle
import shlex
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


DEFAULT_DAG_ID = "notice_processing_pipeline"
DEFAULT_NUM_RUNS = 100
DEFAULT_OUTPUT_PATH = Path("test/test_data/ers_time_performance/current_airflow_step_matrix.csv")
DEFAULT_MAPPING_PATH = Path("test/test_data/ers_time_performance/current_airflow_run_mapping.csv")
DEFAULT_PSQL_COMMAND = "docker exec airflow-postgres psql -U airflow -d airflow"

TASK_STEPS = [
    "branch_selector",
    "notice_normalisation_pipeline",
    "switch_to_transformation",
    "notice_transformation_pipeline",
    "switch_to_distillation",
    "notice_distillation_pipeline",
    "switch_to_validation",
    "notice_validation_pipeline",
    "switch_to_package",
    "notice_package_pipeline",
    "switch_to_publish",
    "notice_publish_pipeline",
    "stop_processing",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the Airflow step x run duration matrix from Postgres metadata."
    )
    parser.add_argument("--dag-id", default=DEFAULT_DAG_ID, help="Airflow DAG id.")
    parser.add_argument("--num-runs", default=DEFAULT_NUM_RUNS, type=int, help="Number of latest DAG runs to export.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, type=Path, help="Matrix CSV output path.")
    parser.add_argument("--mapping-output", default=DEFAULT_MAPPING_PATH, type=Path, help="Run mapping CSV output path.")
    parser.add_argument(
        "--psql-command",
        default=DEFAULT_PSQL_COMMAND,
        help="Command used to run psql against the Airflow metadata DB.",
    )
    return parser.parse_args()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_psql(psql_command: str, query: str) -> List[List[str]]:
    command = [*shlex.split(psql_command), "-AtF", "\t", "-c", query]
    result = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
    )
    rows = []
    for line in result.stdout.splitlines():
        if line.strip():
            rows.append(line.split("\t"))
    return rows


def selected_runs_sql(dag_id: str, num_runs: int) -> str:
    return f"""
with latest_runs as (
    select
        run_id,
        execution_date,
        conf::text as conf_text
    from dag_run
    where dag_id = {sql_literal(dag_id)}
    order by execution_date desc
    limit {int(num_runs)}
)
select
    run_id,
    execution_date::text,
    coalesce(conf_text, '{{}}')
from latest_runs
order by execution_date asc;
"""


def task_durations_sql(dag_id: str, run_ids: Iterable[str]) -> str:
    values_sql = ",".join(f"({sql_literal(run_id)})" for run_id in run_ids)
    return f"""
with selected_runs(run_id) as (
    values {values_sql}
)
select
    ti.run_id,
    ti.task_id,
    coalesce(ti.duration, 0)::text
from task_instance ti
join selected_runs sr on sr.run_id = ti.run_id
where ti.dag_id = {sql_literal(dag_id)}
order by ti.run_id, ti.task_id;
"""


def parse_notice_ids(conf_text: str) -> str:
    if not conf_text:
        return ""

    conf = None
    if conf_text.startswith("\\x"):
        try:
            conf = pickle.loads(bytes.fromhex(conf_text[2:]))
        except (ValueError, pickle.PickleError):
            conf = None

    if conf is None:
        try:
            conf = json.loads(conf_text)
        except json.JSONDecodeError:
            return ""

    if not isinstance(conf, dict):
        return ""
    notice_ids = conf.get("notice_ids") or []
    if not isinstance(notice_ids, list):
        return ""
    return " ".join(str(notice_id) for notice_id in notice_ids)


def fetch_runs(psql_command: str, dag_id: str, num_runs: int) -> Tuple[List[str], Dict[str, str], Dict[str, str]]:
    rows = run_psql(
        psql_command=psql_command,
        query=selected_runs_sql(dag_id=dag_id, num_runs=num_runs),
    )
    if not rows:
        raise RuntimeError(f"No DAG runs found for dag_id={dag_id!r}.")

    run_ids = []
    timestamps_by_run = {}
    notice_ids_by_run = {}
    for run_id, timestamp, conf_text in rows:
        run_ids.append(run_id)
        timestamps_by_run[run_id] = timestamp
        notice_ids_by_run[run_id] = parse_notice_ids(conf_text)
    return run_ids, timestamps_by_run, notice_ids_by_run


def fetch_task_durations(psql_command: str, dag_id: str, run_ids: List[str]) -> Dict[str, Dict[str, Optional[float]]]:
    rows = run_psql(
        psql_command=psql_command,
        query=task_durations_sql(dag_id=dag_id, run_ids=run_ids),
    )
    durations: Dict[str, Dict[str, Optional[float]]] = defaultdict(dict)
    for run_id, task_id, duration in rows:
        durations[task_id][run_id] = float(duration or 0)
    return durations


def write_matrix_csv(
    output_path: Path,
    dag_id: str,
    run_ids: List[str],
    durations: Dict[str, Dict[str, Optional[float]]],
) -> Tuple[int, float]:
    labels = [f"run_{index}" for index in range(1, len(run_ids) + 1)]
    run_totals = {run_id: 0.0 for run_id in run_ids}
    grand_total = 0.0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow([f"{dag_id}_step", *labels, "total_step_time", "average_step_time"])

        for step in TASK_STEPS:
            values = []
            step_total = 0.0
            populated_cells = 0
            for run_id in run_ids:
                value = durations.get(step, {}).get(run_id)
                if value is None:
                    values.append("")
                    continue
                values.append(f"{value:.6f}")
                run_totals[run_id] += value
                step_total += value
                populated_cells += 1

            grand_total += step_total
            average = step_total / populated_cells if populated_cells else 0.0
            writer.writerow([step, *values, f"{step_total:.6f}", f"{average:.6f}"])

        writer.writerow([
            "",
            *[f"{run_totals[run_id]:.6f}" if run_totals[run_id] else "" for run_id in run_ids],
            f"{grand_total:.6f}",
            "",
        ])

    return len(TASK_STEPS), grand_total


def write_mapping_csv(
    mapping_path: Path,
    run_ids: List[str],
    timestamps_by_run: Dict[str, str],
    notice_ids_by_run: Dict[str, str],
) -> None:
    labels = [f"run_{index}" for index in range(1, len(run_ids) + 1)]
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    with mapping_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["column", "airflow_run_id", "timestamp", "notice_ids"])
        for label, run_id in zip(labels, run_ids):
            writer.writerow([
                label,
                run_id,
                run_id.replace("manual__", "") if run_id.startswith("manual__") else timestamps_by_run.get(run_id, ""),
                notice_ids_by_run.get(run_id, ""),
            ])


def main() -> None:
    args = parse_args()
    run_ids, timestamps_by_run, notice_ids_by_run = fetch_runs(
        psql_command=args.psql_command,
        dag_id=args.dag_id,
        num_runs=args.num_runs,
    )
    durations = fetch_task_durations(
        psql_command=args.psql_command,
        dag_id=args.dag_id,
        run_ids=run_ids,
    )
    steps_count, grand_total = write_matrix_csv(
        output_path=args.output,
        dag_id=args.dag_id,
        run_ids=run_ids,
        durations=durations,
    )
    write_mapping_csv(
        mapping_path=args.mapping_output,
        run_ids=run_ids,
        timestamps_by_run=timestamps_by_run,
        notice_ids_by_run=notice_ids_by_run,
    )

    print(f"output={args.output.resolve()}")
    print(f"mapping={args.mapping_output.resolve()}")
    print(f"runs={len(run_ids)}")
    print(f"steps={steps_count}")
    print(f"total_time={grand_total:.6f}")


if __name__ == "__main__":
    main()
