"""Paginated EMS log retrieval via ONTAP REST (requests + backoff)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ontap_mcp.tool_schemas import FetchEmsLogsInput

logger = logging.getLogger(__name__)

EMS_PATH = "/api/support/ems/events"
EMS_FIELDS = "index,time,log_message,message,node,parameters,source"
MAX_BACKOFF_SEC = 32.0


def _session() -> requests.Session:
    retry = Retry(
        total=5,
        connect=3,
        read=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    sess = requests.Session()
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    sess.headers.update({"Accept": "application/hal+json"})
    return sess


def _credentials() -> tuple[str, str]:
    return os.environ["ONTAP_USERNAME"], os.environ["ONTAP_PASSWORD"]


def _verify_ssl() -> bool:
    return os.environ.get("ONTAP_VERIFY_SSL", "true").lower() == "true"


def _resolve_host(cluster_host: str | None) -> str:
    host = (cluster_host or os.environ.get("ONTAP_MGMT_HOST", "")).rstrip("/")
    if not host:
        raise ValueError("cluster_host required or set ONTAP_MGMT_HOST")
    return host


def _build_time_filter(start_time: str | None, end_time: str | None) -> str | None:
    parts: list[str] = []
    if start_time:
        parts.append(f">={start_time}")
    if end_time:
        parts.append(f"<={end_time}")
    if not parts:
        return None
    return ",".join(parts)


def _get_with_backoff(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None,
    auth: tuple[str, str],
    verify: bool,
) -> dict[str, Any]:
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            resp = session.get(url, params=params, auth=auth, verify=verify, timeout=60)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", delay))
                logger.warning(
                    "EMS rate limited (429); backing off %.1fs (attempt %d)",
                    retry_after,
                    attempt + 1,
                )
                time.sleep(min(retry_after, MAX_BACKOFF_SEC))
                delay = min(delay * 2, MAX_BACKOFF_SEC)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_error = exc
            logger.warning("EMS request failed (attempt %d): %s", attempt + 1, exc)
            time.sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF_SEC)
    raise RuntimeError(f"EMS fetch failed after retries: {last_error}") from last_error


def _follow_next_pages(
    session: requests.Session,
    base_host: str,
    first_page: dict[str, Any],
    *,
    auth: tuple[str, str],
    verify: bool,
    max_records: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = list(first_page.get("records", []))
    next_href = first_page.get("_links", {}).get("next", {}).get("href")
    while next_href and len(records) < max_records:
        if next_href.startswith("http"):
            url = next_href
            params = None
        else:
            url = urljoin(base_host + "/", next_href.lstrip("/"))
            params = None
        page = _get_with_backoff(session, url, params=params, auth=auth, verify=verify)
        records.extend(page.get("records", []))
        next_href = page.get("_links", {}).get("next", {}).get("href")
    return records[:max_records]


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, int]] = set()
    unique: list[dict[str, Any]] = []
    for rec in records:
        key = (rec.get("node", {}).get("name", ""), rec.get("index", 0))
        if key not in seen:
            seen.add(key)
            unique.append(rec)
    unique.sort(key=lambda r: r.get("time", ""), reverse=True)
    return unique


def fetch_ems_logs(params: FetchEmsLogsInput) -> dict[str, Any]:
    """Fetch EMS events with pagination and exponential backoff."""
    host = _resolve_host(params.cluster_host)
    auth = _credentials()
    verify = _verify_ssl()
    time_filter = _build_time_filter(params.start_time, params.end_time)

    base_params: dict[str, Any] = {
        "max_records": min(params.page_size, params.max_records),
        "order_by": "time desc",
        "message.severity": params.severities,
        "fields": EMS_FIELDS,
    }
    if params.node_name:
        base_params["node.name"] = params.node_name
    if time_filter:
        base_params["time"] = time_filter

    session = _session()
    all_records: list[dict[str, Any]] = []
    pattern_errors: list[dict[str, str]] = []

    logger.info(
        "Fetching EMS logs from %s patterns=%d max_records=%d",
        host,
        len(params.message_patterns),
        params.max_records,
    )

    for pattern in params.message_patterns:
        if len(all_records) >= params.max_records:
            break
        remaining = params.max_records - len(all_records)
        query = {**base_params, "message.name": pattern, "max_records": min(params.page_size, remaining)}
        url = f"{host}{EMS_PATH}"
        try:
            first_page = _get_with_backoff(session, url, params=query, auth=auth, verify=verify)
            page_records = _follow_next_pages(
                session,
                host,
                first_page,
                auth=auth,
                verify=verify,
                max_records=remaining,
            )
            all_records.extend(page_records)
            logger.debug("Pattern %r returned %d records", pattern, len(page_records))
        except Exception as exc:
            logger.exception("EMS pattern %r failed", pattern)
            pattern_errors.append({"pattern": pattern, "error": str(exc)})

    unique = _dedupe_records(all_records)[: params.max_records]
    result: dict[str, Any] = {
        "cluster_host": host,
        "num_records": len(unique),
        "records": unique,
        "filters": {
            "message_patterns": params.message_patterns,
            "severities": params.severities,
            "node_name": params.node_name,
            "start_time": params.start_time,
            "end_time": params.end_time,
        },
    }
    if pattern_errors:
        result["pattern_errors"] = pattern_errors
    logger.info("EMS fetch complete: %d unique records", len(unique))
    return result
