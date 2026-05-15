#!/usr/bin/env python3
"""Benchmark ERS resolution calls using extracted organisation TTL fragments.

The script builds the same mention payload used by the extraction helper:

    {"mentions": [{"mention": {...}}, ...]}

It measures three shapes of traffic:

* individual requests: one mention per request
* sequential batches: batches of configurable sizes, e.g. 10/30/100/300
* parallel batches: many concurrent requests, each with 4-12 mentions by default
"""

import argparse
import csv
import os
import platform
import random
import socket
import statistics
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import rdflib
import requests
from rdflib.namespace import RDF

DEFAULT_INPUT_DIR = Path("test/test_data/organisations")
DEFAULT_OUTPUT_PATH = Path("test/test_data/ers_time_performance/ers_resolution_performance_report.csv")
ORG_TYPE_URI = rdflib.URIRef("http://www.w3.org/ns/org#Organization")
ERS_SOURCE_ID = "TEDSWS"
ERS_CONTENT_TYPE = "text/turtle"


@dataclass(frozen=True)
class MentionRecord:
    content_file: str
    entity_uri: str
    notice_id: str
    payload: dict


@dataclass(frozen=True)
class RequestResult:
    scenario: str
    mode: str
    batch_size: int
    parallel_workers: int
    mention_count: int
    duration_seconds: float
    status_code: int | None
    success: bool
    error: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send organisation mentions to ERS and write a performance CSV."
    )
    parser.add_argument(
        "--ers-url",
        required=True,
        help=(
            "ERS base URL, e.g. https://ers-api.ersys.meaningfy.ws. "
            "If a full /resolve-bulk URL is passed, it is also accepted."
        ),
    )
    parser.add_argument(
        "--resolve-url",
        help="Optional exact ERS single-resolution endpoint. Defaults to <ers-url>/api/v1/resolve.",
    )
    parser.add_argument(
        "--bulk-url",
        help="Optional exact ERS bulk-resolution endpoint. Defaults to <ers-url>/api/v1/resolve-bulk.",
    )
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        type=Path,
        help="Directory containing organisation TTL fragments.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_PATH,
        type=Path,
        help="CSV report output path.",
    )
    parser.add_argument(
        "--limit",
        default=0,
        type=int,
        help="Maximum mentions to benchmark. 0 means all TTL files.",
    )
    parser.add_argument(
        "--batch-sizes",
        default="10,30,100,300",
        help="Comma-separated sequential batch sizes.",
    )
    parser.add_argument(
        "--parallel-workers",
        default=100,
        type=int,
        help="Number of concurrent workers for the parallel scenario.",
    )
    parser.add_argument(
        "--parallel-requests",
        default="100,50",
        help="Comma-separated request counts for parallel scenarios.",
    )
    parser.add_argument(
        "--parallel-batch-min",
        default=4,
        type=int,
        help="Minimum mentions per parallel request.",
    )
    parser.add_argument(
        "--parallel-batch-max",
        default=12,
        type=int,
        help="Maximum mentions per parallel request.",
    )
    parser.add_argument("--timeout", default=120, type=float, help="HTTP timeout per request in seconds.")
    parser.add_argument("--seed", default=42, type=int, help="Random seed for parallel batches.")
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Extra HTTP header as KEY=VALUE. Can be passed multiple times.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build payloads and report planned scenarios without sending HTTP requests.",
    )
    parser.add_argument(
        "--skip-individual",
        action="store_true",
        help="Skip the one-mention-per-request scenario.",
    )
    parser.add_argument(
        "--skip-sequential",
        action="store_true",
        help="Skip sequential batch scenarios.",
    )
    parser.add_argument(
        "--individual-only",
        action="store_true",
        help="Run only the one-mention-per-request scenario.",
    )
    parser.add_argument(
        "--skip-parallel",
        action="store_true",
        help="Skip parallel batch scenarios.",
    )
    parser.add_argument(
        "--identifier-suffix",
        help=(
            "Suffix appended to each organisation URI before sending requests. "
            "Use this to avoid ERS cache hits between benchmark iterations."
        ),
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append result rows to an existing CSV instead of replacing it.",
    )
    return parser.parse_args()


