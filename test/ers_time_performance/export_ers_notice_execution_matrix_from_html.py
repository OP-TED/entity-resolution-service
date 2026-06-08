#!/usr/bin/env python3
"""Export an ERS Airflow timing matrix for the runs shown in an Airflow Grid.

Airflow's rendered Grid contains the visible run ids and ERS task rows. The
exact per-task durations are read from the Airflow REST API for those runs.
"""

import argparse
import json
import os
import re
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import requests
from export_ers_notice_execution_matrix_postgres import (
    DEFAULT_MAPPING_PATH,
    DEFAULT_OUTPUT_PATH,
    write_ers_matrix_csv,
)
from export_notice_execution_matrix_postgres import (
    DEFAULT_DAG_ID,
    write_mapping_csv,
)

DEFAULT_HTML_PATH = Path("test/test_data/ers_time_performance/02-12-2025-ers-enabled.html")
DEFAULT_GRID_URL = (
    "https://<your-airflow-host>/dags/notice_processing_pipeline/grid?num_runs=365"
)
RUN_CLASS_PATTERN = re.compile(r'class="js-([^"\s]+)')
DAG_ID_PATTERN = re.compile(r'<meta\s+name="dag_id"\s+content="([^"]+)"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the ERS Airflow step x run duration matrix for runs found in an Airflow Grid."
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
    parser.add_argument(
        "--max-runs",
        type=int,
        help="Only export the first N run ids found in the Grid HTML.",
    )
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


def airflow_base_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise RuntimeError(f"Invalid Airflow URL: {url!r}")
    return urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")


def dag_id_from_grid_url(url: str) -> str | None:
    parts = urlsplit(url)
    match = re.search(r"/dags/([^/]+)/grid", parts.path)
    return match.group(1) if match else None


def session_for_args(args: argparse.Namespace) -> requests.Session:
    session = requests.Session()
    if args.username and args.password:
        session.auth = (args.username, args.password)
    if args.cookie:
        session.headers.update({"Cookie": args.cookie})
    return session


def fetch_grid_html(session: requests.Session, grid_url: str) -> str:
    response = session.get(grid_url, timeout=30)
    response.raise_for_status()
    return response.text


def extract_dag_id(html: str) -> str:
    match = DAG_ID_PATTERN.search(html)
    return match.group(1) if match else DEFAULT_DAG_ID


def extract_run_ids(html: str) -> list[str]:
    ordered_run_ids: dict[str, None] = OrderedDict()
    for match in RUN_CLASS_PATTERN.finditer(html):
        run_id = match.group(1)
        if run_id.startswith(("manual__", "scheduled__", "backfill__", "dataset_triggered__")):
            ordered_run_ids[run_id] = None
    return list(ordered_run_ids)


def timestamps_by_run_id(run_ids: list[str]) -> dict[str, str]:
    return {
        run_id: run_id.replace("manual__", "", 1) if run_id.startswith("manual__") else run_id
        for run_id in run_ids
    }


def parse_notice_ids(conf: object) -> str:
    if not isinstance(conf, dict):
        return ""
    notice_ids = conf.get("notice_ids") or []
    if not isinstance(notice_ids, list):
        return ""
    return " ".join(str(notice_id) for notice_id in notice_ids)


def task_instances_url(base_url: str, dag_id: str, run_id: str) -> str:
    return (
        f"{base_url}/api/v1/dags/{quote(dag_id, safe='')}"
        f"/dagRuns/{quote(run_id, safe='')}/taskInstances"
    )


def dag_run_url(base_url: str, dag_id: str, run_id: str) -> str:
    return (
        f"{base_url}/api/v1/dags/{quote(dag_id, safe='')}"
        f"/dagRuns/{quote(run_id, safe='')}"
    )


def fetch_task_durations_from_airflow_api(
    session: requests.Session,
    base_url: str,
    dag_id: str,
    run_ids: list[str],
) -> dict[str, dict[str, float | None]]:
    durations: dict[str, dict[str, float | None]] = {}
    for run_id in run_ids:
        response = session.get(task_instances_url(base_url=base_url, dag_id=dag_id, run_id=run_id), timeout=30)
        response.raise_for_status()
        payload = response.json()
        for task_instance in payload.get("task_instances", []):
            task_id = task_instance.get("task_id")
            if not task_id:
                continue
            value = task_instance.get("duration")
            durations.setdefault(task_id, {})[run_id] = float(value or 0)
    return durations


def fetch_notice_ids_from_airflow_api(
    session: requests.Session,
    base_url: str,
    dag_id: str,
    run_ids: list[str],
) -> dict[str, str]:
    notice_ids_by_run: dict[str, str] = {}
    for run_id in run_ids:
        response = session.get(dag_run_url(base_url=base_url, dag_id=dag_id, run_id=run_id), timeout=30)
        response.raise_for_status()
        payload = response.json()
        conf = payload.get("conf") or {}
        if isinstance(conf, str):
            try:
                conf = json.loads(conf)
            except json.JSONDecodeError:
                conf = {}
        notice_ids_by_run[run_id] = parse_notice_ids(conf)
    return notice_ids_by_run


def load_grid_html(args: argparse.Namespace, session: requests.Session) -> tuple[str, str]:
    if args.prefer_grid_url or not args.html.exists():
        return fetch_grid_html(session=session, grid_url=args.grid_url), args.grid_url
    return args.html.read_text(encoding="utf-8"), str(args.html)


def main() -> None:
    args = parse_args()
    session = session_for_args(args)
    html, grid_source = load_grid_html(args=args, session=session)
    dag_id = args.dag_id or dag_id_from_grid_url(args.grid_url) or extract_dag_id(html)
    run_ids = extract_run_ids(html)
    if args.max_runs is not None:
        run_ids = run_ids[:args.max_runs]
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
    steps_count, grand_total = write_ers_matrix_csv(
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
