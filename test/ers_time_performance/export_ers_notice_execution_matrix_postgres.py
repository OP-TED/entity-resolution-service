#!/usr/bin/env python3
"""Export an Airflow timing matrix for the ERS notice-processing path.

This is the ERS counterpart of export_notice_execution_matrix_postgres.py.
It reads the same Airflow metadata tables from Postgres, but uses the task
sequence that includes URI and entity resolution instead of distillation.
"""

import argparse
import csv
from pathlib import Path

from export_notice_execution_matrix_postgres import (
    DEFAULT_DAG_ID,
    DEFAULT_NUM_RUNS,
    DEFAULT_PSQL_COMMAND,
    fetch_runs,
    fetch_task_durations,
    write_mapping_csv,
)

DEFAULT_OUTPUT_PATH = Path("test/test_data/ers_time_performance/new_code.csv")
DEFAULT_MAPPING_PATH = Path("test/test_data/ers_time_performance/current_airflow_ers_run_mapping.csv")

ERS_TASK_STEPS = [
    "branch_selector",
    "notice_normalisation_pipeline",
    "switch_to_transformation",
    "notice_transformation_pipeline",
    "switch_to_uri_resolution",
    "notice_uri_resolution_pipeline",
    "switch_to_entity_resolution",
    "notice_entity_resolution_pipeline",
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
        description="Create the ERS Airflow step x run duration matrix from Postgres metadata."
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


def write_ers_matrix_csv(
    output_path: Path,
    dag_id: str,
    run_ids: list[str],
    durations: dict[str, dict[str, float | None]],
) -> tuple[int, float]:
    labels = [f"run_{index}" for index in range(1, len(run_ids) + 1)]
    run_totals = {run_id: 0.0 for run_id in run_ids}
    grand_total = 0.0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow([f"{dag_id}_ers_step", *labels, "total_step_time", "average_step_time"])

        for step in ERS_TASK_STEPS:
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

    return len(ERS_TASK_STEPS), grand_total


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
    steps_count, grand_total = write_ers_matrix_csv(
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