def endpoint_urls(ers_url: str, resolve_url: str | None, bulk_url: str | None) -> tuple[str, str]:
    cleaned = ers_url.rstrip("/") + "/"
    if ers_url.rstrip("/").endswith("/api/v1/resolve-bulk"):
        default_bulk_url = ers_url.rstrip("/")
        default_resolve_url = ers_url.rstrip("/")[:-len("-bulk")]
    else:
        default_resolve_url = urljoin(cleaned, "api/v1/resolve")
        default_bulk_url = urljoin(cleaned, "api/v1/resolve-bulk")
    return resolve_url or default_resolve_url, bulk_url or default_bulk_url


def parse_int_list(value: str) -> list[int]:
    numbers = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not numbers:
        raise ValueError("At least one batch size is required.")
    return numbers


def parse_headers(header_values: Sequence[str]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    for header in header_values:
        if "=" not in header:
            raise ValueError(f"Invalid header {header!r}. Expected KEY=VALUE.")
        key, value = header.split("=", 1)
        headers[key.strip()] = value.strip()
    return headers


def notice_id_from_file(path: Path) -> str:
    parts = path.stem.split("__")
    if len(parts) >= 3:
        return parts[-2]
    return path.stem


def ttl_files(input_dir: Path, limit: int) -> list[Path]:
    files = sorted(input_dir.glob("*.ttl"))
    if limit > 0:
        files = files[:limit]
    if not files:
        raise RuntimeError(f"No .ttl files found in {input_dir.resolve()}.")
    return files


def organisation_uri_from_content(content: str, path: Path) -> str:
    graph = rdflib.Graph()
    graph.parse(data=content, format="nt")
    subjects = sorted(
        str(subject)
        for subject in graph.subjects(RDF.type, ORG_TYPE_URI)
        if isinstance(subject, rdflib.URIRef)
    )
    if not subjects:
        raise RuntimeError(f"No org:Organization subject found in {path}.")
    return subjects[0]


def build_mention(entity_uri: str, notice_id: str, content: str) -> dict:
    return {
        "mention": {
            "object_description": entity_uri,
            "identifiedBy": {
                "object_description": entity_uri,
                "source_id": ERS_SOURCE_ID,
                "request_id": entity_uri,
                "entity_type": "ORGANISATION",
            },
            "content": content,
            "content_type": ERS_CONTENT_TYPE,
            "parsed_representation": content,
            "context": notice_id,
        }
    }


def load_mentions(input_dir: Path, limit: int, identifier_suffix: str | None = None) -> list[MentionRecord]:
    mentions = []
    for index, path in enumerate(ttl_files(input_dir=input_dir, limit=limit), start=1):
        content = path.read_text(encoding="utf-8").strip()
        entity_uri = organisation_uri_from_content(content=content, path=path)
        if identifier_suffix:
            suffixed_entity_uri = f"{entity_uri}/{identifier_suffix}-{index:05d}"
            content = content.replace(entity_uri, suffixed_entity_uri)
            entity_uri = suffixed_entity_uri
        notice_id = notice_id_from_file(path)
        mentions.append(
            MentionRecord(
                content_file=path.name,
                entity_uri=entity_uri,
                notice_id=notice_id,
                payload=build_mention(entity_uri=entity_uri, notice_id=notice_id, content=content),
            )
        )
    return mentions


def chunks(items: Sequence[MentionRecord], size: int) -> Iterable[list[MentionRecord]]:
    for start in range(0, len(items), size):
        yield list(items[start:start + size])


def make_parallel_batches(
    mentions: Sequence[MentionRecord],
    request_count: int,
    batch_min: int,
    batch_max: int,
    seed: int,
) -> list[list[MentionRecord]]:
    if batch_min <= 0 or batch_max < batch_min:
        raise ValueError("Parallel batch min/max values are invalid.")

    randomiser = random.Random(seed)
    shuffled = list(mentions)
    randomiser.shuffle(shuffled)
    batches = []
    cursor = 0
    for _ in range(request_count):
        size = randomiser.randint(batch_min, batch_max)
        batch = []
        for _ in range(size):
            batch.append(shuffled[cursor % len(shuffled)])
            cursor += 1
        batches.append(batch)
    return batches


def post_batch(
    session: requests.Session,
    resolve_url: str,
    bulk_url: str,
    headers: dict[str, str],
    batch: Sequence[MentionRecord],
    timeout: float,
    scenario: str,
    mode: str,
    batch_size: int,
    parallel_workers: int,
) -> RequestResult:
    request_url = resolve_url if mode == "individual" else bulk_url
    body = batch[0].payload if mode == "individual" else {"mentions": [mention.payload for mention in batch]}
    started = time.perf_counter()
    try:
        response = session.post(request_url, json=body, headers=headers, timeout=timeout)
        duration = time.perf_counter() - started
        return RequestResult(
            scenario=scenario,
            mode=mode,
            batch_size=batch_size,
            parallel_workers=parallel_workers,
            mention_count=len(batch),
            duration_seconds=duration,
            status_code=response.status_code,
            success=response.ok,
            error="" if response.ok else response.text[:500],
        )
    except requests.RequestException as exc:
        duration = time.perf_counter() - started
        return RequestResult(
            scenario=scenario,
            mode=mode,
            batch_size=batch_size,
            parallel_workers=parallel_workers,
            mention_count=len(batch),
            duration_seconds=duration,
            status_code=None,
            success=False,
            error=str(exc),
        )


def dry_run_results(
    scenario: str,
    mode: str,
    batches: Sequence[Sequence[MentionRecord]],
    batch_size: int,
    parallel_workers: int,
) -> tuple[float, list[RequestResult]]:
    results = [
        RequestResult(
            scenario=scenario,
            mode=mode,
            batch_size=batch_size,
            parallel_workers=parallel_workers,
            mention_count=len(batch),
            duration_seconds=0.0,
            status_code=None,
            success=True,
            error="dry_run",
        )
        for batch in batches
    ]
    return 0.0, results


def run_sequential_scenario(
    resolve_url: str,
    bulk_url: str,
    headers: dict[str, str],
    mentions: Sequence[MentionRecord],
    batch_size: int,
    timeout: float,
    dry_run: bool,
) -> tuple[float, list[RequestResult]]:
    mode = "individual" if batch_size == 1 else "sequential_batch"
    scenario = "individual" if batch_size == 1 else f"batch_{batch_size}"
    scenario_batches = list(chunks(mentions, batch_size))
    if dry_run:
        return dry_run_results(
            scenario=scenario,
            mode=mode,
            batches=scenario_batches,
            batch_size=batch_size,
            parallel_workers=1,
        )

    results = []
    started = time.perf_counter()
    with requests.Session() as session:
        for batch in scenario_batches:
            results.append(
                post_batch(
                    session=session,
                    resolve_url=resolve_url,
                    bulk_url=bulk_url,
                    headers=headers,
                    batch=batch,
                    timeout=timeout,
                    scenario=scenario,
                    mode=mode,
                    batch_size=batch_size,
                    parallel_workers=1,
                )
            )
    return time.perf_counter() - started, results


def run_parallel_scenario(
    resolve_url: str,
    bulk_url: str,
    headers: dict[str, str],
    mentions: Sequence[MentionRecord],
    request_count: int,
    batch_min: int,
    batch_max: int,
    workers: int,
    timeout: float,
    seed: int,
    dry_run: bool,
) -> tuple[float, list[RequestResult]]:
    scenario_batches = make_parallel_batches(
        mentions=mentions,
        request_count=request_count,
        batch_min=batch_min,
        batch_max=batch_max,
        seed=seed,
    )
    scenario = f"parallel_{request_count}_requests_{batch_min}_{batch_max}_mentions"
    if dry_run:
        return dry_run_results(
            scenario=scenario,
            mode="parallel_batch",
            batches=scenario_batches,
            batch_size=0,
            parallel_workers=workers,
        )

    results = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for batch in scenario_batches:
            session = requests.Session()
            futures.append(
                executor.submit(
                    post_batch,
                    session,
                    resolve_url,
                    bulk_url,
                    headers,
                    batch,
                    timeout,
                    scenario,
                    "parallel_batch",
                    len(batch),
                    workers,
                )
            )
        for future in as_completed(futures):
            results.append(future.result())
    return time.perf_counter() - started, results


def percentile(values: Sequence[float], percent: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = round((len(sorted_values) - 1) * percent)
    return sorted_values[index]


def machine_info() -> dict:
    return {
        "machine_hostname": socket.gethostname(),
        "machine_platform": platform.platform(),
        "machine_processor": platform.processor(),
        "machine_architecture": platform.machine(),
        "cpu_count": str(os.cpu_count() or ""),
        "python_version": platform.python_version(),
    }


def summarise_results(
    scenario_wall_time: float,
    results: Sequence[RequestResult],
    resolve_url: str,
    bulk_url: str,
    total_available_mentions: int,
) -> dict:
    mentions_sent = sum(result.mention_count for result in results)
    successful_requests = sum(1 for result in results if result.success)
    failed_requests = len(results) - successful_requests
    request_durations = [result.duration_seconds for result in results]
    per_mention_latencies = [
        result.duration_seconds / result.mention_count
        for result in results
        if result.mention_count
    ]

    first = results[0]
    return {
        **machine_info(),
        "resolve_url": resolve_url,
        "bulk_url": bulk_url,
        "scenario": first.scenario,
        "mode": first.mode,
        "configured_batch_size": str(first.batch_size),
        "parallel_workers": str(first.parallel_workers),
        "available_mentions": str(total_available_mentions),
        "requests_sent": str(len(results)),
        "mentions_sent": str(mentions_sent),
        "successful_requests": str(successful_requests),
        "failed_requests": str(failed_requests),
        "wall_time_seconds": f"{scenario_wall_time:.6f}",
        "wall_time_seconds_per_mention": f"{(scenario_wall_time / mentions_sent) if mentions_sent else 0.0:.6f}",
        "sum_request_time_seconds": f"{sum(request_durations):.6f}",
        "avg_request_time_seconds": f"{statistics.mean(request_durations) if request_durations else 0.0:.6f}",
        "p50_request_time_seconds": f"{percentile(request_durations, 0.50):.6f}",
        "p95_request_time_seconds": f"{percentile(request_durations, 0.95):.6f}",
        "max_request_time_seconds": f"{max(request_durations) if request_durations else 0.0:.6f}",
        "avg_request_time_seconds_per_mention": f"{statistics.mean(per_mention_latencies) if per_mention_latencies else 0.0:.6f}",
        "p50_request_time_seconds_per_mention": f"{percentile(per_mention_latencies, 0.50):.6f}",
        "p95_request_time_seconds_per_mention": f"{percentile(per_mention_latencies, 0.95):.6f}",
        "max_request_time_seconds_per_mention": f"{max(per_mention_latencies) if per_mention_latencies else 0.0:.6f}",
    }


def write_report(output_path: Path, rows: Sequence[dict], append: bool = False) -> None:
    if not rows:
        raise RuntimeError("No benchmark rows to write.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    should_write_header = not append or not output_path.exists() or output_path.stat().st_size == 0
    open_mode = "a" if append else "w"
    with output_path.open(open_mode, newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(rows[0]))
        if should_write_header:
            writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    mentions = load_mentions(
        input_dir=input_dir,
        limit=args.limit,
        identifier_suffix=args.identifier_suffix,
    )
    headers = parse_headers(args.header)
    batch_sizes = parse_int_list(args.batch_sizes)
    parallel_request_counts = parse_int_list(args.parallel_requests)
    resolve_url, bulk_url = endpoint_urls(
        ers_url=args.ers_url,
        resolve_url=args.resolve_url,
        bulk_url=args.bulk_url,
    )

    report_rows = []
    if args.individual_only:
        scenario_batch_sizes = [1]
    else:
        scenario_batch_sizes = batch_sizes if args.skip_individual else [1, *batch_sizes]
    if not args.skip_sequential:
        for batch_size in scenario_batch_sizes:
            wall_time, results = run_sequential_scenario(
                resolve_url=resolve_url,
                bulk_url=bulk_url,
                headers=headers,
                mentions=mentions,
                batch_size=batch_size,
                timeout=args.timeout,
                dry_run=args.dry_run,
            )
            report_rows.append(
                summarise_results(
                    scenario_wall_time=wall_time,
                    results=results,
                    resolve_url=resolve_url,
                    bulk_url=bulk_url,
                    total_available_mentions=len(mentions),
                )
            )

    if not args.skip_parallel:
        for request_count in parallel_request_counts:
            wall_time, results = run_parallel_scenario(
                resolve_url=resolve_url,
                bulk_url=bulk_url,
                headers=headers,
                mentions=mentions,
                request_count=request_count,
                batch_min=args.parallel_batch_min,
                batch_max=args.parallel_batch_max,
                workers=args.parallel_workers,
                timeout=args.timeout,
                seed=args.seed,
                dry_run=args.dry_run,
            )
            report_rows.append(
                summarise_results(
                    scenario_wall_time=wall_time,
                    results=results,
                    resolve_url=resolve_url,
                    bulk_url=bulk_url,
                    total_available_mentions=len(mentions),
                )
            )

    write_report(output_path=args.output, rows=report_rows, append=args.append)
    print(f"input_dir={input_dir}")
    print(f"mentions_loaded={len(mentions)}")
    print(f"resolve_url={resolve_url}")
    print(f"bulk_url={bulk_url}")
    print(f"output={args.output.resolve()}")
    print(f"dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
