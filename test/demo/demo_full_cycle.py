#!/usr/bin/env python3
"""
Demo: Full Entity Resolution lifecycle via ERS REST API.

This demo exercises the complete resolution flow through the ERS HTTP interface
(:8001) — the correct black-box boundary for this ops repository. It does NOT
talk to Redis or ERE directly.

Demonstrated steps:
  1. Health check — ERS API, Curation API, Redis reachability
  2. Submit mentions — 6 synthetic org mentions via POST /api/v1/resolve
  3. Poll for results — GET /api/v1/lookup until canonical cluster IDs arrive
  4. Clustering summary — group mentions by cluster_id
  5. Curation loop — inject ERE placement, assign via Curation API
  6. Bulk refresh — POST /api/v1/refresh-bulk and delta output

Prerequisites:
  make up   (starts the full stack)

Usage:
  poetry run python test/demo/demo_full_cycle.py
  poetry run python test/demo/demo_full_cycle.py --skip-curation
  poetry run python test/demo/demo_full_cycle.py --timeout 120
  poetry run python test/demo/demo_full_cycle.py --data /path/to/mentions.json
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import redis

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_DEMO_DIR = Path(__file__).parent
_DEFAULT_DATA_FILE = _DEMO_DIR / "data" / "demo_mentions.json"
_ENV_FILE = Path(__file__).resolve().parents[2] / "src" / "infra" / ".env"

# French-name mention used exclusively in Step 5 (curation loop).
# Same real-world entity as demo-org-1..3 represented in French, with no address
# fields — ensures ERE assigns it its own cluster (shared address would otherwise
# dominate the similarity score and merge it with the German-name cluster).
# "Ratisbonne" is the French toponym for Regensburg; no token overlaps with the
# German names, so name-based similarity is too low to trigger a merge.
_CURATION_ANCHOR_MENTION: dict = {
    "request_id": "demo-curation-anchor",
    "source_id": "demo-source-001",
    "entity_type": "ORGANISATION",
    "legal_name": "Autorité de district de Ratisbonne",
    "country_code": "DEU",
}

# ---------------------------------------------------------------------------
# Defaults — overridden by infra/.env when available
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "ERS_API_URL": "http://localhost:8001",
    "CURATION_API_URL": "http://localhost:8000",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6379",
    "REDIS_PASSWORD": "changeme",
    "ADMIN_EMAIL": "admin@ers.local",
    "ADMIN_PASSWORD": "changeme",
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def setup_logging() -> logging.Logger:
    """Configure logging with timestamps matching the original ERE demo style."""
    log_level_name = os.environ.get("ERE_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)
    logger.setLevel(log_level)
    return logger


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------


def _parse_env_value(raw: str) -> str:
    """Normalise a raw .env value: unquote and strip inline comments.

    Handles the two common .env conventions:
    - Quoted values:  KEY="value"  or  KEY='value'  — trailing content ignored.
    - Unquoted values with inline comments:  KEY=value  # note — comment stripped.
    """
    value = raw.strip()
    if value and value[0] in ('"', "'"):
        quote_char = value[0]
        end = value.find(quote_char, 1)
        return value[1:end] if end != -1 else value[1:]
    comment_start = value.find(" #")
    if comment_start != -1:
        value = value[:comment_start]
    return value.strip()


def load_config(env_path: Path | None = None) -> dict:
    """Load configuration from infra/.env, with environment variable overrides.

    Mirrors the load_env_file() pattern from the original ERE demo so that
    the same .env file drives both demos.
    """
    resolved_path = env_path or _ENV_FILE
    file_cfg: dict = {}

    if resolved_path.exists():
        with open(resolved_path) as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    file_cfg[key.strip()] = _parse_env_value(value)

    cfg = dict(_DEFAULTS)
    cfg.update(file_cfg)

    # Environment variables take highest precedence.
    for key in _DEFAULTS:
        env_val = os.environ.get(key)
        if env_val is not None:
            cfg[key] = env_val

    return cfg


# ---------------------------------------------------------------------------
# Demo data loading
# ---------------------------------------------------------------------------


def load_demo_mentions(data_file: Path) -> list[dict]:
    """Load mentions list from a JSON file with a top-level 'mentions' key.

    Args:
        data_file: Absolute path to the JSON file.

    Returns:
        List of mention dicts.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not valid JSON or lacks a 'mentions' key.
    """
    if not data_file.exists():
        raise FileNotFoundError(f"Data file not found: {data_file}")

    with open(data_file) as fh:
        data = json.load(fh)

    if "mentions" not in data:
        raise ValueError(f"JSON must contain a top-level 'mentions' key: {data_file}")

    return data["mentions"]


# ---------------------------------------------------------------------------
# Turtle content builder
# ---------------------------------------------------------------------------


def _escape_turtle(value: str) -> str:
    """Escape a Python string for safe embedding in a Turtle string literal."""
    if not value:
        return value
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    value = value.replace("\t", "\\t")
    return value


def build_turtle_content(
    request_id: str,
    legal_name: str,
    country_code: str,
    nuts_code: str | None = None,
    post_code: str | None = None,
    post_name: str | None = None,
    thoroughfare: str | None = None,
) -> str:
    """Build RDF/Turtle content string for a single organisation mention.

    The format matches what the ERS API expects for ORGANISATION entity types.
    Extended address fields are included when provided.
    """
    legal_name_safe = _escape_turtle(legal_name or "")
    country_code_safe = _escape_turtle(country_code or "")

    address_props = [f'epo:hasCountryCode "{country_code_safe}"']
    if nuts_code:
        address_props.append(f'epo:hasNutsCode "{_escape_turtle(nuts_code)}"')
    if post_code:
        address_props.append(f'locn:postCode "{_escape_turtle(post_code)}"')
    if post_name:
        address_props.append(f'locn:postName "{_escape_turtle(post_name)}"')
    if thoroughfare:
        address_props.append(f'locn:thoroughfare "{_escape_turtle(thoroughfare)}"')

    address_block = " ;\n        ".join(address_props)

    return (
        "@prefix org: <http://www.w3.org/ns/org#> .\n"
        "@prefix cccev: <http://data.europa.eu/m8g/> .\n"
        "@prefix epo: <http://data.europa.eu/a4g/ontology#> .\n"
        "@prefix locn: <http://www.w3.org/ns/locn#> .\n"
        "@prefix epd: <http://data.europa.eu/a4g/resource/> .\n"
        "\n"
        f"epd:ent{request_id} a org:Organization ;\n"
        f'    epo:hasLegalName "{legal_name_safe}" ;\n'
        "    cccev:registeredAddress [\n"
        f"        {address_block}\n"
        "    ] ."
    )


def build_resolve_payload(mention: dict) -> dict:
    """Build the POST /api/v1/resolve request body from a mention dict."""
    content = build_turtle_content(
        request_id=mention["request_id"],
        legal_name=mention["legal_name"],
        country_code=mention["country_code"],
        nuts_code=mention.get("nuts_code"),
        post_code=mention.get("post_code"),
        post_name=mention.get("post_name"),
        thoroughfare=mention.get("thoroughfare"),
    )
    return {
        "mention": {
            "identifiedBy": {
                "source_id": mention["source_id"],
                "request_id": mention["request_id"],
                "entity_type": mention["entity_type"],
            },
            "content": content,
            "content_type": "text/turtle",
        }
    }


# ---------------------------------------------------------------------------
# Step 1 — Health checks
# ---------------------------------------------------------------------------


def check_health(cfg: dict, logger: logging.Logger) -> bool:
    """Verify ERS API, Curation API, and Redis are reachable.

    Returns True if all three pass, False otherwise.
    Logs each result individually so the operator sees which service is missing.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("STEP 1 — HEALTH CHECKS")
    logger.info("=" * 80)

    all_ok = True

    # ERS API
    try:
        resp = httpx.get(f"{cfg['ERS_API_URL']}/health", timeout=10.0)
        if resp.status_code == 200:
            logger.info("  ERS API   (:8001) ... OK")
        else:
            logger.error(
                f"  ERS API   (:8001) ... FAIL (HTTP {resp.status_code})"
            )
            all_ok = False
    except httpx.ConnectError as exc:
        logger.error(f"  ERS API   (:8001) ... UNREACHABLE ({exc})")
        all_ok = False

    # Curation API
    try:
        resp = httpx.get(f"{cfg['CURATION_API_URL']}/health", timeout=10.0)
        if resp.status_code == 200:
            logger.info("  Curation  (:8000) ... OK")
        else:
            logger.warning(
                f"  Curation  (:8000) ... DEGRADED (HTTP {resp.status_code})"
            )
    except httpx.ConnectError as exc:
        logger.warning(f"  Curation  (:8000) ... UNREACHABLE ({exc})")

    # Redis
    redis_host = cfg["REDIS_HOST"]
    if redis_host == "redis":
        hosts_to_try = ["redis", "localhost"]
    else:
        hosts_to_try = [redis_host]

    redis_ok = False
    for host in hosts_to_try:
        try:
            rc = redis.Redis(
                host=host,
                port=int(cfg["REDIS_PORT"]),
                password=cfg.get("REDIS_PASSWORD"),
                decode_responses=True,
            )
            rc.ping()
            logger.info(f"  Redis     (:{cfg['REDIS_PORT']}) ... OK (host={host})")
            redis_ok = True
            break
        except Exception:
            continue

    if not redis_ok:
        logger.warning(
            f"  Redis     (:{cfg['REDIS_PORT']}) ... UNREACHABLE"
            " (ERE may be unable to process requests)"
        )

    return all_ok


