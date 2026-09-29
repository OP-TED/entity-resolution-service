#!/usr/bin/env python3
"""Extract organisation mention fragments for ERS performance tests."""

import argparse
import hashlib
import json
import random
import shutil
from pathlib import Path
from typing import TextIO

import rdflib
from rdflib.namespace import RDF

ORG_TYPE_URI = rdflib.URIRef("http://www.w3.org/ns/org#Organization")
ERS_SOURCE_ID = "TEDSWS"
ERS_CONTENT_TYPE = "text/turtle"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract org:Organization RDF fragments from notice TTL files and "
            "write one ERS-ready fragment file per organisation."
        )
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        type=Path,
        help="Directory containing notice TTL files, searched recursively.",
    )
    parser.add_argument(
        "--output-dir",
        default=Path("test/test_data/organisations"),
        type=Path,
        help="Directory where organisation fragment .ttl files and manifest.jsonl are written.",
    )
    parser.add_argument(
        "--limit",
        default=20000,
        type=int,
        help="Maximum number of organisation fragments to write.",
    )
    parser.add_argument(
        "--seed",
        default=42,
        type=int,
        help="Random seed used to shuffle notice files before extraction.",
    )
    parser.add_argument(
        "--clear-output",
        action="store_true",
        help="Remove existing files in the output directory before writing new fragments.",
    )
    return parser.parse_args()


def iter_notice_files(input_dir: Path, seed: int) -> list[Path]:
    notice_files = sorted(input_dir.rglob("*.ttl"))
    random.Random(seed).shuffle(notice_files)
    return notice_files


def notice_id_from_path(path: Path) -> str:
    return path.stem


def package_id_from_path(input_dir: Path, path: Path) -> str:
    relative = path.relative_to(input_dir)
    if len(relative.parts) > 1:
        return relative.parts[0]
    return input_dir.name


def load_graph(path: Path) -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(path, format="turtle")
    return graph


def organisation_subjects(graph: rdflib.Graph) -> list[rdflib.URIRef]:
    subjects = {
        subject
        for subject in graph.subjects(RDF.type, ORG_TYPE_URI)
        if isinstance(subject, rdflib.URIRef)
    }
    return sorted(subjects, key=str)


def fragment_for_subject(graph: rdflib.Graph, subject: rdflib.URIRef) -> rdflib.Graph:
    """Match the production fragment shape: direct triples plus one object dependency level."""
    fragment = rdflib.Graph()
    for _, predicate, obj in graph.triples((subject, None, None)):
        fragment.add((subject, predicate, obj))
        for _, object_predicate, object_obj in graph.triples((obj, None, None)):
            fragment.add((obj, object_predicate, object_obj))
    return fragment


def to_sorted_nt(graph: rdflib.Graph) -> str:
    return "\n".join(
        sorted(line for line in graph.serialize(format="nt").splitlines() if line.strip())
    )


def safe_file_stem(package_id: str, notice_id: str, entity_uri: str) -> str:
    uri_hash = hashlib.sha256(entity_uri.encode("utf-8")).hexdigest()[:16]
    return f"{package_id}__{notice_id}__{uri_hash}"


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


def prepare_output_dir(output_dir: Path, clear_output: bool) -> None:
    if clear_output and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def write_manifest_record(manifest: TextIO, record: dict) -> None:
    manifest.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
    manifest.write("\n")


def extract_organisations(
    input_dir: Path,
    output_dir: Path,
    limit: int,
    seed: int,
) -> tuple[int, int, int, int]:
    notice_files = iter_notice_files(input_dir=input_dir, seed=seed)
    written = 0
    notices_with_organisations = 0
    parse_errors = 0

    manifest_path = output_dir / "manifest.jsonl"
    bulk_request_path = output_dir / "resolve_bulk_request.json"
    mentions = []

    with manifest_path.open("w", encoding="utf-8") as manifest:
        for notice_file in notice_files:
            if written >= limit:
                break

            try:
                graph = load_graph(notice_file)
            except Exception as exc:
                parse_errors += 1
                write_manifest_record(
                    manifest,
                    {
                        "error": str(exc),
                        "source_notice_file": str(notice_file),
                        "status": "parse_error",
                    },
                )
                continue

            subjects = organisation_subjects(graph)
            if subjects:
                notices_with_organisations += 1

            notice_id = notice_id_from_path(notice_file)
            package_id = package_id_from_path(input_dir=input_dir, path=notice_file)

            for subject in subjects:
                if written >= limit:
                    break

                entity_uri = str(subject)
                fragment = fragment_for_subject(graph=graph, subject=subject)
                content = to_sorted_nt(fragment)
                if not content:
                    continue

                file_stem = safe_file_stem(
                    package_id=package_id,
                    notice_id=notice_id,
                    entity_uri=entity_uri,
                )
                fragment_path = output_dir / f"{file_stem}.ttl"
                fragment_path.write_text(content + "\n", encoding="utf-8")

                mention = build_mention(
                    entity_uri=entity_uri,
                    notice_id=notice_id,
                    content=content,
                )
                mentions.append(mention)
                write_manifest_record(
                    manifest,
                    {
                        "content_file": fragment_path.name,
                        "entity_type": "ORGANISATION",
                        "entity_uri": entity_uri,
                        "mention": mention,
                        "notice_id": notice_id,
                        "package_id": package_id,
                        "source_notice_file": str(notice_file),
                        "triple_count": len(fragment),
                    },
                )
                written += 1

    bulk_request_path.write_text(
        json.dumps({"mentions": mentions}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return written, len(notice_files), notices_with_organisations, parse_errors


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not input_dir.exists():
        raise FileNotFoundError(input_dir)

    prepare_output_dir(output_dir=output_dir, clear_output=args.clear_output)
    written, notices_seen, notices_with_organisations, parse_errors = extract_organisations(
        input_dir=input_dir,
        output_dir=output_dir,
        limit=args.limit,
        seed=args.seed,
    )

    print(f"input_dir={input_dir}")
    print(f"output_dir={output_dir}")
    print(f"notice_ttl_files_seen={notices_seen}")
    print(f"notices_with_organisations={notices_with_organisations}")
    print(f"organisation_fragments_written={written}")
    print(f"parse_errors={parse_errors}")
    print(f"manifest={output_dir / 'manifest.jsonl'}")
    print(f"bulk_request={output_dir / 'resolve_bulk_request.json'}")


if __name__ == "__main__":
    main()
