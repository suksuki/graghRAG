#!/usr/bin/env python3
"""Async load test for GraphRAG API endpoints."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class Result:
    endpoint: str
    ok: bool
    status_code: int | None
    elapsed_ms: float
    error: str | None = None


async def _run_one(
    client: httpx.AsyncClient,
    *,
    endpoint: str,
    method: str,
    payload: dict[str, Any] | None,
    params: dict[str, Any] | None,
) -> Result:
    started = time.perf_counter()
    try:
        if method == "GET":
            response = await client.get(endpoint, params=params)
        else:
            response = await client.post(endpoint, json=payload)
        elapsed_ms = (time.perf_counter() - started) * 1000
        ok = response.status_code < 500
        return Result(
            endpoint=endpoint,
            ok=ok,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            error=None if ok else response.text[:200],
        )
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - started) * 1000
        return Result(
            endpoint=endpoint,
            ok=False,
            status_code=None,
            elapsed_ms=elapsed_ms,
            error=str(exc),
        )


async def run_load(
    *,
    base_url: str,
    query: str,
    doc_id: str | None,
    top_k: int,
    requests_per_endpoint: int,
    concurrency: int,
    timeout: float,
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)
    endpoints = [
        ("GET", "/", None, None),
        ("GET", "/settings", None, None),
        ("GET", "/knowledge/search", None, {"q": query, "top_k": top_k}),
        (
            "POST",
            "/api/v1/hybrid-search",
            {
                "query": query,
                "top_k": top_k,
                "graph_expand_k": 10,
                "include_fallback": False,
            },
            None,
        ),
        (
            "POST",
            "/api/v1/insights/document",
            {
                "query": query,
                "top_k": top_k,
                "doc_id": doc_id,
                "include_graph_relations": True,
            },
            None,
        ),
    ]

    results: list[Result] = []

    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        async def wrapped(method: str, endpoint: str, payload: dict[str, Any] | None, params: dict[str, Any] | None):
            async with semaphore:
                result = await _run_one(
                    client,
                    endpoint=endpoint,
                    method=method,
                    payload=payload,
                    params=params,
                )
                results.append(result)

        tasks = []
        for method, endpoint, payload, params in endpoints:
            for _ in range(requests_per_endpoint):
                tasks.append(asyncio.create_task(wrapped(method, endpoint, payload, params)))
        await asyncio.gather(*tasks)

    grouped: dict[str, list[Result]] = {}
    for result in results:
        grouped.setdefault(result.endpoint, []).append(result)

    summary: dict[str, Any] = {
        "base_url": base_url,
        "requests_per_endpoint": requests_per_endpoint,
        "concurrency": concurrency,
        "total_requests": len(results),
        "total_failures": len([r for r in results if not r.ok]),
        "endpoints": {},
    }
    for endpoint, endpoint_results in grouped.items():
        latencies = [r.elapsed_ms for r in endpoint_results]
        failures = [r for r in endpoint_results if not r.ok]
        summary["endpoints"][endpoint] = {
            "count": len(endpoint_results),
            "failures": len(failures),
            "p50_ms": round(statistics.median(latencies), 2),
            "p95_ms": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2),
            "max_ms": round(max(latencies), 2),
            "sample_error": failures[0].error if failures else None,
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Load test GraphRAG API endpoints.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--query", default="architecture overview", help="Query for search endpoints")
    parser.add_argument("--doc-id", default=None, help="Optional doc_id for scoped insight load")
    parser.add_argument("--top-k", type=int, default=3, help="Top K for search and insight requests")
    parser.add_argument("--requests-per-endpoint", type=int, default=5, help="Requests per endpoint")
    parser.add_argument("--concurrency", type=int, default=5, help="Async concurrency")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds")
    parser.add_argument(
        "--max-failures",
        type=int,
        default=0,
        help="Exit non-zero when failures exceed this threshold",
    )
    args = parser.parse_args()

    summary = asyncio.run(
        run_load(
            base_url=args.base_url,
            query=args.query,
            doc_id=args.doc_id,
            top_k=args.top_k,
            requests_per_endpoint=args.requests_per_endpoint,
            concurrency=args.concurrency,
            timeout=args.timeout,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["total_failures"] > args.max_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