# ---------------------------------------------------------------------------
# Step 2 — Submit mentions
# ---------------------------------------------------------------------------


def submit_mentions(
    mentions: list[dict],
    ers_client: httpx.Client,
    logger: logging.Logger,
) -> list[dict]:
    """POST each mention to /api/v1/resolve.

    Returns the list of mentions, each enriched with a 'payload' key containing
    the exact request body that was sent, so downstream steps can use the same
    triad for lookup and curation calls.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("STEP 2 — SUBMIT MENTIONS")
    logger.info("=" * 80)

    enriched = []
    for mention in mentions:
        payload = build_resolve_payload(mention)
        try:
            resp = ers_client.post("/api/v1/resolve", json=payload)
            status = resp.status_code
            ok = status in (200, 202)
            marker = "OK" if ok else "FAIL"
            logger.info(
                f"  -> {mention['request_id']:12s}  {mention['legal_name'][:45]:<45s}"
                f"  [{mention['country_code']}]  HTTP {status} {marker}"
            )
            enriched.append({**mention, "payload": payload, "submit_ok": ok})
        except httpx.HTTPError as exc:
            logger.error(
                f"  -> {mention['request_id']:12s}  SUBMIT ERROR: {exc}"
            )
            enriched.append({**mention, "payload": payload, "submit_ok": False})

    submitted_count = sum(1 for m in enriched if m["submit_ok"])
    logger.info(
        f"  Submitted {submitted_count}/{len(mentions)} mentions successfully."
    )
    return enriched


# ---------------------------------------------------------------------------
# Step 3 — Poll for results
# ---------------------------------------------------------------------------


def poll_mention(
    triad: dict,
    ers_client: httpx.Client,
    timeout_s: float,
    interval_s: float = 1.0,
) -> dict | None:
    """Poll GET /api/v1/lookup until a non-empty cluster_id appears or timeout.

    Returns the lookup response body on success, None on timeout.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            resp = ers_client.get(
                "/api/v1/lookup",
                params={
                    "source_id": triad["source_id"],
                    "request_id": triad["request_id"],
                    "entity_type": triad["entity_type"],
                },
            )
            if resp.status_code == 200:
                body = resp.json()
                cluster_id = body.get("cluster_reference", {}).get("cluster_id")
                if cluster_id:
                    return body
        except httpx.HTTPError:
            pass
        time.sleep(interval_s)
    return None


