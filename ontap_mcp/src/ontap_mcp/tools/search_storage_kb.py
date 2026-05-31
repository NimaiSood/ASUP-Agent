"""Semantic storage knowledge-base search (placeholder vector backend)."""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from ontap_mcp.tool_schemas import SearchStorageKbInput

logger = logging.getLogger(__name__)

# Placeholder corpus — replace _vector_search_backend with real embedding DB.
_MOCK_KB_ARTICLES: list[dict[str, Any]] = [
    {
        "id": "KB-10192",
        "title": "ONTAP FlexGroup stat storm mitigation",
        "snippet": "High metadata GETATTR/LOOKUP rates across constituents can saturate Nblade CPU. "
        "Reduce client stat cache TTL, spread workloads, or add nodes.",
        "products": ["ONTAP"],
        "tags": ["stat storm", "flexgroup", "metadata", "nblade"],
    },
    {
        "id": "KB-8841",
        "title": "Diagnosing WAFL large I/O lifecycle stalls",
        "snippet": "Large sequential reads may trigger fragmentation and CP delays. "
        "Check wafl.log for alloc delays and statit large_io sections.",
        "products": ["ONTAP"],
        "tags": ["large io", "wafl", "fragmentation", "latency"],
    },
    {
        "id": "KB-12004",
        "title": "Google Cloud NetApp Volumes performance tuning",
        "snippet": "GCNV latency spikes often correlate with network path or undersized service level. "
        "Validate client proximity and quota headroom.",
        "products": ["GCNV"],
        "tags": ["gcnv", "cloud", "latency", "network"],
    },
    {
        "id": "KB-11550",
        "title": "Azure NetApp Files metadata-heavy workload guidance",
        "snippet": "ANF volumes with millions of small files benefit from proper SMB/NFS client tuning "
        "and capacity pool sizing for metadata operations.",
        "products": ["ANF"],
        "tags": ["anf", "azure", "metadata", "stat"],
    },
    {
        "id": "KB-10933",
        "title": "OCI Volume Storage Appliance EMS correlation",
        "snippet": "Use EMS wafl.* and resource.* events with Harvest node_cpu metrics "
        "to isolate backend vs protocol latency on OCI VSA.",
        "products": ["OCI_VSA"],
        "tags": ["oci", "vsa", "ems", "rca"],
    },
    {
        "id": "KB-9022",
        "title": "Nblade vs Dblade latency decomposition",
        "snippet": "Compare client-side protocol latency with disk busy and WAFL CP metrics "
        "to determine CS/Nblade vs Dblade bottlenecks.",
        "products": ["ONTAP", "GCNV", "ANF"],
        "tags": ["nblade", "dblade", "latency", "rca"],
    },
]


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def _vector_search_backend(
    query: str,
    *,
    top_k: int,
    product_filter: list[str] | None,
    min_score: float,
) -> list[dict[str, Any]]:
    """
    Placeholder for real vector DB (Pinecone, pgvector, etc.).

    Replace this function with embedding similarity against your KB index.
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    allowed_products: set[str] | None = None
    if product_filter and "ALL" not in product_filter:
        allowed_products = set(product_filter)

    scored: list[tuple[float, dict[str, Any]]] = []
    for article in _MOCK_KB_ARTICLES:
        if allowed_products and not allowed_products.intersection(article["products"]):
            continue

        corpus = " ".join([
            article["title"],
            article["snippet"],
            " ".join(article["tags"]),
        ])
        doc_tokens = _tokenize(corpus)
        if not doc_tokens:
            continue

        overlap = query_tokens & doc_tokens
        if not overlap:
            continue

        # Normalized overlap score as mock cosine similarity.
        score = len(overlap) / math.sqrt(len(query_tokens) * len(doc_tokens))
        if score >= min_score:
            scored.append((score, article))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "id": art["id"],
            "title": art["title"],
            "snippet": art["snippet"],
            "products": art["products"],
            "tags": art["tags"],
            "score": round(score, 4),
        }
        for score, art in scored[:top_k]
    ]


def search_storage_kb(params: SearchStorageKbInput) -> dict[str, Any]:
    """Run semantic KB search with structured request envelope."""
    logger.info(
        "KB search query=%r top_k=%d products=%s",
        params.query[:80],
        params.top_k,
        params.product_filter,
    )

    hits = _vector_search_backend(
        params.query,
        top_k=params.top_k,
        product_filter=params.product_filter,
        min_score=params.min_score,
    )

    result = {
        "query": params.query,
        "top_k": params.top_k,
        "product_filter": params.product_filter,
        "num_results": len(hits),
        "results": hits,
        "backend": "mock_vector_search",
    }
    logger.info("KB search returned %d hits", len(hits))
    return result
