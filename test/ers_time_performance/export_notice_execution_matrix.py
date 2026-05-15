#!/usr/bin/env python3
"""Export an old-code Airflow timing matrix for the runs shown in a Grid HTML.

This is the non-ERS counterpart of export_ers_notice_execution_matrix_from_html.py.
It uses the saved Airflow Grid HTML to select run ids, then reads exact task
durations from the hosted Airflow REST API.
"""

import argparse
import os
from pathlib import Path

from export_ers_notice_execution_matrix_from_html import (
    DEFAULT_GRID_URL,
    airflow_base_url,
    dag_id_from_grid_url,
    extract_dag_id,
    extract_run_ids,
    fetch_notice_ids_from_airflow_api,
    fetch_task_durations_from_airflow_api,
    load_grid_html,
    session_for_args,
    timestamps_by_run_id,
)
from export_notice_execution_matrix_postgres import (
    DEFAULT_DAG_ID,
    DEFAULT_MAPPING_PATH,
    DEFAULT_OUTPUT_PATH,
    write_mapping_csv,
    write_matrix_csv,
)

DEFAULT_HTML_PATH = Path("test/test_data/ers_time_performance/2023-8-10-old-code.html")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the old-code Airflow step x run duration matrix for runs found in a Grid HTML."
    )
    parser.add_argument(
        "--html",
        default=DEFAULT_HTML_PATH,
        type=Path,
        help="Saved Airflow Grid HTML path. Used when present unless --grid-url is passed.",
    )
    parser.add_argument(
        "--grid-url",
        default=DEFAULT_GRID_URL,
        help="Airflow Grid URL to fetch when --html does not exist or when --prefer-grid-url is passed.",
    )
    parser.add_argument(
        "--prefer-grid-url",
        action="store_true",
        help="Fetch the Grid page from --grid-url even if --html exists.",
    )
    parser.add_argument("--dag-id", help="Airflow DAG id. Defaults to the Grid URL, HTML meta dag_id, or notice_processing_pipeline.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, type=Path, help="Matrix CSV output path.")
    parser.add_argument("--mapping-output", default=DEFAULT_MAPPING_PATH, type=Path, help="Run mapping CSV output path.")
    parser.add_argument(
        "--username",
        default=os.environ.get("AIRFLOW_USERNAME"),
        help="Optional Airflow username for basic auth. Defaults to AIRFLOW_USERNAME.",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("AIRFLOW_PASSWORD"),
        help="Optional Airflow password for basic auth. Defaults to AIRFLOW_PASSWORD.",
    )
    parser.add_argument(
        "--cookie",
        default=os.environ.get("AIRFLOW_COOKIE"),
        help="Optional Cookie header for authenticated Airflow sessions. Defaults to AIRFLOW_COOKIE.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session = session_for_args(args)
    html, grid_source = load_grid_html(args=args, session=session)
    dag_id = args.dag_id or dag_id_from_grid_url(args.grid_url) or extract_dag_id(html) or DEFAULT_DAG_ID
    run_ids = extract_run_ids(html)
    if not run_ids:
        raise RuntimeError(f"No Airflow run ids found in {grid_source}.")

    base_url = airflow_base_url(args.grid_url)
    durations = fetch_task_durations_from_airflow_api(
        session=session,
        base_url=base_url,
        dag_id=dag_id,
        run_ids=run_ids,
    )
    notice_ids_by_run = fetch_notice_ids_from_airflow_api(
        session=session,
        base_url=base_url,
        dag_id=dag_id,
        run_ids=run_ids,
    )
    steps_count, grand_total = write_matrix_csv(
        output_path=args.output,
        dag_id=dag_id,
        run_ids=run_ids,
        durations=durations,
    )
    write_mapping_csv(
        mapping_path=args.mapping_output,
        run_ids=run_ids,
        timestamps_by_run=timestamps_by_run_id(run_ids),
        notice_ids_by_run=notice_ids_by_run,
    )

    print(f"grid_source={grid_source}")
    print(f"output={args.output.resolve()}")
    print(f"mapping={args.mapping_output.resolve()}")
    print(f"runs={len(run_ids)}")
    print(f"steps={steps_count}")
    print(f"total_time={grand_total:.6f}")


if __name__ == "__main__":
    main()
