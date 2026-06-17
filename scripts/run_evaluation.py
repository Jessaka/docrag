"""Run the DocsRAG evaluation benchmark against a running backend."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib import error, parse, request


DEFAULT_BASE_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
DEFAULT_BENCHMARK_PATH = Path("tests/evaluation_queries.json")
DEFAULT_RESULTS_PATH = Path("tests/evaluation_results.json")
FALLBACK_ROUTES = {"fallback_no_answer", "unsupported_direct", "clarification_direct"}
FALLBACK_PREFIXES = (
    "i could not find the answer",
    "this question appears to be outside the supported documentation scope",
    "please clarify which tool or documentation area you mean",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the DocsRAG evaluation benchmark.")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base URL of the running DocsRAG API.",
    )
    parser.add_argument(
        "--benchmark-path",
        default=str(DEFAULT_BENCHMARK_PATH),
        help="Path to tests/evaluation_queries.json.",
    )
    parser.add_argument(
        "--results-path",
        default=str(DEFAULT_RESULTS_PATH),
        help="Path where detailed evaluation results will be written.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-query timeout in seconds.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    benchmark_path = Path(args.benchmark_path)
    results_path = Path(args.results_path)

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    queries: List[Dict[str, Any]] = benchmark.get("queries", [])
    if not queries:
        raise SystemExit(f"❌ No queries found in {benchmark_path}")

    results: List[Dict[str, Any]] = []
    failed_queries: List[Dict[str, Any]] = []

    for index, item in enumerate(queries, start=1):
        result = evaluate_query(item=item, base_url=base_url, timeout=args.timeout)
        results.append(result)

        if not all(
            [
                result["provider_hit"],
                result["route_match"],
                result["source_hit"],
                result["has_answer"],
            ]
        ):
            failed_queries.append(
                {
                    "id": result["id"],
                    "query": result["query"],
                    "failure_reasons": result["failure_reasons"],
                    "latency_ms": result["latency_ms"],
                }
            )

        print(
            f"[{index:02d}/{len(queries)}] {result['id']} | "
            f"provider_hit={emoji(result['provider_hit'])} "
            f"route_match={emoji(result['route_match'])} "
            f"source_hit={emoji(result['source_hit'])} "
            f"has_answer={emoji(result['has_answer'])} "
            f"latency={result['latency_ms']}ms"
        )

    summary = build_summary(results=results, failed_queries=failed_queries)
    payload = {
        "benchmark": {
            "path": str(benchmark_path),
            "version": benchmark.get("version"),
            "description": benchmark.get("description"),
        },
        "base_url": base_url,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": summary,
        "results": results,
    }

    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== DocsRAG Evaluation Summary ===")
    print(f"Total queries: {summary['total_queries']}")
    print(f"Provider hit rate: {summary['provider_hit_rate']:.2%}")
    print(f"Route match rate: {summary['route_match_rate']:.2%}")
    print(f"Source hit rate: {summary['source_hit_rate']:.2%}")
    print(f"Has-answer rate: {summary['has_answer_rate']:.2%}")
    print(f"Average latency: {summary['average_latency_ms']:.1f} ms")
    print(f"Detailed results saved to: {results_path}")

    if failed_queries:
        print("Failed queries:")
        for item in failed_queries:
            reasons = ", ".join(item["failure_reasons"])
            print(f"- {item['id']}: {reasons}")
    else:
        print("Failed queries: none")


def evaluate_query(item: Dict[str, Any], base_url: str, timeout: float) -> Dict[str, Any]:
    started = time.perf_counter()
    status_code, payload = http_post_json(
        f"{base_url}/chat",
        payload={"query": item["query"]},
        timeout=timeout,
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    sources = payload.get("sources") if isinstance(payload, dict) else []
    sources = sources if isinstance(sources, list) else []
    answer = payload.get("answer", "") if isinstance(payload, dict) else ""
    route = payload.get("route") if isinstance(payload, dict) else None

    provider_hit = any(source.get("provider") == item["expected_provider"] for source in sources)
    route_match = route == item["expected_route"]

    expected_urls = set(item["expected_source_urls"])
    expected_hostnames = {parse.urlparse(u).hostname for u in expected_urls}
    exact_match = any(source.get("url") in expected_urls for source in sources)
    domain_match = any(
        source.get("provider") == item["expected_provider"]
        and parse.urlparse(source.get("url") or "").hostname in expected_hostnames
        for source in sources
    )
    source_hit = exact_match or domain_match

    has_answer = is_non_fallback_answer(answer=answer, route=route)

    failure_reasons: List[str] = []
    if status_code != 200:
        failure_reasons.append(f"http_{status_code}")
    if not provider_hit:
        failure_reasons.append("provider_miss")
    if not route_match:
        failure_reasons.append("route_miss")
    if not source_hit:
        failure_reasons.append("source_miss")
    if not has_answer:
        failure_reasons.append("no_answer")

    return {
        "id": item["id"],
        "provider_label": item.get("provider_label"),
        "category": item.get("category"),
        "query": item["query"],
        "expected_provider": item["expected_provider"],
        "expected_tool": item.get("expected_tool"),
        "expected_route": item["expected_route"],
        "expected_source_urls": item["expected_source_urls"],
        "status_code": status_code,
        "latency_ms": latency_ms,
        "provider_hit": provider_hit,
        "route_match": route_match,
        "source_hit": source_hit,
        "has_answer": has_answer,
        "failure_reasons": failure_reasons,
        "response": {
            "route": route,
            "answer": answer,
            "sources": sources,
        },
    }


def build_summary(results: List[Dict[str, Any]], failed_queries: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results)
    provider_hits = sum(1 for item in results if item["provider_hit"])
    route_hits = sum(1 for item in results if item["route_match"])
    source_hits = sum(1 for item in results if item["source_hit"])
    answer_hits = sum(1 for item in results if item["has_answer"])
    average_latency_ms = sum(item["latency_ms"] for item in results) / total if total else 0.0

    return {
        "total_queries": total,
        "provider_hit_rate": provider_hits / total if total else 0.0,
        "route_match_rate": route_hits / total if total else 0.0,
        "source_hit_rate": source_hits / total if total else 0.0,
        "has_answer_rate": answer_hits / total if total else 0.0,
        "average_latency_ms": average_latency_ms,
        "failed_queries": failed_queries,
    }


def http_post_json(url: str, payload: Dict[str, Any], timeout: float) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        return exc.code, json.loads(body) if body else {}
    except error.URLError as exc:
        raise SystemExit(f"❌ Request failed: {exc}") from exc


def is_non_fallback_answer(answer: Any, route: Any) -> bool:
    if not isinstance(answer, str) or not answer.strip():
        return False
    normalized = " ".join(answer.strip().lower().split())
    if route in FALLBACK_ROUTES:
        return False
    return not any(normalized.startswith(prefix) for prefix in FALLBACK_PREFIXES)


def emoji(value: bool) -> str:
    return "✅" if value else "❌"


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