def poll_all_mentions(
    enriched_mentions: list[dict],
    ers_client: httpx.Client,
    timeout_s: float,
    logger: logging.Logger,
) -> list[dict]:
    """Poll lookup for every submitted mention, updating cluster_id in each entry.

    Returns the enriched list with 'cluster_id' added to each mention dict.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("STEP 3 — POLL FOR RESULTS")
    logger.info("=" * 80)
    logger.info(f"  Polling with {timeout_s:.0f}s timeout per mention...")

    results = []
    for mention in enriched_mentions:
        if not mention.get("submit_ok"):
            logger.info(
                f"  {mention['request_id']:12s}  SKIPPED (submit failed)"
            )
            results.append({**mention, "cluster_id": None})
            continue

        triad = mention["payload"]["mention"]["identifiedBy"]
        lookup = poll_mention(triad, ers_client, timeout_s=timeout_s)

        if lookup:
            cluster_id = lookup.get("cluster_reference", {}).get("cluster_id")
            status = lookup.get("status", "?")
            logger.info(
                f"  {mention['request_id']:12s}  cluster_id={cluster_id!r:45s}"
                f"  status={status}"
            )
            results.append({**mention, "cluster_id": cluster_id, "lookup": lookup})
        else:
            logger.warning(
                f"  {mention['request_id']:12s}  TIMEOUT after {timeout_s:.0f}s"
            )
            results.append({**mention, "cluster_id": None, "lookup": None})

    resolved = sum(1 for m in results if m["cluster_id"])
    logger.info(
        f"  Resolved {resolved}/{len(enriched_mentions)} mentions."
    )
    return results


# ---------------------------------------------------------------------------
# Step 4 — Clustering summary
# ---------------------------------------------------------------------------


def print_clustering_summary(
    resolved_mentions: list[dict],
    logger: logging.Logger,
) -> None:
    """Print a CLUSTERING SUMMARY block identical in style to the original ERE demo."""
    clusters: dict[str, list[tuple[str, str]]] = {}
    unassigned: list[tuple[str, str]] = []

    for mention in resolved_mentions:
        req_id = mention["request_id"]
        legal_name = mention["legal_name"]
        cluster_id = mention.get("cluster_id")

        if cluster_id:
            clusters.setdefault(cluster_id, []).append((req_id, legal_name))
        else:
            unassigned.append((req_id, legal_name))

    lines = []
    lines.append("=" * 80)
    lines.append("CLUSTERING SUMMARY")
    lines.append("=" * 80)

    if clusters:
        for cluster_id in sorted(clusters.keys()):
            members = clusters[cluster_id]
            lines.append("")
            lines.append(f"{cluster_id} ({len(members)} members):")
            for req_id, legal_name in members:
                lines.append(f"  {req_id:12s} | {legal_name}")
    else:
        lines.append("")
        lines.append("(No clusters formed)")

    if unassigned:
        lines.append("")
        lines.append(f"Unassigned ({len(unassigned)} mentions):")
        for req_id, legal_name in unassigned:
            lines.append(f"  {req_id:12s} | {legal_name}")

    lines.append("=" * 80)
    logger.info("\n%s", "\n".join(lines))


# ---------------------------------------------------------------------------
# Step 5 — Curation loop
# ---------------------------------------------------------------------------


def _obtain_auth_token(cfg: dict, logger: logging.Logger) -> str | None:
    """POST to Curation API /api/v1/auth/login and return the Bearer token."""
    try:
        resp = httpx.post(
            f"{cfg['CURATION_API_URL']}/api/v1/auth/login",
            json={
                "email": cfg["ADMIN_EMAIL"],
                "password": cfg["ADMIN_PASSWORD"],
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token") or data.get("token")
        if not token:
            logger.warning(
                "Curation login succeeded but response contained no token: %s", data
            )
        return token
    except httpx.HTTPError as exc:
        logger.warning("Curation API login failed: %s", exc)
        return None


def run_curation_loop(
    resolved_mentions: list[dict],
    cfg: dict,
    ers_client: httpx.Client,
    timeout_s: float,
    logger: logging.Logger,
) -> None:
    """Demonstrate the full curation workflow using a valid ERE candidate cluster.

    Flow:
      5a. Pick a resolved mention as the curation target.
      5b. Submit the same real-world entity under its French name; ERE assigns it
          its own cluster, giving us a legitimate target cluster ID.
      5c. Poll until the French-name mention is resolved.
      5d. First inject for the target mention: propose [current_cluster, french_cluster].
          The outcome integrator takes candidates[0] as current_placement and
          candidates[1:] as the assignable list — so french_cluster ends up as
          the sole candidate available to /assign.
      5e. Authenticate, find the decision, poll until french_cluster is a valid option.
      5f. Assign the target mention to french_cluster via the Curation API.
          This triggers ERS to send a re-resolution request.
      5g. Second inject: propose [french_cluster] only — confirms the assignment.
          The outcome integrator sets current_placement = french_cluster.
      5h. Poll lookup to confirm the cluster changed.

    Warnings are logged on any sub-step failure; the demo continues regardless.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("STEP 5 — CURATION LOOP")
    logger.info("=" * 80)

    # 5a — pick target mention x (first resolved mention)
    x = next((m for m in resolved_mentions if m.get("cluster_id")), None)
    if not x:
        logger.warning("  No resolved mention available for curation demo. Skipping.")
        return

    x_triad = x["payload"]["mention"]["identifiedBy"]
    x_cluster_id = x["cluster_id"]
    logger.info("  Target mention : %s (%s)", x["request_id"], x["legal_name"])
    logger.info("  Current cluster: %s", x_cluster_id)

    # 5b — submit the same entity under its French name to obtain a target cluster
    logger.info("")
    logger.info(
        "  5b — Resolving same entity under French name: %s  [%s]",
        _CURATION_ANCHOR_MENTION["legal_name"],
        _CURATION_ANCHOR_MENTION["country_code"],
    )
    y_payload = build_resolve_payload(_CURATION_ANCHOR_MENTION)
    try:
        resp = ers_client.post("/api/v1/resolve", json=y_payload)
        if resp.status_code not in (200, 202):
            logger.warning(
                "  Submission returned HTTP %d. Skipping.", resp.status_code
            )
            return
        logger.info("  Submitted (HTTP %d).", resp.status_code)
    except httpx.HTTPError as exc:
        logger.warning("  Submission failed: %s. Skipping.", exc)
        return

    # 5c — poll until the French-name mention has a cluster ID
    logger.info(
        "  5c — Waiting for French-name mention to resolve (timeout %ds) ...",
        int(timeout_s),
    )
    y_triad = y_payload["mention"]["identifiedBy"]
    y_lookup = poll_mention(y_triad, ers_client, timeout_s=timeout_s)
    if not y_lookup:
        logger.warning("  Timed out waiting for resolution. Skipping.")
        return

    y_cluster_id = y_lookup["cluster_reference"]["cluster_id"]
    logger.info("  Resolved to cluster: %s", y_cluster_id)

    # 5d — first inject: seed the decision with [x_cluster_id, y_cluster_id].
    # The outcome integrator takes candidates[0] as current_placement (keeps x where
    # it is) and candidates[1:] as the assignable list (y_cluster_id becomes the
    # sole valid candidate for /assign).
    logger.info("")
    logger.info(
        "  5d — Injecting two candidates: current cluster + French-name cluster ..."
    )
    _scripts_dir = Path(__file__).resolve().parents[2] / "src"
    if _scripts_dir.exists():
        sys.path.insert(0, str(_scripts_dir))
    try:
        from scripts.inject_ere_response import inject_response  # noqa: PLC0415

        inject_response(
            {
                "entity_mention": {
                    "source_id": x_triad["source_id"],
                    "request_id": x_triad["request_id"],
                    "entity_type": x_triad["entity_type"],
                },
                "proposed_cluster_ids": [x_cluster_id, y_cluster_id],
            },
            redis_config={
                "host": cfg["REDIS_HOST"],
                "port": int(cfg["REDIS_PORT"]),
                "password": cfg["REDIS_PASSWORD"],
            },
        )
        logger.info("  First injection pushed to Redis.")
    except Exception as exc:
        logger.warning("  First injection failed: %s. Skipping.", exc)
        return

    # 5e — find the decision, poll until y_cluster_id appears as a valid placement option
    token = _obtain_auth_token(cfg, logger)
    if not token:
        logger.warning("  Cannot obtain auth token. Skipping.")
        return

    with httpx.Client(
        base_url=cfg["CURATION_API_URL"],
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    ) as curation_client:

        # The decision_id equals x_cluster_id (canonical_entity_id from /resolve).
        # Confirm via decisions list to be safe.
        resp = curation_client.get(
            "/api/v1/curation/decisions",
            params={"entity_type": x_triad["entity_type"]},
        )
        if resp.status_code != 200:
            logger.warning(
                "  GET /curation/decisions returned HTTP %d. Skipping.", resp.status_code
            )
            return

        decision_id = None
        for decision in resp.json().get("results", []):
            em = decision.get("about_entity_mention", {}).get("identified_by", {})
            if (
                em.get("source_id") == x_triad["source_id"]
                and em.get("request_id") == x_triad["request_id"]
                and em.get("entity_type") == x_triad["entity_type"]
            ):
                decision_id = decision["id"]
                break

        if not decision_id:
            logger.warning(
                "  Decision for mention %s not found in /curation/decisions"
                " (first page only). Skipping.",
                x_triad["request_id"],
            )
            return

        logger.info("  Decision ID    : %s", decision_id)
        logger.info(
            "  5e — Waiting for French-name cluster as valid placement option"
            " (timeout %ds) ...",
            int(timeout_s / 2),
        )
        candidate_confirmed = False
        deadline = time.monotonic() + timeout_s / 2
        while time.monotonic() < deadline:
            alt_resp = curation_client.get(
                f"/api/v1/curation/decisions/{decision_id}/alternative-canonical-entities"
            )
            if alt_resp.status_code == 200:
                body = alt_resp.json()
                items = body if isinstance(body, list) else body.get("results", [])
                for item in items:
                    cid = (
                        item.get("cluster_id")
                        or item.get("id")
                        or (item.get("cluster_reference") or {}).get("cluster_id")
                    )
                    if cid == y_cluster_id:
                        candidate_confirmed = True
                        break
            if candidate_confirmed:
                break
            time.sleep(2.0)

        if candidate_confirmed:
            logger.info("  French-name cluster confirmed as valid placement option.")
        else:
            logger.warning(
                "  French-name cluster not yet visible — attempting /assign anyway."
            )

        # 5f — assign the target mention to the French-name cluster
        logger.info("  5f — Assigning target mention to French-name cluster ...")
        assign_resp = curation_client.post(
            f"/api/v1/curation/decisions/{decision_id}/assign",
            json={"cluster_id": y_cluster_id},
        )
        if assign_resp.status_code in (200, 202, 204):
            logger.info("  /assign accepted (HTTP %d).", assign_resp.status_code)
        else:
            logger.warning(
                "  /assign returned HTTP %d: %s",
                assign_resp.status_code,
                assign_resp.text,
            )
            return

    # Wait for underlying ERE response triggered by /assign before injecting the
    # fake ERE response — otherwise the injection may arrive before the real
    # request is processed and would effectively be ignored
    time.sleep(2.0)

    # 5g — second inject: confirm the assignment.
    # /assign triggered a re-resolution request from ERS; injecting [y_cluster_id]
    # responds to it and sets current_placement = y_cluster_id.
    logger.info("")
    logger.info("  5g — Injecting assignment confirmation ...")
    try:
        inject_response(
            {
                "entity_mention": {
                    "source_id": x_triad["source_id"],
                    "request_id": x_triad["request_id"],
                    "entity_type": x_triad["entity_type"],
                },
                "proposed_cluster_ids": [y_cluster_id],
            },
            redis_config={
                "host": cfg["REDIS_HOST"],
                "port": int(cfg["REDIS_PORT"]),
                "password": cfg["REDIS_PASSWORD"],
            },
        )
        logger.info("  Confirmation pushed to Redis.")
    except Exception as exc:
        logger.warning("  Confirmation injection failed: %s.", exc)

    # 5h — poll lookup until x's cluster changes to y_cluster_id
    logger.info(
        "  5h — Polling lookup to confirm new cluster (timeout %ds) ...",
        int(timeout_s / 2),
    )
    post_cluster_id = None
    deadline = time.monotonic() + timeout_s / 2
    while time.monotonic() < deadline:
        try:
            resp = ers_client.get(
                "/api/v1/lookup",
                params={
                    "source_id": x_triad["source_id"],
                    "request_id": x_triad["request_id"],
                    "entity_type": x_triad["entity_type"],
                },
            )
            if resp.status_code == 200:
                cid = resp.json().get("cluster_reference", {}).get("cluster_id")
                if cid == y_cluster_id:
                    post_cluster_id = cid
                    break
                elif cid:
                    post_cluster_id = cid
        except httpx.HTTPError:
            pass
        time.sleep(2.0)

    if post_cluster_id == y_cluster_id:
        logger.info(
            "  Cluster updated: %s  ->  %s", x_cluster_id, post_cluster_id
        )
    elif post_cluster_id:
        logger.info(
            "  Cluster after curation: %s (was %s — ERE may still be processing).",
            post_cluster_id,
            x_cluster_id,
        )
    else:
        logger.warning("  Timed out waiting for post-curation lookup.")


