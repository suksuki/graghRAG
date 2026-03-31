#!/usr/bin/env python3
"""Release smoke validation for the GraphRAG API surface."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _get_json(client: httpx.Client, path: str, **kwargs: Any) -> dict[str, Any]:
    response = client.get(path, **kwargs)
    response.raise_for_status()
    data = response.json()
    _expect(isinstance(data, dict), f"{path} did not return a JSON object")
    return data


def _post_json(client: httpx.Client, path: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    response = client.post(path, json=payload, **kwargs)
    response.raise_for_status()
    data = response.json()
    _expect(isinstance(data, dict), f"{path} did not return a JSON object")
    return data


def run_smoke(
    *,
    base_url: str,
    query: str,
    doc_id: str | None,
    top_k: int,
    timeout: float,
) -> dict[str, Any]:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        root = _get_json(client, "/")
        _expect(root.get("status") == "online", "root endpoint is not online")

        settings = _get_json(client, "/settings")
        _expect("ollama_base_url" in settings, "settings missing ollama_base_url")
        _expect("llm_model" in settings, "settings missing llm_model")

        docs = _get_json(client, "/knowledge/docs")
        _expect(isinstance(docs.get("documents"), list), "/knowledge/docs missing documents[]")

        search = _get_json(
            client,
            "/knowledge/search",
            params={"q": query, "top_k": top_k},
        )
        _expect("results" in search, "/knowledge/search missing results")
        _expect(isinstance(search.get("results"), list), "/knowledge/search results is not a list")

        hybrid = _post_json(
            client,
            "/api/v1/hybrid-search",
            {
                "query": query,
                "top_k": top_k,
                "graph_expand_k": 10,
                "include_fallback": False,
            },
        )
        _expect(hybrid.get("query") == query, "hybrid-search query echo mismatch")
        _expect(isinstance(hybrid.get("results"), list), "hybrid-search missing results[]")
        _expect(isinstance(hybrid.get("debug"), dict), "hybrid-search missing debug{}")

        insight_payload: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "include_graph_relations": True,
        }
        if doc_id:
            insight_payload["doc_id"] = doc_id

        insight = _post_json(client, "/api/v1/insights/document", insight_payload)
        _expect("summary" in insight, "insight response missing summary")
        _expect("answer" in insight, "insight response missing answer")
        _expect(insight.get("answer") == insight.get("summary"), "insight answer/summary mismatch")
        _expect(isinstance(insight.get("supporting_chunks"), list), "insight supporting_chunks is not a list")
        _expect(isinstance(insight.get("structured_evidence"), list), "insight structured_evidence is not a list")
        _expect(isinstance(insight.get("debug"), dict), "insight debug is not a dict")
        _expect(isinstance(insight.get("decision"), dict), "insight decision is not a dict")

        if insight["supporting_chunks"]:
            first = insight["supporting_chunks"][0]
            _expect("ref_index" in first, "supporting chunk missing ref_index")

        for row in insight["structured_evidence"]:
            _expect("role" in row, "structured_evidence row missing role")
            _expect("persons" in row, "structured_evidence row missing persons")
            _expect("ref_indices" in row, "structured_evidence row missing ref_indices")
            _expect("file_names" in row, "structured_evidence row missing file_names")

        return {
            "base_url": base_url,
            "query": query,
            "doc_id": doc_id,
            "knowledge_docs": len(docs["documents"]),
            "knowledge_search_hits": len(search["results"]),
            "hybrid_results": len(hybrid["results"]),
            "insight_source": insight.get("source"),
            "insight_supporting_chunks": len(insight["supporting_chunks"]),
            "structured_evidence_rows": len(insight["structured_evidence"]),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Release smoke validation for the GraphRAG API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--query", default="architecture overview", help="Smoke query")
    parser.add_argument("--doc-id", default=None, help="Optional doc_id for scoped insight")
    parser.add_argument("--top-k", type=int, default=3, help="Top K for search/insight calls")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")
    args = parser.parse_args()

    try:
        result = run_smoke(
            base_url=args.base_url,
            query=args.query,
            doc_id=args.doc_id,
            top_k=args.top_k,
            timeout=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