# ---------------------------------------------------------------------------
# Step 6 — Bulk refresh
# ---------------------------------------------------------------------------


def run_bulk_refresh(
    source_id: str,
    ers_client: httpx.Client,
    logger: logging.Logger,
) -> None:
    """POST /api/v1/refresh-bulk and print the delta summary."""
    logger.info("")
    logger.info("=" * 80)
    logger.info("STEP 6 — BULK REFRESH")
    logger.info("=" * 80)

    try:
        resp = ers_client.post(
            "/api/v1/refresh-bulk",
            json={"source_id": source_id},
        )
    except httpx.HTTPError as exc:
        logger.warning("  refresh-bulk request failed: %s", exc)
        return

    if resp.status_code != 200:
        logger.warning(
            "  POST /api/v1/refresh-bulk returned HTTP %d: %s",
            resp.status_code,
            resp.text,
        )
        return

    body = resp.json()
    deltas = body.get("deltas", [])
    logger.info("  Deltas returned: %d", len(deltas))

    if not deltas:
        logger.info("  (no deltas — all assignments are already up-to-date)")
        return

    logger.info("")
    logger.info("  %-12s  %-45s  %s", "request_id", "legal_name (n/a in delta)", "cluster_id")
    logger.info("  " + "-" * 78)
    for delta in deltas:
        identified_by = delta.get("identified_by", {})
        cluster_ref = delta.get("cluster_reference", {})
        req_id = identified_by.get("request_id", "?")
        cluster_id = cluster_ref.get("cluster_id", "?")
        logger.info("  %-12s  %-45s  %s", req_id, "", cluster_id)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(
    data_file: Path = _DEFAULT_DATA_FILE,
    timeout_s: float = 60.0,
    skip_curation: bool = False,
) -> int:
    """Run the full ERE resolution demo.

    Args:
        data_file: Path to the JSON file containing the mentions list.
        timeout_s: Per-mention lookup polling timeout in seconds.
        skip_curation: When True, skips the curation loop step.

    Returns:
        0 on full success, 1 if ERS API is unreachable or critical steps fail.
    """
    logger = setup_logging()
    logger.info(
        "ERE Resolution Demo — %s",
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )

    # Load configuration
    cfg = load_config()
    logger.info(
        "Config: ERS_API_URL=%s  CURATION_API_URL=%s",
        cfg["ERS_API_URL"],
        cfg["CURATION_API_URL"],
    )

    # Load mentions
    try:
        mentions = load_demo_mentions(data_file)
        logger.info("Loaded %d mentions from %s", len(mentions), data_file)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Failed to load mentions: %s", exc)
        return 1

    # Step 1 — Health checks
    healthy = check_health(cfg, logger)
    if not healthy:
        logger.error(
            "ERS API is unreachable. Start the stack with: make up"
        )
        return 1

    with httpx.Client(base_url=cfg["ERS_API_URL"], timeout=60.0) as ers_client:

        # Step 2 — Submit mentions
        enriched_mentions = submit_mentions(mentions, ers_client, logger)

        # Step 3 — Poll for results
        resolved_mentions = poll_all_mentions(
            enriched_mentions, ers_client, timeout_s=timeout_s, logger=logger
        )

        # Step 4 — Clustering summary
        logger.info("")
        logger.info("=" * 80)
        logger.info("STEP 4 — CLUSTERING SUMMARY")
        logger.info("=" * 80)
        print_clustering_summary(resolved_mentions, logger)

        # Step 5 — Curation loop
        if not skip_curation:
            run_curation_loop(
                resolved_mentions, cfg, ers_client,
                timeout_s=timeout_s, logger=logger,
            )
        else:
            logger.info("")
            logger.info("STEP 5 — CURATION LOOP  [skipped via --skip-curation]")

        # Step 6 — Bulk refresh
        source_ids = {m["source_id"] for m in mentions}
        for source_id in sorted(source_ids):
            run_bulk_refresh(source_id, ers_client, logger)

    # Final verdict
    resolved_count = sum(1 for m in resolved_mentions if m.get("cluster_id"))
    total = len(mentions)
    logger.info("")
    logger.info("=" * 80)
    if resolved_count == total:
        logger.info("Demo complete. All %d mentions resolved successfully.", total)
        return 0
    else:
        logger.warning(
            "Demo complete. %d/%d mentions resolved. "
            "Unresolved mentions may indicate a timeout or a service issue.",
            resolved_count,
            total,
        )
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "ERE Resolution Demo — exercises the full entity resolution lifecycle "
            "through the ERS REST API."
        )
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=_DEFAULT_DATA_FILE,
        metavar="PATH",
        help=f"Path to JSON file with demo mentions (default: {_DEFAULT_DATA_FILE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        metavar="SECONDS",
        help="Per-mention polling timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--skip-curation",
        action="store_true",
        default=False,
        help="Skip the curation loop step (useful for quick smoke runs)",
    )
    args = parser.parse_args()

    sys.exit(
        main(
            data_file=args.data,
            timeout_s=args.timeout,
            skip_curation=args.skip_curation,
        )
    )
